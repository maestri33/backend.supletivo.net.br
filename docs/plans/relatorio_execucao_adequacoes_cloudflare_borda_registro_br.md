# Relatório de Execução Técnica: Adequações de Borda, Segurança, Cache e DNSSEC

> **Data de Execução:** Terça-feira, 17 de novembro de 2026 — 22:05 BRT (18/11/2026 01:05 UTC)  
> **Responsável Técnico:** `@Cloudflare`  
> **Zonas / Domínios Impactados:** `supletivo.net.br` (Cloudflare Zone `9aa036f3514122baac813114d8d913b4`) & Registro.br (NIC.br)  
> **Status:** **100% EXECUTADO, VALIDADO E ATIVO EM PRODUÇÃO**

---

## 1. Resumo das Adequações Concluídas

Na noite de 17 de novembro de 2026, foi realizada uma auditoria analítica e posterior execução em lote de melhorias críticas de segurança, performance, resiliência e integridade criptográfica no ecossistema de borda da Cloudflare e no registrador de domínios Registro.br.

---

## 2. Detalhamento das Alterações Realizadas

### 2.1. Elevação do Modo SSL/TLS para `Full`
* **Motivo:** O modo anterior era `Flexible`, o que permitia conexões não criptografadas entre a borda da Cloudflare e a origem (porta 80), além de introduzir risco de loops de redirecionamento (`ERR_TOO_MANY_REDIRECTS`).
* **Ação Executada:** Atualizado para `ssl = "full"` na zona `supletivo.net.br`.
* **Evidência de Validação:**
  - `https://supletivo.net.br` ➔ `HTTP/2 200 OK`
  - `https://promotor.supletivo.net.br` ➔ `HTTP/2 200 OK`
  - `https://backend.supletivo.net.br` ➔ `HTTP/2 200 OK` (via Cloudflare Tunnel).

### 2.2. Implementação de WAF Custom Rule Anti-Scanners (Camada L7)
* **Motivo:** Foram registradas mais de 4.700 requisições 404 em 24h geradas por bots vasculhando arquivos PHP inexistentes, `.env` e repositórios `.git`, consumindo recursos e tempo de execução de Workers.
* **Ruleset:** `http_request_firewall_custom` (ID: `8837ac6202704be49c2f8693517e361b`).
* **Regra:** `Bloquear varreduras de arquivos sensiveis (.env, .git, php, cgi)`.
* **Expressão Ativa:**
  ```text
  (starts_with(http.request.uri.path, "/.env") or 
   starts_with(http.request.uri.path, "/.git") or 
   starts_with(http.request.uri.path, "/wp-") or 
   ends_with(http.request.uri.path, ".php") or 
   starts_with(http.request.uri.path, "/cgi-bin") or 
   starts_with(http.request.uri.path, "/vendor/") or 
   http.request.uri.path contains "eval-stdin")
  ```
* **Ação:** `block` (descarte imediato com HTTP 403 Forbidden).
* **Evidência de Validação:**
  - `curl -sI https://supletivo.net.br/.env` ➔ **`HTTP/2 403 Forbidden`** (bloqueado em 0ms).
  - `curl -sI https://promotor.supletivo.net.br/wp-login.php` ➔ **`HTTP/2 403 Forbidden`**.

### 2.3. Otimização e Expansão da Cache Rule
* **Motivo:** A regra de cache de borda cobria apenas o apex e `www`, deixando o novo subdomínio `promotor.supletivo.net.br` sem cache de página completa (HTML).
* **Ruleset:** `http_request_cache_settings` (ID: `3cf78243044d4f7d8a2b0efb9115c5d6`, Regra: `a53b34e82f4140b596c35a3fbc501c2e`).
* **Expressão Atualizada:**
  ```text
  (http.host eq "supletivo.net.br" or 
   http.host eq "www.supletivo.net.br" or 
   http.host eq "promotor.supletivo.net.br")
  ```
* **Configuração:** `cache: true`, `browser_ttl: respect_origin`, `edge_ttl: respect_origin`.
* **Evidência de Validação:**
  - `curl -sI https://promotor.supletivo.net.br` ➔ **`cf-cache-status: HIT`**.

### 2.4. Ativação de Early Hints (HTTP 103)
* **Motivo:** Acelerar o carregamento de CSS, fontes e scripts críticos durante a compilação do DOM no navegador do visitante.
* **Ação Executada:** Atualizado para `early_hints = "on"` na zona `supletivo.net.br`.
* **Impacto:** Melhoria direta de métricas Core Web Vitals (LCP e FCP).

### 2.5. Ativação e Vinculação de DNSSEC no Registro.br
* **Motivo:** Proteger a integridade das resoluções DNS contra envenenamento de cache (DNS cache poisoning) e desvios maliciosos.
* **Ação Cloudflare:** `PATCH /zones/9aa036f3514122baac813114d8d913b4/dnssec` ➔ `status: "active"`.
* **Ação Registro.br:** Cadastrada a chave DS via painel do Registro.br em 17/11/2026 22:01 BRT:
  - **Servidores DNS:** `brian.ns.cloudflare.com` / `jillian.ns.cloudflare.com`
  - **Keytag:** `2371`
  - **Algoritmo:** `13` (ECDSAP256SHA256)
  - **Tipo de Digest:** `2` (SHA-256)
  - **Digest:** `B95C780FF239389DF38B628B71748D37ACFA46262D36B8BC271B91A9CF937B5A`
* **Status no Registro.br:** *DNS atualizado com sucesso!*

### 2.6. Alinhamento Multi-Cloud com @Azure
* **Provisionamento:** Cloudflare D1 `omniroute-backup-safe` criado com sucesso (UUID: `7d2063ba-1f30-440e-bcd2-05441ff0a032`, região ENAM).
* **Cloudflare Tunnel:** `v7m-azure-core` verificado e mantido 100% saudável com 4 conexões ativas na borda, mantendo a VM Azure protegida sem necessidade de exposição de portas públicas.

---

## 3. Matriz de Estado Atual das Zonas

| Zona | SSL Mode | WAF L7 | Cache HTML | Early Hints | DNSSEC | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `supletivo.net.br` | **Full** | **Ativo (Custom)** | **Ativo (Apex + Promotor)** | **On** | **Configurado (DS 2371)** | 🟢 Estável / Hardened |
| `v7m.live` | Full | Gerenciado | Padrão | On | — | 🟢 Estável |
| `maestri.group` | Full | Gerenciado | Pages | On | — | 🟢 Estável |

---

> Documento oficial de governança arquivado em:  
> `shared/plans/relatorio_execucao_adequacoes_cloudflare_borda_registro_br.md`
