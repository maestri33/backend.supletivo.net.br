# Plano Estratégico de Arquitetura e Decisão de Governança: Migração Multi-Cloud Gradual & Preservação dos Créditos Azure (Nonprofit Grant)

> **Documento Oficial de Especificação Técnica e Decisão Arquitetural para o Plannotator**  
> **Repositórios Alvo no GitHub:**  
> - `https://github.com/maestri33/backend.supletivo.net.br`  
> - `https://github.com/maestri33/supletivo.net.br`  
> - `https://github.com/maestri33/app.supletivo.net.br`  
> - `https://github.com/maestri33/promotor.supletivo.net.br`  
> - `https://github.com/maestri33/api.supletivo.net.br`  
> - `https://github.com/maestri33/notify.v7m.live`  
> **Autores / Bots Responsáveis:** `@Azure`, `@Plannotator Reviewer`, `@Cloudflare`, `@Github`, `@Omniroute`, `@Mail.V7m.live`, `@CI/CD`  
> **Status:** REGISTRADO E AUDITADO PARA REVISÃO NO PLANNOTATOR & DISPARO DE EXECUÇÃO  
> **Data:** Terça-feira, 17 de novembro de 2026 — 21:38 BRT (2026-11-18T00:38:09Z UTC)  
> **Premissa e Diretriz do Usuário:** Manter os contêineres Docker pesados no Azure por enquanto (migração de contêineres postergada); planejar e executar imediatamente todo o restante (borda, backups leves em D1/R2, Zero Trust, DNS, e-mails e governança de custos) com persistência obrigatória no GitHub.

---

## 1. Resumo Executivo e Contexto Estratégico

### 1.1 O Grant Anual da Microsoft (Nonprofit Sponsorship)
A conta de nuvem da organização (`Azure subscription 1` / ID `17472659-0f27-4a6b-9aec-39a53b3a2348`) opera sob o programa oficial **Microsoft for Nonprofits (Tech for Social Impact)** com a política:
* **Quota ID:** `Sponsored_2016-01-01`
* **Tenant Corporativo:** `Igreja Evangelica Assembleia De Deus` (`ieadpg.onmicrosoft.com` / `prvictormaestri@ieadpg.onmicrosoft.com`)
* **Teto de Crédito Anual:** **US$ 2.000,00 USD / ano** (~R$ 11.000,00 BRL na taxa de câmbio da Microsoft).

### 1.2 Auditoria do Consumo e Diagnóstico de Faturamento (Novembro/2026)
* **Consumo Histórico Coberto:** Setembro/2026 (R$ 30,12) e Outubro/2026 (R$ 333,59) foram 100% abonados pelos créditos de patrocínio.
* **Consumo de Novembro/2026 (até 17/11/2026):** **R$ 1.010,19 BRL** (~US$ 180,40 USD).
  * **Pico em 16/11/2026:** Um bot configurado em `gpt-6-astra` consumiu R$ 738,93 em 24h.
  * **Intervenção em 17/11/2026:** Toda a frota (23 bots) foi resetada para o modelo padrão `combo-ultra (default)`. O custo diário de IA caiu para **R$ 0,00** no dia 17/11.
  * **Proteção Orçamentária Ativada:** Criado o Azure Budget `Budget-Mensal-Alerta` com teto de R$ 1.100,00 BRL e notificações para `prvictormaestri@ieadpg.onmicrosoft.com` em 80%, 90% e 100%.
* **Saldo Restante do Ciclo Anual:** **~US$ 1.754,70 USD** (aproximadamente **R$ 9.650,00 BRL** disponíveis).

### 1.3 A Decisão Arquitetural: "Azure para Ocasiões Especiais"
Manter uma máquina virtual Linux de uso geral (`vm-v7m-core` - Standard_F1ams_v7) ligada 24/7 no Azure consome cerca de **R$ 380,00/mês (~US$ 68,00/mês)**, consumindo mais de **40% de todo o crédito anual da igreja**.
A decisão tomada estabelece o seguinte desacoplamento:
1. **Contêineres Docker:** Permanecem temporariamente na VM do Azure para evitar qualquer fricção operacional imediata, sendo migrados para VPS de baixo custo (ex: Hetzner / Oracle Free) em fase futura.
2. **Todo o Restante (Borda, Frontends, Backups, Armazenamento, Segurança, E-mail):** É transferido/planejado para serviços gratuitos ou de custo marginal (Cloudflare Pages, Workers, D1, R2, Zero Trust, Resend/Mail.V7m.live).
3. **Papel Exclusivo da Azure:** Preservar a totalidade dos US$ 2.000 anuais como "reserva nobre" para:
   * **Azure AI Foundry:** Inferência sob demanda em modelos de ponta (`claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5-5`, `gpt-4o`/`gpt-5.x`).
   * **Cold Storage / Archive Tier:** Backup histórico e imutável de cadastros e contratos de alunos a frações de centavo.
   * **Recuperação de Desastres (DR) e Computação Sob Demanda:** Instâncias temporárias para batch processing.

