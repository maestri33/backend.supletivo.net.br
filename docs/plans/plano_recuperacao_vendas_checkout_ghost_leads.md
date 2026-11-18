# Plano de Recuperação de Vendas e Resgate Multicanal — Supletivo Brasil

**Documento:** Arquitetura Técnica de Réguas de Reengajamento, Webhooks e Resgate de Vendas  
**Autor:** Recuperação de Vendas (`supletivo.net.br`)  
**Data:** 16 de Novembro de 2026  
**Destinatários:** Marketing (`cmwjyagsuhg49quv4o6i2g6z8`), Whatsapp (`cmwhyzhjg0iy4x0u22bcmktl4`), InfinitePay, Asaas, app.supletivo.net.br  
**Status:** Especificação Aprovada para Implementação Operacional  

---

## 1. Visão Geral e Diagnóstico das Pontas de Perda

No funil do **Supletivo Brasil**, a perda de receita concentra-se em três gargalos principais:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PONTAS DE PERDA DE CONVERSÃO                          │
├───────────────────────┬─────────────────────────┬───────────────────────────┤
│ 1. GHOST LEADS        │ 2. PIX NÃO PAGO         │ 3. CARTÃO RECUSADO        │
│ (Landing / Omnibar)   │ (Checkout App / Asaas)  │ (Checkout / InfinitePay)  │
├───────────────────────┼─────────────────────────┼───────────────────────────┤
│ Lead digita WhatsApp  │ Gera QR Code PIX, mas   │ Operadora rejeita por     │
│ no passo 1 e hesita   │ sai do app, esquece ou  │ limite insuficiente, erro │
│ no passo 2 ao ver CPF │ esbarra em limite PIX   │ de dados ou antifraude/3DS│
│ Perda estimada: ~35%  │ Perda estimada: ~25%    │ Perda estimada: ~15%      │
└───────────────────────┴─────────────────────────┴───────────────────────────┘
```

A recuperação dessas três pontas representa um incremento direto de **+32% a +48% no faturamento bruto** sem necessidade de elevar o investimento em mídia paga.

---

## 2. Frente 1: Régua de Resgate de Ghost Leads na Sofia Omnibar

### 2.1. O Ponto de Fricção e Causa Raiz
No passo 1 da Omnibar em `supletivo.net.br`, o visitante informa o telefone e a rota pública `POST /api/v1/clients/auth/check` (`check_or_capture`) consulta a rede WhatsApp e cria instantaneamente os registros no banco:
- `User` + `Profile(phone)`
- Role `lead`
- `Lead` com status `PENDING` vinculado ao promotor do `?ref=` (ou promotor padrão)
- Snapshot de precificação travado (`lock_pricing`)

O abandono ocorre entre o passo 1 e o passo 2 (solicitação de CPF para consulta de elegibilidade do MEC e validação do OTP). O usuário hesita por insegurança sobre fornecer documento online ou por interrupção no dispositivo móvel.

### 2.2. Gatilhos Técnicos de Disparo
1. **Detecção**: Task agendada no backend (Celery / cron no Django ou Cloudflare Queue em `notify.v7m.live`):
   - `Lead.status == PENDING`
   - `Profile.cpf` é nulo / vazio (não avançou para o passo 2)
   - `Profile.user.sessions` ou tokens de login ativos = 0
   - Tempo decorrido: exatamente **8 minutos** após `lead.created_at`.
2. **Filtro de Segurança / Cancelamento (Killswitch)**:
   - Se o lead preencher o CPF ou autenticar via OTP antes de 8 minutos, a tarefa é cancelada e o evento é descartado.

### 2.3. Cadência Multicanal: Ghost Leads (WhatsApp Sofia)

| Momento | Canal | Remetente | Objetivo | Mensagem Operacional (Humanizer 90+ / Anti-Slop) |
| :--- | :--- | :--- | :--- | :--- |
| **T + 8 min** | WhatsApp | Sofia (Evolution Go) | Acolhimento empático e suporte técnico | *"Oi, tudo bem? Aqui é a Sofia do Supletivo Brasil. Vi que você começou a sua consulta no nosso site pelo celular, mas não concluiu. Ficou alguma dúvida sobre como funciona o curso ou a emissão do certificado pelo MEC? Posso te ajudar por aqui."* |
| **T + 3 horas** | WhatsApp | Sofia (Evolution Go) | Quebra de objeção do CPF + Prova Oficial | *"Oi! Só para te tranquilizar: pedimos o CPF apenas para verificar a sua elegibilidade no sistema do MEC e emitir a publicação no Diário Oficial. Não cobramos nada pela consulta. Se quiser, me passe o seu nome por aqui que eu vejo a sua liberação na hora."* |
| **T + 24 horas** | WhatsApp | Sofia (Evolution Go) | Urgência real de fechamento de turma | *"A turma de homologação acelerada desta semana está fechando as vagas hoje. Conseguimos liberar para você o plano de 12x de R$ 99 sem juros. Posso reservar o seu acesso antes de encerrar as inscrições?"* |

*Regra de Handoff*: Qualquer mensagem recebida do usuário pausa a automação e cria um ticket com prioridade alta no **Chatwoot**, transferindo a conversa para atendimento humano ou IA interativa.

---

## 3. Frente 2: Recuperação de Checkout no `app.supletivo.net.br`

### 3.1. Sub-jornada A: PIX Gerado e Não Pago

#### Causa Raiz
O aluno escolhe PIX, o gateway (Asaas) emite o QR Code dinâmico com vencimento. O aluno minimiza o app para abrir o banco, recebe outra notificação, esquece de colar o código, ou esbarra em limites de transferência noturna (após as 20h).

#### Gatilhos e Webhooks
1. Gateway (Asaas) dispara webhook com payload da cobrança.
2. `integrations/bank/asaas/webhooks.py` recebe e grava `WebhookEvent`.
3. Se a cobrança passar de 15 minutos sem confirmação de `PAYMENT_RECEIVED`:
   - Task `tasks.check_pix_pending_recovery` identifica o checkout pendente.
4. Se o gateway emitir `PAYMENT_OVERDUE`:
   - `core.hooks.dispatch("payment.expired", provider="asaas", ...)` aciona `mark_payment_expired` e gera link com renovação automática de 1 toque.

#### Cadência de Resgate (WhatsApp + E-mail via `mail.v7m.live`)

| Momento | Canal | Ação / Objetivo | Conteúdo Operacional |
| :--- | :--- | :--- | :--- |
| **T + 15 min** | WhatsApp (2 mensagens) | Envio de código copia-e-cola direto na mão | **Mensagem 1:** *"Oi, {nome}! Sua vaga na turma do Supletivo Brasil está reservada. Para você não perder tempo, segue abaixo o seu código PIX copia e cola para pagar direto no app do seu banco:"*<br>**Mensagem 2 (isolada para cópia em 1 toque):** `{qrcode_payload}` |
| **T + 15 min** | E-mail | Backup visual com QR Code renderizado | **Assunto:** `{nome}, seu código PIX da matrícula no Supletivo Brasil`<br>**Corpo:** QR Code com botão direto de copiar chave e link do app: `{checkout_url}`. |
| **T + 2 horas** | WhatsApp | Quebra de objeção bancária (limite noturno) | *"Oi, {nome}! Tivemos relatos de alunos que enfrentam limite de horário bancário para PIX à noite. Se preferir, você pode alterar a forma de pagamento para cartão de crédito em até 12x ou parcelar no PIX. Quer ajuda para trocar a forma de pagamento?"* |
| **T + 24 horas** | WhatsApp + E-mail | Renovação de chave expirada + Última chamada | **WhatsApp:** *"O seu código PIX anterior venceu, mas geramos um novo código para manter o seu desconto de matrícula. Acesse aqui para gerar o novo PIX com 1 clique: {link_renovado}"*<br>**E-mail:** Assunto: `Último dia para confirmar sua vaga na turma desta semana`. |

---

### 3.2. Sub-jornada B: Cartão de Crédito Recusado

#### Causa Raiz e Classificação da Recusa
A recusa de cartão pelo gateway (InfinitePay via webhook `payment_failed` ou Asaas via `PAYMENT_CREDIT_CARD_CAPTURE_REFUSED`) ocorre por 3 causas técnicas:
1. `insufficient_funds` (Saldo/Limite insuficiente no cartão de crédito).
2. `risk_rejection` / `antifraude` (Bloqueio preventivo pelo banco emissor por compra pela internet).
3. `invalid_data` / `expired_card` (Digitação incorreta do CVV, validade ou nome).

#### Gatilhos e Webhooks
1. InfinitePay emite evento `payment_failed` ou Asaas emite `PAYMENT_CREDIT_CARD_CAPTURE_REFUSED` / `PAYMENT_REPROVED_BY_RISK_ANALYSIS`.
2. Backend executa `core.hooks.dispatch("payment.failed", provider=..., reason=fail_reason)`.
3. `mark_payment_failed` em `users/roles/lead/service.py` atualiza `Lead.status = FAILED`, registra `lead.failed_reason` e dispara `_notify_payment_recovery(lead, event_type="lead.card_declined")`.

#### Cadência de Resgate (WhatsApp + E-mail)

| Momento | Canal | Abordagem / Solução | Conteúdo Operacional (Zero Constrangimento) |
| :--- | :--- | :--- | :--- |
| **Imediato (T + 2 min)** | WhatsApp | Aviso amigável e despersonalizado da recusa + link de troca | *"Oi, {nome}. A operadora do seu cartão não autorizou a transação da matrícula. Isso costuma acontecer por segurança do próprio banco em compras online. Você pode tentar passar outro cartão ou pagar à vista no PIX com desconto pelo link seguro: {checkout_url}"* |
| **Imediato (T + 2 min)** | E-mail | Confirmação técnica e instruções de liberação | **Assunto:** `Tentativa de pagamento não autorizada pelo banco emissor`<br>**Corpo:** Explicação clara de como autorizar no app do banco ou escolher outra forma de pagamento. |
| **T + 2 horas** | WhatsApp | Oferta de solução para limite (PIX Parcelado ou 2 Cartões) | *"Oi, {nome}! Se o problema foi limite no cartão, nós temos duas soluções para você não ficar de fora da turma: podemos parcelar o valor via PIX mensal ou dividir a matrícula em dois cartões diferentes. Me avise aqui se você quer que eu libere essa opção no seu cadastro."* |
| **T + 24 horas** | WhatsApp + E-mail | Contato da Coordenação + Condição especial | *"Oi, {nome}, sou da coordenação pedagógica do Supletivo Brasil. Queremos garantir que você conclua o seu Ensino Médio com publicação no Diário Oficial. Conseguimos aprovar uma condição com entrada reduzida para você começar as aulas hoje. Me responda aqui para ativarmos o seu acesso."* |

---

## 4. Integração Técnica com Gateways e Webhooks

### 4.1. InfinitePay (Checkout Integrado)
- **Base de Homologação**: Conforme auditoria oficial em `shared/infinitepay/pesquisa-infinitepay-gateway-2026-11-16.md`:
  - Criação de links via `POST https://api.checkout.infinitepay.io/links`.
  - Webhooks cadastrados: `created`, `paid`, `settled`, `canceled`, `refunded`, `payment_failed`.
  - **Trava de Validação**: O webhook da InfinitePay não possui assinatura HMAC pública. O backend **obrigatoriamente reconfirma o pagamento** via `POST /payment_check` (enviando `handle`, `order_nsu`, `transaction_nsu`, `slug`) antes de marcar `is_paid = True`.
  - Captura de falhas: Ao receber `payment_failed`, o backend extrai `order_nsu`, localiza o `Checkout` e dispara `lead.card_declined` para o `notify.v7m.live`.

