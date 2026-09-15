# API Clients (Aluno)

## Visão geral

O grupo `clients` (`api/clients.py`) é o backend do funil público do **ALUNO**: da captação
(lead) até virar `student` e depois `veteran`. É a API que **$$ ENTRA** — todo cliente entra
OBRIGATORIAMENTE como `lead`, paga, vira `enrollment` (matrícula) e preenche um wizard de
5 seções (RG → endereço → escolaridade → selfie → liberação). O modelo é **accept-first**: o
aluno NUNCA fica travado esperando a IA validar um documento. Ele sobe a foto, o backend aceita
na hora e AVANÇA o wizard; a validação de verdade roda em background (task assíncrona). Se a IA
rejeitar depois, o backend cria um `ValidationBlock` — um aviso que aparece como modal no app,
resolvido automaticamente no re-upload. Isso existe porque, no modelo antigo (esperar a IA antes
de avançar), o aluno abandonava o cadastro no meio da espera; accept-first tira esse atrito e
empurra a correção pro fluxo normal (modal + re-upload), não pro caminho crítico do cadastro.

## Fluxo completo (passo a passo)

### 1. Register (captação do lead)

- **Endpoint**: `POST /api/v1/clients/auth/register`
- **O que o frontend envia**: `{cpf, phone, email, payment_method?, ref?}` — `payment_method`
  default `"card"`; `ref` é o `external_id` do promotor (vem do `?ref=` da landing).
- **O que o backend faz** (`lead_iface.create_lead`): resolve o promotor (pelo `ref`, ou o
  promotor/coordenador padrão do hub padrão se não houver `ref` válido); chama `auth.register`
  (valida CPF/telefone/e-mail únicos, cria `User` + `Profile` + role `lead` + dispara OTP); cria
  `Lead(PENDING)` + uma linha de `Checkout` LOCAL (sem rede — nasce na hora, com link curto já
  gerado); enfileira em background (Django-Q, `build_checkout`) a criação da cobrança real no
  gateway (PIX via Asaas / cartão via InfinitePay) — se o gateway ainda não respondeu quando o
  cliente clicar no link, a criação acontece "lazy" no clique. Dispara notificações (lead
  capturado + aviso ao promotor).
- **O que o backend retorna** (`201`, shape `LeadOut`): `external_id` (do LEAD), `user_external_id`
  (do USER — **é esse que o login usa**, não o do lead), `status`, `checkout` (método, provider,
  valor, `is_paid`, `checkout_url`/`short_url`/QR — pode vir vazio se o gateway ainda não respondeu).
- **O que o frontend deve fazer**: guardar `user_external_id`; se `checkout.checkout_url` vier
  nulo, usar `short_url` (o redirect resolve lazy) ou dar polling em `GET /clients/lead/me`.

### 2. Login (por OTP)

- **Endpoint**: `POST /api/v1/clients/auth/check` (dispara OTP) e o endpoint de login do funil
  registrado por `add_funnel_login` (verifica o OTP e emite o JWT com TODAS as roles ativas do
  usuário — lead/enrollment/student/veteran, a mais avançada primeiro).
- **O que o frontend envia**: `{cpf, phone, external_id?, send_otp}`.
- **O que o backend faz**: `auth_iface.check` — **vaza existência de propósito** (convenção do
  projeto): devolve `found` + `roles` honestos, pro front decidir "é cadastro novo" vs "é login" e
  pra qual fase do funil mandar. `send_otp=false` não dispara SMS/WhatsApp, devolve o JWT direto
  (uso interno/webhook, prova de identidade é o canal do chamador).
- **O que o backend retorna**: `CheckOut` (found, roles, etc.) no `/check`; token JWT no login.
- **O que o frontend deve fazer**: rotear pelo array `roles` retornado — se só `lead`, mandar pro
  fluxo de pagamento; se `enrollment`, mandar pro wizard; se `student`/`veteran`, pro respectivo hub.

