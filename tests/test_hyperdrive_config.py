import os
from pathlib import Path
import yaml
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_cloudflare_tunnel_hyperdrive_ingress():
    config_path = REPO_ROOT / "deploy" / "cloudflare-tunnel" / "config.yml"
    assert config_path.exists(), "config.yml must exist"
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    ingress = data.get("ingress", [])
    assert len(ingress) > 0, "ingress rules must not be empty"
    
    db_routes = [
        rule for rule in ingress 
        if rule.get("hostname") == "db.v7m.live"
    ]
    assert len(db_routes) == 1, "Must have exactly 1 ingress route for db.v7m.live"
    assert "5432" in db_routes[0].get("service"), "Must point to PostgreSQL port 5432"

def test_hyperdrive_setup_sql_script():
    sql_path = REPO_ROOT / "deploy" / "hyperdrive" / "setup-user-ro.sql"
    assert sql_path.exists(), "setup-user-ro.sql must exist"
    content = sql_path.read_text(encoding="utf-8")
    
    assert "hyperdrive_ro" in content, "Must configure hyperdrive_ro role"
    assert "GRANT CONNECT ON DATABASE backend" in content, "Must grant connect to backend database"
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public" in content, "Must grant select on public tables"
    assert "REVOKE CREATE ON SCHEMA public" in content, "Must revoke create privilege for safety"

def test_hyperdrive_documentation():
    readme_path = REPO_ROOT / "deploy" / "hyperdrive" / "README.md"
    assert readme_path.exists(), "Hyperdrive README.md must exist"
    content = readme_path.read_text(encoding="utf-8")
    assert "db.v7m.live" in content
    assert "hyperdrive_ro" in content
    assert "d13fec466a424ac59c25399ee8628d4a" in content
    assert "supletivo-prod-hyperdrive" in content
