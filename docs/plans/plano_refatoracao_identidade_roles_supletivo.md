# Plano de Ação Arquitetural: Desacoplamento de Personas (RBAC) e Estados de Negócio (Funil) — Backend Supletivo

> **Documento de Especificação e Planejamento para Revisão no Plannotator**  
> **Repositório:** `https://github.com/maestri33/backend.supletivo.net.br`  
> **Autor / Responsável Técnico:** Arquiteto de Identidade (Victor Maestri)  
> **Status:** AGUARDANDO REVISÃO E AJUSTES DO USUÁRIO (PRÉ-EXECUÇÃO)  
> **Data de Emissão:** 16 de Novembro de 2026  
> **Política de Execução:** Nenhuma alteração de código ou migração de banco será executada em produção sem revisão, anotações e validação explícita no Plannotator.

---

## 1. Resumo Executivo e Justificativa

O **Backend Supletivo** opera atualmente com um acoplamento histórico entre o **Controle de Acesso Baseado em Papéis (RBAC / JWT)** e o **Progresso no Funil de Conversão / Operação**.

### Sintomas e Dores Identificados na Auditoria:
1. **Queda Constante de Sessão (JWT Churn):** Cada avanço de etapa no funil (ex.: lead efetuando pagamento de matrícula ou polo aprovando documentos de promotor) aciona `roles.promote()`, que incrementa `token_version` e invalida imediatamente o access token ativo. O usuário sofre `401 Unauthorized` em plena navegação.
2. **Fragilidade de Configuração (`ROLE_RULES` em JSON no `.env`):** As transições de negócio dependem de parsing de JSON no `.env` e geração de hash dinâmico via `uuid5`. Uma falha sintática no `.env` derruba o boot do Django (`ImproperlyConfigured`).
3. **Ofuscação na Camada de API:** O objeto `Principal.has_any` implementa um dicionário de "aliases mágicos" invertidos (`lead -> student`, `coordinator -> hub`), ocultando as reais regras de autorização das rotas.
4. **Acúmulo de Roles Transitórias no Banco:** A tabela `UserRole` acumula registros como `lead`, `enrollment`, `veteran`, `candidate` e `training`, quando o papel substantivo do indivíduo no sistema é simplesmente **aluno** (`student`) ou **promotor** (`promoter`).

### O Estado Desejado:
* **4 Personas Canônicas no RBAC / JWT:** Exclusivamente `student`, `promoter`, `coordinator` e `admin`.
* **Estados de Negócio no Domínio:** Ciclo de vida explícito nas tabelas de domínio (`Lead/Student`: `LEAD -> ENROLLMENT -> ACTIVE -> GRADUATED`; `Candidate/Promoter`: `CANDIDATE -> TRAINING -> ACTIVE -> SUSPENDED`).
* **Sessão Estável:** Transições de funil não afetam o JWT nem o `token_version`. O campo `token_version` fica estritamente reservado para logout explícito, comprometimento de credencial ou revogação disciplinar.
* **Eliminação Total de `ROLE_RULES` e `catalog.py`:** Transições implementadas como métodos de código em Python, sem dependência de `.env`.

---

## 2. Matriz Comparativa: Estado Atual Auditado vs. Arquitetura Proposta

