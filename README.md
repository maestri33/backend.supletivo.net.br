# ⚙️ Supletivo Brasil Backend — API Principal & Regras de Negócio

API central do ecossistema educacional **Supletivo.net.br** / **Supletivo Brasil**, desenvolvida em **Django 5.2**, **Django Ninja** e **Django-Q2**, com persistência no **Neon Cloud Postgres** e cache em **Redis**.

---

## 🏗️ Superfície de APIs (`/api/v1/`)

1. **`/api/v1/clients/`**: Funil do Aluno, Autenticação OTP, Matrícula Documental, Sala de Aula e Área do Veterano.
2. **`/api/v1/collaborators/`**: Onboarding de Promotores, Captação de Leads, Gestão de Chave Pix e Extrato de Comissões.
3. **`/api/v1/leadership/`**: Painel do Coordenador de Polo (Pagamento de Taxas, Aprovação Manual de Docs, Correção de Provas e Retirada de Diploma).
4. **`/api/v1/staff/`**: Cockpit de Administração Master (Criação de Polos, Soberania Financeira, Fechamento e Usuários).
5. **`/api/v1/tools/`**: Endpoints de integração interna protegidos por segredo de serviço e DMZ.
6. **`/api/v1/health/healthz`**: Liveness probe e diagnóstico de banco e migrações pendentes.

---

## ⚡ Comandos de Desenvolvimento & Testes

```bash
# Sincronizar dependências com uv
uv sync

# Executar migrações locais
uv run python manage.py migrate

# Iniciar servidor local
uv run python manage.py runserver 0.0.0.0:8000

# Executar suíte completa de testes unitários e de integração (444 testes)
uv run pytest -v
```
