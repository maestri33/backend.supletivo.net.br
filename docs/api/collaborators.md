# API Collaborators (Promotor)

Fonte: `api/collaborators.py`, `users/roles/candidate/service.py`, `users/roles/promoter/service.py`,
`users/roles/training/service.py`, `users/blocks/service.py` + `users/blocks/signals.py`.

Prefixo de tudo abaixo: `/api/v1/collaborators`.

## Visão geral

Quem usa: o **PROMOTOR** — o colaborador que capta alunos (leads) via link `?ref=`. Antes de virar
promotor, essa pessoa é um **CANDIDATO** passando por um wizard de cadastro.

Dois sub-fluxos:

1. **Candidatura** (`candidate → promoter`): wizard de coleta de dados, aprovado automaticamente pela
   selfie (ou manualmente pelo coordenador). Espelha o funil do aluno (`enrollment`), mas com
   diferenças (ver tabela mais abaixo).
2. **Treino** (LMS do promotor): assim que vira promotor, o backend atribui matérias obrigatórias.
   Enquanto houver matéria obrigatória pendente, o promotor **nasce travado** — só o treino aparece;
   a captação (`ref_url`, leads, comissões) fica bloqueada até ele passar.

Regra de ouro do wizard (accept-first, plan/15): **o candidato avança sem esperar a IA validar**. Toda
foto/documento entra assíncrono (fila Django-Q); o front recebe um **ack** (`{stored, analysis_status,
poll_after_ms, expires_at}`) e continua. Se a IA rejeitar depois, o jeito de avisar o candidato é um
**ValidationBlock** (não um erro bloqueante retroativo).

Máquina de estados do `Candidate.status` (`users/roles/candidate/models.py:20-30`):

```
started → profile → address → documents → pix → education → selfie → completed → approved
                                                                            ↳ (soft) rejected
```

`completed` na prática não é alcançado pelo caminho automático — a selfie aprovada promove direto
(`_complete_candidate`); `completed`/`rejected` só aparecem no fluxo manual do coordenador. Toda
mutação do wizard devolve o **`me_dict` canônico** (`CandidateMeOut`): o front roteia a tela sem
re-fetch.

## Fluxo 1: Candidatura (candidate → promoter)

### 1. Registro — `POST /auth/register` (`api/collaborators.py:434`, público)

- **Front envia**: `{cpf, phone, email, hub?}` — `hub` é o `external_id` do `?ref=` da landing (pode
  ser um POLO ou um PROMOTOR; resolvido pro hub dele).
- **Backend faz** (`candidate_iface.create_candidate`, `users/roles/candidate/service.py:42`):
  resolve o hub de captação (`hub_iface.resolve_capture_hub`; ref ruim/ausente cai no polo padrão,
  não bloqueia), cria o `User` (role `candidate`) e o `Candidate(status=STARTED)` ligado ao hub.
- **Retorna**: `201 {external_id (candidato), user_external_id (user — é o que o /auth/login usa),
  status}`.
- **Front deve**: guardar `user_external_id` para o login/OTP a seguir.
- Erros: `NO_HUB` (422) se nem o polo padrão existir.

### 2. Login — `POST /auth/check` + login do funil (`api/collaborators.py:446`, `add_funnel_login`)

- `check` dispara OTP por cpf/phone e **vaza existência** (`found`+`roles`) — o front decide cadastro
  novo × login.
- Login funil (`add_funnel_login`, roles aceitas: `coordinator > promoter > training > candidate`, a
  mais avançada primeiro) emite o JWT com todas as roles ativas do user.

### 3. Perfil — `POST /candidate/profile` (`api/collaborators.py:489`)

- **Front envia**: `{mother_name?, father_name?, marital_status?, birthplace?, nationality?}` — só o
  que o **documento não traz** (filiação/naturalidade vêm da extração OCR depois).
- **Backend faz** (`set_profile`, `service.py:181`): grava no `Profile` (nunca no `Candidate`); exige
  status `started`/`profile`; avança `started→profile` na primeira chamada.