### 3. Pagamento (checkout do lead)

- **Endpoints**: `GET /api/v1/clients/lead/me` e `GET /api/v1/clients/lead/checkout-url`
  (autenticados, aceitam qualquer role do funil do aluno — mesmo já promovido, o cliente continua
  vendo o próprio checkout/recibo).
- **O que o frontend envia**: nada (GET).
- **O que o backend faz**: `lead_me` devolve TODOS os dados do lead (`lead_iface.lead_self_dict`);
  `checkout-url` devolve só a URL — que é **única** (o mesmo link redireciona pro checkout do
  gateway se ainda não pago, ou pro recibo se já pago). O pagamento em si é confirmado por um
  **webhook** externo (fora deste grupo de API) que chama `lead_iface.mark_paid`: dentro de uma
  transação, marca `Lead.PAID`, credita comissão do promotor (se ativo) e chama
  `enrollment_iface.create_from_lead` — que cria o `Enrollment` (status inicial `rg`) e promove a
  role `lead → enrollment`.
- **O que o backend retorna**: `LeadMeOut` (status `pending|paid|failed`, `customer`, `promoter`,
  `checkout` com `url`/`receipt_url`).
- **O que o frontend deve fazer**: dar polling em `lead/me` até `status: "paid"`; ao virar `paid`,
  fazer login de novo (ou refresh do JWT) pra pegar a role `enrollment` e entrar no wizard.

### 4. RG (documento — primeira seção do wizard)

- **Endpoints**:
  - `POST /api/v1/clients/enrollment/documents/rg/photo/{slot}` (`slot`: `front`|`back`|`full`,
    multipart `file`)
  - `POST /api/v1/clients/enrollment/documents/classify` (multipart `file`) — classificação
    RÁPIDA e SÍNCRONA (não valida, só reconhece: é documento? RG ou CNH? frente/verso/inteiro?)
    para a UI generativa decidir o próximo componente
  - `GET /api/v1/clients/enrollment/documents/rg`
  - `PATCH /api/v1/clients/enrollment/documents/rg` (`{number, issuing_agency, issue_date,
    mother_name, father_name, birthplace, marital_status, nationality}`, todos opcionais)
- **O que o frontend envia**: a foto (JPEG/PNG/WEBP ou PDF, convertido internamente) no slot
  indicado por `next_slot` (o backend nunca pede frente+verso ao mesmo tempo); no PATCH, só os
  campos que o OCR não conseguiu extrair (`missing_fields`).
- **O que o backend faz**: salva a foto, RE-ZERA o veredito daquele slot (`_reset_rg_validation`)
  e ENFILEIRA a task assíncrona `validate_rg` (Django-Q): visão (é RG? lado certo? legível?) → se
  a seção fechar (inteira aprovada, ou frente+verso aprovadas) → OCR + extração por LLM (nome,
  filiação, naturalidade, nascimento) → confere nome vs cadastro → aprova/rejeita/manda pra
  revisão do coordenador → se aprovado, biometria best-effort (enrola o rosto pra usar no
  face-match da selfie depois). **Accept-first**: `_advance_rg` avança `rg → address` assim que
  há `number` + foto — SEM esperar o veredito da IA. Se a IA rejeitar depois, o signal de
  `post_save` do model RG cria um `ValidationBlock` automaticamente (ver seção dedicada).
- **O que o backend retorna**: no upload, `RgUploadAck` (`slot`, `stored`, `analysis_status:
  pending`, `poll_after_ms`, `expires_at`); no PATCH, o `EnrollmentMeOut` canônico (status já
  avançado, se for o caso); no GET, `RgSectionOut` completo (todos os campos extraídos, `photos`
  por slot, `next_slot`, `missing_fields`).
- **O que o frontend deve fazer**: pedir o slot indicado em `next_slot`; dar polling em
  `GET .../rg` (ou no `blocks` do `/me`) a cada `poll_after_ms`; se `missing_fields` não vazio,
  renderizar input só pros campos faltando e mandar via PATCH.

