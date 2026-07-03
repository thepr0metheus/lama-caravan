#!/usr/bin/env bash
# install-llama.sh — build llama.cpp (CUDA) for lama-caravan.
#
# Usage:
#   ./scripts/install-llama.sh [--llama-tag b9101] [--llama-dir DIR] [--force] [--no-restart]
#
# Idempotent: skips the build if llama-server already exists.
# Use --force to rebuild even if the binary is present.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-llama]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

# ── defaults ──────────────────────────────────────────────────────────────────
LLAMA_DIR="${HOME}/llama.cpp"
LLAMA_TAG=""
FORCE=0
RESTART=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --llama-tag)   LLAMA_TAG="$2"; shift ;;
    --llama-dir)   LLAMA_DIR="$2"; shift ;;
    --force)       FORCE=1 ;;
    --no-restart)  RESTART=0 ;;
    -h|--help)
      sed -n '/^#/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) err "unknown arg: $1"; exit 1 ;;
  esac
  shift
done

# ── platform checks ───────────────────────────────────────────────────────────
if [[ "$(uname -s)" == "Darwin" ]]; then
  warn "macOS: install llama.cpp via Homebrew: brew install llama.cpp"
  warn "Then ensure ~/llama.cpp/build/bin/llama-server exists or set LLAMA_HOME."
  exit 0
fi

if ! lspci 2>/dev/null | grep -qi "nvidia"; then
  warn "No NVIDIA GPU detected — skipping llama.cpp build."
  exit 0
fi

# ── toolchain ─────────────────────────────────────────────────────────────────
if ! have nvcc; then
  info "Installing build deps (cmake, build-essential, git) ..."
  sudo apt-get update -qq
  sudo apt-get install -y cmake build-essential git
  # Try the system CUDA toolkit; if still missing, user must install driver+toolkit manually.
  if ! have nvcc; then
    info "nvcc not found after apt — trying nvidia-cuda-toolkit ..."
    sudo apt-get install -y nvidia-cuda-toolkit || true
  fi
fi

if ! have nvcc; then
  err "nvcc not on PATH — install the CUDA toolkit matching your driver and retry."
  exit 1
fi

have cmake || { err "cmake not found"; exit 1; }

# ── detect CUDA architectures from installed GPUs ────────────────────────────
detect_cuda_arches() {
  python3 - <<'PY' 2>/dev/null || echo "native"
import subprocess, re, sys
try:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
        text=True
    ).strip()
    caps = sorted({c.replace(".", "") for c in out.splitlines() if c.strip()})
    # Blackwell sm_120 needs the 120a suffix for CUDA >= 12.8
    result = []
    for c in caps:
        result.append(c + "a" if c == "120" else c)
    print(";".join(result))
except Exception:
    print("native")
PY
}

CUDA_ARCHES=$(detect_cuda_arches)
info "CUDA architectures: ${CUDA_ARCHES}"

