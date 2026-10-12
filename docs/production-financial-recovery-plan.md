# Recuperação de cobrança e processamento em produção

Data: 9 de outubro de 2026. Destino canônico: VM Azure `vm-v7m-core`, `/opt/v7m-platform`.
Este plano substitui qualquer referência a Proxmox/LXC no plano financeiro. As operações de
produção pertencem ao integrador da sessão. As alterações abaixo estão locais até sua promoção.

## Evidência e prioridade

| Evidência | Consequência | Correção essencial | Estado |
| --- | --- | --- | --- |
| Auditoria do integrador: Asaas efetivo usa placeholder e leitura autenticada retorna 401; PlatformSetting vazia | O gateway não pode emitir PIX oficial | Recuperar a credencial correta em fonte autorizada, configurar fora da imagem e repetir leitura autenticada | Bloqueio externo de configuração |
| Auditoria do integrador: InfinitePay handle efetivo é placeholder | Recebedor/configuração comercial não comprovados | Recuperar handle da conta real; não criar cobrança para tentar adivinhar | Bloqueio externo de configuração |
| `static_qr.py` fabricava BR Code e ID `FALLBACK_` quando o Asaas falhava | A interface apresentava uma cobrança inexistente como pronta | Propagar indisponibilidade; exigir ID e payload oficiais; impedir reutilização de fallback legado | Implementado localmente |
| `core/tasks.py` aceitava threads em produção e executava tarefa inline se o broker falhasse | Jobs somem em reinícios; falha de enfileiramento pode executar efeitos de forma inesperada | Manter threads no backend-web para economia de memória na VM Azure e qcluster dedicado no notify-qcluster; broker com fallback resiliente | Conforme arquitetura canônica |
| Retry terminal gravava FAILED sem reler checkout/pagamento | Um job velho podia encerrar uma cobrança nova ou já paga | Travar Lead e Checkout na mesma ordem; conferir identidade, pagamento e construção atuais | Implementado localmente |
| Troca de checkout mantinha Lead FAILED | Recuperação deixava o estado da role incorreto | Reabrir PENDING e limpar motivo ao criar checkout substituto; despachar após commit | Implementado localmente |
| Aplicação de webhook com exceção podia devolver sucesso | Remetente/edge parava de tentar antes dos efeitos necessários | Evento bruto permanece salvo; erro de aplicação e falha temporária do payment_check propagam | Implementado localmente |
| Confirmar pagamento e consumir eventos de falha usavam objetos lidos antes da transação | Concorrência podia repetir efeitos ou rebaixar pagamento | Reler sob lock antes da decisão; pagamento confirmado prevalece sobre falha/expiração | Implementado localmente |
| Fila de documentos exigia external_id ausente e lia rg_reviews/selfie_reviews em resposta rg/selfie | Itens desapareciam ou toda a fila retornava 500 | Contrato HTTP com IDs estáveis e chaves reais; comprovantes review/needs_kinship expostos | Implementado localmente |
| Funções desacopladas da fachada ficaram sem helpers importados | GET de revisões e decisão de comprovante falhavam em runtime | Reconectar helpers já existentes; manter regras e gates do polo | Implementado localmente |

Os três leads sem checkout observados pelo integrador não provam falha: o funil cria o checkout
quando o cliente escolhe a forma de pagamento. O alerta depende de método escolhido/checkout
solicitado, não apenas da existência de um lead.

## Fluxo mínimo necessário

1. Captura e autenticação persistem usuário, papel e lead; o preço comercial continua o snapshot existente.
2. Escolher pagamento cria intenção local e agenda o provider no ORM depois do commit.
3. O provider precisa responder com uma cobrança oficial. Erro mantém indisponibilidade explícita;
   após cinco tentativas, somente o checkout ainda atual e não pago pode levar o lead a FAILED.
4. O webhook chega autenticado, é persistido e conciliado pelo adaptador do gateway. InfinitePay
   continua exigindo payment_check fora do payload recebido.
5. Confirmar pagamento trava o estado atual, marca PAID e executa os efeitos já existentes na mesma
   transação: matrícula no polo herdado e comissão conforme as regras atuais. Não altera valores.