- **Retorna**: `me_dict` (`CandidateMeOut`).
- **Front deve**: renderizar o form; qualquer status fora de `started/profile` → `409 WRONG_STATUS`
  com `expected_status` (o front redireciona pra etapa certa).

### 4. Endereço — `GET/POST/PATCH /candidate/address` (linhas 497-521)

- `GET`: devolve o endereço + `missing_fields` (o front só pede input do que falta).
- `POST {cep}`: busca no ViaCEP e preenche; `missing_fields` avisa o que falta digitar (cidade de CEP
  único vem com rua/bairro vazios). Avança `profile→address` quando `address_iface.is_complete`.
- `PATCH {street?, number?, complement?, neighborhood?, city?, state?}`: sobrescreve o que vier
  (não-vazio); serve pra corrigir dado errado.
- Exige status `profile`/`address`.

### 5. Documento — RG ou CNH (linhas 523-635)

Diferente do aluno: **o candidato aceita RG e CNH** (o aluno só aceita RG).

- `POST /candidate/documents/classify` (multipart, síncrono, linha 584): classificação RÁPIDA da foto
  ANTES do upload — só reconhece (é doc? rg/cnh? completo/frente/verso?), **não valida**. Alimenta a
  UI generativa. `is_document=null` → o front pergunta pra pessoa confirmar.
- `POST /candidate/documents/photo/{slot}` (multipart, linha 555): slots
  `rg_front|rg_back|rg_full|cnh_front|cnh_back|cnh_full`. O **1º slot enviado define o `doc_type`**
  do candidato — imutável depois (`DOC_TYPE_LOCKED`, só o coordenador destrava via
  `reset_doc_type`). Dispara `validate_document` (Django-Q): visão → OCR/extração → biometria
  best-effort. Retorna **ack** `AnalysisAckOut`.
- `POST /candidate/documents` (linha 523): grava campos textuais direto (`doc_type, number,
  issuing_agency, issue_date, category, national_register, date_of_birth, expires_on`); avança
  `address→documents`.
- `GET /candidate/document` (linha 534): seção rica — fotos, `analysis_status/reason`, `extracted`,
  `missing_fields`, **`next_slot`** (qual foto pedir agora — nunca frente+verso ao mesmo tempo) e
  `photos` (status por slot).
- `PATCH /candidate/document` (linha 545): completa/corrige o que o OCR não trouxe; aceito em
  qualquer etapa da coleta.
- **Avanço `documents→pix`** (`_advance_documents`, `service.py:606`): acontece assim que há
  `number` + alguma foto (frente ou inteira) — **sem esperar o veredito da IA** (comentário no
  código: `# ponytail: sem gate de validação — usuário avança na hora; rejeição = ValidationBlock`).
- Comprovante de residência — `POST /candidate/documents/address-proof` (linha 595, multipart,
  obrigatório): assíncrono, acompanha por `address_proof.status` no `me_dict`. Se vier
  `needs_kinship`, `POST /candidate/documents/address-proof/kinship {relation}` (linha 606) libera.

### 6. Pix — `POST /candidate/pix` (linha 620)

- **Front envia**: `{key, key_type}` (aceita apelidos PT: celular/aleatoria/etc — normalizado pro
  canônico DICT).
- **Backend faz** (`set_pix`, `service.py:1137`): valida a chave no **Asaas/DICT de verdade**
  (⚠️ move R$0,01 real) contra o CPF do `Profile`; grava só no `Profile`. Exige status
  `documents`/`pix`.
- Erros: `PROFILE_CPF_MISSING` (422, refazer cadastro), `PIX_INVALID` (422, `extra.reason`).
- Avança `documents→pix` (o status já estaria em `pix` normalmente; aqui fecha a etapa).

### 7. Escolaridade — `POST /candidate/education` (linha 630)

- **Front envia**: `{level: "fundamental"|"medio", completed: bool}`.
- **Backend faz** (`set_education`, `service.py:1178`): grava no `Profile` (nível-pessoa, reusado se
  virar aluno depois); **última pergunta antes da selfie** (tem que vir antes porque a selfie
  aprovada auto-promove). Sem médio completo → o promotor nasce **`pre_matriculado`**
  (`users/roles/promoter/service.py:33`, F4: aos 3 leads pagos vira bolsista automático).
  Avança `pix→education`.