# ── resolve tag ───────────────────────────────────────────────────────────────
if [[ -z "$LLAMA_TAG" ]]; then
  info "Fetching latest llama.cpp release tag ..."
  if have curl; then
    LLAMA_TAG=$(curl -fsSL "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || echo "")
  fi
  if [[ -z "$LLAMA_TAG" ]]; then
    LLAMA_TAG="master"
    warn "Could not fetch latest tag — using master branch"
  else
    info "Latest tag: ${LLAMA_TAG}"
  fi
else
  info "Using pinned tag: ${LLAMA_TAG}"
fi

# ── clone / update ────────────────────────────────────────────────────────────
if [[ -d "${LLAMA_DIR}/.git" ]]; then
  info "llama.cpp exists at ${LLAMA_DIR} — fetching ..."
  git -C "$LLAMA_DIR" fetch --tags -q
  git -C "$LLAMA_DIR" checkout "$LLAMA_TAG" -q 2>/dev/null \
    || git -C "$LLAMA_DIR" checkout "tags/${LLAMA_TAG}" -q 2>/dev/null \
    || git -C "$LLAMA_DIR" checkout master -q
else
  info "Cloning llama.cpp @ ${LLAMA_TAG} ..."
  if [[ "$LLAMA_TAG" == "master" ]]; then
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
  else
    git clone --depth 1 --branch "$LLAMA_TAG" \
      https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
  fi
fi

# ── Blackwell (sm_120) workaround patch ──────────────────────────────────────
# Root cause: cudaDeviceProp.sharedMemPerBlockOptin reads from the wrong struct
# offset when the build CUDA toolkit headers differ from the runtime driver's
# struct layout (observed on CUDA 13.x / Blackwell: returns a garbage ~4 GiB
# value instead of the real ~99 KiB). That bogus value is later passed to
# cudaFuncSetAttribute(MaxDynamicSharedMemorySize), which the driver rejects
# with "invalid argument", aborting the server (surfaced as "SOFT_MAX failed").
#
# Fix: read the value via cudaDeviceGetAttribute() — a stable driver API that
# does not depend on the struct layout. This single-file change is sufficient;
# earlier defensive patches to fattn.cu / softmax.cu were verified unnecessary
# once smpbo is correct (MMA flash-attention and cooperative softmax work fine).
apply_blackwell_patches() {
  local dir="$1"

  # ggml-cuda.cu: use cudaDeviceGetAttribute for smpbo (avoids struct layout mismatch)
  python3 - "$dir/ggml/src/ggml-cuda/ggml-cuda.cu" << 'PY'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

old = '        info.devices[id].smpbo = prop.sharedMemPerBlockOptin;\n        info.devices[id].cc = 100*prop.major + 10*prop.minor;'
new = '''        info.devices[id].cc = 100*prop.major + 10*prop.minor;
        // Use cudaDeviceGetAttribute instead of prop.sharedMemPerBlockOptin to avoid
        // struct layout mismatches between CUDA toolkit versions (seen on CUDA 13.x / Blackwell).
        {
            int smpbo_val = 0;
            if (cudaDeviceGetAttribute(&smpbo_val, cudaDevAttrMaxSharedMemoryPerBlockOptin, id) == cudaSuccess && smpbo_val > 0) {
                info.devices[id].smpbo = (size_t) smpbo_val;
            } else {
                info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
            }
        }'''
new_marker = 'cudaDeviceGetAttribute(&smpbo_val, cudaDevAttrMaxSharedMemoryPerBlockOptin'
if new_marker in src:
    print('  [skip]  ggml-cuda.cu: smpbo patch already applied')
elif old in src:
    src = src.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(src)
    print('  [patch] ggml-cuda.cu: smpbo via cudaDeviceGetAttribute')
else:
    print('  [skip]  ggml-cuda.cu: pattern not found (API may have changed)')
PY
}

# Apply Blackwell patches if an sm_120 GPU is present
if echo "${CUDA_ARCHES}" | grep -q '120'; then
  info "Blackwell GPU detected — applying sm_120 workaround patches ..."
  apply_blackwell_patches "$LLAMA_DIR"
fi

# ── build ─────────────────────────────────────────────────────────────────────
LLAMA_BIN="${LLAMA_DIR}/build/bin/llama-server"
if [[ -f "$LLAMA_BIN" && "$FORCE" == "0" ]]; then
  info "llama-server already built at ${LLAMA_BIN} (use --force to rebuild)"
else
  JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
  info "Building llama-server with -j${JOBS} (first build ~10-20 min) ..."

  # Note: do NOT set -DGGML_CUDA_FORCE_CUBLAS=ON. It was used as a stop-gap to
  # avoid the MMQ kernel crash on Blackwell, but the real fix is the smpbo
  # correction (apply_blackwell_patches). Forcing cuBLAS only disables the
  # faster MMQ kernels and buys nothing once smpbo is correct.
  cmake -S "$LLAMA_DIR" -B "${LLAMA_DIR}/build" \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHES}" \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_USE_PREBUILT_UI=ON \
    -Wno-dev

  # The build downloads prebuilt UI assets from HuggingFace.
  # If HF is unreachable (corporate network, etc.) the llama-server target
  # will fail. In that case we download dist.tar.gz via curl ourselves and
  # retry with prebuilt UI disabled (using the just-downloaded assets).
  if ! cmake --build "${LLAMA_DIR}/build" \
      --config Release --target llama-server -j "$JOBS" 2>&1; then

    UI_DIST="${LLAMA_DIR}/build/tools/ui/dist"
    UI_ARCHIVE="${LLAMA_DIR}/build/tools/ui/dist.tar.gz"
    warn "Build failed — likely HuggingFace UI download blocked."
    info "Attempting to download UI assets via curl ..."

    if curl -fsSL \
        "https://huggingface.co/buckets/ggml-org/llama-ui/resolve/latest/dist.tar.gz" \
        -o "$UI_ARCHIVE" \
        && file "$UI_ARCHIVE" | grep -q "gzip"; then
      rm -rf "$UI_DIST"
      mkdir -p "$UI_DIST"
      tar -xzf "$UI_ARCHIVE" -C "$UI_DIST"
      info "UI assets extracted — retrying build ..."
      cmake -S "$LLAMA_DIR" -B "${LLAMA_DIR}/build" \
        -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_UI=OFF -Wno-dev
      cmake --build "${LLAMA_DIR}/build" \
        --config Release --target llama-server -j "$JOBS"
    else
      err "Could not download UI assets. Build failed."
      err "Try running with network access to huggingface.co, or:"
      err "  download dist.tar.gz manually and place at ${UI_ARCHIVE}"
      exit 1
    fi
  fi

  info "Build complete: ${LLAMA_BIN}"
fi

if [[ ! -f "$LLAMA_BIN" ]]; then
  err "Build finished but ${LLAMA_BIN} is missing."
  exit 1
fi

# ── restart lama-cell services ────────────────────────────────────────────────
if [[ "$RESTART" == "1" ]] && have systemctl; then
  CELLS=$(systemctl --user list-units 'lama-cell@*.service' --no-pager --plain 2>/dev/null \
    | awk '{print $1}' | grep 'lama-cell@')
  if [[ -n "$CELLS" ]]; then
    info "Restarting lama-cell services to pick up new binary ..."
    for svc in $CELLS; do
      systemctl --user restart "$svc" && info "  restarted $svc" || warn "  could not restart $svc"
    done
  else
    info "No active lama-cell services found — start them from the UI."
  fi
fi

# ── faster-whisper ASR server ─────────────────────────────────────────────────
# Provision it here too so a whisper "command" cell works straight from CARAVAN
# with no extra setup. Non-fatal: a whisper hiccup must not fail the llama build.
info "Provisioning faster-whisper ASR server ..."
bash "$(dirname "$0")/install-whisper.sh" \
  || warn "whisper provisioning failed (non-fatal) — run scripts/install-whisper.sh manually"

info "Done. llama-server: ${LLAMA_BIN}"
info "Run 'llama-server --version' to verify:"
"$LLAMA_BIN" --version 2>/dev/null || true
