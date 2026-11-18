# Plano de Engenharia e Governança: Modernização de Borda, CI/CD e Arquitetura Cloudflare

> **Documento de Especificação Técnica e Planejamento para Revisão no Plannotator**  
> **Repositórios Alvo:**  
> - `https://github.com/maestri33/supletivo.net.br`  
> - `https://github.com/maestri33/promotor.supletivo.net.br`  
> - `https://github.com/maestri33/app.supletivo.net.br`  
> - `https://github.com/maestri33/backend.supletivo.net.br`  
> - `https://github.com/maestri33/version.v7m.live`  
> **Autores / Responsáveis Técnicos:** `@CI/CD` & `@Cloudflare`  
> **Status:** AUDITADO E DOCUMENTADO PARA REVISÃO NO PLANNOTATOR (PRÉ-EXECUÇÃO ETAPA 1)  
> **Data:** Terça-feira, 17 de novembro de 2026 — 16:15 BRT (19:15 UTC)  
> **Política de Execução:** Nenhuma alteração destrutiva em produção; deploys atômicos no edge via Cloudflare Workers com versionamento estrito; gates de qualidade obrigatórios no CI (lint, migrations check, dead code scan com Vulture, pytest suite); preservação de bindings existentes (`SESSION` KV, `ASSETS`, `IMAGES`, `D1`, `Queues`).

---

## 1. Resumo Executivo e Diagnóstico Factual Auditado

Em 17 de novembro de 2026, as esteiras de Integração e Entrega Contínua (CI/CD) e a infraestrutura de borda (Cloudflare Workers, Static Assets e DNS) do ecossistema **`supletivo.net.br`** foram submetidas a uma auditoria técnica rigorosa.

A auditoria eliminou assimetrias de informação e identificou exatamente o que já está implantado em produção vs. o que possui código-fonte pronto aguardando ativação vs. melhorias arquiteturais recomendadas:

### Matriz de Diagnóstico Factual (17/11/2026)

