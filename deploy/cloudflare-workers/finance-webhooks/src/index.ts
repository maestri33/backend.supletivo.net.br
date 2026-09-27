/**
 * Cloudflare Edge Webhook Worker: Financial Gateways (Asaas & InfinitePay).
 *
 * Arquitetura de Borda Canônica (Zero-Loss / Zero-Timeout / D1 + KV):
 * 1. Terminação Imediata (<15ms): Responde HTTP 200 OK instantaneamente ao gateway bancário,
 *    eliminando tempestades de retry, bloqueios de webhook e esgotamento do pool do Django.
 * 2. Auditoria SQL Estruturada (Cloudflare D1): Registra todo webhook recebido com IP, URL e payload
 *    para rastreabilidade forense imutável.
 * 3. Despacho Assíncrono Seguro (ctx.waitUntil): Encaminha o webhook em segundo plano
 *    diretamente para o endpoint do backend Django, com X-Edge-Delivery-Id e X-Original-User-Agent.
 * 4. Buffer de Contingência Distribuído (Workers KV): Se o backend estiver indisponível ou reiniciando,
 *    o evento é persistido no KV e reprocessado automaticamente via trigger cron a cada 5 minutos.
 * 5. 100% Free Tier: Operando de forma resiliente e com cotas controladas na Cloudflare.
 */

export interface Env {
  FINANCE_WEBHOOKS_KV: KVNamespace;
  DB?: D1Database;
  BACKEND_ASAAS_URL: string;
  BACKEND_INFINITEPAY_URL: string;
  BACKEND_HEALTH_URL: string;
  INTERNAL_SERVICE_SECRET?: string;
  ASAAS_WEBHOOK_SECRET?: string;
  FINANCE_WEBHOOKS_QUEUE?: Queue<WebhookMessage>;
}

export interface WebhookMessage {
  id: string;
  provider: "asaas" | "infinitepay";
  orderNsu?: string;
  receivedAt: string;
  url: string;
  headers: Record<string, string>;
  payload: unknown;
  clientIp: string;
  attempts: number;
}

/**
 * Comparação em tempo constante (timing-safe) para evitar ataques de temporização.
 */
function timingSafeCompare(a: string, b: string): boolean {
  const encoder = new TextEncoder();
  const aBuf = encoder.encode(a);
  const bBuf = encoder.encode(b);
  if (aBuf.byteLength !== bBuf.byteLength) return false;
  return crypto.subtle.timingSafeEqual(aBuf, bBuf);
}

/**
 * Extrai order_nsu do request (seja da query string ou do corpo JSON).
 */
function extractOrderNsu(url: URL, payload: any): string {
  const fromQuery = url.searchParams.get("order_nsu");
  if (fromQuery && fromQuery.trim()) {
    return fromQuery.trim();
  }
  if (payload && typeof payload === "object") {
    if (typeof payload.order_nsu === "string" && payload.order_nsu.trim()) {
      return payload.order_nsu.trim();
    }
    if (typeof payload.external_id === "string" && payload.external_id.trim()) {
      return payload.external_id.trim();
    }
  }
  return "";
}

function resolveTargetUrl(msg: WebhookMessage, env: Env): string {
  if (msg.provider === "asaas") {
    return env.BACKEND_ASAAS_URL;
  }

  // InfinitePay: propaga order_nsu na query string para o Django (request.GET.get('order_nsu'))
  let target = env.BACKEND_INFINITEPAY_URL;
  const orderNsu = msg.orderNsu;
  if (orderNsu) {
    const separator = target.includes("?") ? "&" : "?";
    target = `${target}${separator}order_nsu=${encodeURIComponent(orderNsu)}`;
  }
  return target;
}

