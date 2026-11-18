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
> **Status:** AUDITADO, HOMOLOGADO NO PLANNOTATOR & FASE 2 100% EXECUTADA E VERIFICADA  
> **Data:** Terça-feira, 17 de novembro de 2026 — 22:45 BRT (2026-11-18T01:45:00Z UTC)  
> **Premissa e Diretriz do Usuário:**  
> 1. Manter os contêineres Docker pesados no Azure por enquanto (migração de contêineres postergada);  
> 2. Infraestrutura Cloudflare opera sob **Workers Paid & R2 Paid (PAYGO)** (capacidade industrial, 50M writes/mês no D1, Queues, Cron Triggers, sem os gargalos artificiais de Free Tier);  
> 3. Planejar e executar imediatamente todo o restante (borda, catálogo D1 `omniroute-db`, backup bit-a-bit R2 `omniroute-backups`, Zero Trust, DNS, e-mails e governança de custos) com persistência obrigatória no GitHub.

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
  * **Custo Diário em 17/11/2026:** Fechado em apenas **R$ 9,15 BRL** (estritamente infraestrutura fixa da VM e disco).
  * **Proteção Orçamentária Ativada:** Criado o Azure Budget `Budget-Mensal-Alerta` com teto de R$ 1.100,00 BRL e notificações para `prvictormaestri@ieadpg.onmicrosoft.com` em 80%, 90% e 100%.
* **Saldo Restante do Ciclo Anual:** **~US$ 1.754,70 USD** (aproximadamente **R$ 9.650,00 BRL** disponíveis).

### 1.3 A Decisão Arquitetural: "Azure para Ocasiões Especiais"
Manter uma máquina virtual Linux de uso geral (`vm-v7m-core` - Standard_F1ams_v7) ligada 24/7 no Azure consome cerca de **R$ 380,00/mês (~US$ 68,00/mês)**, consumindo mais de **40% de todo o crédito anual da igreja**.
A decisão tomada estabelece o seguinte desacoplamento:
1. **Contêineres Docker:** Permanecem temporariamente na VM do Azure para evitar qualquer fricção operacional imediata, sendo migrados para VPS de baixo custo (ex: Hetzner / Oracle Free) em fase futura.
2. **Borda, Frontends, Backups e Armazenamento (Cloudflare Workers Paid & R2 Paid):**
   * A conta Cloudflare opera com os planos corporativos pagos ativos:
     - **`workers_paid`:** 50M writes/mês no D1, 25B reads/mês, Cloudflare Queues, Cron Triggers, CPU time até 30s.
     - **`r2_paid`:** 10M operações Classe A e B/mês, armazenamento escalável ilimitado com **taxa zero de tráfego de saída (zero egress)**.
     - **`images_v2_stream_basic`:** Otimização e entrega de assets.
     - **`teams_free`:** Zero Trust Gateway & Tunnels com até 50 usuários.
3. **Papel Exclusivo da Azure:** Preservar a totalidade dos US$ 2.000 anuais como "reserva nobre" para:
   * **Azure AI Foundry:** Inferência sob demanda em modelos de ponta (`claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5-5`, `gpt-4o`/`gpt-5.x`).
   * **Cold Storage / Archive Tier:** Backup histórico e imutável de cadastros e contratos de alunos a frações de centavo.
   * **Recuperação de Desastres (DR) e Computação Sob Demanda:** Instâncias temporárias para batch processing.

---

## 2. Matriz de Atribuição por Serviço & Provedor

