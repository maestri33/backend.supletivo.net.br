# Plano de prontidão para produção

## Objetivo

Levar o backend a uma versão que possa ser promovida para produção com configuração validada,
dependências reproduzíveis, migrações reversíveis, integrações verificadas e rollback definido.

Uma suíte verde não prova sozinha que o ambiente real está correto. A garantia operacional será dada
por gates obrigatórios: nenhum segredo na imagem, configuração de produção fail-fast, banco e fila
saudáveis, smoke tests sem movimentar dinheiro e observação do canário antes do cutover.

## Estado atual verificado

- 615 testes passam localmente.
- `manage.py check` não encontrou erros e `makemigrations --check --dry-run` não encontrou migrações pendentes.
- O `.env` local resolve `APP_ENV=prod` com `DEBUG=true`, CORS aberto e URLs locais; isso é configuração de desenvolvimento incompatível com produção.
- `check --deploy` ainda acusa DEBUG, chave secreta fraca, ausência de HSTS, redirect SSL, cookies seguros e Sentry.
- O `.dockerignore` não exclui `.env`, `.env.*`, `keys/` ou outros artefatos locais.
- `edge-tts` é instalado no Docker fora do `pyproject.toml`/`uv.lock`, tornando o runtime diferente do lock.
- O CI executa testes, mas não há pipeline versionado para promover o backend da branch principal até a VM Azure (`vm-v7m-core` em `/opt/v7m-platform`).
- O Worker financeiro aceita o webhook Asaas quando `ASAAS_WEBHOOK_SECRET` está vazio e armazena payloads completos no D1 sem política de retenção explícita.

## Fases e commits pequenos

### Fase 0 — congelar o ponto de partida

1. Separar as mudanças atuais de funcionalidade e seus testes em uma branch de release.
2. Registrar o SHA de origem, o resultado dos 615 testes e o estado do banco local.
3. Não misturar limpeza de infraestrutura com mudanças de regra de negócio.

Gate: branch reproduzível, `git diff --check` limpo e nenhuma credencial versionada.

### Fase 1 — fechar o perímetro de segredos e da imagem

1. Excluir do contexto Docker `.env`, `.env.*`, `keys/`, banco local, mídia, caches, artefatos do Wrangler e `node_modules`.
2. Adicionar uma verificação CI que falhe se arquivos de segredo ou chaves privadas forem rastreados ou enviados ao build.
3. Colocar `edge-tts` nas dependências declaradas e regenerar `uv.lock`; remover o `uv pip install` extra do Dockerfile.
4. Fixar versões/digests da imagem Python e do binário `uv` usados no build.
5. Fazer o build em CI e iniciar o container com um `.env` de produção sintético, sem chamar gateways.

Gate: a imagem não contém `.env`, chaves, banco ou mídia; `uv sync --frozen` instala exatamente o runtime testado.

### Fase 2 — contrato de configuração de produção

1. Criar um comando read-only de validação de produção que mostre somente presença/ausência e valores não sensíveis.
2. Fazer o boot falhar explicitamente quando `APP_ENV=prod` combinar-se com `DEBUG=true`, `TEST_MODE=true`, adaptadores sintéticos, CORS wildcard, banco SQLite ou URLs HTTP públicas.
3. Exigir em produção: `SECRET_KEY` forte, `ALLOWED_HOSTS` explícito, `CORS_ALLOW_ALL_ORIGINS=false`, origens CORS/CSRF HTTPS, `EXTERNAL_URL`/`FRONTEND_URL` canônicos, PostgreSQL, chaves JWT persistentes, R2 configurado e `SENTRY_DSN`.
4. Validar `DATABASE_URL_UNPOOLED` para migrações e separar o caminho de leitura do pooler.
5. Manter `core.prod_settings` compatível, mas validar o `DJANGO_SETTINGS_MODULE` realmente usado pelos serviços systemd; não trocar isso diretamente na máquina viva.

Gate: `manage.py check --deploy` sem avisos de segurança e o comando de configuração passa somente com o contrato completo.

### Fase 3 — segurança das superfícies HTTP

1. Confirmar `SECURE_PROXY_SSL_HEADER`, cookies Secure/HttpOnly/SameSite e HSTS no proxy que termina TLS.
2. Testar que mídia privada exige JWT, que traversal é bloqueado e que URLs públicas não expõem documentos.
3. Exigir segredo de serviço no Worker e no endpoint Django de webhook; em produção, segredo ausente deve responder fail-closed.
4. Rotacionar segredos que tenham aparecido em histórico, logs ou ambientes de desenvolvimento; atualizar o cofre e os serviços de forma coordenada.
5. Revisar o Worker financeiro para redigir PII antes do D1, limitar retenção e monitorar a DLQ.

