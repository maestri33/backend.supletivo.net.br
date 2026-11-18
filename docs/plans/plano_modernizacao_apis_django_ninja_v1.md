# Plano Arquitetural: Modernização e Reestruturação das APIs com Django Ninja e Pydantic v2

> **Documento de Especificação Técnica e Blueprint de Execução**  
> **Repositório:** `https://github.com/maestri33/backend.supletivo.net.br`  
> **Autor / Responsável Técnico:** Arquiteto de APIs (Victor Maestri)  
> **Status:** EM ANDAMENTO (Fase 1 implementada e validada)  
> **Data:** 16 de Novembro de 2026  
> **Diretrizes Estruturais:** Django Ninja 1.6+, Pydantic v2, OpenAPI 3.1, Zero .env (Cloudflare-ready)

---

## 1. Diagnóstico do Estado Atual e Inventário Técnico

### 1.1. Fragmentação em 7 Instâncias Isoladas de `NinjaAPI`
Atualmente, o `core/urls.py` monta 7 instâncias separadas de `NinjaAPI` geradas pela fábrica `build_group` (`api/base.py`):
1. `clients_api` montada em `/api/v1/clients/`
2. `collaborators_api` montada em `/api/v1/collaborators/`
3. `leadership_api` montada em `/api/v1/leadership/`
4. `admin_api` montada em `/api/v1/admin/` (cópia 1:1 idêntica ao `staff_api`)
5. `staff_api` montada em `/api/v1/staff/`
6. `tools_api` montada em `/api/v1/tools/`
7. `health_api` montada em `/api/v1/health/`

#### Impactos Críticos:
* **7 Swagger UIs e 7 `openapi.json`:** O frontend precisa lidar com especificações fragmentadas ou montar scripts ad-hoc para gerar tipagem TypeScript.
* **Colisão de `operation_id` Oculta:** Ao tentar unificar o schema, foram detectadas mais de 15 colisões de `operation_id` (ex.: `api_base_refresh`, `api_base_login`, `recover_phone_endpoint`, aliases em candidatos e promotores), que antes ficavam mascaradas pelo isolamento de cada instância.
* **Duplicação de Código Infraestrutural:** Endpoints utilitários (`/health`, `/whoami`, `/refresh`) são recriados e registrados redundantemente em cada instância.

### 1.2. Mapeamento de Código Duplicado e Dívida Técnica

| Padrão Antigo | Onde Ocorre | Problema Identificado | Solução com Django Ninja |
| :--- | :--- | :--- | :--- |
| **`_guard(request)` defensivo** | `lead.py`, `enrollment.py`, `student.py`, `candidate.py`, `promoter.py`, `training.py` | Cada view chama manualmente uma função auxiliar que extrai claims, checa roles e busca a model no banco. | Injeção de dependência via `Depends(get_current_*)`. |
| **`add_auth_refresh` e `add_funnel_login`** | `api/base.py` chamado em 4 routers de autenticação | Código imperativo que acopla handlers genéricos com os mesmos nomes de função, gerando colisões de `operation_id`. | Routers de Auth modulares com handlers tipados e nomes de operação unívocos. |
| **Serialização Manual `to_dict`** | `lead_self_dict`, `to_dict` em Lead, Enrollment, Student, Candidate, Promoter, Hub | Construção artesanal de dicionários Python (`dict`), ignorando as capacidades de introspecção do Pydantic v2. | Schemas Pydantic v2 com `model_config = ConfigDict(from_attributes=True)` e `@computed_field`. |
| **Paginação por Slicing Rígido** | `api/staff/routers/users.py`, `system.py`, `notify.py`, `finance.py` | Uso de `[:200]`, `[:100]` ou respostas manuais `{"items": ..., "total": ..., "limit": ..., "offset": ...}`. | Decorador nativo `@paginate(PageNumberPagination)` do Django Ninja. |
| **Filtros Manuais com `FilterSchema`** | `api/staff/routers/users.py`, `documents.py`, `finance.py` | Instanciação condicional manual (`f = filters if isinstance(...) else ...`) e repasse de campos soltos. | Injeção declarativa `filters: MyFilterSchema = Query(...)` e aplicação direta `filters.filter(qs)`. |
| **Bloqueio Síncrono de I/O** | `turnstile`, `notify/whatsapp`, gateways | Chamadas HTTP externas lentas em views síncronas bloqueando workers gunicorn/uvicorn. | Rotas assíncronas `async def` com `httpx.AsyncClient`. |

---

## 2. Injeção de Dependências Declarativa (`api/deps.py`)

A infraestrutura foi desenhada e implementada no arquivo `api/deps.py`, provendo o mecanismo `Depends` e o `InjectedRouter`, além de resolvers fortemente tipados.