| Componente | Provedor Atual | Provedor Alvo | Nível de Serviço / Plano | Justificativa Técnica |
| :--- | :--- | :--- | :---: | :--- |
| **Frontends Web** (`supletivo.net.br`, `promotor...`, `app...`) | VM Azure / Borda | **Cloudflare Edge (Pages/Workers)** | **Workers Paid** | Deploy atômico via GitHub Actions, CDN Anycast global, SSL automático e zero egress. |
| **APIs Serverless de Borda** (`api.supletivo.net.br`, `agent...`, `notify...`) | VM Azure | **Cloudflare Workers + D1** | **Workers Paid** | Baixa latência, execução serverless desacoplada, suporte a Queues e Cron Triggers. |
| **Catálogo Estrutural e Configuração OmniRoute** | Disco local host | **Cloudflare D1 (`omniroute-db`)** | **Workers Paid** | UUID `6fb2f4d4-1a39-4bfd-8e3d-620301e270b5`. 146 tabelas DDL, 252 índices e 2.067 linhas com segredos mascarados. |
| **Backup Bit-a-Bit Integral OmniRoute (.sqlite)** | Disco local host | **Cloudflare R2 (`omniroute-backups`)** | **R2 Paid** | Arquivo `omniroute_cloudflare_backup_20261116.sqlite` (40.56 MB, SHA-256 `4f6e8057...`) armazenado com zero egress. |
| **Mídia e Documentos (Anexos do Supletivo)** | Disco da VM | **Cloudflare R2 (`supletivo-media`, `notify-media`)** | **R2 Paid** | Compatível com S3 (AWS SigV4 já implementado no backend), sem taxa de saída. |
| **Ingresso de Tráfego / Segurança** | IP Público Azure (R$ 10/mês) | **Cloudflare Zero Trust / Tunnel (`v7m-azure-core`)** | **Zero Trust** | Túnel multiplexado com 4 conexões Anycast, dispensa portas 80/443 abertas e elimina dependência de IP público. |
| **E-mails Transacionais & Inbound** | VM / Stalwart | **Mail.V7m.live / Resend / Brevo + CF Email Routing** | **Email Routing & Stalwart** | Zona `v7m.live` pronta no CF Email Routing; `supletivo.net.br` MX roteado para Stalwart via túnel. |
| **Contêineres Docker Pesados** (Evolution, Chatwoot, Dify, Backend) | VM Azure (`vm-v7m-core`) | **Mantidos no Azure temporariamente** (Fase posterior: Hetzner / VPS ~€4 a €7/mês) | Absorvido no Grant | Evita indisponibilidade imediata; transição planejada de forma modular. |
| **Modelos de IA Avançados** | Azure AI Foundry (`IEADPG`) | **Azure AI Foundry (Sob Demanda)** | Crédito Anual | Reservado para tarefas críticas via `claude-sonnet-5-5` e catálogo Azure, sem concorrência com VM. |

---

## 3. Mapeamento de Responsabilidades da Frota de Bots

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
   - Validação técnica da arquitetura multi-cloud e homologação formal dos gates de governança.
   - Rastreamento dos documentos em `shared/plans/` e conformidade com o ecossistema.
2. **`@Azure` (este bot):**
   - Gestão de custos e acompanhamento do `Budget-Mensal-Alerta` (R$ 1.100).
   - Manutenção dos 24 deployments Succeeded no Azure Cognitive Services.
   - Fornecimento de credenciais e rotas seguras do Azure AI Foundry (`claude-sonnet-5-5`) para ocasiões especiais.
3. **`@Cloudflare`:**
   - Gestão do banco D1 `omniroute-db` (UUID `6fb2f4d4-1a39-4bfd-8e3d-620301e270b5`).
   - Gestão dos buckets R2 (`omniroute-backups`, `supletivo-media`, `notify-media`) sob Workers/R2 Paid.
   - Supervisão contínua do Cloudflare Zero Trust Tunnel (`v7m-azure-core`) e modo SSL/TLS `Full`.
4. **`@Github`:**
   - Persistência dos planos de arquitetura nos repositórios oficiais (`backend.supletivo.net.br` e satélites).
   - Atualização de secrets de CI/CD para deploy dos frontends e Workers.
5. **`@Omniroute`:**
   - Manutenção do script de sanitização `shared/sanitize_omniroute_for_d1.js`.
   - Sincronização periódica do catálogo de capacidades e combos no D1.