| Dimensão | Estado Atual Auditado | Nova Arquitetura Proposta | Benefício Técnico |
| :--- | :--- | :--- | :--- |
| **Personas no JWT (`roles`)** | 11 roles misturadas (`lead`, `enrollment`, `student`, `veteran`, `candidate`, `training`, `promoter`, `coordinator`, `hub`, `staff`, `admin`) | **Apenas 4:** `student`, `promoter`, `coordinator`, `admin` | Modelo RBAC limpo, previsível e padronizado |
| **Progresso de Funil** | Manipulado via substituição de role (`roles.promote(user, to_role, mode="replace")`) | Atributo explícito `status` nas entidades de domínio (`Lead`, `Enrollment`, `Student`, `Candidate`, `Promoter`) | Rastreabilidade de negócio descolada da autenticação |
| **Versão de Token (`token_version`)** | Incrementado a cada transição de funil (`_bump_token_version`), derrubando tokens de acesso | Inalterado durante o funil. Incrementado apenas em logout, revogação ou troca de credencial | **Fim do churn de JWTs e do erro 401 para alunos e promotores** |
| **Refresh Token (`users/auth/jwt/service.py`)** | Gambiarra `_funnel_transition_roles` para permitir salto de versão `claims_version + 1` | Validação estrita: `version_matches(external_id, token_version)`. Sem exceções ad-hoc | Código de criptografia simples, sem acoplamento a regras de negócio |
| **Configuração de Regras** | `ROLE_RULES` em JSON no `.env` com validação no boot e hash `uuid5` em `catalog.py` | Regras explícitas em código Python (models/services). Remoção total de `ROLE_RULES` | Sem risco de quebra de boot por `.env`, versionamento via Git |
| **Gates de Rota (`Principal.has_any`)** | Dicionário de equivalências mágicas (`aliases = {"lead": ("student",), ...}`) | Verificação direta: `any(r in self.roles for r in roles)`. Rotas checam status via DB/Model | Autorização explícita e auditável em cada endpoint |
| **Segredos e Ambiente** | Dependência de JSON no `.env` | Alinhamento com Cloudflare Wrangler Secrets e Hyperdrive (sem senhas ou regras em arquivos de texto) | Conformidade com melhores práticas de segurança |

---

## 3. Arquitetura de Identidade e Modelagem de Estados

```
┌────────────────────────────────────────────────────────────────────────┐
│                   PERSONAS CANÔNICAS (RBAC / JWT)                      │
│                                                                        │
│   [ student ]         [ promoter ]       [ coordinator ]     [ admin ] │
│   (Aluno)             (Promotor)         (Líder de Polo)     (Staff)   │
└────────┬───────────────────┬────────────────────┬─────────────────┬────┘
         │                   │                    │                 │
         ▼                   ▼                    ▼                 ▼
┌──────────────────┐┌──────────────────┐┌──────────────────┐┌───────────┐
│ FUNIL DO ALUNO   ││FUNIL DO PROMOTOR ││  COORDENAÇÃO     ││ ADMIN     │
│ Entidade: Student││Entidade: Promoter││  Entidade: Hub   ││ Superuser │
├──────────────────┤├──────────────────┤├──────────────────┤├───────────┤
│ • LEAD           ││ • CANDIDATE      ││ • ACTIVE         ││ • ACTIVE  │
│ • ENROLLMENT     ││ • TRAINING       ││                  ││           │
│ • ACTIVE         ││ • ACTIVE         ││                  ││           │
│ • GRADUATED      ││ • SUSPENDED      ││                  ││           │
└──────────────────┘└──────────────────┘└──────────────────┘└───────────┘
```

### 3.1. Especificação dos Estados do Funil do Aluno (`student`)
A persona canônica concedida no momento do primeiro cadastro/captura é sempre `student`.
O endpoint `/whoami` e os serviços resolvem o status a partir das entidades:
1. `LEAD`: O usuário possui registro em `Lead` e checkout pendente ou pago, sem matrícula ativa.
2. `ENROLLMENT`: O pagamento da matrícula foi confirmado; o registro em `Enrollment` está em preenchimento (documentos, endereço, selfie, taxa).
3. `ACTIVE`: A matrícula foi homologada; o aluno possui registro em `Student` ativo e cursa os módulos preparatórios.
4. `GRADUATED`: O aluno realizou os exames finais com aprovação e obteve a conclusão/diploma (substitui a nomenclatura arcaica `veteran`).

### 3.2. Especificação dos Estados do Funil do Promotor (`promoter`)
A persona canônica concedida ao iniciar o credenciamento de parceiro é sempre `promoter`.
1. `CANDIDATE`: O usuário possui registro em `Candidate` e está completando os dados de onboarding (chave PIX, documentos, contrato).
2. `TRAINING`: O cadastro foi pré-aprovado pelo coordenador do polo e o promotor está realizando a capacitação obrigatória no LMS.
3. `ACTIVE`: O promotor concluiu o treinamento e está plenamente habilitado para captar alunos com link parametrizado (`?ref=...`).
4. `SUSPENDED`: O promotor sofreu bloqueio administrativo ou disciplinar (bloqueia o link de indicação e saques de comissão).

