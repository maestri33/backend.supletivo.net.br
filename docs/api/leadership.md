# API Leadership (Coordenador)

> Código-fonte: `api/leadership.py` · `hub/interface/__init__.py` · `users/roles/enrollment/service.py`

## Visão geral

O coordenador é um **cargo de confiança** que gerencia um **polo (hub)**. Ele é sempre, na origem,
um **promotor** promovido pelo staff — não existe registro/auto-cadastro de coordenador; só o
staff cria o polo (`hub.interface.create_hub`) e designa quem o coordena
(`hub.interface.set_coordinator`). Exceção de resgate: um usuário `is_superuser` (staff) pode
assumir a coordenação de um polo sem ser promotor, como último recurso quando o polo trava sem
coordenador ativo (`hub/interface/__init__.py:27-63`).

Um coordenador COORDENA no máximo o(s) polo(s) onde ele é o `Hub.coordinator` (FK dura, sem
fallback) — `hub_iface.coordinated_by(user)`. Todo endpoint do grupo `leadership` passa por dois
gates, nesta ordem (`api/leadership.py:84-100`):

1. `_coordinator(request)` — a role JWT precisa ser `coordinator` e o `User` precisa existir/estar ativo.
2. `_coordinator_hub(coordinator)` — o `User` precisa de fato coordenar um hub (`Hub.coordinator_id`).
   Sem isso: `403 NOT_HUB_COORDINATOR`.

Nas ações sobre uma matrícula específica (RG/selfie/taxa/conclude/proxy), o gate é ainda mais
estrito: `enrollment.service._enrollment_for_coordinator` exige que o `coordinator` seja o dono do
`Hub` **daquela matrícula** (`enr.hub.coordinator_id == coordinator.id`), não só de "algum" hub.

O que o coordenador gerencia, em ordem de fluxo:

- **Leads e matrículas** do próprio polo (consulta).
- **Fila de revisão** (`/reviews`) — tudo que a IA jogou para decisão humana, num único lugar.
- **Decisões**: RG/selfie de matrícula, selfie/documento de candidato, documentos de student.
- **Taxa da matrícula** (2 parcelas PIX) → **conclusão** (aluno vira `student`).
- **Aprovação de candidato** → vira promotor; destrava matéria de treino de promotor preso.
- **Suspensão/reativação** de promotores do polo.
- **Diploma e pendências** do aluno, até virar `veteran`.
- **Proxy auditado**: o coordenador pode agir NO LUGAR do cliente sem prática digital (endereço,
  foto de RG, selfie, correção de identidade), sempre logando `leadership.acted_for`.

## Fluxo de entrada

`POST /api/v1/leadership/auth/check` → `POST /api/v1/leadership/auth/login` (OTP) →
`POST /api/v1/leadership/auth/refresh`.

Não há registro neste grupo — o campo de entrada é sempre um `external_id`/CPF/telefone de um
`User` já existente (criado pelo staff como promotor + coordenador).

### `POST /auth/check` (`auth=None`, público)

Reusa o `check` genérico de auth (acha a pessoa pelo CPF/telefone/external_id e dispara o MESMO
OTP do sistema — não existe um OTP "de coordenador" separado) e enriquece a resposta:

- `found` — achou a pessoa.
- `otp_sent`/`otp_wait`/`whatsapp` — normal do check genérico.
- `roles` — todas as roles ativas da pessoa.
- `is_coordinator` — `true` só se `hub_iface.coordinated_by(user)` achar um hub.
- `hub` — `{external_id, brand}` do polo que ela coordena (só quando `is_coordinator=true`).
- `detail` — presente quando a pessoa existe mas **não** coordena polo: mensagem fixa
  ("Você não pode entrar como coordenador: não coordena nenhum polo. Faça seu login na área da sua
  função.") — o front deve **redirecionar** para a área de login da role real da pessoa (em
  `roles`), levando o `external_id` (o OTP já disparado continua válido lá).