### 5. Endereço

- **Endpoints**:
  - `GET /api/v1/clients/enrollment/address`
  - `POST /api/v1/clients/enrollment/address` (body só `{cep}`)
  - `PATCH /api/v1/clients/enrollment/address` (`{street, number, complement, neighborhood,
    city, state}`, todos opcionais — sobrescreve o que vier, vazio/None é ignorado)
- **O que o frontend envia**: primeiro só o CEP (POST); depois, via PATCH, só o que
  `missing_fields` indicar (ex.: `["number"]` = ViaCEP achou tudo, só falta o número; rua/bairro
  na lista = CEP genérico de cidade pequena, o aluno digita).
- **O que o backend faz**: `set_address_cep` consulta o ViaCEP e grava; `set_address_data` faz
  merge dos campos digitados. Em ambos, `_advance_address` avança `address → education` quando o
  endereço fica completo (**gate G9**: precisa também do comprovante aprovado — chain-skip nunca
  pula esse gate mesmo que o `Address` já exista de outro funil).
- **O que o backend retorna**: `EnrollmentMeOut` canônico, com `address.missing_fields` avisando
  o que falta.
- **O que o frontend deve fazer**: renderizar inputs só do que está em `missing_fields`; repetir
  PATCH até a lista esvaziar.

### 6. Comprovante de endereço

- **Endpoints**:
  - `POST /api/v1/clients/enrollment/address/proof` (multipart `file`)
  - `POST /api/v1/clients/enrollment/address/proof/kinship` (`{relation}`)
- **O que o frontend envia**: a foto/PDF do comprovante; se a IA identificar que o titular do
  comprovante é outra pessoa (`needs_kinship`), o front pede o grau de parentesco e manda no
  segundo endpoint.
- **O que o backend faz**: **aceito em qualquer etapa pré-conclusão** (não tem gate de status —
  é o próprio texto do accept-first: o aluno pode já ter avançado pro RG/educação e reenviar o
  comprovante depois). Salva a foto, resolve qualquer `ValidationBlock` de `address_proof` na
  hora (o re-upload já conta como resolução), zera o `validation_status` pra `pending` e
  enfileira `validate_address_proof` (Django-Q): visão → confere endereço batendo com o
  cadastrado → confere titular → aprova, rejeita, manda pra revisão, ou marca
  `needs_kinship`. Kinship: grava o parentesco e libera.
- **O que o backend retorna**: `EnrollmentMeOut` canônico; o bloco `address_proof` (dentro do
  `/me`) traz `status` (`pending|approved|rejected|review|needs_kinship`), `reason`,
  `needs_kinship`, `kinship_relation`.
- **O que o frontend deve fazer**: dar polling em `address_proof.status` (ou nos `blocks`); se
  `needs_kinship: true`, mostrar o formulário de parentesco.

### 7. Escolaridade

- **Endpoints**:
  - `GET /api/v1/clients/enrollment/education`
  - `POST /api/v1/clients/enrollment/education` (`{level, grade, completed, last_school, city,
    state, last_year_when?}`)
- **O que o frontend envia**: `level` (`fundamental`|`medio`), `grade` (1–9 fundamental / 1–3
  médio), `completed`, escola/cidade/UF/quando concluiu.
- **O que o backend faz**: exige status `education` (gate ESTRITO — diferente do RG/endereço,
  aqui NÃO é accept-first fora de ordem: `set_education` só roda se a matrícula estiver
  exatamente na etapa `education`, senão `409 WRONG_STATUS`); valida `level` e a faixa de `grade`
  pro nível; grava e avança direto pra `selfie` (`_set_status(enr, _S.SELFIE)`).
