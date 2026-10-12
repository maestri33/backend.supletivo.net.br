import assert from "node:assert/strict";
import { test } from "node:test";
import { timingSafeEqual } from "node:crypto";
import worker from "../src/index.ts";

Object.assign(crypto.subtle, { timingSafeEqual });

function context() {
  const promises: Promise<unknown>[] = [];
  return { promises, waitUntil: (promise: Promise<unknown>) => promises.push(promise) };
}

function request(provider = "infinitepay") {
  return new Request(`https://webhooks.v7m.live/bank/${provider}`, {
    method: "POST", headers: { "Content-Type": "application/json", "asaas-access-token": "unit-secret" },
    body: JSON.stringify({ event: "unit-ingestion", payment: { id: "unit-payment" } }),
  });
}

test("does not acknowledge before Queue confirms persistence", async () => {
  let release!: () => void;
  const storage = new Promise<void>((resolve) => { release = resolve; });
  let responded = false;
  const result = worker.fetch(request(), { FINANCE_WEBHOOKS_QUEUE: { send: () => storage } } as any, context() as any);
  void result.then(() => { responded = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(responded, false);
  release();
  assert.equal((await result).status, 200);
});

test("returns retryable failure when Queue and KV storage both fail", async () => {
  const fail = async () => { throw new Error("unit storage offline"); };
  const result = await worker.fetch(request(), {
    FINANCE_WEBHOOKS_QUEUE: { send: fail }, FINANCE_WEBHOOKS_KV: { put: fail },
  } as any, context() as any);
  assert.equal(result.status, 503);
  assert.equal((await result.json() as any).error, "Webhook storage unavailable");
});

test("persists KV before dispatch and never stores the Asaas credential", async () => {
  let stored: any;
  let dispatched = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, init) => {
    assert.ok(stored);
    assert.equal((init?.headers as any)["asaas-access-token"], "unit-secret");
    dispatched = true;
    return new Response("{}", { status: 200 });
  };
  try {
    const ctx = context();
    const result = await worker.fetch(request("asaas"), {
      ASAAS_WEBHOOK_SECRET: "unit-secret", BACKEND_ASAAS_URL: "https://backend.supletivo.net.br/integrations/asaas/webhook/",
      FINANCE_WEBHOOKS_KV: { put: async (_key: string, value: string) => { stored = JSON.parse(value); }, delete: async () => {} },
    } as any, ctx as any);
    assert.equal(result.status, 200);
    assert.equal(JSON.stringify(stored).includes("unit-secret"), false);
    await Promise.all(ctx.promises);
    assert.equal(dispatched, true);
  } finally { globalThis.fetch = originalFetch; }
});

test("fails closed when Asaas authentication is not configured", async () => {
  assert.equal((await worker.fetch(request("asaas"), {} as any, context() as any)).status, 503);
});
