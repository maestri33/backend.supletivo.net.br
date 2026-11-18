# Plano Técnico de Otimização, Hardening e Backup — OmniRoute Docker

> **Documento de Especificação Técnica e Planejamento para Revisão no Plannotator**  
> **Ambiente Alvo:** Host Docker `win11-home` (`C:\Users\maestri33\dev\omniroute-docker`)  
> **Serviços Afetados:** `omniroute` (`diegosouzapw/omniroute:latest` v3.8.53), `omniroute-redis` (`redis:alpine`)  
> **Origem Técnica:** Auditoria do banco `storage.sqlite` e topologia Docker realizada por `@Omniroute`  
> **Data:** Terça-feira, 17 de novembro de 2026 — 14:55 BRT (17:55 UTC)  
> **Status:** AGUARDANDO REVISÃO E APROVAÇÃO TÉCNICA (PLANNOTATOR)  
> **Política de Integridade:** Zero downtime para roteamento ativo; alterações de schema/dados via transações atômicas `better-sqlite3`; backup preventivo pré-execução obrigatório; sem exposição de credenciais upstream.

---

## 1. Resumo Executivo e Justificativa

Após a reorganização bem-sucedida do combo principal (**`combo-ultra`**) — que posicionou o modelo de custo zero **`antigravity/gemini-3.8-flash-high`** em 1º lugar e relegou modelos de alto consumo para o final da fila —, identificou-se a necessidade de estender essa arquitetura aos demais serviços e reforçar a segurança do ambiente.

A auditoria identificou quatro frentes prioritárias de melhoria:
1. **Divergência de Custo nos Combos:** Combos secundários ativos (`default` e `atendimento-pro`) ainda possuem modelos de alto custo ou sob rate limit severo (ex.: `azure-astra/gpt-6-astra`) no topo da fila.
2. **Degradação de Latência por Rotas Falhas:** O modelo `azure-astra/kimi-k3-1-pro` registrou 306 falhas (HTTP 429) em 307 requisições (taxa de erro de 99,7%), gerando timeouts e sobrecarga desnecessária antes de acionar fallbacks.
3. **Exposição de Rede Local (0.0.0.0):** A porta `20128` está publicada em todas as interfaces de rede no Windows, expondo o gateway na rede local física/Wi-Fi sem necessidade.
4. **Acúmulo de Telemetria no SQLite (42,5 MB):** Mais de 50.000 registros históricos em tabelas de logs e snapshots de quotas sem expiração automática configurada.
5. **Automação de Backup Cloudflare R2:** Snapshot manual gerado com sucesso (`4f6e8057...`), porém sem rotina contínua automatizada para o bucket provisionado `omniroute-backups`.

---

## 2. Diagnóstico Factual Auditado vs. Estado Desejado

| Item / Vetor | Estado Atual Auditado (17/11/2026) | Estado Desejado Proposto | Impacto / Benefício |
| :--- | :--- | :--- | :--- |
| **Combo `default`** | 1º: Gemini Flash High, 2º: Claude Sonnet, 3º: Llama 70B Fast | Alinhar ao padrão econômico: Gemini (1º) -> DeepSeek V4 Pro (2º) -> DeepSeek R1 (3º) -> Fallbacks | Redução drástica de consumo de cotas comerciais em rotas padrão. |
| **Combo `atendimento-pro`** | 1º: `azure-astra/gpt-6-astra` (35% sucesso, 429 freq.), 2º: Llama 70B Fast | 1º: Gemini 3.8 Flash High -> 2º: DeepSeek V4 Pro -> 3º: GPT-6 Astra (fallback) | Elimina latência e timeouts no atendimento automatizado. |
| **Rotas Instáveis (Kimi)** | `azure-astra/kimi-k3-1-pro` ativo em combos legados (99,7% de falha) | Desativado/removido de todas as rotas ativas de produção | Elimina tentativas inúteis de ~3s por requisição. |
| **Binding de Portas Docker** | `0.0.0.0:20128:20128` (exposto na LAN física) | `127.0.0.1:20128:20128` no `docker-compose.yml` | Zero exposição em redes locais não confiáveis; acesso via túnel/loopback. |
| **Segurança do Redis** | Sem autenticação, conectado na rede Docker compartilhada | Isolamento em rede interna estrita ou senha `requirepass` | Impede injeção de comandos Redis via outros containers na bridge. |
| **Telemetria SQLite** | 18.276 linhas em `quota_snapshots`, 14.048 em `conversation_turn_nodes`, 7.297 em `usage_history` | Retenção máxima de 30 dias com `VACUUM INTO` periódico | Controle de I/O em disco, backup mais leve e queries mais rápidas. |
| **Backup R2 Cloudflare** | Manual no host (`omniroute_cloudflare_backup_20261116.sqlite`) | Script agendado diário via S3 API / Wrangler para bucket `omniroute-backups` | Recuperação de desastres garantida sem intervenção humana. |