- **O que o backend retorna**: `EnrollmentMeOut` canônico já com `status: "selfie"`.
- **O que o frontend deve fazer**: usar o `GET` pra pré-preencher (o backend já faz prefill do
  Profile se a pessoa respondeu escolaridade como candidata antes); depois do POST, ir direto pra
  tela da selfie sem precisar re-buscar `/me`.

### 8. Selfie (= assinatura da matrícula)

- **Endpoints**:
  - `GET /api/v1/clients/enrollment/selfie`
  - `POST /api/v1/clients/enrollment/selfie` (multipart `file`)
  - `GET /api/v1/clients/contract/current` (texto/versão/hash do contrato — pra exibir antes da
    selfie)
- **O que o frontend envia**: a foto da selfie.
- **O que o backend faz**: exige status `selfie` + gates mínimos (`_require_rg_ready_for_selfie`:
  RG com foto e sem `missing_fields`) — aqui SIM há um gate de pré-condição, mas não espera
  veredito de IA, só presença de dado. Salva a foto, grava o **aceite LGPD** (a selfie É a
  assinatura do contrato: versão/hash do `STUDENT_CONTRACT` + IP + user-agent + timestamp
  gravados no ato), zera o veredito e enfileira `validate_selfie` (Django-Q): liveness → biometria
  (face-match vs o rosto extraído do RG) → aprovado → avança pra `awaiting_release` e notifica o
  coordenador; rejeitado → `ValidationBlock` (via signal) + aluno reenvia (após 5 rejeições
  seguidas, marca "precisa de reunião" mas AINDA libera pra `awaiting_release` — não trava o
  aluno pra sempre); dúvida → `review` (coordenador decide manualmente).
- **O que o backend retorna**: `EnrollmentMeOut` + ack de polling (`poll_after_ms`,
  `expires_at`, `analysis_status: pending`) na mesma resposta do POST.
- **O que o frontend deve fazer**: mostrar o contrato antes de photografar; após o POST, dar
  polling em `GET .../selfie` (ou `blocks`) a cada `poll_after_ms` até `analysis_status` sair de
  `pending`.

### 9. Aguardando liberação → conclusão

- Não há endpoint de POST nesta fase para o aluno — `awaiting_release` é um status de espera. O
  status REAL internamente pode ser `fee_paid`/`fee_scheduled` (fase da taxa do credenciador,
  tratada pelo COORDENADOR, fora deste grupo de API), mas o aluno NUNCA vê isso: `public_status`
  mascara ambos como `awaiting_release` — política interna do polo (o aluno não sabe da taxa).
  Quando o coordenador confirma as 2 parcelas e envia as credenciais da plataforma (função
  `conclude`, endpoint do grupo do coordenador/hub), a matrícula vira `completed` e a role do
  usuário é promovida `enrollment → student` na mesma transação.
- **O que o frontend deve fazer**: dar polling em `GET /api/v1/clients/enrollment/me` até
  `status` virar `completed`; a partir daí, tratar o usuário como `student` (novo login/JWT pega
  a role) e usar os endpoints `/api/v1/clients/student/*`.

### 10. Pós-conclusão: student → veteran

Fora do wizard de matrícula, mas no mesmo grupo `clients`, expostos ao aluno já promovido:

- `GET /api/v1/clients/student/me` — dados do aluno (status, plataforma, documentos, pendências).
- `POST /api/v1/clients/student/blood-type` — `{blood_type}`.
- `POST /api/v1/clients/student/documents/{doc_type}` — upload de documento do aluno (ack
  assíncrono igual ao RG/selfie).
- `POST /api/v1/clients/student/exam/schedule` — `{subject, scheduled_at}`.
- `GET /api/v1/clients/student/pendencies` — pendências financeiras/documentais em aberto.
- `GET /api/v1/clients/veteran/me` — visão consolidada read-only do veterano (dados pessoais +
  matrícula completa + documentos + diploma), depois de formado.

## ValidationBlocks (o coração do accept-first)