async function logToD1(
  env: Env,
  id: string,
  provider: string,
  orderNsu: string,
  url: string,
  clientIp: string,
  payload: unknown,
  status: string
): Promise<void> {
  if (!env.DB) return;
  try {
    await env.DB.prepare(
      `INSERT INTO webhook_events (id, provider, order_nsu, url, client_ip, payload, status)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    )
      .bind(
        id,
        provider,
        orderNsu || "",
        url,
        clientIp,
        JSON.stringify(payload),
        status
      )
      .run();
  } catch (err) {
    console.warn("Falha ao registrar webhook no D1 (não bloqueante):", err);
  }
}

async function updateD1Status(
  env: Env,
  id: string,
  status: string,
  error?: string
): Promise<void> {
  if (!env.DB) return;
  try {
    if (status === "DELIVERED") {
      await env.DB.prepare(
        `UPDATE webhook_events SET status = ?, delivered_at = CURRENT_TIMESTAMP WHERE id = ?`
      )
        .bind(status, id)
        .run();
    } else {
      await env.DB.prepare(
        `UPDATE webhook_events SET status = ?, last_error = ?, attempts = attempts + 1 WHERE id = ?`
      )
        .bind(status, error || null, id)
        .run();
    }
  } catch (err) {
    console.warn("Falha ao atualizar status no D1:", err);
  }
}

async function dispatchWebhook(msg: WebhookMessage, env: Env): Promise<boolean> {
  const targetUrl = resolveTargetUrl(msg, env);
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Forwarded-For": msg.clientIp,
      "X-CF-Connecting-IP": msg.clientIp,
      "X-Edge-Delivery-Id": msg.id,
      "X-Original-User-Agent": msg.headers["user-agent"] || "",
      ...(msg.headers["asaas-access-token"] ? { "asaas-access-token": msg.headers["asaas-access-token"] } : {}),
      ...(env.INTERNAL_SERVICE_SECRET ? { "X-Service-Secret": env.INTERNAL_SERVICE_SECRET } : {}),
    };

    const response = await fetch(targetUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(msg.payload),
      signal: AbortSignal.timeout(6000),
    });

    if (response.ok) {
      await updateD1Status(env, msg.id, "DELIVERED");
      return true;
    }

    if (response.status === 400 || response.status === 422) {
      // 400/422: Payload malformado/inválido pelo cliente de origem; não re-tentar para evitar loop
      await updateD1Status(env, msg.id, "REJECTED_4XX", `HTTP ${response.status}`);
      return true;
    }

    // 401, 403, 408, 429 e 5xx: Transitórios ou falhas de configuração recarregáveis; re-tentar
    await updateD1Status(env, msg.id, "RETRYING", `HTTP ${response.status}`);
    return false;
  } catch (err: any) {
    console.error(`Falha ao despachar webhook ${msg.id} para ${targetUrl}:`, err);
    await updateD1Status(env, msg.id, "RETRYING", String(err?.message || err));
    return false;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const pathname = url.pathname.replace(/\/+$/, "");
    const clientIp = request.headers.get("CF-Connecting-IP") || "0.0.0.0";

    // 1. Health check leve (Sem KV.list para proteger cota diária de 1.000 list ops do Free Tier)
    if (pathname === "/health" || pathname === "/bank/health") {
      let d1Status = "unconfigured";
      if (env.DB) {
        try {
          await env.DB.prepare("SELECT 1").first();
          d1Status = "connected";
        } catch {
          d1Status = "error";
        }
      }

      return new Response(
        JSON.stringify({
          status: "healthy",
          edge: "cloudflare",
          timestamp: new Date().toISOString(),
          d1_storage: d1Status,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // 2. Reprocessamento Manual sob Demanda (/bank/drain) - Fail Closed com Timing-Safe Check
    if (pathname === "/bank/drain" && request.method === "POST") {
      const authHeader = request.headers.get("X-Service-Secret") || request.headers.get("Authorization");
      if (!env.INTERNAL_SERVICE_SECRET) {
        return new Response(JSON.stringify({ error: "Service secret unconfigured" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }

      const expectedBearer = `Bearer ${env.INTERNAL_SERVICE_SECRET}`;
      const isAuthorized = Boolean(
        authHeader &&
          (timingSafeCompare(authHeader, env.INTERNAL_SERVICE_SECRET) ||
            timingSafeCompare(authHeader, expectedBearer))
      );

      if (!isAuthorized) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      ctx.waitUntil(
        (async () => {
          const list = await env.FINANCE_WEBHOOKS_KV.list({ prefix: "pending:", limit: 50 });
          for (const k of list.keys) {
            const raw = await env.FINANCE_WEBHOOKS_KV.get(k.name);
            if (raw) {
              const msg: WebhookMessage = JSON.parse(raw);
              msg.attempts += 1;
              const ok = await dispatchWebhook(msg, env);
              if (ok) {
                await env.FINANCE_WEBHOOKS_KV.delete(k.name);
              } else if (msg.attempts >= 10) {
                await env.FINANCE_WEBHOOKS_KV.put(`dlq:${msg.id}`, JSON.stringify(msg), { expirationTtl: 2592000 });
                await env.FINANCE_WEBHOOKS_KV.delete(k.name);
                if (env.DB) {
                  await env.DB.prepare(
                    `INSERT INTO webhook_dead_letter (id, provider, order_nsu, payload, reason) VALUES (?, ?, ?, ?, ?)`
                  )
                    .bind(msg.id, msg.provider, msg.orderNsu || "", JSON.stringify(msg.payload), "Exceeded 10 drain attempts")
                    .run();
                }
              } else {
                await env.FINANCE_WEBHOOKS_KV.put(k.name, JSON.stringify(msg), { expirationTtl: 604800 });
              }
            }
          }
        })()
      );

      return new Response(JSON.stringify({ ok: true, draining: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Apenas POST é permitido para webhooks bancários
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 3. Webhook Asaas (/bank/asaas) - Normalização de trailing slash e autenticação segura
    if (pathname === "/bank/asaas" || pathname.endsWith("/bank/asaas")) {
      const token = request.headers.get("asaas-access-token");
      if (env.ASAAS_WEBHOOK_SECRET) {
        if (!token || !timingSafeCompare(token, env.ASAAS_WEBHOOK_SECRET)) {
          return new Response(JSON.stringify({ error: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          });
        }
      }

      try {
        const payload = await request.json();
        const msgId = crypto.randomUUID();
        const orderNsu = (payload as any)?.payment?.externalReference || (payload as any)?.payment?.id || "";

        const msg: WebhookMessage = {
          id: msgId,
          provider: "asaas",
          orderNsu,
          receivedAt: new Date().toISOString(),
          url: request.url,
          headers: {
            "asaas-access-token": token || "",
            "content-type": request.headers.get("content-type") || "application/json",
            "user-agent": request.headers.get("user-agent") || "",
          },
          payload,
          clientIp,
          attempts: 1,
        };

        // Grava no D1 e despacha assincronamente (<15ms)
        ctx.waitUntil(
          (async () => {
            await logToD1(env, msgId, "asaas", orderNsu, request.url, clientIp, payload, "RECEIVED");
            const ok = await dispatchWebhook(msg, env);
            if (!ok) {
              await env.FINANCE_WEBHOOKS_KV.put(`pending:${msgId}`, JSON.stringify(msg), {
                expirationTtl: 604800,
              });
            }
          })()
        );

        return new Response(JSON.stringify({ ok: true, received: true, id: msgId }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } catch (err: any) {
        return new Response(JSON.stringify({ error: "Invalid JSON payload", detail: String(err) }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    // 4. Webhook InfinitePay (/bank/infinitepay) - Normalização de trailing slash e extração robusta de order_nsu
    if (pathname === "/bank/infinitepay" || pathname.endsWith("/bank/infinitepay")) {
      try {
        const payload = await request.json();
        const msgId = crypto.randomUUID();
        const orderNsu = extractOrderNsu(url, payload);

        const msg: WebhookMessage = {
          id: msgId,
          provider: "infinitepay",
          orderNsu,
          receivedAt: new Date().toISOString(),
          url: request.url,
          headers: {
            "content-type": request.headers.get("content-type") || "application/json",
            "user-agent": request.headers.get("user-agent") || "",
          },
          payload,
          clientIp,
          attempts: 1,
        };

        // Grava no D1 e despacha assincronamente (<15ms)
        ctx.waitUntil(
          (async () => {
            await logToD1(env, msgId, "infinitepay", orderNsu, request.url, clientIp, payload, "RECEIVED");
            const ok = await dispatchWebhook(msg, env);
            if (!ok) {
              await env.FINANCE_WEBHOOKS_KV.put(`pending:${msgId}`, JSON.stringify(msg), {
                expirationTtl: 604800,
              });
            }
          })()
        );

        return new Response(JSON.stringify({ ok: true, received: true, id: msgId }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } catch (err: any) {
        return new Response(JSON.stringify({ error: "Invalid JSON payload", detail: String(err) }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    return new Response(JSON.stringify({ error: "Not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  },

  /**
   * Cron Trigger Recorrente (A cada 5 minutos): Drena e reprocessa webhooks pendentes no buffer KV.
   * Garante a persistência de tentativas incrementadas no KV (anti-reset de loop).
   */
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      (async () => {
        const list = await env.FINANCE_WEBHOOKS_KV.list({ prefix: "pending:", limit: 30 });
        if (list.keys.length === 0) return;

        console.log(`Reprocessando ${list.keys.length} webhooks pendentes no buffer KV...`);
        for (const k of list.keys) {
          const raw = await env.FINANCE_WEBHOOKS_KV.get(k.name);
          if (!raw) continue;

          const msg: WebhookMessage = JSON.parse(raw);
          msg.attempts += 1;

          const ok = await dispatchWebhook(msg, env);
          if (ok) {
            await env.FINANCE_WEBHOOKS_KV.delete(k.name);
            console.log(`Webhook ${msg.id} entregue com sucesso e removido do buffer.`);
          } else if (msg.attempts >= 10) {
            // Após 10 tentativas com falha, move para DLQ permanente
            await env.FINANCE_WEBHOOKS_KV.put(`dlq:${msg.id}`, JSON.stringify(msg), { expirationTtl: 2592000 });
            await env.FINANCE_WEBHOOKS_KV.delete(k.name);
            if (env.DB) {
              await env.DB.prepare(
                `INSERT INTO webhook_dead_letter (id, provider, order_nsu, payload, reason) VALUES (?, ?, ?, ?, ?)`
              )
                .bind(msg.id, msg.provider, msg.orderNsu || "", JSON.stringify(msg.payload), "Exceeded 10 retry attempts")
                .run();
            }
            console.error(`Webhook ${msg.id} excedeu 10 tentativas. Movido para DLQ.`);
          } else {
            // Persiste contador de tentativas incrementado de volta ao KV
            await env.FINANCE_WEBHOOKS_KV.put(k.name, JSON.stringify(msg), { expirationTtl: 604800 });
          }
        }
      })()
    );
  },

  /**
   * Cloudflare Queue Consumer Handler (Quando disponível no plano)
   */
  async queue(batch: MessageBatch<WebhookMessage>, env: Env): Promise<void> {
    for (const msg of batch.messages) {
      try {
        const ok = await dispatchWebhook(msg.body, env);
        if (ok) {
          msg.ack();
        } else {
          msg.retry();
        }
      } catch (err) {
        console.error(`Falha no consumidor da fila para mensagem ${msg.id}:`, err);
        msg.retry();
      }
    }
  },
};