### 4.2. Asaas (PIX e Cartão)
- **Base de Homologação**: Conforme documentação em `integrations/bank/asaas/webhooks.py`:
  - Evento `PAYMENT_CREATED`: Inicia o cronômetro de 15 minutos para cobrança PIX.
  - Evento `PAYMENT_RECEIVED` / `PAYMENT_CONFIRMED`: Cancela imediatamente qualquer fila de recuperação e despacha `payment.paid`.
  - Evento `PAYMENT_OVERDUE`: Dispara `payment.expired` e gera o link de renovação imediata.
  - Eventos `PAYMENT_CREDIT_CARD_CAPTURE_REFUSED` e `PAYMENT_REPROVED_BY_RISK_ANALYSIS`: Disparam `payment.failed` com o campo `failReason` mapeado para acionar a régua de cartão recusado.

---

## 5. Regras Operacionais, Anti-Colisão e Idempotência

1. **Killswitch Imediato no Pagamento**:
   Quando qualquer evento `payment.paid` é processado pelo backend, uma chamada síncrona remove ou invalida todos os disparos pendentes agendados para aquele `lead_id` nas filas do `notify.v7m.live` e do Celery.
2. **Janela de Silêncio Regulamentar**:
   - É proibido disparar mensagens de cobrança e resgate entre as **21:30 e as 08:00**.
   - Mensagens agendadas para cair nessa faixa são automaticamente reprogramadas para as **08:05** do dia seguinte.