### 8. Selfie — `POST/GET /candidate/selfie` (linhas 640-681)

- `POST` (multipart): salva a foto, marca `selfie_status=pending`, **enfileira**
  `validate_candidate_selfie` (Django-Q), responde na hora com o ack. O envio da selfie **também é
  o aceite do contrato de promotor** (`consent_accepted=True`, versão/hash gravados —
  `GET /contract/current`, linha 667, expõe o texto atual).
- `GET`: leitura pura do estado (`analysis_status/reason/expires_at`) — não muta nada; o TTL
  estourado vira `review` só no job agendado `age_stale_selfies`.
- Pipeline assíncrona (`run_selfie_validation`, `service.py:1336`): liveness → face-match biométrico
  vs. o documento aprovado → 3 desfechos:
  - **approved** → `_complete_candidate` → `_promote_to_promoter` (cria `Promoter`, atribui
    matérias fixas do treino, `status=approved`).
  - **rejected** → avisa o candidato pra tentar de novo; na 5ª reprovação **não trava** — marca
    `needs_meeting` (nível-pessoa) e promove mesmo assim (o encontro presencial fica pro fim do
    curso).
  - **review** → avisa o coordenador (`decide_selfie`, grupo `leadership`, fora deste doc).

### 9. Aprovação do coordenador (fallback manual)

Não fica em `collaborators` — vive no grupo `leadership` (`approve_candidate`/`reject_candidate` em
`users/roles/candidate/service.py:1651/1683`). É o caminho quando a selfie cai em `review`: o
coordenador decide vendo (`candidate_detail_for_coordinator`). Rejeição é **soft** — o candidato
`rejected` continua na fila e pode ser aprovado depois; nunca é destrutivo.

## Fluxo 2: Treino (LMS do promotor)

Ao virar promotor (`_promote_to_promoter` → `training_iface.on_became_promoter`,
`users/roles/training/service.py:280`): atribui todas as matérias **FIXAS** ativas
(`MaterialAssignment` pending). Se sobrar alguma **obrigatória** (`blocking=True`) pendente, o
promotor ganha a role overlay `training` — **essa é a trava**. A trava é lida do banco
(`is_locked`/`pending_blocking_count`), nunca do JWT — não precisa de novo login pra destravar.

### Endpoints (role `promoter`, prefixo `/training`)

- `GET /training/materials` (linha 688): matérias atribuídas AO promotor (fixas do onboarding +
  transitórias publicadas pra ele) **com conteúdo** (texto/blocos/vídeo/foto/pergunta), sem
  gabarito, + status.
- `GET /training/progress` (linha 696): mesmo formato, sem conteúdo — atalho pra barra de progresso.
- `POST /training/submissions` (linha 704): `{material_external_id, answer}` — resposta em texto.
- `POST /training/submissions/audio` (linha 715, multipart `material_external_id` + `file`):
  resposta em áudio (mp3/m4a/aac/ogg/webm/wav, até `MAX_UPLOAD_MB`); o backend transcreve (Gemini
  STT) e corrige na mesma task.

### Correção

Toda submissão nasce `pending` e é corrigida **assíncrona** por IA
(`django_q` task `grade_submission` → `apply_grade`, `service.py:463`): nota (`Decimal`) +
justificativa; `grade >= pass_score()` → `approved`, senão `rejected`. Reenviar a mesma matéria
resolve o bloco na hora (`blocks.resolve_for_source`, ver seção blocks) — não espera a IA re-corrigir
pra tirar o aviso.

Aprovado → `_mark_assignment_approved` marca a atribuição `approved` e **re-checa a trava**
(`_recheck_lock`): zerou as obrigatórias pendentes → tira a role overlay `training` e notifica
"painel liberado" (`training.cleared`, evento com TTS).

### O que acontece quando reprova

- `Submission.status = rejected`.
- Um **signal `post_save`** (`users/blocks/signals.py`, conectado em `users/apps.py`) cria
  automaticamente um `ValidationBlock` com `source_type=f"training_{material.id}"` — não é o service
  de training que chama `create_block` diretamente.
