#!/bin/bash
# MiniCPM-o 4.5 voice cell launcher (self-building, for a CARAVAN command cell): OpenBMB's omni model behind
# llama.cpp-omni's `llama-omni-server`. A spoken question in, a spoken answer out, English and Chinese; it sees
# images too. The server speaks a WebSocket protocol, ws://<host>:<port>/backend (turn-based, or full duplex), and
# not the OpenAI API; it has no page of its own. GET /health answers {"status":"ok","engine":"comni"}.
#
# Usage: run_minicpm_omni.sh <port> <model-dir> [--install-only]
#   model-dir  the library's folder of openbmb/MiniCPM-o-4_5-gguf, as the /hf page lays it out: <dir>/default,
#              <dir>/F16 and <dir>/Q4_K_M, each with its .gguf files (ten files, 8 GB)
#   --install-only  builds the server and lays out the model folder, then exits (2 to 8 minutes on 16 cores)
#
# Why the odd bits, each a defect that was paid for (2026-10-15):
#  * The server finds every part of the model by the folder of the main GGUF (-m) and has no flag for them: the ten
#    files of the library are linked into one folder of the layout it expects ($OMNI_LAYOUT, else $HOME/omni-gguf).
#  * prompt_cache.gguf must be 211613152 bytes: copies of the older repository are 67 MB, load without a word and
#    speak with another voice. The launcher refuses such a copy and says so.
#  * llama-moe-slot.cpp (added to the repository 2026-10-11) calls fcntl with F_NOCACHE, a macOS flag: the file does
#    not compile on Linux. The flag is defined as -1 — a command no kernel knows — for a path (experts read from an
#    SSD) that this dense model never takes.
#  * -DLLAMA_OPENSSL=OFF: with the OpenSSL headers installed the server builds HTTPS-only. -Xcicc -O1: the CUDA 13.2
#    compiler garbles some kernels at its default optimisation.
#  * The server must run in its source folder: the default reference voice is loaded relative to the working directory.
#  * The models load at the FIRST session, not at start (30-90 s from a NAS); every later session finds them loaded.
#    One session at a time. The server has no password: it listens on the machine's loopback, as every cell does, and the
#    controller reaches it through the scout (rules::CellDoor::LISTEN).
#  * Each session leaves its audio chunks in $TMPDIR/omni_ws/<session>/ and never removes them: the launcher removes the
#    sessions older than a day at every start.
#  * In full duplex llama.cpp-omni voices each step of a turn with at most 26 audio tokens, about a second
#    (tools/omni/omni.cpp, `duplex_mode ? 26 : 500`, after the Python reference's max_token_per_chunk = 25 + 1), and the
#    step that ends the turn is the last one voiced: when a short answer's text and its end of turn come in one step, all
#    but its first second is never heard (2026-10-22: the first answer of a call, «The capital of France is Paris.», came as
#    1.2 s, «The capital, France,»). The launcher patches that one line before it builds: the step that ends the turn is
#    voiced to the audio's end, as a turn-based answer is (500). Upstream has the same line at its HEAD; the issue text is
#    the owner's to post.
set -euo pipefail

# The flag may stand anywhere: it is taken out first, and what is left is <port> <model-dir>.
INSTALL_ONLY=""
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--install-only" ]; then INSTALL_ONLY=1; else ARGS+=("$arg"); fi
done
PORT="${ARGS[0]:-}"
MODEL_DIR="${ARGS[1]:-}"

say() { echo "minicpm-omni: $*"; }
die() { echo "minicpm-omni: $*" >&2; exit "${2:-1}"; }

[ -n "$PORT" ] && [ -n "$MODEL_DIR" ] || die "usage: run_minicpm_omni.sh <port> <model-dir> [--install-only]" 2

PIN="88bd37eb671f67cf8d747140ed100231756e0bc3"
# The patch the pinned source gets before it is built (see the head of this file). Its name is in the build's marker, so a tree
# built without it, or with another version of it, is built again once. The line it changes must be in the pinned file exactly
# once, or nothing is built: a patch that silently did not apply would be a build that silently cuts the voice again.
PATCH="duplex-last-step-1"
PATCH_FILE="tools/omni/omni.cpp"
PATCH_WAS='    const int max_audio_tokens = ctx_omni->duplex_mode ? 26 : 500;'
PATCH_NOW='    const int max_audio_tokens = (ctx_omni->duplex_mode && !is_end_of_turn) ? 26 : 500;'
SRC="${OMNI_SRC:-$HOME/llama.cpp-omni}"
LAYOUT="${OMNI_LAYOUT:-$HOME/omni-gguf}"
JOBS="${BUILD_JOBS:-8}"
MAIN="MiniCPM-o-4_5-Q4_K_M.gguf"
PROMPT_CACHE_BYTES=211613152
export PATH="$HOME/.local/bin:$PATH"

# The file name in the library, and the folder of the layout it goes to.
PARTS=(
  "$MAIN:."
  "MiniCPM-o-4_5-audio-F16.gguf:audio"
  "MiniCPM-o-4_5-vision-F16.gguf:vision"
  "MiniCPM-o-4_5-tts-F16.gguf:tts"
  "MiniCPM-o-4_5-projector-F16.gguf:tts"
  "encoder.gguf:token2wav-gguf"
  "flow_matching.gguf:token2wav-gguf"
  "flow_extra.gguf:token2wav-gguf"
  "hifigan2.gguf:token2wav-gguf"
  "prompt_cache.gguf:token2wav-gguf"
)