3. **Idempotência Estrita**:
   - Chave de idempotência no envio: `{event_slug}_{lead_external_id}_{intervalo}` (ex.: `ghost_lead_8m_3fa85f64...`).
   - Evita duplicidade em caso de reexecução de workers ou retentativas de webhooks.
4. **Pausa por Atendimento Humano (Chatwoot)**:
   - Se o lead responder qualquer mensagem no WhatsApp, o bot silencia o fluxo automatizado de régua para não interferir no diálogo do atendente humano.

---

## 6. Métricas de Sucesso, SLA e Monitoramento de ROI

| Indicador | Meta / Benchmark | Fonte dos Dados |
| :--- | :--- | :--- |
| **Taxa de Conversão Ghost Leads (8 min - 24h)** | **≥ 12.5%** dos leads recuperados pagam a matrícula | `Lead.status == 'paid'` com `attribution.ghost_recovered = True` |
| **Taxa de Recuperação de PIX Pendente** | **≥ 22.0%** dos PIX gerados resgatados | Asaas `PAYMENT_RECEIVED` pós-disparo T+15m |
| **Taxa de Recuperação de Cartão Recusado** | **≥ 16.0%** (via novo cartão ou conversão em PIX) | InfinitePay/Asaas `paid` pós-disparo T+2m |
| **Taxa de Entrega WhatsApp (Evolution Go)** | **≥ 98.5%** | `notify.v7m.live` audit logs |
| **Taxa de Abertura de E-mail (`mail.v7m.live`)** | **≥ 42.0%** | Cloudflare Email Sending logs |
| **Incremento de Receita Mensal Estimado** | **+ R$ 85.000,00 a R$ 140.000,00 / mês** | Finance dashboard / D1 analytics |

---
