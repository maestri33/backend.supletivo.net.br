# Pagamentos: implementação e publicação de 14/10/2026

Escopo autorizado: integrar a solução de pagamentos no backend, app e admin e publicar após os testes. Infraestrutura principal preservada na Azure; frontends continuam nos Workers Cloudflare. Nenhum serviço financeiro novo foi contratado.

## Comportamento implementado

- A proposta preserva o preço capturado. Repetir o mesmo método retoma a mesma cobrança e o mesmo link.
- Cada cobrança possui histórico `PaymentAttempt`, com identificadores originais do lead e usuário. Trocar método conserva as referências anteriores. Excluir uma conta não permite aplicar sua cobrança em uma conta recriada.
- A intenção InfinitePay é vinculada ao lead antes da rede. Timeout ou resposta incerta bloqueia uma segunda emissão automática. A API pública não documenta idempotência remota de `POST /links`; não foi presumida.
- Webhooks são gravados antes do HTTP 200. Django-Q processa os eventos com lease persistente; o schedule `payment_event_recovery` roda a cada minuto, com lote pequeno para respeitar o tempo do worker. Falhas têm retry com backoff, limite de dez tentativas e revisão no admin após esgotar.
- `forwarded_ok` significa consumo pelo domínio de negócio. Recebimento confirmado sem aplicação no app continua visível como pendência.
- InfinitePay confere `amount` e `paid_amount`, transação, fatura e handle original. Callback duplicado não substitui o recibo persistido nem aceita outra transação.
- Asaas confere o valor bruto da cobrança, inclusive QR estático identificado por `pixQrCodeId`.
- Retorno do cartão só é consultado após conferir que a cobrança pertence ao usuário autenticado. Query string e navegador não provam pagamento.
- Matrícula, comissão e lançamento do recebimento são aplicados sob lock do lead e na mesma transação. Recebimento adicional fica em revisão e não gera outra comissão ou matrícula.
- Ledger conserva valor contratado e adicional pago pelo comprador. Asaas só apresenta líquido e taxa quando comprovados. InfinitePay e Asaas têm contas distintas; líquido desconhecido gera recebível pendente, nunca saldo disponível inventado.
- App mostra falha de consulta e cópia do Pix de forma explícita. Página Pix pública não leva um visitante anônimo para a matrícula de outra pessoa. Dock tem uma fase ativa por vez.
- Admin distingue consulta indisponível de zero, rascunho de configuração salva e confirmação do provedor de aplicação no app. Reconciliação não emite cobrança nem confirma dinheiro manualmente.

## Evidência técnica e limites

Suíte completa do backend: **967 testes passaram** após integração de histórico, reconciliação e ledger. Migrações estão coerentes com os models (`makemigrations --check`: sem alterações pendentes). As fronteiras externas são controladas nos testes automatizados; isso não representa pagamento real da nova jornada.

Frontend app: 36 testes unitários e typecheck passaram. Admin: 26 testes e Astro check passaram. Evidência de browser e identidades de publicação são registradas nos logs e no resultado operacional desta release.

Consulta somente leitura da InfinitePay em produção: canário antigo com base de 101 centavos, pago 107 centavos, uma parcela e `credit_card`, ambos confirmados por `payment_check`. Nenhuma cobrança ou pagamento novo foi criado por essa consulta. Esse registro era um teste direto do provedor e não foi transformado em matrícula.

Antes desta publicação não havia Enrollment/Student em produção, e havia um lead histórico pago com papéis posteriormente alterados. Ele não foi restaurado nem anexado a conta recriada. O novo canário completo pela landing, pagamento, webhook, matrícula, comissão, ledger e documentos permanece requisito de homologação.

Não há endpoint público documentado de estorno/cancelamento InfinitePay no contrato consultado. Estorno pelo aplicativo do provedor, liquidação de recebível com líquido posteriormente conhecido e classificação de recebimentos de contas removidas ainda exigem procedimento e evidência próprios. A release não declara essas etapas concluídas.

## Publicação e rollback

Backend: overlay da imagem efetivamente ativa, lista explícita de arquivos, hashes, build, preflight, migrações aditivas, troca conjunta web/worker e health com identidade do artefato. App e admin: builds Cloudflare identificados, deploys anteriores guardados para rollback. Cada entrega incrementa o patch global no oráculo.

O proprietário informou que o banco contém apenas cadastros de teste e dispensou backup nesta etapa. A exceção é registrada no resultado da migração; as novas tabelas e colunas permanecem em um rollback de código.

Antes de voltar o backend para imagem sem `integrations.bank.recovery`, suspenda o schedule `payment_event_recovery`; use o `compose.rollback.json` da release. Ao retornar a esta versão, reative o schedule e confira eventos pendentes. Rollback não desfaz movimentações financeiras no provedor.

Fontes do contrato: https://www.infinitepay.io/checkout-documentacao e https://docs.asaas.com/docs/webhooks-2. Condições de taxas no checkout continuam conforme configuração da conta autorizada pelo proprietário.
