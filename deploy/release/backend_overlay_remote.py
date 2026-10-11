"""Explicit operator actions for a staged backend overlay; no automatic migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

STAGE = Path(__file__).resolve().parent
BASE = Path("/opt/v7m-platform")
METADATA_KEYS = {"APP_VERSION", "RELEASE_ARTIFACT_SHA", "RELEASE_SOURCE_COMMIT", "RELEASE_BUILT_AT"}
OPERATOR_ENV: dict[str, str] = {}


def run(args: list[str], timeout: int = 90) -> str:
    result = subprocess.run(args, cwd=BASE, env=os.environ | OPERATOR_ENV, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # Compose config and process output can contain credentials. Never echo them.
        raise RuntimeError(f"Operation {args[0]} failed with exit {result.returncode}; inspect sanitized logs separately")
    return result.stdout.strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_environment(env: dict[str, str]) -> str:
    return digest(json.dumps({k: v for k, v in env.items() if k not in METADATA_KEYS}, sort_keys=True).encode())


def inspect(name: str) -> tuple[dict, dict]:
    obj = json.loads(run(["docker", "inspect", name]))[0]
    return obj, dict(x.split("=", 1) for x in obj["Config"]["Env"])


def baseline_guard(manifest: dict) -> None:
    for name, expected in manifest["baseline"]["containers"].items():
        obj, env = inspect(name)
        if obj["Image"] != expected["image"]:
            raise RuntimeError(f"Running image changed since preparation: {name}")
        if digest(json.dumps(env, sort_keys=True).encode()) != expected["environment_sha256"]:
            raise RuntimeError(f"Runtime environment changed since preparation: {name}")
        mounts = [{"type": m["Type"], "source": m["Source"], "destination": m["Destination"], "rw": m["RW"]} for m in obj["Mounts"]]
        if mounts != expected["mounts"] or obj["Config"]["Cmd"] != expected["command"]:
            raise RuntimeError(f"Runtime volumes or command changed: {name}")


def verify_payload(manifest: dict) -> None:
    for name, entry in manifest["files"].items():
        source = STAGE / "overrides" / name
        if not source.resolve().is_relative_to((STAGE / "overrides").resolve()):
            raise RuntimeError("Payload path escapes release")
        if digest(source.read_bytes()) != entry["sha256"]:
            raise RuntimeError(f"Payload changed after preparation: {name}")


def compose(file: str) -> list[str]:
    return ["docker", "compose", "-f", str(BASE / "docker-compose.yml"), "-f", str(STAGE / file)]


def configuration_guard(manifest: dict, image: str) -> None:
    configuration = json.loads(run([*compose("compose.override.json"), "config", "--format", "json"]))
    inherited = dict(x.split("=", 1) for x in json.loads(run(["docker", "image", "inspect", image]))[0]["Config"]["Env"])
    for service, container in (("backend-web", "v7m-backend-web"), ("backend-qcluster", "v7m-backend-qcluster")):
        _, current = inspect(container)
        effective = inherited | configuration["services"][service].get("environment", {})
        if stable_environment(effective) != stable_environment(current):
            raise RuntimeError(f"Compose would change established runtime credentials/configuration: {service}")


def verify_running(manifest: dict, image: str) -> None:
    for name, expected in manifest["baseline"]["containers"].items():
        obj, env = inspect(name)
        if obj["Image"] != image or not obj["State"]["Running"]:
            raise RuntimeError(f"Expected release is not running: {name}")
        mounts = [{"type": m["Type"], "source": m["Source"], "destination": m["Destination"], "rw": m["RW"]} for m in obj["Mounts"]]
        if mounts != expected["mounts"] or obj["Config"]["Cmd"] != expected["command"] or sorted(obj["NetworkSettings"]["Networks"]) != expected["networks"]:
            raise RuntimeError(f"Runtime wiring changed: {name}")
        stable = {k: v for k, v in env.items() if k not in METADATA_KEYS}
        expected_stable = expected.get("stable_environment_sha256", expected["environment_sha256"])
        if digest(json.dumps(stable, sort_keys=True).encode()) != expected_stable:
            raise RuntimeError(f"Runtime configuration changed: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "build", "preflight", "migrate", "promote", "rollback"))
    parser.add_argument("--expected-artifact", help="Exact artifact SHA from the reviewed manifest")
    args = parser.parse_args()
    manifest = json.loads((STAGE / "manifest.json").read_text())
    # Compose interpolates the established PEMs. Read them from the running web
    # process in memory instead of losing them when invoked in a new SSH shell.
    _, live_environment = inspect("v7m-backend-web")
    OPERATOR_ENV.update({key: live_environment[key] for key in ("JWT_PRIVATE_KEY_PEM", "JWT_PUBLIC_KEY_PEM") if key in live_environment})
    if args.action != "inspect" and args.expected_artifact != manifest["artifact_sha256"]:
        parser.error("Supply the reviewed artifact SHA explicitly")
    target = "v7m-backend:" + manifest["release"]
    verify_payload(manifest)
    if args.action == "inspect":
        baseline_guard(manifest)
        print(json.dumps({"release": manifest["release"], "artifact_sha256": manifest["artifact_sha256"], "baseline_unchanged": True, "migration_policy": manifest["migration_policy"]}))
        return
    if args.action == "rollback":
        run([*compose("compose.rollback.json"), "up", "-d", "--no-deps", "--no-build", "backend-web", "backend-qcluster"], timeout=120)
        for name, expected in manifest["baseline"]["containers"].items():
            obj, _ = inspect(name)
            if obj["Image"] != expected["image"]:
                raise RuntimeError(f"Rollback image mismatch: {name}")
        print(json.dumps({"release": manifest["release"], "rolled_back_code": True, "database_rollback": False}))
        return
    baseline_guard(manifest)
    if args.action == "build":
        if json.loads(run(["docker", "image", "inspect", manifest["base_tag"]]))[0]["Id"] != manifest["base_image"]:
            raise RuntimeError("Base image tag no longer matches frozen digest")
        built_at = datetime.now(timezone.utc).isoformat()
        command = ["docker", "build", "--pull=false", "-t", target]
        for key, value in {"APP_VERSION": manifest["version"], "ARTIFACT_SHA": manifest["artifact_sha256"], "SOURCE_COMMIT": manifest["source_commit"], "BUILT_AT": built_at}.items():
            command += ["--build-arg", key + "=" + value]
        run(command + [str(STAGE)], timeout=240)
        image = json.loads(run(["docker", "image", "inspect", target]))[0]["Id"]
        record = {"image": image, "artifact_sha256": manifest["artifact_sha256"], "built_at": built_at, "deployed": False}
        (STAGE / "build-result.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record))
        return
    record = json.loads((STAGE / "build-result.json").read_text())
    image = json.loads(run(["docker", "image", "inspect", target]))[0]["Id"]
    if image != record["image"] or record["artifact_sha256"] != manifest["artifact_sha256"]:
        raise RuntimeError("Built artifact changed")
    configuration_guard(manifest, image)
    if args.action == "preflight":
        run([*compose("compose.override.json"), "run", "--rm", "--no-deps", "backend-web", "python", "manage.py", "check"], timeout=90)
        plan = run([*compose("compose.override.json"), "run", "--rm", "--no-deps", "backend-web", "python", "manage.py", "migrate", "--plan"], timeout=90)
        print(json.dumps({"release": manifest["release"], "check_passed": True, "migration_plan": plan, "migrations_applied": False}))
        return
    if args.action == "migrate":
        backup = STAGE / "database-before-migration.dump"
        if backup.exists():
            raise RuntimeError("Backup already exists; inspect the earlier migration action")
        with backup.open("xb") as output:
            result = subprocess.run(["docker", "exec", "v7m-postgres", "sh", "-c", 'pg_dump -U "$POSTGRES_USER" -d supletivo_backend -Fc'], stdout=output, stderr=subprocess.PIPE, timeout=120)
        if result.returncode or backup.stat().st_size < 1000:
            raise RuntimeError("Database backup failed; migration was not started")
        run([*compose("compose.override.json"), "run", "--rm", "--no-deps", "backend-web", "python", "manage.py", "migrate", "users", "0043", "--noinput"], timeout=120)
        record = {"backup_file": backup.name, "backup_bytes": backup.stat().st_size, "backup_sha256": digest(backup.read_bytes()), "migration": "users.0043_checkout_paid_at", "applied_at": datetime.now(timezone.utc).isoformat(), "restore_tested": False}
        (STAGE / "migration-result.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record))
        return
    # Applying migrations is a separate, explicit operator action after a backup.
    no_pending = "from django.db import connections; from django.db.migrations.executor import MigrationExecutor; e=MigrationExecutor(connections['default']); assert not e.migration_plan(e.loader.graph.leaf_nodes()), 'Unapplied migrations block promotion'"
    run([*compose("compose.override.json"), "run", "--rm", "--no-deps", "backend-web", "python", "manage.py", "shell", "-c", no_pending], timeout=90)
    try:
        run([*compose("compose.override.json"), "up", "-d", "--no-deps", "--no-build", "backend-web", "backend-qcluster"], timeout=120)
        verify_running(manifest, image)
        health = None
        probe = "import json,urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/healthz',timeout=5).read().decode())"
        for attempt in range(10):
            try:
                health = json.loads(run(["docker", "exec", "v7m-backend-web", "python", "-c", probe], timeout=8))
                if health.get("db") is True and health.get("migrations_pending") == 0 and health.get("sha") == manifest["artifact_sha256"] and health.get("version") == manifest["version"] and health.get("built_at") == record["built_at"]:
                    break
            except (RuntimeError, json.JSONDecodeError):
                pass
            time.sleep(3)
        else:
            raise RuntimeError("Origin health did not identify the expected artifact")
        record.update({"deployed": True, "health": health, "promoted_at": datetime.now(timezone.utc).isoformat()})
        (STAGE / "build-result.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record))
    except Exception:
        run([*compose("compose.rollback.json"), "up", "-d", "--no-deps", "--no-build", "backend-web", "backend-qcluster"], timeout=120)
        raise


if __name__ == "__main__":
    os.umask(0o077)
    main()
