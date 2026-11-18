# Plano de Ação Técnico: Ativação e Correção de Infraestrutura — mail.v7m.live

> **Documento de Especificação e Planejamento para Revisão no Plannotator**  
> **Domínio Principal:** `v7m.live` | **Subdomínio de Serviço:** `mail.v7m.live`  
> **Origem Técnica:** Auditoria realizada por `@Mail.V7m.live` (16/11/2026)  
> **Status:** AGUARDANDO REVISÃO HUMANA (PRÉ-EXECUÇÃO)  
> **Política de Execução:** Nenhuma alteração destrutiva, abertura de portas ou alteração de registros MX em produção será executada sem validação e aprovação explícita no Plannotator.

---

## 1. Resumo Executivo e Contexto

O domínio **`v7m.live`** requer infraestrutura estável e moderna de correio eletrônico para atender a serviços corporativos, comunicações transacionais e fluxos de mensageria da plataforma V7M.

A infraestrutura on-premises anterior baseada em Proxmox (`10.0.1.20`) foi formalmente descontinuada. Todo o ambiente core está migrado e ativo na **Microsoft Azure** (`rg-v7m-core`), sob orquestração de containers Docker na máquina virtual `vm-v7m-core`, com conectividade perimetral intermediada por **Cloudflare Zero Trust Tunnels**.

Este plano de ação estabelece os passos exatos, pré-requisitos, validações e gates de aprovação para ativar com segurança os endpoints Webmail, Admin e API JMAP em `https://mail.v7m.live`, configurando os registros de identidade de domínio no servidor de correio **Stalwart** e resolvendo as limitações de protocolo inerentes à topologia atual.

---

## 2. Topologia Factual Auditada vs. Estado Desejado

| Componente | Estado Atual Auditado | Estado Desejado / Correção |
| :--- | :--- | :--- |
| **Infraestrutura Cloud** | VM `vm-v7m-core` (`Standard_F1ams_v7`), Ubuntu 24.04 LTS em `eastus`. IP Privado `10.2.1.4`, IP Público `20.127.0.185`. | Mantida. Sem necessidade de expansão de VM ou abertura de portas na WAN. |
| **Segurança de Rede (NSG)** | `nsg-v7m-core`: Porta 22 liberada apenas para IPs administrativos. Portas 25, 80, 443, 587, 993 e 8080 **bloqueadas para a WAN**. | Mantida. Acesso externo realizado exclusivamente via túnel criptografado de saída. |
| **Servidor de E-mail (Stalwart)** | Container `v7m-stalwart` (`stalwartlabs/stalwart:latest`) ativo via Docker Compose. Domínios ativos: `v7m.org`, `supletivo.net.br`. | Domínio `v7m.live` provisionado via API JMAP com chaves criptográficas compatíveis. |
| **Cloudflare Tunnel (`4b8764a6...`)** | Ingress configurado para `mail.v7m.org`, mas **`mail.v7m.live` está ausente** (gera 404). | Adicionar regra de Ingress para `mail.v7m.live` apontando para `https://stalwart:443`. |
| **DNS `mail.v7m.live`** | **NXDOMAIN** (registro não existe na zona `v7m.live`). | Criar registro CNAME `mail.v7m.live` apontando para o CNAME do túnel com Proxy ativo. |
| **Registros DKIM** | `v1-ed25519-20260823` e `v1-rsa-20260823` presentes no DNS. | Validar correspondência exata com o chaveiro persistido do Stalwart. |
| **Registro SPF** | `v=spf1 include:_spf.mx.cloudflare.net ~all`. | Manter alinhado com o provedor de recepção/envio aprovado. |
| **Registro DMARC** | `v=DMARC1; p=quarantine; rua=mailto:postmaster@v7m.org; ...` | Validar alinhamento estrito quando os envios forem ativados. |

---

## 3. Desafios Arquiteturais e Análise Crítica de Riscos

### 3.1. Limitação de Protocolo do Cloudflare Tunnel Standard (HTTP vs. SMTP Puro)
* **Diagnóstico:** O Cloudflare Tunnel (gratuito/padrão) opera no modelo reverse proxy HTTP/HTTPS/WebSocket. Ele **não** transporta tráfego TCP raw arbitrário (como SMTP na porta 25) originado de MTAs externos da internet sem Cloudflare Spectrum.
* **Impacto:** Apontar um registro público MX para `mail.v7m.live` (que resolve para o túnel) **não receberá e-mails externos diretos** de provedores como Google, Microsoft ou Yahoo via porta 25.
* **Solução Recomendada:** Utilizar a estratégia de **Cloudflare Email Routing** (já antecipada no registro SPF atual `include:_spf.mx.cloudflare.net`). O Cloudflare Email Routing recebe os e-mails na borda Cloudflare (portas MX da Cloudflare) e pode despachar para webhooks/workers ou contas internas.

### 3.2. Bloqueio de Saída na Porta 25 na Microsoft Azure (Outbound SMTP Block)
* **Diagnóstico:** A Microsoft bloqueia por padrão conexões de saída TCP na porta 25 em assinaturas e VMs padrão do Azure para prevenção de spam.
* **Impacto:** O servidor Stalwart não conseguirá entregar e-mails diretamente aos servidores MX de destino na porta 25 sem autorização especial da Microsoft.
* **Solução Recomendada:** Configurar o Stalwart com um **Smarthost / Relay SMTP Autenticado** via porta 587 (TLS/Submission) utilizando provedor transacional confiável (ex.: Resend, SendGrid, Amazon SES ou Brevo).

---

## 4. Plano de Ação Faseado para Execução

