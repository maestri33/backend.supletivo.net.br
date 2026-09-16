# Cloudflare Edge Webhook Worker: Finance Gateways

Worker de borda para terminação ultrarrápida (`<15ms`), validação e buffering via **Cloudflare Queues** de webhooks bancários (Asaas e InfinitePay) para a plataforma Supletivo Brasil.

## Arquitetura & Governança

- **Domínio Canônico:** Conforme a Regra 5 do `c:\rep\AGENTS.md`, este serviço de infraestrutura e utilitário opera sob `webhooks.v7m.live/bank/*` (reservando `*.supletivo.net.br` estritamente para os produtos de negócio e usuário final).
- **Proteção contra Sobrecarga:** Elimina a saturação de workers do Django causada por picos de webhooks ou chamadas síncronas de verificação para as adquirentes.
- **Garantia de Entrega:** Mensagens persistidas em fila distribuída com tolerância a falhas, retries automáticos e Dead Letter Queue (`finance-webhooks-dlq`).

## Rotas Expostas

| Rota | Provedor | Cabeçalhos Verificados | Comportamento |
|---|---|---|---|
| `POST /bank/asaas` | Asaas | `asaas-access-token` | Enfileira em `finance-webhooks-queue` e responde `200 OK` |
| `POST /bank/infinitepay` | InfinitePay | — | Enfileira em `finance-webhooks-queue` e responde `200 OK` |
| `GET /bank/health` | Health Check | — | Devolve `{"status": "healthy"}` |

## Deploy via Wrangler

```bash
cd deploy/cloudflare-workers/finance-webhooks
wrangler secret put INTERNAL_SERVICE_SECRET
wrangler secret put ASAAS_WEBHOOK_SECRET
wrangler deploy
```

## Regras de WAF Recomendadas no Cloudflare Dashboard

Crie uma regra de WAF na zona `v7m.live`:
- **URI Path**: `starts_with "/bank/"`
- **Action**: Bypass WAF ou Allow apenas para os blocos IP oficiais do Asaas e InfinitePay.
