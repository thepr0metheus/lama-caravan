#!/usr/bin/env bash
# install-llama.sh — build llama.cpp (CUDA) on this host and wire it into the
# scout's config.json (llamaServerBin + modelsBasePath).
#
# Can be run standalone on an already-provisioned agent:
#   ./scripts/install-llama.sh [--llama-tag b9101] [--install-dir DIR] [--no-restart]
#
# Or sourced by install.sh, which then calls install_llama().
#
# Idempotent: skips the build if llama-server already exists, and repairs
# config.json if llamaServerBin is missing or points at a vanished binary.

# ── shared helpers (safe to redefine when sourced) ───────────────────────────
# Guard with `declare -F` (function exists), NOT `command -v`: names like `info`
# collide with real system binaries (GNU texinfo), so `command -v info` would
# succeed and our function would never be defined.
__il_RED='\033[0;31m'; __il_GREEN='\033[0;32m'; __il_YELLOW='\033[1;33m'; __il_NC='\033[0m'
declare -F info       >/dev/null 2>&1 || info()       { echo -e "${__il_GREEN}[install]${__il_NC} $*"; }
declare -F warn       >/dev/null 2>&1 || warn()       { echo -e "${__il_YELLOW}[warn]${__il_NC}   $*"; }
declare -F err        >/dev/null 2>&1 || err()        { echo -e "${__il_RED}[error]${__il_NC}  $*" >&2; }
declare -F have       >/dev/null 2>&1 || have()       { command -v "$1" &>/dev/null; }
# nvidia-smi first; lspci without -q as the driverless fallback. `grep -q` closes the pipe at its first match, under `set -o pipefail` lspci dies of that, and a
# machine with two cards read "no NVIDIA GPU" and got no llama.cpp (2026-11-02).
declare -F is_nvidia  >/dev/null 2>&1 || is_nvidia()  { nvidia-smi -L >/dev/null 2>&1 || lspci 2>/dev/null | grep -i "nvidia" >/dev/null; }
declare -F nproc_safe >/dev/null 2>&1 || nproc_safe() { nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4; }

