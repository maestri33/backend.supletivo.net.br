# Pendências de lançamento beta do Supletivo

Leituras concluídas até 14/10/2026, 10h40, America/Sao_Paulo. Escopo desta execução: inspeção em leitura e correção do ledger em dois arquivos combinados com o responsável financeiro. Somente o proprietário homologa a entrega. Este registro não promove a plataforma para beta.

## Estado observado

| Cenário | Esperado | Obtido agora | Classificação |
| --- | --- | --- | --- |
| Oráculo e health backend | Identidade de release coerente | Ambos `0.0.0-sandbox.119`; health DB=true, migrações pendentes=0; artefato `0e6ced6c56dc424531aa2a618b33413f00c8568c404820a4b99dd4b61508697c` | Observado; divergência .118/.119 do handoff superada |
| Containers backend | Web e consumidor identificados | Ambos `v7m-backend:tts-direct-20261014-v119`; biometria `v7m-biometric:selfie-recovery-v97` | Observado por SSH; não comprova jornada |
| Configuração Django efetiva | Ambiente real identificado | APP_ENV=prod, TEST_MODE=false, TEST_EXTERNAL_ADAPTERS=false, ASAAS_BASE_URL=https://api.asaas.com, BIOMETRIC_ENABLED=true | Observado dentro do web |
| Recebimentos contabilizados | Pagamentos rastreáveis no ledger | FinancialTransaction: somente 1 commission_accrued, zero payment_received | Observado por consulta agregada; sem alteração de saldo |
| Matrículas atuais | Vínculo efetivo após pagamento | Enrollment=0, Student=0; Lead: 3 pending e 1 paid | Observado; histórico pago exige classificação, sem restaurar papéis automaticamente |
| Recuperação durável | Agenda ativa após implantação financeira | payment_event_recovery inexistente no runtime .119; OrmQ=0 e Failure=0 | Observado antes do release financeiro; fila vazia não prova entrega |
| Alertas Sentry | Captura de exceções operacional | settings.SENTRY_DSN vazio; bootstrap chama init_sentry, que é no-op sem DSN | Observado em configuração e código; alertas alternativos não verificados |
| Landing pública | Versão servida identificável | Rodapé `v0.0.0-sandbox.72`; preços sem indicação R$1.615 Pix ou 12×R$159,90; CTA abre modal Sofia/WhatsApp | Observado no navegador; oráculo apps=.119 não comprova runtime da landing |
| Modelo biométrico | Pesos e licença identificados | Container configurado MODEL_NAME=buffalo_l, MODEL_ROOT=/models | Observado; contrato/licença comercial não localizado nesta execução |

## Correção financeira preparada

`finance/interface/ledger.py` agora oferece `record_lead_receipt(*, attempt)` com chave `lead_receipt_{attempt.external_id}` e referência da tentativa. O responsável financeiro integra a chamada no primeiro recebimento, repetição aplicada e pagamento adicional, dentro da transação de negócio.

Com Asaas, líquido e taxa só são contabilizados quando `confirmation_payload.value/netValue`, o valor contratado e `Payment.net_value` concordam. Sem essa prova, o ativo permanece recebível pendente separado de ASSET_ASAAS. InfinitePay possui ASSET_INFINITEPAY nominal e pendente, com líquido/taxa desconhecidos explícitos. Acréscimo pago pelo comprador é registrado como evidência, sem presumir que seja receita líquida do comerciante. Outra cobrança da mesma proposta credita passivo de recebimento adicional em revisão.

Partidas existentes não são reescritas quando chegar prova posterior do líquido. A liquidação posterior exige lançamento separado e vínculo auditável. A função não verifica o provedor por rede: essa responsabilidade continua no fluxo financeiro que a chama. Não substitui teste PostgreSQL concorrente nem comprovação do canário pago.

Evidência controlada: 16 testes novos em `tests/test_payment_receipt_ledger.py` passaram, incluindo bruto/líquido/taxa Asaas, líquido ausente/divergente, InfinitePay, cobrança adicional, rollback e colisão da chave única. Os 7 testes existentes de ledger também passaram. O tratamento de IntegrityError usa savepoint para preservar a transação externa na colisão. Nenhum desses testes é prova de movimentação real.

O achado inicial sobre prefixo `no_matching_charge` foi retirado após conferir a normalização já presente na frente concorrente. Não deve permanecer como lacuna aberta.

## Bloqueios e próxima evidência

1. **Publicação financeira integrada:** concluir suíte completa e artefato revisado; confirmar no runtime migrações, chamadas do ledger e agenda de recuperação. O chat “Mapear arquitetura e produção (5)” mantém integração, commit e publicação. A publicação do app deve incorporar os deadlines do chat “Mapear arquitetura e produção (3)”.
2. **Canário real atual:** após publicação, classificar a tentativa existente e combinar um único operador. Provar proposta → provedor → matrícula → comissão → ledger → recibo → notificação. Não recriar usuários ou cobrar novamente para contornar o histórico. Pagamento e selfie ao vivo dependem do titular. A leitura de payment_check antigo base101/bruto107, informada pelo chat financeiro, é histórico do provedor, não uma nova jornada concluída.
3. **Biometria:** comprovar positivo/negativo e captura ao vivo sem relaxar aprovação. A [política oficial InsightFace](https://github.com/deepinsight/insightface#license) distingue código MIT de modelos distribuídos para pesquisa não comercial e informa licenciamento separado de buffalo_l. Confirmar autorização aplicável aos pesos efetivamente carregados. Licença contratada é não verificada; não afirmar inexistência.
4. **Operação:** comprovar alertas de exceção, fila parada e confirmação sem aplicação; responsável por recuperação; backup e restauração em ambiente isolado. O controller existente registra `restore_tested=False`; isso não comprova que ninguém executou restauração por outro procedimento. Evidência atual de restauração permanece não verificada.
5. **Jornadas restantes:** endereço, escolaridade, contrato sem placeholder, ativação do promotor, taxas/parceiro e autorização por polo; fechamento/estornos/compensações com testes pertinentes. Ausência de matrícula atual impede alegar aluno ativo exercitado. Prova e diploma futuros precisam regras temporais testadas sem adulterar pagamento ou fabricar documentação em produção.

Este arquivo e a correção preparada não foram publicados por este chat. O responsável financeiro pode integrar os arquivos revisados; a versão efetivamente servida deve ser conferida novamente após o release.

## Atualização de coordenação

O responsável por deadlines informou publicação do app `.120`, commit `70abeb6d33647eb5ca80c94209339cad7fc96b52`, Worker `754f30c3-362b-4256-b18b-13b1f98803a4`. Informou 5 testes de transporte, 20 casos de navegador e typecheck/build passando, com indisponibilidade controlada. Trata-se de evidência fornecida por outro chat; não foi repetida por esta execução. O responsável financeiro deve preservar esse HEAD no build posterior. As chamadas de `record_lead_receipt` já foram observadas na integração local de `mark_paid`; isso não comprova publicação financeira.