### `POST /auth/login`

Body: `{external_id, otp}`. Antes de logar, o backend re-checa `hub_iface.coordinated_by(user)` —
se não coorderna, `403 NOT_HUB_COORDINATOR` mesmo que o OTP esteja certo. Sucesso →
`TokenOut` (JWT com role `coordinator`).

### `POST /auth/refresh`

Padrão do `add_auth_refresh` (igual aos demais grupos).

## Painel: consultas

### `GET /leads?status=`

Leads do polo do coordenador (`lead_iface.list_leads(hub=hub, status=status)`). Cada item
(`HubLeadRowOut`): `external_id`, `status`, `name`, `phone`, `promoter_external_id`,
`payment_link`, `receipt_url`.

### `GET /leads/{external_id}`

Detalhe COMPLETO de um lead do próprio polo — nome, CPF, e-mail, telefone, promotor e checkout
(link, recibo, valor, QR). 404 `LEAD_NOT_FOUND` se o lead não existe **ou** não é do polo do
coordenador (mesma resposta para os dois casos — não vaza existência).

### `GET /enrollments?status=`

Matrículas do polo com status REAL (sem a máscara que o aluno vê) + resumo das 2 parcelas da taxa
em cada linha (`HubEnrollmentRowOut`: `fees.first_paid`/`fees.second_scheduled`). Filtro útil:
`?status=awaiting_release` = quem terminou o wizard e espera ação do coordenador.

### `GET /enrollments/{external_id}`

Detalhe COMPLETO (`HubEnrollmentDetailOut`) — espelha o `/me` do aluno + status real + as duas
seções que o coordenador decide (RG, selfie) + `fees`. Usa
`enrollment_iface.detail_for_hub(enrollment_external_id, coordinator)`, que já valida internamente
que a matrícula pertence ao hub do coordenador.

### `GET /reviews` — a fila de decisões

Tela-âncora do coordenador: TUDO que espera decisão dele, num payload único e normalizado
(`ReviewsOut`), somando 7 baldes:

| balde | `type` | `kind` | origem |
|---|---|---|---|
| `enrollment_rg` | `enrollment` | `rg` | RG de matrícula em revisão |
| `enrollment_selfie` | `enrollment` | `selfie` | selfie de matrícula em revisão |
| `candidate_document` | `candidate` | `document` | RG/CNH de candidato em revisão |
| `candidate_selfie` | `candidate` | `selfie` | selfie de candidato em revisão |
| `student_documents` | `student` | `document` | documento de student em revisão (traz também `student_external_id` + `document_external_id`) |
| `candidates_awaiting_approval` | `candidate` | `awaiting_approval` | candidato que terminou a coleta, aguardando aprovar/virar promotor |
| `locked_promoters` | `promoter` | `locked_training` | promotor travado no treino com matéria em aberto (traz `pending_materials`) |

Cada item (`ReviewItemOut`) é normalizado: sempre tem `external_id` (o id do recurso a decidir) +
`type` + `kind`, mais campos extras conforme o balde. **O front roteia pela dupla `type`+`kind`** e
usa `external_id` para montar o link de detalhe/decisão — sem precisar saber o nome interno de
cada balde.

## Decisões do coordenador (o núcleo)

Toda decisão usa o mesmo shape de entrada `{approve: bool, reason?: str}` (schema `SelfieDecideIn`
reaproveitado) e a decisão humana é **FINAL** — não há uma segunda revisão da IA em cima.

### RG da matrícula — `POST /enrollments/{external_id}/rg/decide`

- Pré-condição: `rg.validation_status == "review"`. Fora disso → `422 RG_NOT_IN_REVIEW` (com
  `rg_validation_status` atual).