6. **`@Mail.V7m.live`:**
   - Garantia de que nenhum e-mail transacional dependa de portas SMTP diretas da VM do Azure.
   - Roteamento via Cloudflare Email Routing e Stalwart via Zero Trust Tunnel.

---

## 4. Status de Execução das Fases

### Fase 1: Governança, Plannotator & Sincronização GitHub (100% Concluída)
* [x] **Criação da Especificação no Plannotator:** Arquivo `shared/plans/plano_estrategico_migracao_multicloud_preservacao_azure.md`.
* [x] **Persistência no Repositório Canônico:** Commit da documentação em `maestri33/backend.supletivo.net.br/docs/plans/` com push para a branch `main` (commits `f0f68c3`, `870a450`, `1133f37`, `51b251d`).
* [x] **Homologação pelo `@Plannotator Reviewer`:** Plano auditado e aprovado com checklist de gates oficializado.

### Fase 2: Desacoplamento de Borda, D1 e R2 (100% Concluída e Verificada)
* [x] **Snapshot do SQLite Validado:** `omniroute_backup_manifest.json` com SHA-256 `4f6e8057a0e695992b0f99e0b1ef952d843b6b72b2ad4a84e57e46f18af029b5` e integridade verificada.
* [x] **Criação e Ingestão do Cloudflare D1 (`omniroute-db`):** UUID `6fb2f4d4-1a39-4bfd-8e3d-620301e270b5`, região ENAM. Ingeridas **146 tabelas DDL**, **252 índices** e **2.067 linhas** de dados vitais sanitizados (segredos mascarados como `[REDACTED_SECRET_FOR_D1]`).
* [x] **Criação e Upload do Cloudflare R2 (`omniroute-backups`):** Bucket provisionado e arquivo binário `omniroute_cloudflare_backup_20261116.sqlite` (42.528.768 bytes / 40.56 MB) carregado com sucesso via API e verificado com status ativo.
* [x] **Validação do Cloudflare Zero Trust Tunnel:** Túnel `v7m-azure-core` ativo com **4 conexões simultâneas** e modo SSL `Full` confirmado na zona `supletivo.net.br`.
* [x] **Auditoria de Rede Azure NSG:** Portas 80 e 443 100% fechadas para tráfego externo; porta 22 restrita a IPs administrativos autorizados.
* [x] **Auditoria de E-mail:** Zona `v7m.live` configurada em modo ready no Email Routing; zona `supletivo.net.br` apontada para Stalwart via Zero Trust Tunnel.

### Fase 3: Isolamento da VM e Transição Posterior dos Contêineres (Planejada)
* [x] **Congelamento da VM Azure:** A VM permanece operacional rodando os contêineres atuais sem novas adições de carga (custo estabilizado em R$ 9,15/dia).
* [ ] **Mapeamento de Volumes Docker:** Mapear volumes persistentes (`/app/data`, uploads e bancos locais) para futura migração suave para VPS externa (Hetzner CPX21 / Oracle Cloud).

---

## 5. Critérios de Sucesso e Gates de Qualidade

1. **Gate Financeiro:** O consumo diário da assinatura Azure deve permanecer estritamente abaixo de **R$ 13,00 BRL/dia** até o final de Novembro/2026, com total acumulado inferior a R$ 1.100,00.
2. **Gate de Disponibilidade:** Zero indisponibilidade nos frontends (`supletivo.net.br`, `promotor.supletivo.net.br`, `app.supletivo.net.br`) e no backend.
3. **Gate de Segurança:** Nenhuma chave de API upstream ou segredo corporativo exposto nos backups do D1 ou repositórios públicos.
4. **Gate de Versionamento:** Todas as decisões arquiteturais e mudanças estruturais registradas com commits claros no GitHub do projeto `maestri33`.

---
*Documento aprovado, revisado com as assinaturas reais Cloudflare Workers/R2 Paid e integrado ao repositório canônico.*
