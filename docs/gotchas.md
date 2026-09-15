# Gotchas — lições que o código não conta

> Resgatado da wiki removida em 2026-08-18. Só o que ainda morde: armadilhas de
> integração, ambiente e semântica que não são óbvias no código e já custaram horas.

## Asaas

- **Auth de webhook NÃO é HMAC.** O legado validava com HMAC `asaas-signature` — esse
  header **não existe** na doc oficial; era invenção (delírio de IA consolidado). A auth
  real de tudo que o Asaas chama de volta é **só o header `asaas-access-token`** ==
  `ASAAS_WEBHOOK_SECRET` no `.env` (comparação tempo-constante em
  `integrations/bank/asaas/security.py`). Filtro por IP oficial foi dispensado (decisão
  do dono).
- **A api-key começa com `$` (`$aact_…`) e o django-environ trata `$` como proxy** → no
  `.env` e no `env_file` do Compose precisa de `$$`. O settings lê via `os.environ`
  literal pra escapar disso.
- **`EXTERNAL_URL` não pode ter comentário inline** — django-environ engole o resto da
  linha.
- **Validar chave Pix MEXE na API real**: cria uma transferência de **R$0,01 AGENDADA**
  pro dia seguinte (o Agendado resolve o DICT) e cancela em seguida
  (`asaas/pixkey.py`). Confere titularidade vs CPF do profile. Não há guarda de
  TEST_MODE: com key de produção, é produção.
- **Transfer-validation**: o Asaas chama `POST /integrations/asaas/transfer-validation/`
  ~5s após **cada** PIX-out pedindo APPROVED/REFUSED — precisa de `EXTERNAL_URL`
  publicamente alcançável, senão toda saída vira `FAILED`.

## InfinitePay

- **Não usa api-key**: autentica só pelo `handle` (InfiniteTag). O HMAC
  `x-infinitepay-signature` + IP-allowlist do legado era delírio — a segurança real é o
  **`payment_check`**: o webhook só marca PAID depois de reconfirmar o pagamento direto
  na API. O `order_nsu` (= nosso `external_id`) liga o webhook ao checkout.
- **Handle é case-sensitive** (`v7m` minúsculo; `V7M` → "Merchant not found").

## Biometria (InsightFace/ArcFace)

- **Score = cosseno dos embeddings, NÃO é porcentagem.** Escala prática ~0.2–0.7;
  mesma pessoa ~0.4–0.7; pessoas diferentes <0.3. Thresholds no `.env`
  (`BIOMETRIC_MATCH_THRESHOLD=0.35`, `BIOMETRIC_REVIEW_THRESHOLD=0.28`). Fail-safe:
  modelo fora/sem rosto → `review`, nunca passa em silêncio.

## Dinheiro (invariante)

- Idempotência **no banco**, nunca em memória: `external_reference` unique
  (`PaymentRequest`), `unique(source_type, source_external_id)` (`Commission`), ref
  determinística `fee_enr_{external_id}_now/_due` (taxa). Re-rodar fechamento da mesma
  semana = no-op.
- Webhook não é a única fonte de verdade: reconciliação ativa lê `get_transfer` /
  `refresh_payout` (worker).

## Testes / ambiente

- Rodar a suíte **dentro do container**: o `env_file` do Compose injeta
  `DATABASE_URL=postgres://…@db` e vence a sobrescrita do `conftest` — forçar
  `-e DATABASE_URL="sqlite:///:memory:"` no `docker compose run` (ou subir o `db`).
  A imagem slim **não tem `git`**: `tests/test_sentry.py::test_git_sha_*` só passa
  onde o git existe (CI passa; container não).
- No SQLite todo `select_for_update` é **no-op** — corridas só são exercitadas de
  verdade em Postgres (o CI do branch da auditoria aponta pra um Postgres de serviço).

## Repo

- **Rename**: `backend-supletivo` → `backend-v7m` (2026-08). Nada de nome de repo
  hardcoded — ler de `GITHUB_REPOSITORY`/env.