- **Aprovou**: as fotos presentes no RG passam a `approved` (auditado por foto), o aluno é
  avisado (`enrollment.rg_approved` best-effort), e a extração de dados roda: se já havia um
  resultado de extração pendente (revisão por dúvida de nome), aplica na hora; senão dispara
  `fill_rg_data` em fila (`django_q`) para extrair best-effort em background. Depois roda
  `_rg_post_approval` (avança o fluxo).
- **Reprovou**: RG marcado `rejected` com o motivo; aluno é avisado a reenviar a foto
  (`enrollment.rg_rejected`).
- Resposta (`EnrollmentRgDecideOut`): `{external_id, status, rg_validation_status}`.

### Selfie da matrícula — `POST /enrollments/{external_id}/selfie/decide`

- Pré-condição: `enr.selfie_status == "review"`. Fora disso → `422 SELFIE_NOT_IN_REVIEW`.
- **Aprovou**: `selfie_status=approved`, `selfie_verified=true`; notifica o aluno
  (`enrollment.selfie_approved`), avança a matrícula para `awaiting_release` e notifica o
  coordenador de que a matrícula está esperando ele.
- **Reprovou**: `selfie_status=rejected`, `selfie_verified=false`; notifica o aluno a refazer
  (`enrollment.selfie_rejected`). O motivo interno da IA (`selfie_description`) **nunca** vai para
  o aluno — ele recebe só a mensagem genérica do catálogo.
- Resposta (`EnrollmentSelfieDecideOut`): `{external_id, status, selfie_status, selfie_verified}`.

### Selfie do candidato — `POST /candidates/{external_id}/selfie/decide`

Mesmo contrato de entrada/saída, mas sobre `candidate_iface.decide_selfie`. Antes de decidir, o
front deve buscar `GET /candidates/{external_id}/selfie` (`CandidateSelfieDetailOut`: foto +
`analysis_status`/`analysis_reason` da IA + `in_review`) — o coordenador decide **vendo**, não às
cegas.

### Documento do candidato (RG/CNH) — `POST /candidates/{external_id}/document/decide`

- Aprovou → candidato avisado, biometria roda, extração best-effort preenche filiação/naturalidade
  (candidato) e número/órgão/etc (sub-doc RG/CNH).
- Reprovou → candidato avisado a reenviar a foto (com o motivo).
- Resposta: `CandidateMeOut` — o `/me` inteiro do candidato já atualizado (o front não precisa de
  um segundo GET).
- Irmão: `POST /candidates/{external_id}/document/reset` — destrava o candidato que fixou o
  `doc_type` errado (escolheu RG só tendo CNH, por ex.): zera `doc_type` e volta para a etapa
  `documents`, sem mexer no resto já coletado.

### Documento do student — `POST /students/{external_id}/documents/{document_external_id}/decide`

Mesmo padrão `{approve, reason}` → `DocDecisionOut` (`{external_id, validation_status}`).

### Aprovar/rejeitar candidato → PROMOTOR

- `POST /candidates/{external_id}/approve` — aprova o candidato do polo → promove a **PROMOTOR**
  direto (sem entrevista/trainee — isso saiu do fluxo) e atribui o treino obrigatório. Resposta
  (`CandidateActionOut`): `{external_id, status}` com `status="approved"`.
- `POST /candidates/{external_id}/reject` — body `{reason}`; rejeita sem promover.
  `status="rejected"`.
- Antes de decidir: `GET /candidates/{external_id}` (`CandidateDetailOut`) — perfil, documento
  (fotos + veredito IA), selfie, pix. `GET /candidates` lista a fila de quem aguarda aprovação.

### Matéria de treino — `POST /promoters/{external_id}/materials/{material_external_id}/approve`

Destrava um promotor preso no treino aprovando manualmente uma matéria em aberto (para quem não
tem prática digital para concluir sozinho). `external_id` = do PROMOTOR; `material_external_id` =
da matéria. Resposta (`MaterialApproveOut`): `{promoter_external_id, material_external_id, locked}`.

## Fluxo da TAXA + conclusão da matrícula