### 3.3. Contrato da Resposta do `/whoami`
Tanto `/api/v1/clients/whoami` quanto `/api/v1/collaborators/whoami` retornam uma estrutura padronizada e previsível:
```json
{
  "external_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "roles": [
    "student",
    "promoter"
  ],
  "role_statuses": {
    "student": "enrollment",
    "promoter": "active"
  },
  "name": "Maria Silva",
  "phone": "5511999990000",
  "photo_url": "https://media.supletivo.net.br/avatars/...",
  "avatar_url": "https://media.supletivo.net.br/avatars/..."
}
```

---

## 4. Plano de Implementação Faseado

```
[Fase 1: Domínio & RBAC] ➔ [Gate 1] ➔ [Fase 2: Expurgamento de Config] ➔ [Gate 2] ➔ [Fase 3: Auth & JWT] ➔ [Gate 3] ➔ [Fase 4: Limpeza de Routers] ➔ [Gate 4] ➔ [Fase 5: Migração & Testes]
```

### Fase 1: Camada de Domínio e RBAC Canônico
*Objetivo: Tornar as personas canônicas a única fonte de RBAC e transformar transições em métodos explícitos.*

1. **Atualização de `users/roles/service.py`:**
   * Definir a constante imutável:
     ```python
     CANONICAL_ROLES = ("student", "promoter", "coordinator", "admin")
     ```
   * Modificar `assign(user, role)`:
     * Aceita apenas as 4 personas canônicas.
     * **Eliminar a chamada `_bump_token_version(user)`** na concessão de persona.
   * Modificar `promote(user, to_role)`:
     * Descontinuar o uso de `promote` para avanço de funil. Transições de negócio chamam diretamente métodos das entidades (`enrollment.complete()`, `student.graduate()`, `candidate.approve()`).
   * Refatorar `resolve_user_roles_and_statuses(user)`:
     * Retornar estritamente as 4 personas legítimas e seus respectivos status calculados (`student`: `lead`/`enrollment`/`active`/`graduated`; `promoter`: `candidate`/`training`/`active`/`suspended`; `coordinator`: `active`; `admin`: `active`).

### Fase 2: Expurgamento do Catálogo em `.env` e Hashing Dinâmico
*Objetivo: Eliminar dependências frágeis no ambiente e simplificar o boot do Django.*

1. **Remoção de Módulos Legados:**
   * Excluir `users/roles/catalog.py` e suas dependências de `uuid5`.
2. **Limpeza do `core/settings.py`:**
   * Remover a leitura de `ROLE_RULES`.
   * Remover `ROLE_RULES` de `.env.ci`, `.env.example` e documentações.
3. **Ajuste de Checks e Boot:**
   * Atualizar `users/apps.py` removendo `from users.roles import catalog`.
   * Atualizar `users/checks.py` para validar a coerência estática dos models em vez de iterar sobre `ROLE_RULES`.

### Fase 3: Estabilização de Sessão e Limpeza de JWT
*Objetivo: Garantir que a sessão do usuário permaneça estável e eliminar exceções artificiais no token.*

1. **Limpeza de `users/auth/jwt/service.py`:**
   * Remover completamente a função `_funnel_transition_roles`.
   * Simplificar `refresh(refresh_token)`:
     ```python
     def refresh(refresh_token: str) -> dict:
         token = RefreshToken(refresh_token)
         external_id = token.get("external_id", "")
         if not version_matches(external_id, token.get("token_version")):
             raise TokenError("token_version_stale")
         roles = _live_roles(external_id)
         if roles is None:
             raise TokenError("token_user_inactive")
         return issue(external_id, roles)
     ```
2. **Desacoplamento de `Principal` em `api/auth.py`:**
   * Remover o mapa de aliases mágicos (`aliases = {"lead": ("student",), ...}`).
   * O método `has_any` passa a ser direto:
     ```python
     def has_any(self, roles: tuple[str, ...]) -> bool:
         return any(r in self.roles for r in roles)
     ```
   * Manter apenas a compatibilidade estrita `coordinator` / `hub` temporária caso ainda existam chamadas legadas em transição.

### Fase 4: Limpeza da Camada de API e Routers (Django Ninja)
*Objetivo: Fazer com que cada rota declare a persona canônica exigida, verificando o status de domínio quando necessário.*