# 1. The model folder, before anything is built: the ten files, and the right prompt cache.
FOUND=()
for entry in "${PARTS[@]}"; do
  name="${entry%%:*}"
  path=""
  IFS= read -r path < <(find -L "$MODEL_DIR" -type f -name "$name" 2>/dev/null) || true
  [ -n "$path" ] || die "$name is not under $MODEL_DIR: download openbmb/MiniCPM-o-4_5-gguf (all of it) on the /hf page first"
  FOUND+=("$path")
  if [ "$name" = "prompt_cache.gguf" ]; then
    size="$(wc -c < "$path")"
    [ "${size// /}" = "$PROMPT_CACHE_BYTES" ] || die "$path is ${size// /} bytes, not $PROMPT_CACHE_BYTES: it is a copy of the older repository (another voice): download it again"
  fi
done

# 2. The server, built at one commit, for the architecture of EVERY card of this machine: a cell may be pinned to any
# of them, and a server built for one architecture dies with "no kernel image" on the other (2026-10-17: an RTX 3090,
# sm_86, came to stand beside the RTX 5090, sm_120, and the card with the lower number is where an unpinned cell goes).
# $CUDA_ARCH overrules the cards; no nvidia-smi: the card of the fleet, sm_120. The marker is written when the build is
# DONE, and with it the architectures it was made for: a build that stopped halfway is finished by the next start (cmake
# builds what is left), and a card of another architecture added since asks for a new build. The marker names the patch too.
ARCH="${CUDA_ARCH:-}"
if [ -z "$ARCH" ]; then
  caps="$({ nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | tr -d '. \r' | sort -un | paste -sd';' -; } || true)"
  ARCH="${caps:-120}"
fi
if [ ! -f "$SRC/build/.built-$PIN-$PATCH" ] || [ "$(cat "$SRC/build/.arch" 2>/dev/null || true)" != "$ARCH" ]; then
  command -v cmake >/dev/null 2>&1 || die "cmake is not installed"
  command -v git >/dev/null 2>&1 || die "git is not installed"
  NVCC="${NVCC:-}"
  for candidate in "${CUDA_HOME:+$CUDA_HOME/bin/nvcc}" /usr/local/cuda/bin/nvcc "$(command -v nvcc || true)"; do
    [ -n "$NVCC" ] && break
    [ -n "$candidate" ] && [ -x "$candidate" ] && NVCC="$candidate"
  done
  [ -n "$NVCC" ] || die "nvcc is not found: install the CUDA toolkit (13.x for an RTX 5090) or set NVCC"
  say "building llama-omni-server for sm_${ARCH//;/, sm_} with $NVCC (first start on this machine: several minutes)"
  [ -d "$SRC/.git" ] || git clone -q https://github.com/tc-mb/llama.cpp-omni "$SRC"
  if [ "$(git -C "$SRC" rev-parse HEAD)" != "$PIN" ]; then
    git -C "$SRC" checkout -q --force "$PIN"
  fi
  # The patch, on the file as the pin has it: a tree patched by an earlier build is put back first.
  git -C "$SRC" checkout -q "$PIN" -- "$PATCH_FILE"
  [ "$(grep -cxF -- "$PATCH_WAS" "$SRC/$PATCH_FILE" || true)" = 1 ] \
    || die "patch $PATCH no longer applies: the line it changes is not in $PATCH_FILE at $PIN exactly once; nothing is built"
  awk -v was="$PATCH_WAS" -v now="$PATCH_NOW" '$0 == was { print now; next } { print }' "$SRC/$PATCH_FILE" > "$SRC/$PATCH_FILE.patched"
  mv "$SRC/$PATCH_FILE.patched" "$SRC/$PATCH_FILE"
  say "patched $PATCH_FILE ($PATCH): the step that ends a duplex turn is voiced to its end"
  # A tree configured before (an interrupted build, another compiler path, an older commit) is not reused: cmake then
  # deletes its cache and configures again WITHOUT the options of this command line (seen 2026-10-15: the switches and
  # F_NOCACHE were lost, and the build stopped at the macOS flag once more).
  rm -rf "$SRC/build"
  cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=OFF \
      -DCMAKE_CUDA_COMPILER="$NVCC" -DCMAKE_CUDA_ARCHITECTURES="$ARCH" -DCMAKE_CUDA_FLAGS="-Xcicc -O1" \
      -DCMAKE_CXX_FLAGS="-DF_NOCACHE=-1" -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
      -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined
  cmake --build "$SRC/build" --target llama-omni-server -j"$JOBS"
  printf '%s\n' "$ARCH" > "$SRC/build/.arch"
  touch "$SRC/build/.built-$PIN-$PATCH"
fi

# 3. The layout the server expects, out of links to the library's files.
i=0
for entry in "${PARTS[@]}"; do
  dest="${entry#*:}"
  mkdir -p "$LAYOUT/$dest"
  ln -sfn "${FOUND[$i]}" "$LAYOUT/$dest/${entry%%:*}"
  i=$((i + 1))
done

if [ -n "$INSTALL_ONLY" ]; then
  say "ready (install-only): server $SRC/build/bin/llama-omni-server, model folder $LAYOUT"
  exit 0
fi

# 4. Yesterday's sessions leave the disk; today's stay.
SESSIONS="${TMPDIR:-/tmp}/omni_ws"
if [ -d "$SESSIONS" ]; then
  find "$SESSIONS" -mindepth 1 -maxdepth 1 -mtime +0 -exec rm -rf {} +
fi

say "serving on port $PORT: $LAYOUT/$MAIN"
cd "$SRC"
exec build/bin/llama-omni-server -m "$LAYOUT/$MAIN" --host 127.0.0.1 --port "$PORT" -ngl 99 -c 8192 --temp 0.7 --repeat-penalty 1.05
