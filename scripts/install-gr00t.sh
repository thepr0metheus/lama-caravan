#!/usr/bin/env bash
# install-gr00t.sh — provision NVIDIA's Isaac-GR00T runtime on this host so it can run a `gr00t`
# cell:
#
#     COMMAND:     bash ~/run_gr00t.sh $PORT <checkpoint folder> --backbone <folder> ...
#     HEALTH_PATH: /health
#
# GR00T N1.7 is a vision-language-action model: camera frames, the robot's state and an
# instruction in, a chunk of actions out. Its runtime is NVIDIA's own Python package, and this
# installs it the way it was verified on an RTX 5090 (2026-10-13): Isaac-GR00T at a pinned
# commit, its environment exactly as its uv.lock names it (torch 2.9.0+cu128, transformers
# 4.57.3, flash-attn 2.8.3), uv itself checked against its published sha256. Inference took
# 7.0 GB of VRAM and 58 ms a request there.
#
#     scripts/install-gr00t.sh
#
# The weights are not installed here: the cell's two folders — the checkpoint
# (nvidia/GR00T-N1.7-3B) and its backbone (nvidia/Cosmos-Reason2-2B, a gated repository whose
# terms the owner accepts on Hugging Face) — come from the caravan's library, brought by the
# scout like any cell's model.
#
# Needs: Linux x86_64, an NVIDIA GPU, python3.12, git, curl, and FFmpeg 4–7 (torchcodec 0.8
# cannot load FFmpeg 8). Idempotent. Standalone on purpose — NOT invoked from install-llama.sh.
# Licences: Isaac-GR00T code Apache-2.0; GR00T-N1.7-3B weights NVIDIA Open Model License;
# Cosmos-Reason2-2B its own, accepted on its model page.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-gr00t]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

GR00T_HOME="${GR00T_HOME:-$HOME/Isaac-GR00T}"
COMMIT="d2b7e75b937e3ec9aa5dbc798f08b89692c49734"
UV_VERSION="0.13.0"
UV_SHA256="1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154"
UV="$HOME/.local/bin/uv"

[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || { err "Isaac-GR00T's locked environment is for Linux x86_64"; exit 1; }
for tool in python3.12 git curl ffmpeg; do
  have "$tool" || { err "$tool is required"; exit 1; }
done
major="$(ffmpeg -version | head -1 | sed -E 's/^ffmpeg version n?([0-9]+).*/\1/')"
if [ "${major:-0}" -ge 8 ] 2>/dev/null; then
  err "FFmpeg $major found; torchcodec 0.8 loads FFmpeg 4–7 only"
  exit 1
fi

# ── uv, checked ──────────────────────────────────────────────────────────────
if [ -x "$UV" ] && [ "$("$UV" --version | awk '{print $2}')" = "$UV_VERSION" ]; then
  info "uv $UV_VERSION is here"
else
  info "installing uv $UV_VERSION into $HOME/.local/bin"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
  curl -fsSL -o "$tmp/uv.tar.gz" "$url"
  got="$(sha256sum "$tmp/uv.tar.gz" | cut -d' ' -f1)"
  [ "$got" = "$UV_SHA256" ] || { err "uv archive sha256 $got, expected $UV_SHA256"; exit 1; }
  tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
  mkdir -p "$HOME/.local/bin"
  install -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$tmp/uv-x86_64-unknown-linux-gnu/uvx" "$HOME/.local/bin/"
fi

# ── the runtime, pinned ──────────────────────────────────────────────────────
# No LFS payloads: the repository's demo data is not the cell's, and git-lfs is a system package.
if [ -d "$GR00T_HOME/.git" ]; then
  info "fetching into $GR00T_HOME"
  GIT_LFS_SKIP_SMUDGE=1 git -C "$GR00T_HOME" fetch -q origin
else
  info "cloning Isaac-GR00T into $GR00T_HOME"
  GIT_LFS_SKIP_SMUDGE=1 git clone -q https://github.com/NVIDIA/Isaac-GR00T.git "$GR00T_HOME"
fi
GIT_LFS_SKIP_SMUDGE=1 git -C "$GR00T_HOME" -c advice.detachedHead=false checkout -q "$COMMIT"
info "Isaac-GR00T at $(git -C "$GR00T_HOME" rev-parse --short=12 HEAD)"

info "syncing its locked environment (several GB on the first run)"
(cd "$GR00T_HOME" && "$UV" sync --frozen --python "$(command -v python3.12)")

info "checking the card"
(cd "$GR00T_HOME" && "$UV" run --frozen python -c '
import torch, gr00t  # noqa: F401
assert torch.cuda.is_available(), "torch sees no CUDA device"
print("torch", torch.__version__, "on", torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))
')
info "done: a gr00t cell can start here"