---

## 3. Especificação Técnica e Scripts de Execução

### Ação 1: Atualização dos Combos `default` e `atendimento-pro` (Atômica no SQLite)
* **Objetivo:** Inverter a ordem para garantir **Gemini 3.8 Flash High** (Custo Zero Antigravity) e **DeepSeek** (Cloudflare AI) antes de qualquer modelo tarifado.
* **Script Node.js para Execução Segura via Docker:**

```javascript
// update_combos_cost_optimized.js
const Database = require('better-sqlite3');
const db = new Database('/app/data/storage.sqlite');
db.pragma('busy_timeout = 5000');

const tx = db.transaction(() => {
  const now = new Date().toISOString();

  // 1. Atualizar 'atendimento-pro'
  const rowAtend = db.prepare('SELECT id, data FROM combos WHERE name=?').get('atendimento-pro');
  if (rowAtend) {
    const dataAtend = JSON.parse(rowAtend.data);
    dataAtend.description = "Atendimento Otimizado: Gemini 3.8 Flash High -> DeepSeek V4 Pro -> GPT-6 Astra Fallback";
    dataAtend.models = [
      { id: "atend-model-1-gemini", kind: "model", model: "antigravity/gemini-3.8-flash-high", providerId: "antigravity", weight: 10 },
      { id: "atend-model-2-deepseek", kind: "model", model: "cloudflare-ai/@cf/deepseek-ai/deepseek-v4-pro-0813", providerId: "cloudflare-ai", weight: 9 },
      { id: "atend-model-3-llama", kind: "model", model: "cloudflare-ai/@cf/meta/llama-3.3-70b-instruct-fp8-fast", providerId: "cloudflare-ai", weight: 8 },
      { id: "atend-model-4-gpt6", kind: "model", model: "azure-astra/gpt-6-astra", providerId: "azure-astra", weight: 4 }
    ];
    dataAtend.strategy = "priority";
    dataAtend.updatedAt = now;
    db.prepare('UPDATE combos SET data=?, updated_at=? WHERE name=?').run(JSON.stringify(dataAtend), now, 'atendimento-pro');
  }

  // 2. Atualizar 'default'
  const rowDef = db.prepare('SELECT id, data FROM combos WHERE name=?').get('default');
  if (rowDef) {
    const dataDef = JSON.parse(rowDef.data);
    dataDef.description = "Default Economy: Gemini 3.8 Flash High -> DeepSeek V4 Pro -> DeepSeek R1 -> Sonnet";
    dataDef.models = [
      { id: "def-model-1-gemini", kind: "model", model: "antigravity/gemini-3.8-flash-high", providerId: "antigravity", weight: 10 },
      { id: "def-model-2-deepseek-v4", kind: "model", model: "cloudflare-ai/@cf/deepseek-ai/deepseek-v4-pro-0813", providerId: "cloudflare-ai", weight: 9 },
      { id: "def-model-3-deepseek-r1", kind: "model", model: "cloudflare-ai/@cf/deepseek-ai/deepseek-r1-distill-qwen-32b", providerId: "cloudflare-ai", weight: 8 },
      { id: "def-model-4-sonnet", kind: "model", model: "antigravity/claude-sonnet-4-6", providerId: "antigravity", weight: 5 }
    ];
    dataDef.strategy = "priority";
    dataDef.updatedAt = now;
    db.prepare('UPDATE combos SET data=?, updated_at=? WHERE name=?').run(JSON.stringify(dataDef), now, 'default');
  }
});

tx();
console.log("COMBOS ATUALIZADOS COM SUCESSO!");
db.close();
```