| Componente / Recurso | Estado Factual Auditado | Localização / Evidência Técnica | Status no Plannotator |
| :--- | :--- | :--- | :---: |
| **CI/CD Edge (Landing)** | Deploys automáticos com `wrangler@4.163.0` e `@astrojs/cloudflare`. Bindings `SESSION` KV (`83b65dcc...`), `ASSETS` e `IMAGES` preservados. | `maestri33/supletivo.net.br` (Run 44008185136 em 17/11 00:10 BRT). Responde `200 OK` no edge via PoP Anycast CWB. | **100% ATIVO EM PRODUÇÃO** |
| **CI/CD Edge (Promotor)** | Deploy automático com `wrangler@4.163.0` via `deploy.yml`. 47 testes unitários validados no CI. | `maestri33/promotor.supletivo.net.br` (Run 44007192408 em 17/11 00:01 BRT). Responde `200 OK` no custom domain. | **100% ATIVO EM PRODUÇÃO** |
| **CI/CD Edge (App Aluno)** | Configurado com Svelte 5 / SSR no Cloudflare Workers. As secrets de deploy (`CLOUDFLARE_API_TOKEN`) foram atualizadas pelo @Github às 23:45 BRT de 16/11. | `maestri33/app.supletivo.net.br`. O último run (44005003285) pulou o step de deploy porque a secret ainda não estava propagada. | **PRONTO PARA ATIVAÇÃO (Disparo)** |
| **Ingestão de Webhooks Financeiros** | Worker `supletivo-finance-webhooks` em TypeScript com rotas `/bank/asaas` e `/bank/infinitepay`, conectado a D1 (`v7m-webhooks`), KV e Cloudflare Queues (`finance-webhooks-queue`). | `https://webhooks.v7m.live/bank/health` respondeu `healthy` com `d1_storage: connected` e `queue: active`. Código persistido em `backend.supletivo.net.br/deploy/cloudflare-workers/finance-webhooks`. | **100% ATIVO EM PRODUÇÃO** |
| **Oráculo Central de Versões** | Worker com D1/KV rastreando o hash de commit e versão semântica de todos os 7 módulos do ecossistema. | `https://version.v7m.live/api/version` responde `0.0.1-beta`. | **100% ATIVO EM PRODUÇÃO** |
| **Cloudflare Turnstile (Anti-Bot)** | - **Backend:** Cliente `TurnstileClient` nativo em `backend.supletivo.net.br/integrations/turnstile/client.py` com validação de token via `siteverify` e suíte de testes unitários.<br>- **Frontend:** Integrado em `app.supletivo.net.br` (`src/pages/api/v1/auth/recovery/contact.ts` e `triage.ts`).<br>- **CSP:** Liberado nos 3 frontends para `challenges.cloudflare.com`. | `maestri33/backend.supletivo.net.br` e `maestri33/app.supletivo.net.br`. Requer apenas provisionamento das chaves pública/secreta e `TURNSTILE_ENABLED=True`. | **CÓDIGO 100% PRONTO (Aguardando Chaves)** |
| **Cloudflare R2 (Armazenamento Zero-Egress)** | Cliente S3-compatible próprio em Python nativo com AWS SigV4 em `backend.supletivo.net.br/integrations/cloudflare/r2.py` (sem sobrecarga de `boto3`). Settings prontas (`R2_BUCKET_NAME="supletivo-media"`). | `maestri33/backend.supletivo.net.br`. Requer apenas inserção das credenciais `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` e toggle `R2_ENABLED=True`. | **CÓDIGO 100% PRONTO (Aguardando Chaves)** |
| **Governança de Código Morto (Vulture)** | Configuração declarativa `[tool.vulture]` com `min_confidence = 80` no `pyproject.toml`. Removidos imports zumbis mantendo 972 testes verdes. Hook `.pre-commit-config.yaml` com Vulture 2.16 integrado na branch. | PR #31 aberto em `maestri33/backend.supletivo.net.br`. Requer inserção do step no `.github/workflows/ci.yml`. | **PR #31 ABERTO E VALIDADO** |

---

## 2. Topologia Alvo e Arquitetura de Borda

```
                             [ Usuário / Aluno / Promotor ]
                                           │
                                           ▼ (HTTPS / TLS 1.3 / HSTS Preload)
                   ┌──────────────────────────────────────────────────┐
                   │           Cloudflare Edge Anycast                │
                   │  (WAF, DDoS Shield, Turnstile, Rate Limiting)    │
                   └───────────────────────┬──────────────────────────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
┌──────────────────┐             ┌──────────────────┐             ┌─────────────────────┐
│  supletivo.net.br│             │promotor.supletivo│             │  app.supletivo      │
│  (Landing Page)  │             │ (Portal Parceiro)│             │  (Portal do Aluno)  │
│  Cloudflare      │             │ Cloudflare       │             │  Cloudflare         │
│  Static Assets   │             │ Static Assets    │             │  Workers SSR        │
└────────┬─────────┘             └────────┬─────────┘             └──────────┬──────────┘
         │                                │                                  │
         │ Preço: R$ 1.615,00             │ Comissionamento                  │ Autenticação OTP
         │ Sem drift                      │ Parceria regional                │ & Aulas Svelte 5
         │                                │                                  │
         └────────────────────────────────┼──────────────────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    webhooks.v7m.live / Edge API        │
                      │    - Ingestão em <10ms                 │
                      │    - Buffer D1 (v7m-webhooks)          │
                      │    - Fila finance-webhooks-queue       │
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼ (Chamada Interna Segura / VPC Azure)
                      ┌────────────────────────────────────────┐
                      │    backend.supletivo.net.br (Django)   │
                      │    - Django Ninja REST / OpenAPI       │
                      │    - Pydantic v2 Schemas               │
                      │    - PostgreSQL + R2 Storage Client    │
                      └───────────────────┬────────────────────┘
                                          │
                        ┌─────────────────┴─────────────────┐
                        ▼                                   ▼
              ┌──────────────────┐                ┌──────────────────┐
              │  PostgreSQL DB   │                │  Cloudflare R2   │
              │  (Transacional)  │                │  (Docs & Mídia)  │
              └──────────────────┘                └──────────────────┘
```