1. **Rotas de Clientes (`api/clients/routers/`):**
   * Em `auth.py`, `lead.py`, `enrollment.py`, `student.py`:
     * Substituir `require_roles(request.auth, *FUNNEL_ROLES)` por:
       ```python
       require_roles(request.auth, "student")
       ```
     * Eliminar a constante `FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")`.
     * Quando um endpoint for exclusivo de uma etapa (ex.: `/lead/checkout`), verificar se o usuário possui `Lead` com status compatível, levantando `403` ou `409` se já tiver avançado.
2. **Rotas de Colaboradores (`api/collaborators/routers/`):**
   * Em `candidate.py`, `promoter.py`, `training.py`:
     * Substituir `require_roles(request.auth, *allowed)` por:
       ```python
       require_roles(request.auth, "promoter")
       ```
     * Validar status de treinamento ou aprovação diretamente via `Promoter.status` ou `Candidate.status`.
3. **Rotas de Liderança (`api/leadership/`):**
   * Exigir diretamente `require_roles(request.auth, "coordinator")`.

### Fase 5: Migração de Dados, Testes e Homologação
*Objetivo: Garantir transição transparente em produção sem downtime e validação 100% automatizada.*

1. **Data Migration Idempotente no Django (`users/migrations/0051_canonical_personas_and_funnel_status.py`):**
   * Executar normalização na tabela `users_user_role`:
     * Registros ativos com `role IN ('lead', 'enrollment', 'veteran')` -> atualizar para `'student'`.
     * Registros ativos com `role IN ('candidate', 'training')` -> atualizar para `'promoter'`.
     * Registros ativos com `role = 'hub'` -> atualizar para `'coordinator'`.
     * Registros ativos com `role = 'staff'` de superusers -> atualizar para `'admin'`.
     * Desduplicação: Para usuários que já possuem a role de destino ativa, revogar a duplicada (`revoked_at = timezone.now()`) para não violar `uniq_active_role_per_user`.
2. **Atualização da Suíte de Testes:**
   * Atualizar `tests/test_canonical_roles_and_admin_refactor.py`.
   * Atualizar `tests/test_canonical_role_status_regressions.py`:
     * Remover o teste que exigia 401 ao avançar de fase no funil (o comportamento correto agora é **manter a sessão 200 OK ativa**).
     * Adicionar teste comprovando que pagamento de matrícula e envio de selfie **não invalidam** o token de acesso.
3. **Validação Geral:**
   * Executar suíte completa: `uv run --extra dev pytest`.
   * Executar checagens de sistema do Django: `CI=1 uv run python manage.py check`.

---

## 5. Pontos de Decisão Obrigatória para Revisão no Plannotator (Gates)

Antes de iniciarmos as alterações no código, solicitamos que o usuário revise e faça anotações nos seguintes pontos-chave:

* **[GATE 1] Nomenclatura dos Estados de Funil:**
  * O plano padroniza o status final do aluno como `GRADUATED` (substituindo o antigo termo `VETERAN`). Está de acordo ou o termo `VETERAN` deve ser mantido como alias de compatibilidade com o frontend?
* **[GATE 2] Comportamento de Multi-Persona no Login:**
  * Quando um usuário for simultaneamente `student` e `promoter`, o token JWT emitido conterá ambas as roles: `roles: ["student", "promoter"]`. Confirmar se o seletor de persona no frontend já suporta essa listagem no payload do token.
* **[GATE 3] Desduplicação na Migração de Produção:**
  * Aprovação da regra de merge de roles ativas para garantir integridade com a constraint `uniq_active_role_per_user`.
* **[GATE 4] Retirada de `_bump_token_version`:**
  * Confirmar que a única hipótese de deslogar o usuário remotamente é via chamada explícita de `bump_token_version` (logout / bloqueio administrativo / troca de telefone pelo staff).

---

## 6. Procedimento de Rollback e Segurança

Se durante a homologação for identificada qualquer inconsistência:
1. **Rollback de Código:** O branch de refatoração será revertido para o commit base `origin/main` de forma limpa.
2. **Rollback de Banco de Dados:** A migração de dados conterá método reverso explícito (`migrations.RunPython(forward, backward)`), restaurando as roles legadas a partir do histórico de status das entidades caso necessário.
3. **Integridade de Sessões:** A reversão não descarta senhas nem segredos de infraestrutura, mantendo a conformidade com as diretrizes do Cloudflare Hyperdrive.
