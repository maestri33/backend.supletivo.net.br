# Documentação de fluxo das APIs

Guias de **fluxo** (não referência técnica) dos 4 grupos da API Ninja do backend-supletivo. Cada um explica, por público: o passo a passo do funil, o que o backend faz internamente, o que retorna, e o **contrato com o frontend** (o que o app precisa fazer).

Base de todas: `/api/v1/<grupo>/...` — grupos versionados montados em `core/urls.py`.

| Guia | Público | Grupo | Resumo |
|---|---|---|---|
| [clients.md](clients.md) | Aluno | `/api/v1/clients/` | Funil de matrícula accept-first: register → RG → endereço → selfie → student. ValidationBlocks. |
| [collaborators.md](collaborators.md) | Promotor | `/api/v1/collaborators/` | Candidatura (vira promotor) + treino (LMS). Aceita CNH, tem PIX. |
| [leadership.md](leadership.md) | Coordenador | `/api/v1/leadership/` | Gerência do polo: decide docs/selfie em revisão, taxa, conclui matrícula, diploma. |
| [staff.md](staff.md) | Admin (superuser) | `/api/v1/staff/` | Hubs, materiais de treino, finanças, notificações, integrações. |

## Conceitos transversais

**Accept-first (clients + collaborators):** o usuário avança no wizard sem esperar a validação de IA. A análise roda em background; se rejeitar, cria um **`ValidationBlock`** (flag no `/me`) que o app mostra como modal. O re-upload resolve o bloco automaticamente. O usuário nunca fica "preso esperando a IA".

**Envelope de erro (todos os grupos):** todo 4xx/5xx sai como `{detail, code, ...extra}`. O front roteia por `code` (`switch(code)`), nunca parseia `detail`. Códigos comuns em `api/base.py::COMMON_ERROR_REGISTRY`; específicos no `_ERROR_REGISTRY` de cada grupo.

**Auth:** JWT (RS256) por padrão. Login passwordless por OTP (WhatsApp). Cada grupo tem seu `/auth/check` + `/auth/login` + `/auth/refresh`. Staff/coordenador não têm registro público — são provisionados por cima.
