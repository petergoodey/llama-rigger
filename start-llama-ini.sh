#!/usr/bin/env bash
# ===========================================================================
#  start-llama-ini.sh - start llama-server (router mode) from a preset .ini
#  Linux / macOS twin of start-llama-ini.cmd; same lookup, same env vars.
#
#  Usage:  ./start-llama-ini.sh [preset.ini] [--dry-run] [extra args...]
#
#    <preset.ini>  OPTIONAL. Defaults to $LLAMA_PRESET, else local/models.ini,
#                  else models.example.ini; used when it is omitted or the first
#                  argument starts with "-". A bare name is also looked up in
#                  local/ and next to this script, ".ini" optional:
#                    ./start-llama-ini.sh models
#    --here        accepted for compatibility with the .cmd (always runs here)
#    --dry-run     print the command line and exit
#    extra args    passed to llama-server AFTER the defaults, so they win.
#
#  Defaults: --host 127.0.0.1 --port 9931. Models auto-unload: with
#  LLAMA_MODELS_MEMORY_MARGIN set, --models-memory-margin N --models-max 0 (evict
#  least-recently-used models by memory); without it, --models-max 1 (one model
#  at a time; requesting another swaps it in).
#  Override with env vars LLAMA_HOST / LLAMA_PORT / LLAMA_MODELS_MAX /
#  LLAMA_MODELS_MEMORY_MARGIN, per session or in local/env.sh (sourced if present).
#  Run it in the background with:  nohup ./start-llama-ini.sh > router.log 2>&1 &
# ===========================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { echo "[start-llama-ini] $*" >&2; }

usage() {
    sed -n '3,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  Presets found:"
    for f in "$DIR"/local/*.ini "$DIR"/*.ini; do [ -f "$f" ] && echo "    $f"; done
    exit 0
}
case "${1:-}" in -h|--help) usage ;; esac

# ---- machine defaults (session env vars win if env.sh uses ${VAR:-default}) --
# shellcheck disable=SC1091
[ -f "$DIR/local/env.sh" ] && . "$DIR/local/env.sh"

# ---- resolve the ini --------------------------------------------------------
first_file() { for f in "$@"; do [ -f "$f" ] && { echo "$f"; return 0; }; done; return 1; }

FIRST="${1:-}"
if [ -z "$FIRST" ] || [ "${FIRST:0:1}" = "-" ]; then
    if [ -n "${LLAMA_PRESET:-}" ]; then
        INI="$LLAMA_PRESET"     # set but missing is an error below, never a silent fallback
    else
        INI="$(first_file "$DIR/local/models.ini" "$DIR/models.example.ini" \
               || echo "$DIR/local/models.ini")"
    fi
else
    shift
    # files only: a bare "models" must find local/models.ini, not the models/ folder
    INI="$(first_file "$FIRST" "$DIR/local/$FIRST.ini" "$DIR/local/$FIRST" \
                      "$DIR/$FIRST.ini" "$DIR/$FIRST" || echo "$FIRST")"
fi
if [ -d "$INI" ]; then
    say "ERROR: $INI is a folder, not a preset .ini"
    exit 1
fi
if [ ! -f "$INI" ]; then
    say "ERROR: preset not found: $INI"
    say "       Copy models.example.ini to local/models.ini and edit it,"
    say "       or pass a preset path / set LLAMA_PRESET."
    exit 1
fi
INI="$(cd "$(dirname "$INI")" && pwd)/$(basename "$INI")"

# ---- defaults (env overrides) -----------------------------------------------
LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
LLAMA_PORT="${LLAMA_PORT:-9931}"
# Auto-unload needs a limit: llama-server's own margin default is 0 (disabled).
# With a margin, evict by memory; without one, keep one model at a time.
if [ -n "${LLAMA_MODELS_MEMORY_MARGIN:-}" ]; then LLAMA_MODELS_MAX="${LLAMA_MODELS_MAX:-0}"
else LLAMA_MODELS_MAX="${LLAMA_MODELS_MAX:-1}"; fi

# ---- remaining args ---------------------------------------------------------
DRY=0
EXTRA=()
for a in "$@"; do
    case "$a" in
        --here) ;;
        --dry-run) DRY=1 ;;
        *) EXTRA+=("$a") ;;
    esac
done

CMD=(llama-server --models-preset "$INI" --host "$LLAMA_HOST" --port "$LLAMA_PORT"
     --models-max "$LLAMA_MODELS_MAX")
[ -n "${LLAMA_MODELS_MEMORY_MARGIN:-}" ] && CMD+=(--models-memory-margin "$LLAMA_MODELS_MEMORY_MARGIN")
CMD+=("${EXTRA[@]+"${EXTRA[@]}"}")

if [ "$DRY" = 1 ]; then
    printf '%q ' "${CMD[@]}"; echo
    exit 0
fi

# ---- sanity checks ----------------------------------------------------------
command -v llama-server >/dev/null 2>&1 || {
    say "ERROR: llama-server not on PATH (brew install llama.cpp, or build from source)."
    exit 1
}
if (exec 3<>"/dev/tcp/127.0.0.1/$LLAMA_PORT") 2>/dev/null; then
    say "ERROR: port $LLAMA_PORT is already in use - is a server already running?"
    say "       Stop it, or pass --port N / set LLAMA_PORT=N."
    exit 1
fi

say "$(printf '%q ' "${CMD[@]}")"
exec "${CMD[@]}"