- Notifica o promotor via WhatsApp (`training.submission_rejected`) com a justificativa (fail-open:
  falha no notify não derruba a correção).
- O promotor **continua travado** (a matéria segue `pending` até uma submissão aprovar) — ele
  reenvia a resposta pra tentar de novo.

### Coordenador destrava manualmente

`POST` do grupo `leadership` → `coordinator_approve_material` (`training/service.py:510`): aprova
uma matéria **em aberto** (sem submissão) de um promotor preso — pensado pra quem não tem prática
digital. `list_locked_promoters_for_hub` alimenta o inbox do coordenador.

## Diferenças vs funil do aluno

| Aspecto | Promotor (collaborators) | Aluno (clients/enrollment) |
|---|---|---|
| Documento aceito | **RG e CNH** (`doc_type` escolhido no 1º upload) | Só RG |
| Pix | **Sim** — obrigatório, valida no Asaas/DICT (etapa própria do wizard) | Não faz parte do wizard do aluno |
| Escolaridade | Coletada no wizard (`education`), define `pre_matriculado` | Não aplicável (já é aluno) |
| Contrato/consentimento | Aceite implícito ao enviar a selfie (`PROMOTER_CONTRACT`) | Contrato do aluno é outro (fora deste doc) |
| Pós-aprovação | **Treino (LMS) trava** o painel até completar matérias obrigatórias | Não há treino |
| Papel final | `Promoter` (capta leads, ganha comissão) | `Student`/`Enrollment` (estuda) |
| Modelo de status | `Candidate.status` (started…approved) | `Enrollment` tem sua própria máquina |
| Auto-estudo | Promotor pode **virar aluno** também (`/promoter/study/*`, preço próprio sem comissão) | — |

## ValidationBlocks

Neste funil, blocks vêm de um **signal centralizado** (`users/blocks/signals.py`, `_on_validation_change`,
conectado em `users/apps.py` a `post_save` de `RG`, `CNH`, `AddressProof`, `StudentDocument`,
`Enrollment`, `Submission`). Quando o campo de validação (`validation_status`/`selfie_status`/`status`)
vira `rejected`, o signal cria o bloco; quando volta a `pending`/`approved`, resolve.

`source_type` relevantes para candidato/promotor:

| source_type | dispara quando | `action_route` (candidato) | resolve quando |
|---|---|---|---|
| `rg` | `RG.validation_status` → rejected | `/candidate/document` | novo veredito pending/approved (re-upload do slot) |
| `cnh` | `CNH.validation_status` → rejected | `/candidate/document` | idem |
| `address_proof` | `AddressProof.validation_status` → rejected | `/candidate/address` | novo upload / kinship aceito |
| `selfie` | `Candidate.selfie_status` → rejected | `/candidate/selfie` | novo upload da selfie resolve |
| `training_{material_id}` | `Submission.status` → rejected | (sem rota específica no mapa do candidato/promotor) | reenvio da resposta resolve na hora (`resolve_for_source` explícito em `training/service.py:394`), independente do resultado da re-correção |

A selfie do candidato (`Candidate.selfie_status`) está conectada ao signal de blocos (paridade com
o `Enrollment.selfie_status` do aluno): uma selfie reprovada gera `ValidationBlock`
(`source_type="selfie"`) **e** dispara a notificação — o front vê o bloco no `/candidate/me`.

`GET /candidate/me` e `GET /promoter/me` sempre devolvem `blocks: [{external_id, source_type, title,
description, action_label, action_route, created_at}]` — o front lista os blocos ativos como avisos
não-bloqueantes (banner/modal com botão pro `action_route`).

## Códigos de erro relevantes

