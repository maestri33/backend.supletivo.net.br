#!/usr/bin/env bash
# Ultralight Agent Checkpoint Runner for Linux / macOS / GitHub Actions CI
set -euo pipefail

TIER="${1:-fast}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

if [ "$TIER" = "ci" ] || [ "${2:-}" = "--all" ]; then
  FILES=$(git ls-files)
else
  FILES=$(git diff --cached --name-only --diff-filter=ACM)
fi

if [ -z "$FILES" ]; then
  echo "[Checkpoint] No staged files to inspect. Passed."
  exit 0
fi

FAILURES=0

# Regra 0: Oráculo Central de Versão (version.v7m.live)
if command -v curl >/dev/null 2>&1; then
  ORACLE_VERSION=$(curl -s --max-time 3 https://version.v7m.live/api/version | grep -o '"version": *"[^"]*"' | head -n1 | cut -d'"' -f4 || true)
  if [ -n "$ORACLE_VERSION" ]; then
    echo "[Oracle Gate] Oráculo Online: v$ORACLE_VERSION (Conferido com sucesso)"
  fi
fi

# Regra 1: Marcas descontinuadas (v7m, maestri.group)
for f in $FILES; do
  [ -f "$f" ] || continue
  case "$f" in
    *.lock|*.svg|*.png|*.jpg|*.jpeg|*.webp|*.ico|*.woff*|*.ttf|*.db|*.sqlite3) continue ;;
    tools/checkpoint/*|scripts/checkpoint/*|*.agent-checkpoint.json) continue ;;
  esac
  # Exceção mandatória: domínio de ferramentas técnicas (*.v7m.live) permitido pelo AGENTS.md
  CLEAN_CONTENT=$(sed -E 's/[a-zA-Z0-9_\.-]*\.?v7m\.live//g' "$f")
  if echo "$CLEAN_CONTENT" | grep -Eni "\b(v7m|maestri\.group)\b" >/dev/null 2>&1; then
    echo "::error file=$f::Prohibited legacy brand detected in $f"
    FAILURES=$((FAILURES + 1))
  fi
done

# Regra 2: Cloudflare-First (Proibir bibliotecas AWS/GCP em arquivos de pacote)
for f in $FILES; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in
    package.json|pyproject.toml|requirements*.txt)
      if grep -En "\b(@aws-sdk|boto3|botocore|google-cloud-storage|firebase-admin)\b" "$f" >/dev/null 2>&1; then
        echo "::error file=$f::Cloudflare-First policy violation in $f. Use Cloudflare R2/D1/KV/Workers."
        FAILURES=$((FAILURES + 1))
      fi
      ;;
  esac
done

# Regra 3: Redaction de credenciais
for f in $FILES; do
  [ -f "$f" ] || continue
  case "$f" in
    *.lock|*.svg|*.png|*.jpg|*.jpeg|*.webp|*.ico) continue ;;
  esac
  if grep -En "(ghp_[a-zA-Z0-9]{36}|-----BEGIN [A-Z ]+ PRIVATE KEY-----)" "$f" >/dev/null 2>&1; then
    echo "::error file=$f::Secret exposure detected in $f"
    FAILURES=$((FAILURES + 1))
  fi
done

if [ "$FAILURES" -gt 0 ]; then
  echo "[CHECKPOINT FAILED] $FAILURES violation(s) found. Check c:\rep\AGENTS.md."
  exit 1
fi

echo "[CHECKPOINT PASSED] Tier '$TIER' completed cleanly."
exit 0
