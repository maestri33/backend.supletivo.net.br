# Guia de Operação: Cloudflare Hyperdrive com PostgreSQL (CT 2100)

Este documento descreve a integração da infraestrutura de produção do **PostgreSQL 18** (CT 2100, Proxmox `pve-prod`) com o **Cloudflare Hyperdrive** para acelerar leituras nos Workers da Cloudflare (`app`, `admin`, `notify-edge`).

---

## 1. Topologia de Rede & Fluxo Zero Trust

```
[ Worker na Borda ] 
       │ (TCP / PostgreSQL Protocol)
       ▼
[ Cloudflare Hyperdrive ] (Connection Pool + Edge Query Caching)
       │
       ▼
[ Cloudflare Access (Edge) ] (Validação de Service Token mTLS/HTTP)
       │
       ▼ (Túnel QUIC Outbound)
[ Cloudflare Tunnel Daemon (cloudflared) ] (CT 30101 ou Gateway Proxmox)
       │
       ▼ (LAN Física 10.1.20.100:5432)
[ PostgreSQL 18 — CT 2100 ] (Base 'dmz')
```

* **Hostname Canônico:** `db.v7m.live` (Respeitando a Regra 5: domínios `*.v7m.live` para ferramentas e utilitários técnicos).
* **Base Oficial:** `dmz` (a base `v7m` é casca legada).

---

## 2. Passo a Passo de Implantação

### Passo 1: Atualizar o Cloudflare Tunnel
O arquivo `deploy/cloudflare-tunnel/config.yml` já contém a rota TCP:

```yaml
ingress:
  # ... rotas existentes (backend, infisical, hindsight, openviking, tools) ...

  # 6. PostgreSQL Produção (CT 2100) — Acesso seguro Hyperdrive via TCP
  - hostname: db.v7m.live
    service: tcp://10.1.20.100:5432

  # 7. Fallback Catch-All Mandatório
  - service: http_status:404
```

No servidor do túnel, crie a rota DNS e reinicie o daemon:
```bash
cloudflared tunnel route dns <CLOUDFLARE_TUNNEL_ID> db.v7m.live
sudo systemctl restart cloudflared.service
```

---

### Passo 2: Cloudflare Zero Trust (Access) & Service Token

1. No painel do **Cloudflare Zero Trust** (`dash.teams.cloudflare.com`):
   - Vá em **Access** > **Service Auth** > **Service Tokens** > **Create Service Token**.
   - Nome: `hyperdrive-postgres-prod`.
   - Guarde o `Client ID` e o `Client Secret` no Infisical (`infisical.v7m.live`).
2. Vá em **Access** > **Applications** > **Add an Application** > **Self-hosted**:
   - Nome: `PostgreSQL Production (Hyperdrive)`
   - Domínio: `db.v7m.live`
3. Crie a política de acesso:
   - Nome: `Enforce Service Token`
   - Action: **`Service Auth`** *(MANDATÓRIO: valida os tokens diretamente na borda sem tela de login)*
   - Rule: `Include` > `Service Token` > `hyperdrive-postgres-prod`.

---

### Passo 3: Provisionar a Role Read-Only no PostgreSQL
No CT 2100 (ou via `psql` administrativo):
```bash
psql -h 10.1.20.100 -U postgres -d dmz -f deploy/hyperdrive/setup-user-ro.sql
```
*(Certifique-se de substituir `<SENHA_FORTE_INFISICAL>` pela senha gerada).*

---

### Passo 4: Criar a Configuração do Hyperdrive via Wrangler

Execute no terminal com os valores resgatados do Infisical:

```bash
npx wrangler hyperdrive create supletivo-prod-hyperdrive \
  --host="db.v7m.live" \
  --database="dmz" \
  --user="hyperdrive_ro" \
  --password="<SUA_SENHA_INFISICAL>" \
  --access-client-id="<CLIENT_ID>" \
  --access-client-secret="<CLIENT_SECRET>" \
  --max-age=60 \
  --swr=300
```

> **Atenção:** Ao utilizar autenticação sobre Access, as flags `--access-client-id` e `--access-client-secret` são usadas em conjunto com `--host`, `--database`, `--user` e `--password` (não use `--connection-string`).

O comando retornará o identificador da configuração:
```json
{
  "id": "e49f8721c0ef49738874836f4521abcd",
  "name": "supletivo-prod-hyperdrive"
}
```

---

### Passo 5: Adicionar o Binding ao Worker (`wrangler.jsonc`)

No Worker desejado (ex.: `c:\rep\app.supletivo.net.br\wrangler.jsonc`):

```jsonc
{
  "name": "app-supletivo-net-br",
  "compatibility_date": "2026-09-01",
  "compatibility_flags": ["nodejs_compat"],
  "hyperdrive": [
    {
      "binding": "HYPERDRIVE",
      "id": "e49f8721c0ef49738874836f4521abcd"
    }
  ]
}
```

---

### Passo 6: Consumo em Código (TypeScript)

Recomenda-se o driver moderno **`postgres` (Postgres.js)** (`npm i postgres`):

```typescript
import postgres from "postgres";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const sql = postgres(env.HYPERDRIVE.connectionString, {
      max: 5,
      fetch_types: false,
    });

    try {
      // Consulta com tagged template literals seguros
      const pricing = await sql`
        SELECT key, value 
        FROM core_platformsetting 
        WHERE key LIKE 'pricing_%'
      `;

      return Response.json({ success: true, data: pricing });
    } catch (err: any) {
      return Response.json({ success: false, error: err.message }, { status: 500 });
    }
  },
};
```
