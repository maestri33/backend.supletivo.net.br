# Plano Mestre: Arquitetura Orientada a Roles/Estados — Dify + Cloudflare + Atendimento

> **Documento de Especificação e Governança para Revisão no Plannotator**  
> **Responsáveis:** Dify (Especialista Dify), Victor Maestri (Owner), Plannotator Reviewer  
> **Status:** EM APROVAÇÃO (FASE PREPARATÓRIA)  
> **Data:** 17 de Novembro de 2026  

---

## 1. Visão Geral e Justificativa

### 1.1 O Problema Atual
* **Roles e Estados Sobrecarregados no Monólito (Django):** Regras de permissão, RBAC e etapas do funil de vendas/acadêmico estão acopladas no backend Django, gerando sobrecarga, lentidão de resposta e vulnerabilidade a estados inconsistentes.
* **Complexidade no Atendimento com IA:** O bot precisa de contexto e ferramentas específicas para cada etapa da jornada do usuário. Sem isolamento estrito de estado, a IA corre risco de alucinar permissões ou disponibilizar APIs inadequadas (ex: oferecer renegociação para quem ainda nem se matriculou).
* **Alinhamento de Infraestrutura (Correção de Contexto):** O backend legado não opera mais em Proxmox. Atualmente é acessado via Cloudflare em `https://backend.supletivo.net.br`, e o objetivo estratégico final é **recompor todo o backend usando exclusivamente a plataforma Cloudflare** (Workers, D1, KV, Hyperdrive, Queues).

### 1.2 A Solução Arquitetural e Novo Padrão de Rotas
* **Padrão Canônico de Rotas (Cloudflare Edge):**
  ```http
  /api/v1/<role>/<status>/<funcao>
  ```
  *Exemplos práticos:*
  * `GET  /api/v1/student/lead/pricing` (consulta de tabela e condições de entrada)
  * `POST /api/v1/student/lead/checkout` (geração de link de pagamento / PIX)
  * `POST /api/v1/student/enrollment/documents` (upload e validação de RG/histórico)
  * `GET  /api/v1/student/active/overview` (painel do aluno, matérias e provas)
  * `GET  /api/v1/student/financial_pending/invoice` (2ª via e renegociação)
  * `POST /api/v1/promoter/candidate/apply` (inscrição no programa de parceiros)
  * `GET  /api/v1/promoter/active/commissions` (extrato e saque)

* **Contexto Dinâmico no Dify (v1.19.0):** As ferramentas (Tools/APIs) e o system prompt disponíveis para o modelo no Dify serão estritamente delimitados pela role/status ativa retornada pela borda.
* **Refatoração do Frontend (`app.supletivo.net.br`):** Telas e fluxos do frontend serão refatorados espelhando exatamente os mesmos contratos de estados e APIs da borda.

---

## 2. Metodologia de Execução em Fatias Verticais (Estado por Estado)

Para eliminar riscos, evitar retrabalho e garantir zero alucinações, cada role/estado passará pelo ciclo estrito de 7 etapas:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. DEFINIÇÃO      ➔ Explicação de negócio da Role / Status pelo Victor      │
│ 2. AUDITORIA       ➔ Mapeamento do que existe hoje (lógica/dados legados)    │
│ 3. PLANNOTATOR     ➔ Registro de Spec Técnica & Contratos no Plannotator     │
│ 4. REFATORAÇÃO     ➔ Implementação na borda (Worker Cloudflare com a rota)   │
│ 5. CONTEXTO BOT    ➔ Configuração de Prompt, Nós e Tools no Dify             │
│ 6. TESTES E2E      ➔ Simulação completa (Chatwoot ➔ Dify ➔ Cloudflare ➔ DB) │
│ 7. PRODUÇÃO        ➔ Deploy seguro do estado e abertura do próximo ciclo     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Matriz Canônica de Personas (RBAC) e Estados (Funil)

Conforme alinhamento arquitetural prévio, separamos **Persona (Quem o usuário é)** de **Status (Onde o usuário está na jornada)**:

| Persona (`<role>`) | Status (`<status>`) | Escopo de Ação do Bot / APIs (`<funcao>`) |
| :--- | :--- | :--- |
| **`student`** | `lead` | Tira-dúvidas de entrada, simulação de parcelas, emissão de checkout |
| **`student`** | `enrollment` | Coleta e validação de documentos, status de homologação |
| **`student`** | `active` | Acesso a aulas, cronograma de provas, suporte pedagógico |
| **`student`** | `financial_pending` | Resgate de inadimplência, 2ª via de PIX/boleto, renegociação |
| **`student`** | `graduated` | Emissão de certificado, validação GDAE/Diário Oficial |
| **`promoter`** | `candidate` | Apresentação do programa de parceiros, termos e comissões |
| **`promoter`** | `training` | Módulos de capacitação, links de afiliados |
| **`promoter`** | `active` | Painel de métricas, extrato de comissões, saldo a sacar |
| **`promoter`** | `suspended` | Notificação de infração, canal de contestação |

---

## 4. Avaliação Estratégica: Começar no Cloudflare vs. Usar Django Atual

| Critério | Opção A: Ligar Bot no Django Atual | Opção B: Migrar Borda Diretamente (Recomendada) |
| :--- | :--- | :--- |
| **Padrão de Rotas** | `/api/v1/clients/*` (antigo e bagunçado) | `/api/v1/<role>/<status>/<funcao>` (definitivo) |
| **Retrabalho** | **Alto (100% duplicado)**: Configura Dify agora, depois refaz tudo no Cloudflare | **Zero**: O Dify já nasce plugado na API definitiva |
| **Risco de Alucinação** | Alto (Django expõe rotas genéricas sem isolamento de estado) | Mínimo (Worker só expõe as rotas do estado atual) |
| **Latência** | ~200-400ms (origem monolítica) | <30ms (Edge Cloudflare) |
| **Esforço Inicial** | Imediato, mas descartável | Pequeno investimento por fatia (apenas 2 a 3 endpoints por estado) |