# install_llama [install_dir] [llama_dir] [llama_tag] [restart=1]
install_llama() {
  local install_dir="${1:-${HOME}/caravan-scout}"
  local llama_dir="${2:-${HOME}/llama.cpp}"
  local llama_tag="${3:-}"
  local restart="${4:-1}"
  local config_json="${install_dir}/config.json"

  if [[ "$(uname -s)" == "Darwin" ]]; then
    warn "macOS: build llama.cpp via Homebrew (brew install llama.cpp), then set"
    warn "llamaServerBin in ${config_json} manually."
    return 0
  fi

  if ! is_nvidia; then
    warn "No NVIDIA GPU detected — skipping llama.cpp build."
    return 0
  fi

  # CUDA installs itself under /usr/local/cuda, which a non-login shell's PATH
  # does not include: nvcc looked missing on a machine that had it, and the
  # toolkit was about to be installed a second time from apt.
  [[ -d /usr/local/cuda/bin ]] && export PATH="/usr/local/cuda/bin:${PATH}"

  local llama_bin="${llama_dir}/build/bin/llama-server"
  if [[ -f "$llama_bin" ]]; then
    # Built already: nothing to install, nothing to fetch. The checkout used to
    # move to the latest tag here while the binary stayed as it was — source
    # and binary of two different builds. Updating is the update job's work
    # (scripts/update-llama.sh), which rebuilds what it checks out.
    info "llama-server already built at $llama_bin — keeping it"
  else
    info "NVIDIA GPU detected — building llama.cpp with CUDA"

    # ── toolchain ──────────────────────────────────────────────────────────────
    if ! have nvcc; then
      info "Installing CUDA toolkit + build deps (nvidia-cuda-toolkit, cmake, build-essential, git)..."
      sudo apt-get update -qq
      sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git
    else
      have cmake || sudo apt-get install -y cmake build-essential git
    fi
    if ! have nvcc; then
      err "nvcc still not on PATH after install — cannot build CUDA llama.cpp."
      return 1
    fi

    # ── resolve tag ──────────────────────────────────────────────────────────────
    if [[ -z "$llama_tag" ]]; then
      info "Fetching latest llama.cpp release tag..."
      if have curl; then
        llama_tag=$(curl -fsSL "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" \
          | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || echo "")
      fi
      if [[ -z "$llama_tag" ]]; then
        llama_tag="master"
        warn "Could not fetch latest tag — using master branch"
      else
        info "  latest tag: $llama_tag"
      fi
    else
      info "Using pinned llama.cpp tag: $llama_tag"
    fi

    # ── clone / update ───────────────────────────────────────────────────────────
    if [[ -d "${llama_dir}/.git" ]]; then
      info "llama.cpp exists at ${llama_dir}, fetching..."
      git -C "$llama_dir" fetch --tags -q
      git -C "$llama_dir" checkout "$llama_tag" -q 2>/dev/null || \
        git -C "$llama_dir" checkout "tags/${llama_tag}" -q 2>/dev/null || \
        git -C "$llama_dir" checkout master -q
    else
      info "Cloning llama.cpp @ ${llama_tag}..."
      if [[ "$llama_tag" == "master" ]]; then
        git clone --depth 1 https://github.com/ggml-org/llama.cpp "$llama_dir"
      else
        git clone --depth 1 --branch "$llama_tag" \
          https://github.com/ggml-org/llama.cpp "$llama_dir"
      fi
    fi

    # ── build ────────────────────────────────────────────────────────────────────
    info "Building llama-server (first build ~10-20 min)..."
      cmake -S "$llama_dir" -B "${llama_dir}/build" \
        -DGGML_CUDA=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_SERVER=ON \
        -Wno-dev -DCMAKE_WARN_DEPRECATED=OFF
      cmake --build "${llama_dir}/build" \
        --config Release \
        --target llama-server \
        -j "$(nproc_safe)"
      info "Build complete: $llama_bin"
  fi  # built already
  if [[ ! -f "$llama_bin" ]]; then
    err "Build finished but $llama_bin is missing."
    return 1
  fi

  # ── wire into config.json (self-heal stale/missing llamaServerBin) ───────────
  local model_cache="${HOME}/llama-model-cache"
  mkdir -p "$model_cache"
  python3 - "$config_json" "$llama_bin" "$model_cache" <<'PYEOF'
import sys, json, os
path, bin_path, cache = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    c = json.load(open(path))
except FileNotFoundError:
    c = {}
changed = False
cur = (c.get("llamaServerBin") or "").strip()
# Set if empty, or if the configured binary no longer exists on disk.
if not cur or not os.path.isfile(cur):
    c["llamaServerBin"] = bin_path
    changed = True
    print(f"  set llamaServerBin={bin_path}")
if not (c.get("modelsBasePath") or "").strip():
    c["modelsBasePath"] = cache
    changed = True
    print(f"  set modelsBasePath={cache}")
if changed:
    json.dump(c, open(path, "w"), indent=2, ensure_ascii=False)
else:
    print("  config.json already has llamaServerBin + modelsBasePath")
PYEOF

  # ── restart the agent so it reloads config ───────────────────────────────────
  if [[ "$restart" == "1" ]] && have systemctl; then
    if systemctl --user cat caravan-scout.service >/dev/null 2>&1; then
      info "Restarting caravan-scout.service to pick up new config..."
      systemctl --user restart caravan-scout.service || \
        warn "Could not restart the service — restart it manually."
    fi
  fi

  info "llama.cpp ready: $llama_bin"
}

# ── standalone entrypoint ─────────────────────────────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  IL_INSTALL_DIR="${HOME}/caravan-scout"
  IL_LLAMA_DIR="${HOME}/llama.cpp"
  IL_TAG=""
  IL_RESTART=1
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --llama-tag)   IL_TAG="$2"; shift ;;
      --install-dir) IL_INSTALL_DIR="$2"; shift ;;
      --llama-dir)   IL_LLAMA_DIR="$2"; shift ;;
      --no-restart)  IL_RESTART=0 ;;
      -h|--help)
        grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) err "unknown arg: $1"; exit 1 ;;
    esac
    shift
  done
  install_llama "$IL_INSTALL_DIR" "$IL_LLAMA_DIR" "$IL_TAG" "$IL_RESTART"
fi