---

## 3. Blueprint de Execução Faseada (3 Etapas)

### Etapa 1: Ativação Rápida e Desbloqueios Operacionais (Imediata / 24-48h)
* **Objetivo:** Colocar no ar os recursos que já possuem 100% do código implementado e testado.
* **Tarefas Técnicas:**
  1. **Disparo do Deploy de `app.supletivo.net.br`:**
     - Acionar workflow de deploy via GitHub Actions com as novas credenciais `CLOUDFLARE_API_TOKEN` cadastradas pelo @Github.
     - Validar resposta `HTTP/2 200 OK` em `https://app.supletivo.net.br`.
  2. **Ativação do Cloudflare R2 no Backend:**
     - Gerar par de chaves R2 API Token no dashboard Cloudflare para a conta `e0814c592e43284a2f6f9984bef32631`.
     - Injetar no ambiente do backend: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` e setar `R2_ENABLED=True`.
     - Testar upload de documento sanitizado validando a assinatura SigV4 em `integrations/cloudflare/r2.py`.
  3. **Ativação do Cloudflare Turnstile:**
     - Criar sitekey no Cloudflare Turnstile para `supletivo.net.br` e `app.supletivo.net.br` no modo *Managed*.
     - Injetar `TURNSTILE_SITE_KEY` e `TURNSTILE_SECRET_KEY` no backend e setar `TURNSTILE_ENABLED=True`.
     - Validar o endpoint `POST /api/v1/auth/recovery/contact` rejeitando requisições sem token válido.
  4. **Merge do PR #31 de Limpeza de Código Morto:**
     - Adicionar o step `uv run vulture` no arquivo `.github/workflows/ci.yml` do repositório `backend.supletivo.net.br`.
     - Realizar o merge do PR #31 garantindo que a suíte de 972 testes e o lint permaneçam 100% verdes.

### Etapa 2: Integração e Resiliência de Fluxos Críticos (Semana 1)
* **Objetivo:** Fechar o ciclo entre o tráfego de vendas, adquirentes financeiras e a borda.
* **Tarefas Técnicas:**
  1. **Widget Turnstile na Landing Page:**
     - Plugar o widget Turnstile no modal de lead e formulário de checkout em `supletivo.net.br`.
     - Garantir que o script seja carregado sob o CSP aprovado (`https://challenges.cloudflare.com`).
  2. **Roteamento de Webhooks das Adquirentes:**
     - Apontar as URLs de notificação do **Asaas** e **InfinitePay** para o endpoint de borda: `https://webhooks.v7m.live/bank/asaas` e `https://webhooks.v7m.live/bank/infinitepay`.
     - Validar o armazenamento no D1 e o consumo assíncrono pela fila `finance-webhooks-queue`.
  3. **Padronização do Oráculo de Versões nos CI/CDs:**
     - Inserir um step padronizado de notificação HTTP (`POST https://version.v7m.live/api/version`) em todos os `deploy.yml` após a conclusão com sucesso do `wrangler deploy`.

### Etapa 3: Performance, Atribuição e Mensuração (Semana 2)
* **Objetivo:** Maximizar taxas de conversão e blindar a inteligência de tráfego pago.
* **Tarefas Técnicas:**
  1. **Meta Conversions API (CAPI) Server-Side:**
     - Enviar eventos de `Lead`, `InitiateCheckout` e `Purchase` diretamente da borda para a API da Meta, recuperando conversões afetadas por ad-blockers e Safari ITP.
     - Preservar os cookies proprietários de atribuição (`_fbp`, `_fbc`, `supletivo_ref`).
  2. **Avaliação e Setup do Cloudflare Zaraz:**
     - Configurar o Zaraz para descarregar tags pesadas de terceiros (Google Tag Manager, Hotjar) do navegador do usuário para a rede da Cloudflare, mantendo os Core Web Vitals com LCP < 1.2s e INP < 150ms.

