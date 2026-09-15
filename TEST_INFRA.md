# E2E Test Infra: V7M Django Backend

## Test Philosophy
- Requirement-driven, opaque-box and integration testing.
- Target: 100% test pass rate across all tiers, 0 schema divergences, 0 Django check errors, 100% valid OpenAPI 3.x schema compilation.

## Feature Inventory & Test Coverage
| # | Feature Area | Requirement | Baseline Tests | Target Verification |
|---|---|---|---|---|
| 1 | App & Settings Justification | R1 | N/A | System check code 0, 0 undefined settings |
| 2 | Dead Code & Simplicity Cleanup | R2 | Unit & Integration | 0 broken imports, 283+ pytest passing |
| 3 | Finance Database Migrations | R4 | Migration Check | `makemigrations --check --dry-run` exit code 0 |
| 4 | ORM Query Efficiency (N+1 Elimination) | R3 | Service & API tests | Optimized query counts with `select_related`/`prefetch_related` |
| 5 | Django Ninja & Pydantic v2 Standardization | R3 | API contract tests | All 190 routes typed, valid OpenAPI schema generation |
| 6 | Full Test Suite Execution | R4 | `uv run pytest` | 283+ tests passing with 0 failures |

## Verification Commands
1. `uv run python manage.py check`
2. `uv run python manage.py makemigrations --check --dry-run`
3. `uv run pytest`
4. Programmatic OpenAPI Schema Validation across all NinjaAPI instances.
