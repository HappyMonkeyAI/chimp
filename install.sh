#!/usr/bin/env bash
# Install chimp (local OpenAI-compatible VRAM-sticky router).
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/HappyMonkeyAI/chimp/main/install.sh | bash
#
# From a clone:
#   ./install.sh
#
# Options / env:
#   --dir PATH | CHIMP_HOME   Install directory (default: ~/chimp, or cwd if already a checkout)
#   --dev      | CHIMP_DEV=1  Also install pytest extras
#   CHIMP_REPO, CHIMP_REF
set -euo pipefail

REPO_URL="${CHIMP_REPO:-https://github.com/HappyMonkeyAI/chimp.git}"
REF="${CHIMP_REF:-main}"
WANT_DEV=0
DIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      DIR_OVERRIDE="${2:?--dir needs a path}"
      shift 2
      ;;
    --dev)
      WANT_DEV=1
      shift
      ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "ERR unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "${CHIMP_DEV:-}" == "1" ]]; then
  WANT_DEV=1
fi

step() { printf '==> %s\n' "$*"; }
ok() { printf 'OK  %s\n' "$*"; }
fail() { printf 'ERR %s\n' "$*" >&2; exit 1; }

is_chimp_root() {
  local path="$1"
  [[ -f "$path/pyproject.toml" ]] || return 1
  grep -qE '^name[[:space:]]*=[[:space:]]*"chimp"' "$path/pyproject.toml"
}

find_python() {
  local cand
  for cand in python3.12 python3.11 python3 python; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

install_root() {
  if [[ -n "$DIR_OVERRIDE" ]]; then
    cd "$(dirname "$DIR_OVERRIDE")" && echo "$(pwd -P)/$(basename "$DIR_OVERRIDE")"
    return
  fi
  if [[ -n "${CHIMP_HOME:-}" ]]; then
    cd "$(dirname "$CHIMP_HOME")" && echo "$(pwd -P)/$(basename "$CHIMP_HOME")"
    return
  fi
  if is_chimp_root "$PWD"; then
    pwd -P
    return
  fi
  echo "$HOME/chimp"
}

sync_repo() {
  local root="$1"
  if is_chimp_root "$root"; then
    step "Using existing checkout at $root"
    if command -v git >/dev/null 2>&1; then
      (
        cd "$root"
        git fetch --depth 1 origin "$REF" >/dev/null 2>&1 || true
        git checkout "$REF" >/dev/null 2>&1 || true
        git pull --ff-only origin "$REF" >/dev/null 2>&1 || true
      )
    fi
    return
  fi

  if [[ -e "$root" ]] && [[ -n "$(ls -A "$root" 2>/dev/null || true)" ]]; then
    fail "Directory exists and is not a chimp checkout: $root (set --dir / CHIMP_HOME)"
  fi
  mkdir -p "$root"

  if command -v git >/dev/null 2>&1; then
    step "Cloning $REPO_URL ($REF) -> $root"
    local tmp
    tmp="$(mktemp -d)"
    git clone --branch "$REF" --depth 1 "$REPO_URL" "$tmp/repo"
    # shellcheck disable=SC2086
    shopt -s dotglob nullglob
    mv "$tmp/repo"/* "$root"/
    shopt -u dotglob nullglob
    rm -rf "$tmp"
    return
  fi

  step "git not found; downloading zipball"
  command -v curl >/dev/null 2>&1 || fail "Need git or curl to fetch the repo"
  command -v unzip >/dev/null 2>&1 || fail "Need unzip to extract the zipball"
  local owner=HappyMonkeyAI name=chimp
  if [[ "$REPO_URL" =~ github.com[:/]([^/]+)/([^/.]+) ]]; then
    owner="${BASH_REMATCH[1]}"
    name="${BASH_REMATCH[2]}"
  fi
  local zip tmp
  zip="$(mktemp)"
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/${owner}/${name}/archive/refs/heads/${REF}.zip" -o "$zip"
  unzip -q "$zip" -d "$tmp"
  local inner
  inner="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  [[ -n "$inner" ]] || fail "Zipball extract failed"
  shopt -s dotglob nullglob
  mv "$inner"/* "$root"/
  shopt -u dotglob nullglob
  rm -rf "$zip" "$tmp"
}

ROOT="$(install_root)"
step "Install root: $ROOT"

step "Checking Python >= 3.11"
PY="$(find_python)" || fail "Python 3.11+ not found. Install python3.11+ and re-run."
ok "Python $($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])') via $PY"

# venv module
"$PY" -c 'import venv' 2>/dev/null || fail "Python venv module missing (try: apt install python3-venv)"

sync_repo "$ROOT"
is_chimp_root "$ROOT" || fail "Not a chimp project after sync: $ROOT"

VENV="$ROOT/.venv"
VENV_PY="$VENV/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  step "Creating venv"
  "$PY" -m venv "$VENV"
else
  step "Reusing venv at $VENV"
fi

step "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip

SPEC="."
if [[ "$WANT_DEV" -eq 1 ]]; then
  SPEC=".[dev]"
fi
step "Installing chimp ($SPEC)"
(
  cd "$ROOT"
  "$VENV_PY" -m pip install -e "$SPEC"
)

CONFIG="$ROOT/config.yaml"
EXAMPLE="$ROOT/config.example.yaml"
if [[ ! -f "$CONFIG" ]]; then
  step "Creating config.yaml from example"
  cp "$EXAMPLE" "$CONFIG"
  ok "Edit $CONFIG with your endpoint URLs"
else
  ok "Keeping existing config.yaml"
fi

step "Verifying dependencies and config load"
"$VENV_PY" - <<PY
import importlib.util, sys
from pathlib import Path
missing = [m for m in ("chimp", "httpx", "yaml", "starlette", "uvicorn") if importlib.util.find_spec(m) is None]
if missing:
    print("missing modules:", ", ".join(missing))
    sys.exit(1)
from chimp.config import load_settings
load_settings(Path("$EXAMPLE"))
print("ok")
PY

CHIMP_BIN="$VENV/bin/chimp"
[[ -x "$CHIMP_BIN" ]] || fail "Console script missing: $CHIMP_BIN"
ok "chimp entrypoint ready"

printf '\n'
printf 'chimp installed.\n'
printf '  1. Edit endpoints:  %s\n' "$CONFIG"
printf '  2. Start router:    %s\n' "$CHIMP_BIN"
printf '  3. Point clients at http://127.0.0.1:8787/v1\n'
printf '  Status:             http://127.0.0.1:8787/status\n'