Gate: testes automatizados para 401/403, webhook sem segredo, CORS, mídia e retenção; nenhuma rota de dinheiro aceita autenticação implícita.

### Fase 4 — dados e migrações

1. Fazer backup verificável do PostgreSQL no host de banco Azure `vm-v7m-core` (`/opt/v7m-platform`).
2. Rodar `migrate --plan`, `migrate --check` e validação de integridade em uma cópia/staging.
3. Aplicar somente migrações retrocompatíveis antes do código que depende delas.
4. Registrar contagem e estado de filas Django-Q antes e depois da migração.
5. Definir rollback de código separado de rollback de schema; migrações destrutivas ficam em release posterior.

Gate: restauração do backup testada, zero migrações pendentes e nenhuma fila perdida.

### Fase 5 — contratos e integrações

1. Gerar OpenAPI de todos os grupos Ninja e executar Schemathesis/fuzzing no staging.
2. Executar smoke read-only autenticado para `/healthz`, quatro health groups, `/system` e `/health/full`.
3. Verificar Asaas com saldo/webhook de leitura ou sandbox; nunca usar criação de cobrança em smoke test.
4. Verificar Notify, OmniRoute/TTS, Cloudflare/R2, Turnstile, CPFHub, ViaCEP e serviço biométrico com probes que não gerem efeitos irreversíveis.
5. Testar explicitamente o fluxo de falha do Asaas: retry Django-Q, idempotência por `payment_id`, DLQ e alerta.
6. Para InfinitePay e Worker, enviar somente eventos sintéticos de sandbox e confirmar entrega idempotente no backend.

Gate: cada integração crítica tem resultado `configured + reachable + authenticated`, ou uma decisão explícita de indisponibilidade aceitável.

### Fase 6 — observabilidade e operação

1. Configurar Sentry/GlitchTip com release igual ao SHA, scrub de PII e alertas de erro.
2. Criar alertas para health failing, `migrations_pending`, qcluster inativo, fila crescendo, webhook retry/DLQ, falhas de TTS e saldo insuficiente.
3. Versionar um runbook de deploy contendo comandos read-only, critérios de sucesso e sinais esperados do qcluster após reinício.
4. Fixar retenção e acesso aos logs do D1, Django e Sentry.

Gate: um operador consegue detectar e classificar falha sem acessar valores de segredos ou payloads sensíveis.

### Fase 7 — pipeline de release e canário

1. Expandir o CI para incluir `check --deploy`, validação de configuração, secret scan, build da imagem, migrações e OpenAPI.
2. Criar workflow de backend com ambiente protegido e aprovação explícita para produção.
3. Publicar artefato imutável identificado pelo SHA; não reconstruir a imagem no cutover.
4. No staging, executar backup, migração, smoke tests, teste de fila e jornada sintética de lead/candidato/aluno.
5. Em produção, promover primeiro uma instância/canário, observar por janela definida e só então reiniciar web/qcluster integralmente.
6. Após o cutover, executar a bateria read-only descrita em `HANDOFF_ARQUITETURA_V7M.md` e registrar `deploy OK @ <sha>`.

Gate: canário saudável, quatro health endpoints verdes, `migrations_pending=0`, qcluster vivo, sem erros novos no log e sem crescimento anormal da fila.

### Fase 8 — rollback comprovado

1. Manter a imagem anterior e o SHA anterior disponíveis.
2. Definir rollback automático/manual para falha de health, erro de autenticação, webhook ou fila.
3. Se o schema for incompatível, restaurar o backup conforme o runbook; não tentar corrigir banco vivo por edição manual.
4. Após rollback, repetir health, fila, webhook sintético e leitura do ledger financeiro.

Gate: rollback testado em staging antes do primeiro cutover real e tempo de recuperação registrado.

## Critérios finais de aceite

- Configuração de produção passa sem avisos de segurança.
- Imagem é reproduzível e não contém segredos.
- Todos os testes automatizados passam; OpenAPI e migrações estão estáveis.
- PostgreSQL, R2, JWT, qcluster, webhooks, notificações e observabilidade foram verificados no staging.
- Backup e rollback foram ensaiados.
- O canário passou pela janela de observação sem regressões.

Até esses gates serem cumpridos, não é possível afirmar que o sistema está garantido em produção; é possível apenas afirmar que o código passa nos testes locais.

## Fora de escopo

- Alterar regras comerciais, preços, comissões ou payouts.
- Mover dinheiro real durante testes.
- Editar diretamente a LXC viva ou o host Proxmox.
- Comitar `.env`, chaves, payloads de produção ou dumps do banco.
