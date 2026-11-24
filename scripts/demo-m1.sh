#!/usr/bin/env bash
# M1a + M1b demo (docs/12 M1a/M1b "실행 결과"), entirely inside a fresh sandbox.
# Usage (from the repository root): scripts/demo-m1.sh
# Exits 0 only if every step behaves as 12 says. The sandbox is removed at the end.
set -euo pipefail

cd "$(dirname "$0")/../core"
DAYCLOSE_SANDBOX="$(mktemp -d)"
export DAYCLOSE_SANDBOX DAYCLOSE_HOME="$DAYCLOSE_SANDBOX/home"
trap 'rm -rf "$DAYCLOSE_SANDBOX"' EXIT
touch "$DAYCLOSE_SANDBOX/.dayclose-sandbox"
mkdir -p "$DAYCLOSE_SANDBOX/user/Downloads"

# check <exit code> <python expression over `e` (the envelope)> -- command...
check() {
  local want="$1" expr="$2"
  shift 2
  local out rc=0
  out="$("$@")" || rc=$?
  printf '%s\n' "$out"
  if [ "$rc" -ne "$want" ]; then
    echo "demo: expected exit $want, got $rc: $*" >&2
    exit 1
  fi
  ENVELOPE="$out" uv run python -c \
    "import json, os; e = json.loads(os.environ['ENVELOPE']); assert $expr, e" \
    || { echo "demo: check failed: $expr" >&2; exit 1; }
}

# --- M1a
check 0 'e["ok"]' uv run dayclose init --no-default-roots --json
check 0 'e["data"]["created"]' \
  uv run dayclose root add "$DAYCLOSE_SANDBOX/user/Downloads" --kind downloads --json
check 0 'e["data"]["total"] == 1' uv run dayclose root list --json
check 0 'e["data"]["healthy"]' uv run dayclose doctor --json
check 5 'e["error"]["code"] == "E_SANDBOX_VIOLATION"' \
  env DAYCLOSE_SANDBOX="$HOME" uv run dayclose version --json

# --- M1b
check 0 'e["data"]["status"] == "completed"' uv run dayclose scan run --json
echo hi > "$DAYCLOSE_SANDBOX/user/Downloads/a.txt"
check 0 'e["data"]["stats"]["created"] == 1' uv run dayclose scan run --json
mv "$DAYCLOSE_SANDBOX/user/Downloads/a.txt" "$DAYCLOSE_SANDBOX/user/Downloads/b.txt"
check 0 'e["data"]["stats"]["moved"] == 1' uv run dayclose scan run --json
check 0 '[i["event"] for i in e["data"]["items"]] == ["moved"]' \
  uv run dayclose change list --json
echo "demo-m1: ok"