```
[Fase 1: Conectividade de Borda] ➔ [Gate 1] ➔ [Fase 2: Provisionamento Stalwart] ➔ [Gate 2] ➔ [Fase 3: Roteamento & Relay] ➔ [Gate 3] ➔ [Fase 4: Validação E2E]
```

### Fase 1: Habilitação de Acesso e Endpoints Públicos para `mail.v7m.live`
*Objetivo: Tornar as interfaces Web e a API JMAP acessíveis via navegador e clientes modernos.*

1. **Atualização da Configuração do Cloudflare Tunnel (`4b8764a6-d2e5-44a2-a0ff-554cda135343`):**
   * Adicionar no Ingress do túnel:
     ```yaml
     - hostname: mail.v7m.live
       service: https://stalwart:443
       originRequest:
         noTLSVerify: true
     ```
2. **Criação do Registro DNS na Cloudflare (Zona `v7m.live` / ID `547881722ee8920126a78f9e4c79562b`):**
   * Tipo: `CNAME`
   * Nome: `mail` (`mail.v7m.live`)
   * Alvo: `4b8764a6-d2e5-44a2-a0ff-554cda135343.cfargotunnel.com`
   * Proxy Status: `Proxied (Laranja)`
3. **Validação Automática da Fase 1:**
   * Requisição `HEAD https://mail.v7m.live/admin/` deve retornar HTTP 200/302.
   * Requisição `GET https://mail.v7m.live/jmap/session` deve retornar discovery JSON válido.

---

### Fase 2: Configuração e Provisionamento do Domínio `v7m.live` no Stalwart
*Objetivo: Registrar formalmente a identidade do domínio e as identidades de envio no motor de e-mail.*

1. **Provisionamento do Domínio via JMAP (`x:Domain/set`):**
   * Submeter payload autenticado de criação de domínio para `v7m.live`.
2. **Alinhamento de Chaves Criptográficas DKIM:**
   * Inspecionar as chaves privadas carregadas no volume `/opt/stalwart-mail` para os seletores:
     * `v1-ed25519-20260823`
     * `v1-rsa-20260823`
   * Garantir que as chaves públicas nos registros DNS TXT correspondam exatamente às chaves ativas no Stalwart.
3. **Provisionamento de Caixas Postais e Identidades Básicas:**
   * Criar contas de serviço essenciais (ex.: `postmaster@v7m.live`, `admin@v7m.live`, `notificacoes@v7m.live`).

---

### Fase 3: Estratégia de Roteamento (Inbound e Outbound)
*Objetivo: Estabelecer o fluxo de recepção e envio sem violar as restrições de Azure e Cloudflare.*

1. **Recepção (Inbound):**
   * **Decisão:** Configurar Cloudflare Email Routing para o domínio `v7m.live`.
   * **Registros MX da Cloudflare:**
     * `isaac.mx.cloudflare.net` (Prioridade 10)
     * `linda.mx.cloudflare.net` (Prioridade 20)
     * `amir.mx.cloudflare.net` (Prioridade 30)
   * Criar regras de roteamento (Catch-all ou encaminhamento para webhook/Worker de triagem).
2. **Envio (Outbound Smarthost):**
   * Configurar no Stalwart um relay de saída via porta 587 autenticado com TLS.
   * Validar que os cabeçalhos de envio mantêm o alinhamento SPF (`include:_spf...`) e DKIM assinado pelo Stalwart.

---

### Fase 4: Testes de Validação Ponta a Ponta (E2E) e Entregabilidade
*Objetivo: Garantir conformidade com diretrizes RFC e evitar rotulagem como SPAM.*

1. **Teste de API JMAP:**
   * Envio de mensagem transacional via endpoint `urn:ietf:params:jmap:submission`.
2. **Verificação de Entregabilidade e Autenticação:**
   * Envio para caixa de teste e verificação de cabeçalhos:
     * `SPF: PASS`
     * `DKIM: PASS (v1-ed25519 ou v1-rsa)`
     * `DMARC: PASS (p=quarantine / alinhado)`
3. **Validação de Interface Visual:**
   * Teste de login e navegação em `https://mail.v7m.live/account/`.

---

## 5. Pontos de Aprovação Obrigatória (Human-in-the-Loop Gates)

Nenhum comando com impacto de infraestrutura será disparado sem que o usuário revise e confirme os seguintes gates:

* **[GATE 1] Aprovação da Regra de Ingress e DNS:**
  * Autorização para alterar o arquivo de configuração do Cloudflare Tunnel e criar o CNAME na zona `v7m.live`.
  * *Risco:* Baixo (não interfere nos serviços existentes).
* **[GATE 2] Aprovação do Registro do Domínio no Stalwart:**
  * Autorização para gravar o domínio `v7m.live` e criar contas no banco persistente RocksDB.
  * *Risco:* Baixo (aditivo, não altera dados de `v7m.org` ou `supletivo.net.br`).
* **[GATE 3] Aprovação da Estratégia MX e Provedor de Relay:**
  * Autorização para alterar os registros MX públicos da zona `v7m.live` e injetar credenciais do Smarthost de saída.
  * *Risco:* Médio (altera o fluxo de entrega de e-mails do domínio).

---

## 6. Procedimento de Rollback de Contingência

Caso ocorra qualquer anomalia durante o processo:
1. **Reversão de Ingress do Túnel:** Remover a entrada de `mail.v7m.live` e reverter a configuração do túnel para a versão anterior.
2. **Reversão de DNS:** Remover o registro CNAME `mail.v7m.live` na zona Cloudflare.
3. **Reversão MX:** Retornar o registro MX anterior de `v7m.live` apontando para `mail.v7m.org`.
4. Os containers e volumes de dados do Stalwart permanecem íntegros e inalterados em `/opt/stalwart-mail`.