### 2.1. Como Funciona a Injeção
O Django Ninja padrão não possui `Depends` nativo como o FastAPI. Para implementar injeção idiomática sem poluir o schema OpenAPI:
1. `Depends(callable)` marca o parâmetro da view.
2. `inject_dependencies` inspeciona a assinatura, extrai os parâmetros dependentes e redefine `__signature__` para que o Django Ninja veja apenas os parâmetros reais de entrada HTTP (path, query, body, header).
3. Na execução da requisição, as dependências são resolvidas em runtime (com suporte completo a funções sync e `async def`) e injetadas como `kwargs` na view.
4. Qualquer exceção de domínio levantada dentro do resolver (`Unauthorized`, `Forbidden`, `NotFound`) é capturada pelo exception handler central da API Ninja, devolvendo a resposta HTTP e o envelope de erro `{detail, code}` padronizado.

### 2.2. Resolvers Canônicos Implementados

```python
# api/deps.py
from api.deps import Depends, get_current_user, get_current_student, get_current_coordinator, get_current_promoter

# Exemplo 1: View de Aluno com Entidade Pronta
@router.get("/me", response=StudentMeOut, summary="Dados e progresso do aluno")
def student_me(request, student: Student = Depends(get_current_student)):
    return student

# Exemplo 2: View de Liderança recebendo Usuário e Polo Coordenado
@router.get("/students", response=list[HubStudentOut], summary="Listar alunos do polo")
@paginate(PageNumberPagination)
def list_hub_students(
    request,
    status: str | None = None,
    ctx: CoordinatorContext = Depends(get_current_coordinator),
):
    return student_iface.get_queryset_for_hub(hub=ctx.hub, status=status)

# Exemplo 3: View Administrativa com Superuser Garantido
@router.get("/hubs", response=list[HubOut])
def list_hubs(request, admin: User = Depends(get_current_admin)):
    return Hub.objects.select_related("coordinator", "address").all()
```

### 2.3. Resolvers Disponíveis no Módulo:
* `get_current_principal(request) -> Principal`: Validação estrita do token JWT sem tocar o banco.
* `get_current_user(request) -> User`: Resolução do usuário ativo no banco de dados.
* `get_current_admin(request) -> User`: Garante `user.is_superuser` (status HTTP 403 `STAFF_ONLY`).
* `get_current_student(request) -> Student`: Resolução da model `Student` com `select_related('user', 'hub')`.
* `get_current_lead(request) -> Lead`: Resolução da model `Lead`.
* `get_current_enrollment(request) -> Enrollment`: Resolução da model `Enrollment`.
* `get_current_promoter(request) -> Promoter`: Resolução da model `Promoter` com `select_related('user', 'hub')`.
* `get_current_coordinator(request) -> CoordinatorContext`: Resolução atômica do `User` e do `Hub` sob sua coordenação.
* `require_role(*roles)`: Fábrica de gate de papéis canônicos.

---

## 3. Blueprint da API v1 Unificada (Swagger Consolidado)

### 3.1. Arquitetura de Roteamento Unificado
Em vez de instanciar 7 objetos `NinjaAPI`, cria-se um único ponto de entrada `api_v1`:

```
/api/v1/
├── docs                     (Swagger UI Consolidado)
├── openapi.json             (OpenAPI 3.1 Unificado)
│
├── /auth/                   [Tag: Auth]              -> Login, OTP, Refresh, Me (/whoami), Recovery
├── /clients/                [Tag: Students]          -> Lead, Matrícula, Aluno, Prova, Diploma
├── /collaborators/          [Tag: Promoters]         -> Candidato, Onboarding, Treinamento, Indicação
├── /leadership/             [Tag: Hubs / Leadership] -> Alunos do Polo, Revisão de Documentos, Diplomas
├── /staff/                  [Tag: Staff / Admin]     -> Polos, Usuários, Finanças, Notificações, Config
├── /admin/                  [Tag: Staff / Admin]     -> Alias canônico espelhado de /staff/
├── /tools/                  [Tag: Tools]             -> Agendamentos Cron, Webhooks de IA, Radar de Leads
└── /health/                 [Tag: Health]            -> Liveness pública (/healthz) e diagnóstico de infra
```

### 3.2. Resolução de Conflitos de `operation_id`
Para garantir geração determinística de SDKs TypeScript via `openapi-typescript` ou `@hey-api/openapi-ts`:
1. Cada operação recebe um `operation_id` semântico explícito ou derivado da rota e do método (ex.: `auth_login_client`, `auth_refresh_token`, `students_get_me`, `staff_list_leads`).
2. Rotas com múltiplos métodos ou aliases de compatibilidade (como `/recover-phone` e `/recovery/phone`) apontam para a mesma operação sem duplicar `operation_id`.