O `ValidationBlock` (`users/blocks/`) é o mecanismo que permite ao aluno avançar sem esperar a
IA: em vez de travar o wizard esperando validação, o backend cria um bloco quando algo é
rejeitado, e o frontend mostra um modal bloqueante até o aluno resolver.

- **Quando é criado**: um `post_save` signal centralizado (`users/blocks/signals.py`) observa
  TODOS os models com `validation_status`/`selfie_status`/`status` (RG, CNH, AddressProof,
  StudentDocument, a própria `Enrollment` — pra selfie — e `Submission` de treinamento). Sempre
  que esse status vira `"rejected"`, o signal cria (ou atualiza, se já existir um ativo da mesma
  fonte) um `ValidationBlock` para aquele usuário, com `source_type` (`rg`, `address_proof`,
  `selfie`, etc.), título, descrição (o motivo real da IA), `action_label` ("Corrigir") e
  `action_route` — a URL do app pra onde o modal deve levar, resolvida pela role ativa do usuário
  (ex.: `enrollment` + `rg` → `/enrollment/documents/rg`).
- **Como o frontend detecta**: **polling em `GET /api/v1/clients/me/blocks`** — todo `/me` de
  cada seção (`EnrollmentMeOut`) TAMBÉM já embute a lista `blocks` (não-vazia = tem algo
  pendente), então na prática o front nem precisa de uma rota de polling separada: se o `blocks`
  do `/enrollment/me` (ou de qualquer POST de seção) vier não-vazio, mostra o modal ali mesmo.
  `GET /me/blocks/{block_id}` serve pra um deep-link direto no modal (ex.: veio de um push
  notification).
- **Como resolve**: o caminho normal é o **re-upload** — quando o status volta pra `"pending"`
  (nova foto) ou `"approved"`, o mesmo signal resolve automaticamente TODOS os blocos ativos
  daquela fonte (`blocks_svc.resolve_for_source`). Os services de upload (RG, comprovante,
  selfie) também chamam `resolve_for_source` explicitamente no MOMENTO do upload — antes mesmo da
  IA rodar — pra o modal sumir na hora, sem esperar o novo veredito.
- **Endpoints**:
  - `GET /api/v1/clients/me/blocks` — lista blocos ativos do usuário logado.
  - `GET /api/v1/clients/me/blocks/{block_id}` — um bloco específico (404 se não é do usuário).
  - `POST /api/v1/clients/me/blocks/{block_external_id}/resolve` — resolução MANUAL (fallback:
    "descartar" no app, ou o coordenador aprovou por fora); normalmente o bloco já se resolveu
    sozinho no re-upload, então esse endpoint raramente é chamado na prática.

## Estados do wizard (tabela)

| status | o que significa | o que o front mostra | próxima ação |
|---|---|---|---|
| `rg` | Falta enviar/completar o documento (RG) | Upload de foto do slot indicado em `rg.next_slot`; inputs pros campos em `rg.missing_fields` | `POST .../documents/rg/photo/{slot}` e/ou `PATCH .../documents/rg` |
| `address` | RG ok; falta endereço + comprovante | Input de CEP, depois campos de `address.missing_fields`; upload do comprovante | `POST`/`PATCH .../address`, `POST .../address/proof` |
| `education` | Endereço completo; falta escolaridade | Formulário de nível/série/escola | `POST .../education` |
| `selfie` | Falta a selfie (assinatura) | Tela do contrato + câmera para selfie | `POST .../selfie` |
| `awaiting_release` | Selfie enviada; aguardando o coordenador (taxa + credenciais) — pode ser `fee_paid`/`fee_scheduled` por baixo, mas o aluno nunca vê isso | Tela de "aguarde", sem ação do aluno | Polling em `GET .../enrollment/me` |
| `completed` | Matrícula concluída; virou `student` | Redireciona pro fluxo `student` (login/JWT novo) | Trocar de tela para `/api/v1/clients/student/*` |