A taxa do credenciador é **sempre 2 parcelas**: a 1ª à vista, a 2ª agendada para o vencimento lido
de dentro do próprio QR PIX. Os fatos (paga/agendada) vivem na fila do `finance` sob referência
determinística (`fee_enr_{external_id}_now` / `..._due`), o que torna os dois endpoints
**idempotentes**: repostar não paga/agenda 2×.

### Por que o aluno nunca vê a taxa

`public_status()` mascara: enquanto `enr.status` interno é `fee_paid` ou `fee_scheduled`, o aluno
sempre enxerga `awaiting_release`. É política interna do polo (decisão do Victor, 2026-06-12) — a
taxa é um acerto entre polo e credenciador, o aluno não participa dela nem sabe que existe.

### 1ª parcela — `POST /enrollments/{external_id}/fee/pay`

- Body: `{qr_code, amount?}` (`amount` é opcional — sem ele usa o valor decodificado de dentro do QR).
- Só a partir de `awaiting_release` ou `fee_scheduled`. Já paga → `409 FEE_ALREADY_PAID`.
- Valida/decodifica o QR (chamada de rede ao Asaas, fora da transação) → `422 FEE_QR_INVALID` se
  malformado. Enfileira o PIX **imediato**, mesmo que o QR tenha vencimento (à vista é à vista).
- O `enr.status` **não muda aqui** — só muda quando o pagamento CONFIRMAR pago via webhook
  (`fee.paid` → `apply_fee_paid` → status `fee_paid`), que é o gatilho para o coordenador ir buscar
  as credenciais junto ao credenciador.
- Lock de linha (`select_for_update`) serializa duplo-submit concorrente.
- Resposta: `EnrollmentFeesOut` (`{first, second, first_paid, second_scheduled}`).

### 2ª parcela — `POST /enrollments/{external_id}/fee/schedule`

- Body: `{qr_code, amount?}`.
- Só a partir de `awaiting_release` ou `fee_paid`. Já agendada → `409 FEE_ALREADY_SCHEDULED`.
- QR **sem** data de vencimento → `422 FEE_QR_NO_DUE_DATE` (não existe "chutar uma data").
- O `enr.status` muda **na hora** para `fee_scheduled` (o PIX real dispara sozinho no dia, por
  worker). **Não** depende da 1ª parcela estar paga — só a conclusão exige as duas.

### Conclusão — `POST /enrollments/{external_id}/conclude`

- Body: `{platform_login, platform_password, platform_url?, platform_notes?}` — as credenciais da
  plataforma de estudo que a instituição só libera com a 1ª parcela paga.
- Só a partir de `awaiting_release`, `fee_paid` ou `fee_scheduled`.
- **O que trava**: se faltar qualquer uma das 2 parcelas → `409 FEES_INCOMPLETE`, com
  `extra.missing` listando o que falta (`first_fee_paid` e/ou `second_fee_scheduled`).
- `platform_login` precisa ser único entre matrículas (`ensure_platform_login_available`) — valida
  **antes** de promover, para não deixar a promoção pela metade.
- Promoção atômica: concede a role `student`, `enr.status → completed`, cria o registro `Student`
  (herda `hub`, `self_study`, `bolsista`). O JWT antigo do aluno cai (bump de `token_version`) — ele
  precisa logar de novo, agora como student.
- Notifica o aluno da liberação e, separadamente, das credenciais da plataforma.
- Resposta (`EnrollmentActionOut`): `{external_id, status="completed"}`.

## Diploma e pendências

Fluxo do coordenador conduzindo `student → veteran`:

- `POST /students/{external_id}/exam/grade` — body `{passed, notes?}`. Corrige a prova do aluno.
- `POST /students/{external_id}/pendencies` — body `{kind: "document"|"fee", description,
  amount_cents?}`. Abre uma pendência (documento ou taxa) → aluno vai para `PENDING`.
  `amount_cents` é só registro; **não move dinheiro** aqui.