---

## 2. Matriz de Atribuição por Serviço & Provedor

| Componente | Provedor Atual | Provedor Alvo | Custo Mensal | Justificativa Técnica |
| :--- | :--- | :--- | :---: | :--- |
| **Frontends Web** (`supletivo.net.br`, `promotor...`, `app...`) | VM Azure / Borda | **Cloudflare Edge (Pages/Workers)** | **R$ 0,00** | Deploy atômico via GitHub Actions, CDN Anycast global, SSL automático e zero egress. |
| **APIs Serverless de Borda** (`api.supletivo.net.br`, `agent...`, `notify...`) | VM Azure | **Cloudflare Workers + D1** | **R$ 0,00** | Baixa latência, execução serverless sem servidor fixo, tolerante a picos. |
| **Backup Leve do SQLite (OmniRoute)** | Disco local VM Azure | **Cloudflare D1 (`omniroute-db`)** | **R$ 0,00** | 40.56 MB de snapshot íntegro (149 tabelas), replicado globalmente e livre de custos de VM. |
| **Mídia e Documentos (Anexos)** | Disco da VM | **Cloudflare R2 (`supletivo-media`)** | **R$ 0,00** | Compatível com S3 (AWS SigV4 já implementado no backend), sem taxa de tráfego de saída (zero egress). |
| **Ingresso de Tráfego / Segurança** | IP Público Azure (R$ 10/mês) | **Cloudflare Zero Trust / Tunnel (`v7m-azure-core`)** | **R$ 0,00** | Túnel de saída criptografado, dispensa portas abertas e elimina a dependência de IP público fixo. |
| **E-mails Transacionais** | Servidor na VM | **Mail.V7m.live / Resend / Brevo + CF Email Routing** | **R$ 0,00** | Alta entregabilidade, SPF/DKIM/DMARC profissionais, sem queima de reputação do IP da Azure. |
| **Contêineres Docker Pesados** (Evolution, Chatwoot, Dify, Backend) | VM Azure (`vm-v7m-core`) | **Mantidos no Azure temporariamente** (Fase posterior: Hetzner / VPS ~€4 a €7/mês) | Absorvido no Grant | Evita indisponibilidade imediata; transição planejada de forma modular. |
| **Modelos de IA Avançados** | Azure AI Foundry (`IEADPG`) | **Azure AI Foundry (Sob Demanda)** | Crédito Anual | Reservado para tarefas críticas via `claude-sonnet-5-5` e catálogo Azure, sem concorrência com VM. |

---

## 3. Mapeamento de Responsabilidades da Frota de Bots

Para garantir a execução orquestrada, as tarefas foram distribuídas de acordo com a especialidade de cada bot:

```
                            ┌────────────────────────┐
                            │        @Azure          │
                            │ (Orçamento, Cotas e    │
                            │  Preservação do Grant) │
                            └───────────┬────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
┌───────────────────────┐    ┌───────────────────────┐    ┌───────────────────────┐
│ @Plannotator Reviewer │    │      @Cloudflare      │    │        @Github        │
│  (Governança, Planos, │    │ (D1, R2, Zero Trust,  │    │  (Versionamento Git,  │
│   Checklist de Gates) │    │  Pages, Workers, SSL) │    │   Actions, Branches)  │
└───────────────────────┘    └───────────────────────┘    └───────────────────────┘
           │                            │                            │
           ▼                            ▼                            ▼
┌───────────────────────┐    ┌───────────────────────┐    ┌───────────────────────┐
│      @Omniroute       │    │    @Mail.V7m.live     │    │         @CI/CD        │
│ (Sanitização do SQLite│    │ (Entregabilidade DNS, │    │ (Pipelines, Testes e  │
│  e Exportação D1 DDL) │    │  Roteamento de Email) │    │   Deploys Atômicos)   │
└───────────────────────┘    └───────────────────────┘    └───────────────────────┘
```

