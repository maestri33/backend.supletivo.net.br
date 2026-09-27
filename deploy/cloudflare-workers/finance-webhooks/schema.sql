-- D1 Database Schema para Gateway de Webhooks Financeiros (webhooks.v7m.live)
-- Suporta Asaas (Pix) e InfinitePay (Cartão de Crédito) com auditoria imutável

CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    order_nsu TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_order_nsu ON webhook_events(order_nsu);
CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON webhook_events(status);
CREATE INDEX IF NOT EXISTS idx_webhook_events_provider ON webhook_events(provider);
CREATE INDEX IF NOT EXISTS idx_webhook_events_created_at ON webhook_events(created_at);

CREATE TABLE IF NOT EXISTS webhook_dead_letter (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    order_nsu TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_webhook_dlq_order_nsu ON webhook_dead_letter(order_nsu);
CREATE INDEX IF NOT EXISTS idx_webhook_dlq_created_at ON webhook_dead_letter(created_at);