- `POST /pendencies/{external_id}/resolve` — resolve a pendência; sem pendência aberta o aluno
  segue para o diploma.
- `POST /students/{external_id}/documentation/clear` — coordenador confirma que não há pendência →
  libera a emissão do diploma.
- `POST /students/{external_id}/diploma/issue` — multipart: `diploma` (obrigatório) +
  `transcript` (opcional). Sobe o PDF/imagem do diploma (+ histórico) → aluno fica AGUARDANDO
  RETIRADA e é notificado a comparecer ao polo. Diploma vazio → `422 DIPLOMA_FILE_REQUIRED`.
- `POST /students/{external_id}/diploma/pickup` — multipart `file`: foto do aluno recebendo o
  diploma fisicamente → aluno vira `VETERAN` + comissão do coordenador é gerada. **Todo** o fluxo
  do diploma é conduzido pelo coordenador — o aluno não posta nada. Fora de "aguardando retirada" →
  `409 WRONG_STATUS`; diploma ainda não emitido → `422 DIPLOMA_NOT_ISSUED`.
- `POST /students/{external_id}/manual-selfie` — multipart `file`: encontro presencial para quem
  reprovou a selfie 5× (flag `selfie_needs_meeting`). O coordenador tira a foto dele mesmo e posta
  aqui → a flag cai e a prova destrava.

Consultas de apoio: `GET /students?status=&limit=&offset=` (paginado — `PaginatedStudentsOut`) e
`GET /students/{external_id}` (`HubStudentDetailOut`: docs, pendências, diploma, credenciais da
plataforma, identidade).

## Promotores do polo

- `GET /promoters` — lista com status + se está travado no treino.
- `POST /promoters/{external_id}/suspend` — suspende (não capta nem recebe).
- `POST /promoters/{external_id}/reactivate` — reativa um suspenso.

## Proxy: coordenador age no lugar do cliente

Para o aluno sem prática digital, o coordenador pode agir por ele nas mesmas ações do wizard —
sempre auditado (log `leadership.acted_for` com `action`, `enrollment`, `by`) e gated por
`enrollment.coordinated_user_ext` (o coordenador precisa coordenar o hub daquela matrícula):

- `POST /enrollments/{external_id}/address` — body `{cep}` → grava endereço via ViaCEP.
- `POST /enrollments/{external_id}/documents/rg/photo/{slot}` — multipart `file`; `slot` =
  `front`|`back`|`full`. IA valida normal; cair em revisão → decide pelo `/rg/decide` de sempre.
- `POST /enrollments/{external_id}/selfie` — multipart `file`. IA + biometria validam normal;
  review → decide pelo `/selfie/decide`. Devolve o mesmo ack de análise (poll/TTL) que o wizard do
  cliente recebe.
- `PATCH /enrollments/{external_id}/profile` — body `CorrectIdentityIn` (`mother_name`,
  `father_name`, `marital_status`, `nationality`, `birthplace`) — corrige o que o OCR extraiu
  torto. **Não** mexe em nome/nascimento (autoridade é o CPFHub) nem em pix.

## Códigos de erro relevantes