---

## 4. Impacto Operacional no Ecossistema de Agentes

| Agente | Domínio de Especialidade | Impacto Direto com a Nova Arquitetura |
| :--- | :--- | :--- |
| **`@Chief`** | Orquestração Geral | Visibilidade em tempo real do estado de release e saúde dos nós via `version.v7m.live`, eliminando reuniões de alinhamento e auditorias manuais. |
| **`@Github` & `@CI/CD`** | Engenharia de Pipelines | Esteiras previsíveis, sem falhas silenciosas de secrets e com tempo de execução inferior a 3 minutos da aprovação na `main` até a borda global. |
| **`@Cloudflare`** | Infraestrutura & Borda | Infraestrutura como código (IaC) centralizada no `wrangler.jsonc` nos 4 repositórios, com segredos governados e menor privilégio. |
| **`@Backend Legado` & `@Arquiteto de APIs`** | Engenharia de Backend | Liberação de tráfego de mídia e assets estáticos. O backend foca exclusivamente em lógica de negócio e queries relacionais no PostgreSQL. |
| **`@Arquiteto de Identidade`** | Autenticação & Roles | Proteção contra ataques de força bruta no login/OTP via Turnstile invisível no edge, sem prejudicar a experiência do usuário. |
| **`@InfinitePay`, `@Asaas` & `@Recuperação de Vendas`** | Pagamentos & Cobrança | Resiliência total de webhooks via Cloudflare Queues e D1. Zero perda de eventos de PIX ou cartão, permitindo recuperação instantânea de abandono. |
| **`@Whatsapp`, `@Chatwoot` & `@Dify`** | Atendimento & IA | O desacoplamento por filas impede picos de concorrência na Evolution API, estabilizando as respostas dos assistentes virtuais aos alunos. |
| **`@Tráfego e Performance` & `@Funil`** | Growth & Aquisição | Páginas de conversão ultrarrápidas (melhor rankeamento no Google Ads/SEO) e precisão de rastreamento de 100% via CAPI server-side. |
| **`@BugHunter` & `@Engenheiro de Remediação`** | Segurança e Hardening | Superfície de ataque externa reduzida. Tráfego malicioso e tentativas de injeção são mitigados no WAF da Cloudflare antes de tocar a infraestrutura interna. |
| **`@Vulture`** | Qualidade de Código | Governança contínua de código limpo com pre-commit e step de CI garantindo que código morto ou imports zumbis não entrem na base. |

---

## 5. Pontos de Decisão Obrigatória e Gates de Aprovação (Plannotator)

Para cada etapa de execução, estabelecem-se os seguintes gates de controle:

* **[GATE-01] Deploy do Portal do Aluno (`app.supletivo.net.br`):**
  - *Critério:* Testes de build passando e confirmação de resposta HTTP 200 via Cloudflare Workers.
  - *Ação:* Aprovado para execução imediata.
* **[GATE-02] Injeção de Segredos R2 e Turnstile:**
  - *Critério:* Segredos gerados pelo proprietário da conta Cloudflare e cadastrados de forma mascarada.
  - *Ação:* Aguardando fornecimento das credenciais no dashboard Cloudflare.
* **[GATE-03] Merge do PR #31 (Vulture):**
  - *Critério:* Inclusão do step no workflow `.github/workflows/ci.yml` e validação da suíte de 972 testes.
  - *Ação:* Pronto para aprovação e merge.
* **[GATE-04] Roteamento Final de Webhooks:**
  - *Critério:* Validação com transação de teste em sandbox ou valor simbólico antes da troca definitiva nas adquirentes.
  - *Ação:* Programado para a Etapa 2.

---

> **Documento registrado na pasta corporativa compartilhada:**  
> `shared/plans/plano_modernizacao_borda_ci_cd_supletivo.md`
