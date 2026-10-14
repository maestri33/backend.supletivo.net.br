"""Prepare an explicit overlay against the current Azure web image; never deploy."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "azureuser@20.127.0.185"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_production(names: list[str]) -> dict:
    encoded = base64.b64encode(json.dumps(names).encode()).decode()
    remote = """
import base64,hashlib,json,pathlib,subprocess,datetime
names=json.loads(base64.b64decode(PATHS))
def run(args):return subprocess.check_output(args,text=True).strip()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
out={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'containers':{},'host_files':{}}
host=pathlib.Path('/opt/v7m-platform/backend.supletivo.net.br')
for name in names:
 path=host/name
 assert path.resolve().is_relative_to(host.resolve())
 out['host_files'][name]=digest(path)
for name in ['v7m-backend-web','v7m-backend-qcluster']:
 d=json.loads(run(['docker','inspect',name]))[0]
 env=dict(x.split('=',1) for x in d['Config']['Env'])
 stable={k:v for k,v in env.items() if k not in {'APP_VERSION','RELEASE_ARTIFACT_SHA','RELEASE_SOURCE_COMMIT','RELEASE_BUILT_AT'}}
 out['containers'][name]={'image':d['Image'],'tag':d['Config']['Image'],'environment_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),'stable_environment_sha256':hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest(),'environment_names':sorted(env),'command':d['Config']['Cmd'],'compose_files':d['Config']['Labels'].get('com.docker.compose.project.config_files'),'mounts':[{'type':m['Type'],'source':m['Source'],'destination':m['Destination'],'rw':m['RW']} for m in d['Mounts']],'networks':sorted(d['NetworkSettings']['Networks'])}
print(json.dumps(out))
""".replace("PATHS", repr(encoded))
    result = subprocess.run([*SSH, "sudo -n python3 -"], input=remote, text=True, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError(f"Production inspection failed with exit {result.returncode}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--files-json", required=True, type=Path, help="JSON array of explicit repository-relative files")
    parser.add_argument("--requirements", help="Explicit hashed requirements file included in the overlay")
    parser.add_argument("--migration-target", action="append", help="Explicit app:NNNN migration target; default users:0043")
    args = parser.parse_args()
    migration_targets = []
    for target in args.migration_target or ["users:0043"]:
        if not re.fullmatch(r"[a-z_]+:[0-9]{4}", target):
            parser.error("Migration target must be app:NNNN")
        migration_targets.append(target.split(":"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", args.release):
        parser.error("Release must be a lowercase hyphenated identifier")
    if not re.fullmatch(r"0\.0\.0-sandbox\.\d+", args.version):
        parser.error("Use the actual global patch version provided by the release owner")
    names = json.loads(args.files_json.read_text(encoding="utf-8-sig"))
    if not isinstance(names, list) or not names or not all(isinstance(x, str) for x in names):
        parser.error("File list must be a nonempty JSON string array")
    names = sorted(set(names))
    if "api/health/router.py" not in names:
        parser.error("Explicitly include api/health/router.py for artifact identity")
    if args.requirements and args.requirements not in names:
        parser.error("Requirements file must be included in the explicit file list")
    sources = {}
    prohibited = {".env", ".release-secrets", "keys", "media", "data", ".git", ".venv", "node_modules", ".release-build"}
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or any(p in prohibited or p.startswith(".env") for p in path.parts):
            parser.error(f"Unsafe or credential-bearing path: {name}")
        source = ROOT / path
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            parser.error(f"Path escapes repository: {name}")
        data = source.read_bytes()
        if name.endswith(".py"):
            ast.parse(data, filename=name)
        sources[name] = data
    stage = ROOT / ".release-build" / args.release
    archive = stage.with_suffix(".tar.gz")
    if stage.exists() or archive.exists():
        parser.error("Release directory/archive already exists; choose a fresh release ID")
    baseline = inspect_production(names)
    web = baseline["containers"]["v7m-backend-web"]
    # A rollback may leave Config.Image as a local sha256 ID. Docker's FROM
    # interprets that ID as a registry repository, so use a pinned local alias.
    base_tag = "v7m-backend:overlay-base-" + web["image"].removeprefix("sha256:")[:16]
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    files = {name: {"sha256": sha256(data), "host_before_sha256": baseline["host_files"][name]} for name, data in sources.items()}
    identity = {"base_image": web["image"], "version": args.version, "files": {name: entry["sha256"] for name, entry in files.items()}}
    artifact_sha = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    manifest = {"release": args.release, "version": args.version, "artifact_sha256": artifact_sha, "source_commit": source_commit, "source_dirty": dirty, "prepared_at": datetime.now(timezone.utc).isoformat(), "base_image": web["image"], "base_tag": base_tag, "base_source_reference": web["tag"], "baseline": baseline, "files": files, "migration_policy": "explicit operator step; backup omitted only by owner-authorized test-data exception", "deployed": False}
    manifest["migration_targets"] = migration_targets
    stage.mkdir(parents=True)
    for name, data in sources.items():
        target = stage / "overrides" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dockerfile = f"""FROM {base_tag}
ARG APP_VERSION
ARG ARTIFACT_SHA
ARG SOURCE_COMMIT
ARG BUILT_AT
ENV APP_VERSION=$APP_VERSION RELEASE_ARTIFACT_SHA=$ARTIFACT_SHA RELEASE_SOURCE_COMMIT=$SOURCE_COMMIT RELEASE_BUILT_AT=$BUILT_AT
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT org.opencontainers.image.created=$BUILT_AT io.v7m.artifact.sha256=$ARTIFACT_SHA io.v7m.release.version=$APP_VERSION
COPY overrides/ /app/
"""
    if args.requirements:
        if not re.fullmatch(r"[a-zA-Z0-9_/.-]+\.txt", args.requirements):
            parser.error("Invalid requirements path")
        dockerfile += f"RUN uv pip install --python /venv/bin/python --no-deps --require-hashes -r /app/{args.requirements}\n"
    (stage / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (stage / ".dockerignore").write_text("*\n!Dockerfile\n!overrides/\n!overrides/**\n", encoding="utf-8")
    controller = Path(__file__).with_name("backend_overlay_remote.py")
    (stage / "release.py").write_bytes(controller.read_bytes())
    target_tag = f"v7m-backend:{args.release}"
    override = {"services": {name: {"image": target_tag, "pull_policy": "never"} for name in ("backend-web", "backend-qcluster")}}
    (stage / "compose.override.json").write_text(json.dumps(override, indent=2) + "\n", encoding="utf-8")
    rollback = {"services": {role: {"image": baseline["containers"][container]["image"], "pull_policy": "never"} for role, container in (("backend-web", "v7m-backend-web"), ("backend-qcluster", "v7m-backend-qcluster"))}}
    (stage / "compose.rollback.json").write_text(json.dumps(rollback, indent=2) + "\n", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(stage).as_posix())
    print(json.dumps({"release": args.release, "stage": str(stage), "archive": str(archive), "archive_sha256": sha256(archive.read_bytes()), "artifact_sha256": artifact_sha, "base_image": web["image"], "files": len(files), "remote_actions_executed": []}))


if __name__ == "__main__":
    main()