| code | quando | http/extra |
|---|---|---|
| `NOT_HUB_COORDINATOR` | loga como coordenador mas não coordena nenhum polo, ou tenta agir em matrícula de outro polo | 403 |
| `WRONG_STATUS` | ação fora da etapa esperada da matrícula/aluno | 409, `expected_status` |
| `FEES_INCOMPLETE` | `conclude` sem as 2 parcelas | 409, `missing: [...]` |
| `FEE_ALREADY_PAID` / `FEE_ALREADY_SCHEDULED` | repostar parcela já resolvida | 409 |
| `FEE_QR_INVALID` / `FEE_QR_NO_DUE_DATE` | QR PIX inválido / sem vencimento no `schedule` | 422 |
| `RG_NOT_IN_REVIEW` / `DOC_NOT_IN_REVIEW` / `SELFIE_NOT_IN_REVIEW` | decide algo que não está em revisão | 422, `*_validation_status` |
| `ALREADY_APPROVED` | submeteu algo já decidido | 409 |
| `EDUCATION_LEVEL_INVALID` / `EDUCATION_GRADE_OUT_OF_RANGE` | escolaridade fora da faixa | 422, `min`/`max` |
| `DOC_TYPE_LOCKED` / `DOC_TYPE_NOT_SET` | troca de tipo de doc travada | 422 |
| `MILITARY_MALE_ONLY` | doc militar só para masculino | 422 |
| `SLOT_INVALID` / `INVALID_KIND` / `INVALID_MATERIAL_KIND` | parâmetro inválido | 422 |
| `MATERIAL_NOT_FOUND` / `MATERIAL_NOT_ASSIGNED` / `MATERIAL_INACTIVE` | material do LMS | 404/422 |
| `OPEN_PENDENCIES` / `PENDENCY_NOT_FOUND` | pendência do aluno | 409/404 |
| `NO_PENDING_EXAM` / `DIPLOMA_NOT_ISSUED` | exame/diploma fora de ordem | 409 |
| `DIPLOMA_FILE_REQUIRED` | `diploma/issue` sem o arquivo do diploma | 422 |
| `NO_HUB` / `COMMISSION_PAYEE_INVALID` / `PIX_INVALID` | comissão/pix | 422 |
| `LEAD_NOT_FOUND` / `ENROLLMENT_NOT_FOUND` | recurso não existe (ou não é do polo) | 404 |

`GET /students` é paginado (`limit`/`offset` → `{items, total, limit, offset}`); as demais listas
são arrays diretos.

## O que o backend ESPERA do frontend

- [ ] Nunca cachear um "sou coordenador" fora do fluxo `check`/`login` — o gate real é sempre
      servidor-side (`NOT_HUB_COORDINATOR` pode disparar a qualquer momento, ex. hub sem
      coordenador ou troca de coordenação).
- [ ] Tratar `check` sem `is_coordinator` como redirecionamento, não erro — usar `detail` + `roles`
      para mandar a pessoa para a área certa, reaproveitando o OTP já disparado (não pedir de novo).
- [ ] Montar a tela de decisões a partir de `/reviews`, roteando por `type`+`kind` — não assumir
      nomes de balde fixos no front.
- [ ] Antes de decidir selfie/documento, buscar o detalhe (`GET .../selfie`, `GET
      /candidates/{id}`) e mostrar a foto + motivo da IA — nunca decidir "às cegas".
- [ ] Tratar a taxa como assunto interno do polo: **nunca** expor `fee_paid`/`fee_scheduled` para
      telas do aluno; essas telas só existem no leadership.
- [ ] Antes de chamar `conclude`, checar via `GET /enrollments/{id}` (`fees.first_paid` e
      `fees.second_scheduled`) se as 2 parcelas estão resolvidas, para não bater em
      `FEES_INCOMPLETE` sem necessidade — mas sempre tratar o 409 mesmo assim (corrida é possível).
- [ ] `platform_login` do `conclude` precisa ser único — tratar erro de duplicidade tratado pelo
      backend antes de promover (a matrícula não fica "meio concluída").
- [ ] Uploads (RG, selfie, diploma, pickup, manual-selfie) são sempre `multipart/form-data`.
- [ ] Ações de proxy (agir no lugar do cliente) devem deixar claro na UI que é uma ação EM NOME do
      aluno — o backend audita quem fez (`acted_by`), o front deve refletir isso na tela.
- [ ] Após qualquer ação de proxy sobre RG/selfie, reusar o mesmo fluxo de revisão
      (`/rg/decide`/`/selfie/decide`) — proxy não pula a revisão da IA.
