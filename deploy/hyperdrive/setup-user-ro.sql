-- ==============================================================================
-- Script de Provisionamento de Usuário Read-Only para Cloudflare Hyperdrive
-- Executado no PostgreSQL 16 (pve-v7m / CT 150 v7m-core / base 'backend')
-- ==============================================================================

-- 1. Criação da Role com senha segura
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hyperdrive_ro') THEN
        CREATE ROLE hyperdrive_ro WITH LOGIN PASSWORD '<SENHA_FORTE_INFISICAL>';
    ELSE
        ALTER ROLE hyperdrive_ro WITH PASSWORD '<SENHA_FORTE_INFISICAL>';
    END IF;
END
$$;

-- 2. Concessão de conexão estritamente à base de produção 'backend'
GRANT CONNECT ON DATABASE backend TO hyperdrive_ro;

-- 3. Permissão de leitura no schema public
GRANT USAGE ON SCHEMA public TO hyperdrive_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO hyperdrive_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO hyperdrive_ro;

-- 4. Garantir que novas tabelas criadas pelo Django ORM em migrações futuras herdem SELECT
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hyperdrive_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO hyperdrive_ro;

-- 5. Revogação de permissões perigosas (Defesa em Profundidade)
REVOKE CREATE ON SCHEMA public FROM hyperdrive_ro;
