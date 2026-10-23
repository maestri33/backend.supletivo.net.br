# Navegação e acesso — evidência final de publicação

## Código em produção

| Módulo | Versão | Identidade |
| --- | --- | --- |
| Backend | 0.0.0-sandbox.113 | imagem `sha256:3c578471b2032988d4035cef34c2e3926c863942527189eca24b62e873cd7d00` |
| App | 0.0.0-sandbox.112 | Worker `d3f272ce-b6a4-477c-aec2-c6b7e7a7cd6a` |
| Admin | 0.0.0-sandbox.114 | Worker `e5eb1905-40b3-4118-9313-f145f208a599` |

Backend artifact SHA: `5621e46c201a41932aa321034a7ab162054677d8572633b2a17582e583d49b9b`. Health público e origin confirmaram a identidade, banco acessível e zero migrações pendentes. Web e qcluster usam a mesma imagem. Nenhuma migração ou alteração de configuração financeira foi realizada nesta entrega.

Código enviado à branch `codex/production-recovery-20261010` dos três repositórios. Commits: backend `33b4fe7311646e8d7ad1bb4b43608470c5568455`; app `df6bb9a8b75206ed0f9575d319078e50ad95a0e9`; admin `c0dafbdf6aef0fc244b34d04b89f94be87ea566e`.

## Evidência de execução

- Suíte completa do backend: 910 testes passaram após a correção de papel revogado.
- App: 36 testes unitários passaram; verificação Astro sem erros/avisos; build e empacotamento Wrangler concluídos.
- Admin: 12 testes passaram; Astro sem erros/avisos; build e publicação concluídos.
- Browser autenticado em produção: cockpit e saldo consultados; lead real mostrou dados, promotor, polo, coordenador e preço; Documentos preservou o contexto Alunos.
- Browser autenticado: Novo polo abriu após consultas, apresentou promotores reais, coordenador sem seleção automática e flag padrão desmarcada. Criação/troca não submetidas.
- Browser autenticado do promotor: painel carregou, CNH, comprovante e foto da assinatura apareceram no arquivo de documentos. Após backend .113, o histórico de aluno revogado deixou de exibir aba Aluno inacessível.

## Pendências de comprovação

- A consulta real encontrou zero Student e Enrollment; não existe aluno ativo para executar o smoke de Acesso, taxas e financeiro. As telas e contratos foram publicados e exercitados na suíte, mas o fluxo autenticado de aluno ativo continua sem comprovação em produção.
- Nenhuma nova transação de Pix/cartão, repasse, taxa de parceiro ou emissão externa de matrícula foi feita neste smoke.
- Preço de lead só pode ser editado antes de existir Checkout; cobrança emitida permanece protegida. Substituição de proposta já emitida exigiria um fluxo separado para preservar o histórico e conciliar o provedor.
- Infraestrutura no admin oferece status existentes e links para Cloudflare/Azure; links não representam inventário/controle integrado dos provedores.
- Apenas o usuário homologa o resultado visual e os fluxos.

## Rollback

- Backend .113: executar `release.py rollback --expected-artifact 5621e46c201a41932aa321034a7ab162054677d8572633b2a17582e583d49b9b` no diretório `/opt/v7m-platform/releases/revoked-student-20261013-v113`. Retorna à imagem .110 `sha256:ad9647f18def7d15602a5c09c6500ef6ca7a36cef020bc8a5e6baf9253572762`; a .110 mantém os novos contratos.
- Rollback dos contratos .110: controlador em `/opt/v7m-platform/releases/access-leads-20261013-v110`, artifact `61ae0d5d507949eae92f7965414f786e9606a135ce1040e3023fc19aefdf855f`; volta para imagem .108 `sha256:671e016d818c2addb7a1cb5d4e1d2ae1fb89a597af6c9ef7dc91c74fd865be50`. Reverter também os frontends se retirar esses contratos.
- App: Worker `668a12ce-cf1e-4055-a51f-e261b181ab66`.
- Admin .114: Worker `29c7f0e3-87a2-46a5-aeb9-94cfee9b9cac` (.111).
- Rollback de código não reverte banco, pagamentos nem recursos Cloudflare. Não houve migração nesta entrega.
