# Project: V7M Django Backend Audit, Cleanup & Django Ninja Standardization

## Architecture & App Justifications

The V7M backend is a multi-role educational management, enrollment funnel, polo network, and commission distribution platform.
Layer separation strictly follows:
- **Router / Presentation (`api/` and `*.routers`)**: Django Ninja APIs, request validation, authentication injection, OpenAPI schema declaration, HTTP status responses.
- **Domain Services (`*/services.py`, `*/service.py`, `*/interface/`)**: Pure business logic, transaction boundaries, state transitions, business rule enforcement, external integration orchestration.
- **Data Models (`*/models.py`)**: Django ORM persistence, constraints, indexes, timestamps, soft-deletes (`ExternalIdModel`).

### Installed Apps Justification (R1)
| App / Module | Business & Technical Justification | Key Models & Components |
|---|---|---|
| `core` | Core platform foundation: base models (`ExternalIdModel`), dynamic platform configuration (`PlatformSetting`), media storage, PDF rendering, network utils, security/encryption keys. | `PlatformSetting`, `ExternalIdModel`, `crypto`, `pdf`, `storage` |
| `users` | Identity, authentication (passwordless OTP/JWT), multi-role domains: Candidate, Promoter, Lead, Enrollment, Student, Veteran, EducationalData, Documents (RG, CNH, Certs), Biometric linking, Training & Materials. | `User`, `Profile`, `OtpCode`, `Candidate`, `Enrollment`, `Student`, `Lead`, `Promoter`, `Document` |
| `hub` | Physical & regional hub (polo) management, coordinator assignments, brand/white-label settings, geographical coverage. | `Hub`, `Address` |
| `finance` | Financial ledger, multi-tier commissions (direct, veteran, bonus), payout requests (`PaymentRequest`), Asaas payout batching. | `Commission`, `PaymentRequest` |
| `notify` | Outbound communication proxy for transactional messages (SMS, WhatsApp, Email) routed through `notify-server`. | `notify.interface.send` |
| `integrations.bank.asaas` | Banking integration with Asaas: customer synchronization, PIX QR code generation, webhook event processing, automated commission payouts. | `Customer`, `PixKey`, `Payment`, `WebhookEvent` |
| `integrations.bank.infinitepay` | Credit card & checkout integration with InfinitePay: checkout session creation, webhook charge confirmation. | `Checkout`, `WebhookEvent` |
| `integrations.tools.cep` | Address autofill and CEP validation service via ViaCEP with caching. | `cep_service` |
| `integrations.tools.cpf` | CPF validation and demographic data verification via CPFHub with caching. | `cpf_service` |
| `integrations.tools.biometric` | Facial biometric enrollment and verification using local ArcFace InsightFace CPU embeddings. | `FaceBiometric`, `FaceVerification` |
| `integrations.ai` | AI document OCR, fraud analysis, and LLM text processing with token usage logging. | `AiCall` |

---

## Feature Inventory
| # | Feature / Work Item | Description | Milestone | Source |
|---|---|---|---|---|
| 1 | Architectural Justification & Settings Pruning | Document all apps/settings; remove 9 dead settings from `core/settings.py` (legacy PyJWT, Sentry, dead sandbox keys). | M1 | R1, R2 |
| 2 | Dead Code Pruning | Delete `get_jwt.py`, `api/portal.py` (and route in `core/urls.py`), unreferenced functions in `charge.py`, `checkout.py`, `documents/service.py`, `lead/service.py`, `leadership/schemas.py`. | M1 | R2 |
| 3 | Finance Migration Sync | Generate missing migration `0005_alter_commission_status.py` in `finance` app so `makemigrations --check` passes cleanly. | M2 | R4 |
| 4 | ORM N+1 Query Optimization | Optimize `staff/routers/documents.py`, `staff/routers/network.py`, `enrollment/service.py:fee_facts`, `training/service.py:assigned_materials`, and `lead/service.py:lead_to_dict` using `select_related`, `prefetch_related`, and annotations. | M2 | R3 |
| 5 | Django Ninja Typed Out Schemas | Add Pydantic v2 `*Out` schemas with `ConfigDict(from_attributes=True)` to all 60 untyped endpoints across `staff`, `portal`, `clients`, `leadership`. | M3 | R3 |
| 6 | Pydantic v2 `PatchIn` & `FilterSchema` Standardization | Standardize partial update schemas (`PatchIn`) and implement `FilterSchema` query filters for list endpoints; enforce explicit HTTP status codes (200, 201, 204, 400, 404, 422). | M3 | R3 |
| 7 | Full E2E & Programmatic Verification | Run `manage.py check`, `makemigrations --check --dry-run`, `pytest` full test suite (283+ tests), and validate OpenAPI JSON generation across all Ninja APIs. | M4 | R4 |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Architectural Justification & Dead Code Cleanup | Remove `get_jwt.py`, `api/portal.py`, clean `core/settings.py` & `core/urls.py`, clean dead helpers. | None | DONE |
| 2 | M2: Database Migrations & ORM N+1 Elimination | Create `finance` migration 0005, optimize N+1 query hotspots in documents, network, fee_facts, training. | M1 | IN_PROGRESS |
| 3 | M3: Django Ninja & Pydantic v2 Standardization | Type all 60 untyped endpoints with `*Out`, `ConfigDict(from_attributes=True)`, `PatchIn`, `FilterSchema`, explicit status codes. | M2 | PLANNED |
| 4 | M4: Test Verification & OpenAPI Docs Validation | Validate Django check (0 errors), migrations check (0 pending), 100% pytest pass, and clean OpenAPI schema generation. | M3 | PLANNED |

---

## Interface Contracts
### API Routers ↔ Domain Services
- **Routers**: Only parse request payloads (Pydantic `*In` / `*PatchIn`), validate authorization (`request.auth`), invoke domain services, and return Pydantic `*Out` schemas or standard error envelopes (`api/base.py`).
- **Services**: Accept typed arguments or domain objects, perform business operations inside `transaction.atomic()` where appropriate, raise standard exceptions (`ValidationError`, `HttpError`, or domain errors), and return domain models or dicts matching `*Out` schemas.
- **Models**: Inherit from `ExternalIdModel` where applicable, define string representations, constraints, and relationships.

---

## Code Layout
```
backend-v7m/
├── api/                   # Django Ninja API Routers & Central Schemas
│   ├── base.py            # Global error handling, Auth, envelope responses
│   ├── schemas/           # Reusable Pydantic v2 schemas (*In, *PatchIn, *Out, *Filter)
│   ├── clients/           # Student/Candidate/Lead API routers
│   ├── collaborators/     # Promoter/Training API routers
│   ├── leadership/        # Hub Coordinator desk API routers
│   ├── staff/             # Superuser & Operations API routers
│   └── tools/             # DMZ / Webhook / Radar tools
├── core/                  # Project configuration, settings, base models, utils
├── users/                 # Authentication, Profiles, Roles, Documents
├── hub/                   # Hub (Polo) domain models and services
├── finance/               # Ledger, Commissions, Payout requests
├── notify/                # Outbound notification interface
├── integrations/          # Asaas, InfinitePay, ViaCEP, CPFHub, Biometric, AI
└── tests/                 # Pytest test suite
```