1. **`@Plannotator Reviewer`:**
   - Validação técnica da arquitetura multi-cloud e aprovação dos gates de segurança.
   - Rastreamento dos documentos em `shared/plans/` e conformidade com o ecossistema.
2. **`@Azure` (este bot):**
   - Gestão de custos e acompanhamento do `Budget-Mensal-Alerta` (R$ 1.100).
   - Manutenção dos 24 deployments Succeeded no Azure Cognitive Services.
   - Fornecimento de credenciais e rotas seguras do Azure AI Foundry (`claude-sonnet-5-5`) para ocasiões especiais.
3. **`@Cloudflare`:**
   - Criação do banco D1 dedicado `omniroute-db` (Free Tier).
   - Validação dos buckets R2 para armazenamento estático sem egress.
   - Verificação do Cloudflare Tunnel ativo (`v7m-azure-core`) e ajuste do SSL/TLS para modo `Full`.
4. **`@Github`:**
   - Persistência dos planos de arquitetura nos repositórios oficiais (`backend.supletivo.net.br` e satélites).
   - Atualização de secrets de CI/CD para deploy dos frontends e Workers.
5. **`@Omniroute`:**
   - Sanitização do dump SQL do banco `storage.sqlite` (removendo chaves upstream das tabelas `provider_connections` e `api_keys`).
   - Fornecimento dos scripts de carga incremental para o Cloudflare D1.
6. **`@Mail.V7m.live`:**
   - Garantia de que nenhum e-mail transacional dependa de portas SMTP da VM do Azure.
   - Roteamento via Cloudflare Email Routing e provedores API (Resend).

---

## 4. Plano de Ação Imediata & Execução Técnica

### Fase 1: Governança, Plannotator & Sincronização GitHub (Executada Agora)
* [x] **Criação da Especificação no Plannotator:** Arquivo `shared/plans/plano_estrategico_migracao_multicloud_preservacao_azure.md`.
* [x] **Persistência no Repositório Canônico:** Commit da documentação em `maestri33/backend.supletivo.net.br/docs/plans/` com push para a branch `main`.
* [x] **Notificação Assíncrona ao `@Plannotator Reviewer`:** Envio formal do plano para homologação de governança.

### Fase 2: Desacoplamento de Borda & Armazenamento Leve (Em Execução)
* [x] **Snapshot do SQLite Validado:** `omniroute_backup_manifest.json` com SHA-256 `4f6e8057...` e integridade verificada.
* [ ] **Criação do D1 no Cloudflare:** Provisionamento de `omniroute-db` pelo `@Cloudflare`.
* [ ] **Sanitização das Tabelas Sensíveis:** Expurgo de tokens em `provider_connections` e `api_keys` antes do upload para a borda.
* [ ] **Validação do Cloudflare Tunnel:** Garantir que todos os acessos administrativos passem pelo túnel `v7m-azure-core` sem exposição de portas no IP da Azure.

### Fase 3: Isolamento da VM e Preparação para o Contêiner (Posterior)
* [ ] **Congelamento da VM Azure:** A VM permanece operacional rodando os contêineres atuais sem novas adições de carga.
* [ ] **Mapeamento de Volumes Docker:** Mapear volumes persistentes (`/app/data`, uploads e bancos locais) para futura migração suave para VPS externa.

---

## 5. Critérios de Sucesso e Gates de Qualidade

1. **Gate Financeiro:** O consumo diário da assinatura Azure deve permanecer estritamente abaixo de **R$ 13,00 BRL/dia** até o final de Novembro/2026, com total acumulado inferior a R$ 1.100,00.
2. **Gate de Disponibilidade:** Zero indisponibilidade nos frontends (`supletivo.net.br`, `promotor.supletivo.net.br`, `app.supletivo.net.br`) e no backend.
3. **Gate de Segurança:** Nenhuma chave de API upstream ou segredo corporativo exposto nos backups do D1 ou repositórios públicos.
4. **Gate de Versionamento:** Todas as decisões arquiteturais e mudanças estruturais registradas com commits claros no GitHub do projeto `maestri33`.

---
*Documento aprovado e integrado ao repositório de governança do ecossistema.*