### 3.3. Retrocompatibilidade Total
* **Nenhum endpoint de URL existente muda de caminho.** As requisições do frontend continuam trafegando para `/api/v1/clients/...`, `/api/v1/collaborators/...`, `/api/v1/leadership/...`, `/api/v1/staff/...`, etc.
* Para os testes existentes que inspecionam `/api/v1/<grupo>/openapi.json`, mantém-se rotas de compatibilidade que exportam o subconjunto de schemas durante a transição.

---

## 4. Serialização Declarativa Pydantic v2

### 4.1. Fim de `to_dict()` e Dicionários Artesanais
A conversão manual de QuerySets e Models para dicionários gera código frágil, propenso a `KeyError` e com alto custo de manutenção.

### 4.2. Padrão Declarativo com `from_attributes=True`:
```python
from ninja import Schema, Field
from pydantic import ConfigDict, computed_field

class HubAddressOut(Schema):
    model_config = ConfigDict(from_attributes=True)
    zipcode: str = Field(alias="cep")
    street: str
    number: str
    neighborhood: str
    city: str
    state: str

class HubOut(Schema):
    model_config = ConfigDict(from_attributes=True)
    external_id: str
    brand: str
    is_default: bool
    address: HubAddressOut | None = None

    @computed_field
    def coordinator_external_id(self) -> str | None:
        return str(self.coordinator.external_id) if self.coordinator else None

    @computed_field
    def coordinator_name(self) -> str | None:
        if self.coordinator and hasattr(self.coordinator, "profile"):
            return self.coordinator.profile.name
        return None
```
Com isso, a view torna-se uma única linha:
```python
@router.get("/hubs", response=list[HubOut])
def list_hubs(request, admin: User = Depends(get_current_admin)):
    return Hub.objects.select_related("coordinator__profile", "address").all()
```

---

## 5. Paginação e Filtros Nativos do Ninja

### 5.1. Paginação com `@paginate(PageNumberPagination)`
Elimina respostas construídas manualmente e slices `[:200]`.
```python
from ninja.pagination import paginate, PageNumberPagination

@router.get("/users", response=list[StaffUserOut], summary="Listagem geral de usuários")
@paginate(PageNumberPagination, page_size=50)
def list_users(
    request,
    filters: StaffUserFilterSchema = Query(default=None),
    admin: User = Depends(get_current_admin),
):
    qs = User.objects.select_related("profile").prefetch_related("roles").order_by("-id")
    if filters:
        qs = filters.filter(qs)
    return qs
```

### 5.2. Filtragem Declarativa com `FilterSchema`
O `FilterSchema` aplica automaticamente os lookups do Django ORM sem lógica de `if/else` espalhada:
```python
from ninja import FilterSchema, Field

class StaffLeadFilterSchema(FilterSchema):
    status: str | None = Field(None, q="status")
    hub: str | None = Field(None, q="hub__external_id")
    created_after: datetime | None = Field(None, q="created_at__gte")
```

---

## 6. Resiliência e Rotas Assíncronas (`async def`)

Endpoints que realizam I/O com a rede externa passam a ser assíncronos:
1. **Verificação de Cloudflare Turnstile (`/auth/check`, `/auth/register`):**
   Uso de `httpx.AsyncClient` para validar o token com a API da Cloudflare sem travar a thread do Django.
2. **Disparo de Mensagens no WhatsApp (`notify-server`):**
   Envio assíncrono para o microserviço de notificação.
3. **Consultas de CPFHub e ViaCEP:**
   Fallback assíncrono durante a validação de formulários de cadastro.

---

## 7. Plano de Migração Incremental (Fatia por Fatia)

```
┌─────────────────────────┐
│ Fase 1: Infraestrutura  │ -> api/deps.py + testes unitários de DI (CONCLUÍDO)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Fase 2: Hubs & Staff    │ -> Substituir to_dict e slicing por Pydantic v2 + Paginate
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Fase 3: Funil de Alunos │ -> Refatorar Lead, Enrollment e Student para Depends(get_current_*)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Fase 4: Promotores      │ -> Refatorar Candidate, Promoter e Training para Depends
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Fase 5: OpenAPI v1      │ -> Consolidar core/urls.py com Swagger unificado e retrocompatibilidade
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Fase 6: Async Edge I/O  │ -> Migrar rotas de Turnstile e Notify para async def
└─────────────────────────┘
```

### Critérios de Aceite por Fase:
* Cada fatia mantém 100% dos testes existentes passando (`uv run --extra dev pytest`).
* Nenhuma rota do frontend sofre alteração de contrato HTTP ou payload de erro.
* Ausência de warnings de colisão de `operation_id` na geração do Swagger.
