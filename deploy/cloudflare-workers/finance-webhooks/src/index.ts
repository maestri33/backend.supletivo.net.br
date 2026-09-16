/**
 * Cloudflare Edge Webhook Worker for Financial Gateways (Asaas & InfinitePay).
 *
 * Responsibilities:
 * 1. Rapid Acknowledgment (<15ms): Terminates gateway HTTP requests immediately with HTTP 200,
 *    preventing timeout retry storms and worker pool exhaustion in Django.
 * 2. Queue Buffering: Enqueues validated webhook payloads into Cloudflare Queues (`finance-webhooks-queue`).
 * 3. Controlled Consumption: Dispatches queued events in regulated batches to the Django backend
 *    via an internal authenticated endpoint (`/api/internal/webhooks/ingest/`).
 */

export interface Env {
  FINANCE_WEBHOOKS_QUEUE: Queue<WebhookMessage>;
  BACKEND_INGEST_URL: string;
  INTERNAL_SERVICE_SECRET: string;
  ASAAS_WEBHOOK_SECRET?: string;
}

export interface WebhookMessage {
  id: string;
  provider: "asaas" | "infinitepay";
  receivedAt: string;
  url: string;
  headers: Record<string, string>;
  payload: unknown;
  clientIp: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const clientIp = request.headers.get("CF-Connecting-IP") || "0.0.0.0";

    // Health check endpoint
    if (url.pathname === "/health" || url.pathname === "/bank/health") {
      return new Response(JSON.stringify({ status: "healthy", timestamp: new Date().toISOString() }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Only accept POST for webhooks
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 1. Asaas Webhook Endpoint: /bank/asaas
    if (url.pathname.endsWith("/bank/asaas")) {
      const token = request.headers.get("asaas-access-token");
      if (env.ASAAS_WEBHOOK_SECRET && token !== env.ASAAS_WEBHOOK_SECRET) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      try {
        const payload = await request.json();
        const msg: WebhookMessage = {
          id: crypto.randomUUID(),
          provider: "asaas",
          receivedAt: new Date().toISOString(),
          url: request.url,
          headers: {
            "asaas-access-token": token || "",
            "content-type": request.headers.get("content-type") || "application/json",
          },
          payload,
          clientIp,
        };

        await env.FINANCE_WEBHOOKS_QUEUE.send(msg);

        return new Response(JSON.stringify({ ok: true, queued: true, id: msg.id }), {
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

    // 2. InfinitePay Webhook Endpoint: /bank/infinitepay
    if (url.pathname.endsWith("/bank/infinitepay")) {
      try {
        const payload = await request.json();
        const msg: WebhookMessage = {
          id: crypto.randomUUID(),
          provider: "infinitepay",
          receivedAt: new Date().toISOString(),
          url: request.url,
          headers: {
            "content-type": request.headers.get("content-type") || "application/json",
          },
          payload,
          clientIp,
        };

        await env.FINANCE_WEBHOOKS_QUEUE.send(msg);

        return new Response(JSON.stringify({ ok: true, queued: true, id: msg.id }), {
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
   * Cloudflare Queue Consumer: Processes batches of bank webhook events and posts to Django.
   */
  async queue(batch: MessageBatch<WebhookMessage>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      try {
        const response = await fetch(env.BACKEND_INGEST_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${env.INTERNAL_SERVICE_SECRET}`,
            "X-Service-Secret": env.INTERNAL_SERVICE_SECRET,
            "X-CF-Connecting-IP": message.body.clientIp,
          },
          body: JSON.stringify(message.body),
        });

        if (response.ok) {
          message.ack();
        } else if (response.status >= 400 && response.status < 500) {
          // Client errors (invalid schema / bad signature) should not loop indefinitely
          console.error(`Backend rejected webhook message ${message.body.id} with status ${response.status}`);
          message.ack();
        } else {
          // 5xx or network errors trigger queue retry with exponential backoff
          console.warn(`Backend transient error ${response.status} for message ${message.body.id}, retrying...`);
          message.retry();
        }
      } catch (err) {
        console.error(`Failed to dispatch message ${message.body.id} to backend:`, err);
        message.retry();
      }
    }
  },
};