Em qualquer status, se `blocks` vier não-vazio no corpo da resposta, o front deve sobrepor um
modal bloqueante usando `title`/`description`/`action_label`/`action_route` do bloco — isso tem
prioridade visual sobre a tela normal do `status`.

## Códigos de erro relevantes

| code | quando | o que o front faz |
|---|---|---|
| `WRONG_STATUS` | ação de POST fora da etapa atual do wizard (409) | Re-sincronizar com `expected_status` (a etapa real no servidor) e `missing_fields` (se vier); redirecionar pra etapa certa |
| `SLOT_INVALID` | slot de foto do RG desconhecido (422) | Bug de front — checar o valor de `slot` enviado |
| `CPF_EXISTS` / `PHONE_EXISTS` / `EMAIL_EXISTS` | cadastro duplicado no register (409) | Mostrar "já existe conta" e oferecer login |
| `CPF_INVALID` / `PHONE_INVALID` / `CPF_NOT_FOUND` | dado rejeitado na validação externa (422) | Pedir correção do campo |
| `CPF_SERVICE_DOWN` / `PHONE_SERVICE_DOWN` / `CEP_SERVICE_DOWN` | serviço externo fora do ar (502) | Retry / mensagem de "tente novamente" |
| `CEP_NOT_FOUND` / `STATE_INVALID` | endereço inválido (422) | Pedir CEP/UF novamente |
| `CHECKOUT_NOT_FOUND` / `LEAD_NOT_FOUND` / `STUDENT_NOT_FOUND` / `ENROLLMENT_NOT_FOUND` | recurso do aluno não existe (404) | Estado inconsistente — normalmente indica JWT de role errada |
| `BLOCK_NOT_FOUND` | bloco inválido/já resolvido/de outro usuário (404) | Fechar o modal, refazer o GET de `blocks` |
| `EDUCATION_LEVEL_INVALID` / `EDUCATION_GRADE_OUT_OF_RANGE` | dados de escolaridade fora da faixa (422) | Validar no front antes de enviar (nível/série) |

## O que o backend ESPERA do frontend

- **Nunca travar a UI esperando a IA**: todo upload responde na hora com um ack (`analysis_status:
  pending`, `poll_after_ms`, `expires_at`) — o front deve deixar o aluno seguir em frente
  (o backend já avançou o `status` quando aplicável) e só voltar a perguntar depois de
  `poll_after_ms`.
- **Rotear pelo campo `status`** de `EnrollmentMeOut` (não inferir por outros campos) — toda
  mutação de seção já devolve o shape canônico completo, então normalmente **não é preciso**
  um GET extra depois de um POST/PATCH.
- **Checar `blocks` em toda resposta** (`/me` e qualquer mutação) e sobrepor o modal se não-vazio
  — isso é o mecanismo principal de "algo foi rejeitado", não um código de erro HTTP.
- **Renderizar inputs só do que está em `missing_fields`** (RG e endereço) — o backend já fez o
  trabalho de decidir o que falta; o front não deve re-perguntar campos já preenchidos.
- **Re-upload é a correção padrão**: ao ver um bloco, a ação do modal deve levar pra tela de
  upload daquela seção (`action_route`); o backend resolve o bloco sozinho assim que a nova foto
  chega — o front não precisa (nem deve, como regra) chamar `POST .../resolve` manualmente.
  Esse endpoint é só o fallback de "dispensar".
- **`next_slot` do RG manda um slot por vez** — nunca pedir frente+verso simultaneamente; seguir
  a ordem que o backend indica.
- **Guardar o `user_external_id`, não o `external_id` do lead**, para login — são identificadores
  diferentes (proposta #8 do projeto).
- **Tratar `awaiting_release` como estado terminal do wizard** (sem input do aluno) e dar polling
  em `enrollment/me` até `completed` — não existe endpoint que o aluno chame pra "forçar" a
  liberação; isso é ação do coordenador.
