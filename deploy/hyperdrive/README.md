# Guia de Operação: Cloudflare Hyperdrive com PostgreSQL

Este documento descreve a integração da infraestrutura de produção do **PostgreSQL 16** (Host Proxmox `pve-v7m`, CT 150 `v7m-core`, container Docker `v7m-postgres`) com o **Cloudflare Hyperdrive** para acelerar leituras nos Workers da Cloudflare (`app`, `admin`, `notify-edge`).

---

## 1. Topologia de Rede & Fluxo de Borda

```
[ Cloudflare Worker na Borda ] 
       │ (TCP / TLSv1.3 Seguro)
       ▼
[ Cloudflare Hyperdrive ] (ID: d13fec466a424ac59c25399ee8628d4a)
       │ (Pooling global + Edge Query Caching: max-age=60s, swr=300s)
       ▼
[ Hostname: db.v7m.live:5432 ] (IP Público: 51.79.77.31 / pve-v7m)
       │ (DNAT iptables em vmbr0)
       ▼
[ LAN Física / Bridge vmbr1: 10.0.1.50:5432 ] (CT 150 v7m-core)
       │ (Docker network v7m-core)
       ▼
[ PostgreSQL 16 — v7m-postgres ] (Base de Produção: 'backend')
```

* **Hostname Canônico:** `db.v7m.live` (Respeitando a Regra 5: domínios `*.v7m.live` para ferramentas e utilitários técnicos).
* **Porta:** `5432` (Criptografia TLSv1.3 obrigatória ativada).
* **Base Oficial:** `backend` (Owner: `backend`).
* **Usuário Read-Only:** `hyperdrive_ro`.
* **Config ID no Cloudflare:** `d13fec466a424ac59c25399ee8628d4a`.

---

## 2. Passo a Passo Executado & Verificado

### Passo 1: Regra de Roteamento TCP no Host Proxmox (`pve-v7m`)
Adicionada regra de DNAT no `iptables` e persistida em `/etc/network/interfaces`:

```bash
# Encaminhamento da porta 5432 para o container interno
iptables -t nat -A PREROUTING -d 51.79.77.31/32 -i vmbr0 -p tcp --dport 5432 -j DNAT --to-destination 10.0.1.50:5432
```

### Passo 2: Habilitação de SSL/TLS no PostgreSQL
O Cloudflare Hyperdrive exige obrigatoriamente criptografia SSL/TLS (`code: 2012`).
Gerados certificados RSA 2048 (`server.crt` e `server.key`) em `/var/lib/postgresql/data` e ativado no `postgresql.auto.conf`:

```sql
ALTER SYSTEM SET ssl = 'on';
ALTER SYSTEM SET ssl_cert_file = 'server.crt';
ALTER SYSTEM SET ssl_key_file = 'server.key';
```
*Status verificado:* `TLSv1.3` com cifra `TLS_AES_256_GCM_SHA384`.

### Passo 3: Provisionamento da Role Read-Only (`hyperdrive_ro`)
Executado script `deploy/hyperdrive/setup-user-ro.sql` na base `backend`:
- Permissão `CONNECT` na base `backend`.
- Permissão `SELECT` no schema `public`.
- Bloqueio de criação (`REVOKE CREATE ON SCHEMA public FROM hyperdrive_ro`).

### Passo 4: Criação do Hyperdrive Config no Cloudflare
Criado via Wrangler CLI:

```bash
npx wrangler hyperdrive create supletivo-prod-hyperdrive \
  --origin-host="db.v7m.live" \
  --origin-port=5432 \
  --origin-user="hyperdrive_ro" \
  --origin-password="<SENHA>" \
  --database="backend" \
  --max-age=60 \
  --swr=300
```

Retorno oficial do Cloudflare:
```json
{
  "id": "d13fec466a424ac59c25399ee8628d4a",
  "name": "supletivo-prod-hyperdrive",
  "origin": {
    "host": "db.v7m.live",
    "port": 5432,
    "database": "backend",
    "scheme": "postgresql",
    "user": "hyperdrive_ro"
  },
  "origin_connection_limit": 60,
  "caching": {
    "disabled": false,
    "stale_while_revalidate": 300
  }
}
```

---

## 3. Como Vincular a Qualquer Worker (`wrangler.jsonc`)

Adicione o binding no `wrangler.jsonc` do Worker:

```jsonc
{
  "hyperdrive": [
    {
      "binding": "HYPERDRIVE",
      "id": "d13fec466a424ac59c25399ee8628d4a"
    }
  ]
}
```

---

## 4. Consumo em Código (TypeScript)

Utilize o driver moderno **`postgres` (Postgres.js)**:

```typescript
import postgres from "postgres";

export interface Env {
  HYPERDRIVE: {
    connectionString: string;
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const sql = postgres(env.HYPERDRIVE.connectionString, {
      max: 5,
      fetch_types: false,
    });

    try {
      const settings = await sql`
        SELECT key, value 
        FROM core_platformsetting 
        WHERE key LIKE 'pricing_%'
      `;

      return Response.json({ success: true, data: settings });
    } catch (err: any) {
      return Response.json({ success: false, error: err.message }, { status: 500 });
    }
  },
};
```

*Prova empírica de teste na borda:*
```json
{
  "success": true,
  "message": "Cloudflare Hyperdrive is fully working and connected to PostgreSQL!",
  "data": {
    "database": "backend",
    "user": "hyperdrive_ro",
    "total_settings": 25
  }
}
```