6. Replay do mesmo pagamento não recria efeitos. Exceção nos efeitos essenciais continua recuperável
   por nova entrega. Analytics e notificações dependem de seus próprios despachos e observabilidade.
7. A matrícula mantém coleta de documentos, revisão e entrega ao parceiro. A fila do coordenador
   precisa expor cada documento/estado e o endpoint de decisão correspondente.

Enfeites de avatar, voz opcional e dashboards auxiliares não substituem autenticação, cobrança,
conciliação, estados persistentes e entrega de notificações. Health HTTP 200 e teste sintético
isoladamente também não comprovam estes fluxos reais.

## Promoção e recuperação no Azure

1. Antes do cutover: guardar imagem/configuração anterior e snapshot sanitizado dos estados de Lead,
   Checkout, Payment, WebhookEvent, OrmQ, Schedule e PaymentRequest. Fazer backup PostgreSQL.
2. Confirmar credenciais efetivas por presença e leitura autenticada, sem imprimir valores secretos.
   Corrigir os placeholders antes de chamar o gateway novamente.
3. Auditar os schedules e PaymentRequests existentes antes de iniciar qcluster. O comando
   `finance_schedules` habilita envio automático de payouts; não faz parte de um smoke test.
4. Promover web e qcluster com a mesma imagem/configuração, `TASK_BACKEND=django_q`, ORM no PostgreSQL
   e JWT/mídia persistentes. Confirmar que a imagem não contém o .env local.
5. Auditar especificamente registros `FALLBACK_`: não equivalem a cobranças oficiais. Preservar o
   histórico, conferir ausência de pagamento real e invalidar o checkout sintético, payload/URL e cache
   associados. Remover o código do fallback não corrige sozinho os dados já gravados.
6. Para checkouts oficiais: consultar o gateway e conciliar IDs existentes antes de recriar qualquer
   cobrança. Para eventos persistidos não aplicados: reprocessar individualmente de forma idempotente,
   preservando trilha de auditoria. Não inferir PAID a partir de status da interface.
7. Confirmar que o Worker financeiro confirma recepção somente depois de uma gravação durável e que
   erro do origin gera retry/DLQ. Essa implementação pertence ao integrador.
8. Observar erros, atraso de fila e crescimento de eventos não aplicados. Se houver regressão,
   restaurar a imagem anterior mantendo banco, chaves e trilha de eventos.

## Verificação técnica e critério de operação

- Regressões locais cobrem provider fora/incompleto, QR legado, checkout substituído/pago durante retry,
  reabertura de método, webhook temporariamente indisponível, falha do broker sem execução inline,
  persistência ORM de jobs/schedules e contrato/decisões da fila do polo.
- Suíte completa em 9 de outubro: **641 passed** (`.venv\\Scripts\\python.exe -m pytest -q --tb=short`,
  39,07 s). `compileall` dos arquivos alterados passou e `git diff --check` não encontrou erros.
  O pytest usa SQLite isolado; isso não comprova locking concorrente no PostgreSQL de produção.
- Em produção, requer Asaas autenticado, handle real conhecido, qcluster vivo com mesmo release,
  jobs/schedules que sobrevivem ao reinício, webhook autenticado e retry durável, zero QR sintético
  exposto, pagamento conciliado sem efeitos duplicados e fila do polo HTTP 200 com os IDs corretos.
- O primeiro pagamento real deve ser acompanhado pelo seu ID do gateway até matrícula/comissão e
  notificação. Não criar cobranças nem transferências reais apenas para testar.
- Aceite e homologação pertencem ao usuário. Testes locais não são uma declaração de operação plena.

## Limites ainda relevantes

O modelo atual de troca de método apaga a linha anterior de Checkout. Links tardios de cartão podem
continuar existentes no provider e cair no log de pagamento sem consumidor. Esse caso exige
conciliação pelo registro do gateway; uma tabela de histórico/migração não foi improvisada nesta
correção de incidente. O mutex atual de construção também usa cache com TTL: a operação precisa
de canário concorrente em PostgreSQL e avaliação de locking compartilhado antes de tratar builds
de cartão entre múltiplos processos como plenamente comprovados. Esses riscos não se resolvem
com páginas de aparência funcional.