---

### Ação 2: Hardening de Rede no `docker-compose.yml`
* **Arquivo:** `C:\Users\maestri33\dev\omniroute-docker\docker-compose.yml`
* **Diff Proposto:**

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -10,7 +10,7 @@
     container_name: omniroute
     restart: always
     ports:
-      - "0.0.0.0:20128:20128"
+      - "127.0.0.1:20128:20128"
     volumes:
       - omniroute_data:/app/data
     environment:
```

---

### Ação 3: Higiene de Telemetria e Purga de Logs Antigos (> 30 dias)
* **Objetivo:** Manter a base SQLite leve sem perder configurações, conexões de provedores ou combos.
* **Comando SQL de Retenção:**

```sql
-- Executar em transação segura
BEGIN TRANSACTION;
DELETE FROM quota_snapshots WHERE created_at < datetime('now', '-30 days');
DELETE FROM conversation_turn_nodes WHERE created_at < datetime('now', '-30 days');
DELETE FROM job_runs WHERE created_at < datetime('now', '-30 days');
DELETE FROM call_logs WHERE created_at < datetime('now', '-30 days');
DELETE FROM proxy_logs WHERE created_at < datetime('now', '-30 days');
DELETE FROM usage_history WHERE timestamp < datetime('now', '-30 days');
COMMIT;
PRAGMA wal_checkpoint(TRUNCATE);
```

---

### Ação 4: Script de Automação de Backup R2 (PowerShell)
* **Arquivo:** `C:\Users\maestri33\dev\omniroute-docker\scripts\backup-r2.ps1`
* **Fluxo:**
  1. Cria snapshot atômico via `better-sqlite3 db.backup` dentro do container.
  2. Valida hash SHA-256 e `PRAGMA integrity_check`.
  3. Despacha para o bucket R2 `omniroute-backups` mantendo histórico rotativo de 7 dias.

---

## 4. Matriz de Riscos e Procedimento de Rollback

| Risco | Probabilidade | Impacto | Mitigação / Rollback |
| :--- | :---: | :---: | :--- |
| **Incompatibilidade no bind `127.0.0.1`** | Baixa | Médio (se outro host na LAN consumia direto) | Reverter a linha do compose para `0.0.0.0:20128:20128` e executar `docker compose up -d`. |
| **Falha transitória em modelo gratuito** | Baixa | Baixa | A estratégia `priority` já possui fallback imediato para Cloudflare AI e Claude. |
| **Corrupção em script SQLite** | Nula | Alto | Snapshot atômico de segurança prévio é gerado antes de qualquer comando (`storage_pre_hardening.sqlite`). |

---

## 5. Próximos Passos e Gates de Aprovação

1. **Revisão Técnica pelo `@Plannotator Reviewer`:** Validação do plano, anotações de conformidade e liberação técnica.
2. **Conexão do Computador:** Victor ativa *"Let bots use this computer"* no app Rakazo Desktop.
3. **Execução Automatizada:** Execução não disruptiva dos scripts validados.
4. **Verificação de Integridade:** Teste de chamada nas rotas atualizadas e emissão de relatório final.