| code | quando | http | extras |
|---|---|---|---|
| `WRONG_STATUS` | ação fora da etapa do wizard | 409 | `expected_status` |
| `NO_HUB` | nenhum polo disponível pro cadastro | 422 | — |
| `INVALID_DOC_TYPE` | `doc_type` ≠ rg/cnh | 422 | — |
| `SLOT_INVALID` | slot de foto desconhecido | 422 | — |
| `DOC_TYPE_LOCKED` | tentando trocar de RG↔CNH depois do 1º upload | 422 | — |
| `DOC_TYPE_NOT_SET` | PATCH/GET antes de qualquer foto enviada | 422 | — |
| `PIX_INVALID` | chave Pix inválida ou não é do titular | 422 | `reason` |
| `PROFILE_CPF_MISSING` | perfil sem CPF (refazer cadastro) | 422 | — |
| `EDUCATION_LEVEL_INVALID` | nível fora de fundamental/medio | 422 | `level`, `allowed` |
| `MATERIAL_NOT_FOUND` / `TRAINEE_NOT_FOUND` / `CANDIDATE_NOT_FOUND` / `PROMOTER_NOT_FOUND` | recurso não existe | 404 | — |
| `MATERIAL_INACTIVE` | submissão em matéria desativada | 422 | — |
| `MATERIAL_NOT_ASSIGNED` | matéria não atribuída a este user | 422 | — |
| `ALREADY_GRADING` | já há resposta pendente de correção nesta matéria | 409 | — |
| `INVALID_AUDIO_TYPE` | áudio fora de mp3/m4a/aac/ogg/webm/wav | 422 | — |
| `AUDIO_TOO_LARGE` | áudio acima de `MAX_UPLOAD_MB` | 422 | — |
| `SELFIE_NOT_IN_REVIEW` | decisão de selfie fora de `review` (grupo leadership) | 422 | `selfie_status` |
| `NOT_HUB_COORDINATOR` | coordenador não é do polo (grupo leadership) | 403 | — |
| `CPF_EXISTS` / `PHONE_EXISTS` / `EMAIL_EXISTS` | cadastro duplicado | 409 | — |
| `CPF_INVALID` / `PHONE_INVALID` / `CPF_NOT_FOUND` | dado rejeitado na validação | 422 | — |

## O que o backend ESPERA do frontend

- [ ] Sempre reler o `me_dict`/`PromoterMeOut` devolvido por CADA mutação — nunca assumir o próximo
      passo por conta própria; `status` e `missing_fields` mandam.
- [ ] Tratar `409 WRONG_STATUS` como roteamento, não como erro fatal: usar `extra.expected_status`
      para levar o usuário à etapa certa.
- [ ] Documento é **foto-primeiro**: nunca pedir número/tipo antes do upload — o 1º slot enviado
      define `doc_type` e é imutável (se errar, só o coordenador destrava via `reset_doc_type`).
- [ ] Usar `GET /candidate/document.next_slot` para saber qual foto pedir agora — nunca mostrar
      frente+verso ao mesmo tempo.
- [ ] Todo upload (foto de documento, comprovante, selfie) devolve um **ack assíncrono**
      (`stored/analysis_status/poll_after_ms/expires_at`) — fazer polling do GET correspondente, não
      bloquear a UI esperando resposta síncrona.
- [ ] Aceitar RG **e** CNH no fluxo do promotor (diferente do aluno) — não hardcode "só RG".
- [ ] Pix move dinheiro real (R$0,01, validação DICT) — tratar `PIX_INVALID` com mensagem clara
      (`extra.reason`), não deixar o usuário martelar o submit.
- [ ] Coletar escolaridade **antes** da selfie — a selfie aprovada promove sozinha (sem tela
      intermediária no backend); o front precisa ter a pergunta de escolaridade resolvida antes de
      abrir a câmera.
- [ ] Envio da selfie é o aceite do contrato — exibir `GET /contract/current` antes/durante essa
      etapa, não depois.
- [ ] Depois de promovido, checar `promoter.locked` + `pending_materials` — se travado, mostrar só o
      treino (nada de captação/leads/comissões na UI até destravar).
- [ ] Reprovação de matéria de treino não impede reenviar — reenviar resolve o aviso (`block`) na
      hora, mesmo antes da IA re-corrigir.
- [ ] Renderizar `blocks: [...]` de `/candidate/me` e `/promoter/me` como avisos não-bloqueantes
      (banner com `action_label`/`action_route`), nunca travar a navegação por causa deles — accept
      first, sempre.
