#!/bin/bash
# Voice-clone TTS cell launcher (self-installing, CARAVAN command-cell ready).
# Usage: run_tts.sh [port] [engine] [--install-only]
#        engine: xtts | cosyvoice | f5 | mock
# --install-only provisions the venv (and the cosyvoice model) then exits —
# used by install-tts.sh --prewarm so a cell's first start is fast.
# Run several engines on different ports to A/B them from the client app:
#     bash run_tts.sh 8021 xtts
#     bash run_tts.sh 8022 cosyvoice
#     bash run_tts.sh 8023 f5
set -e
PORT="${1:-8021}"
ENGINE="${2:-xtts}"
VENV="${VENV:-$HOME/tts-$ENGINE}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "tts[$ENGINE]: creating venv $VENV …"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -U pip
  case "$ENGINE" in
    # coqui-tts pulls neither torch nor torchcodec (torch>=2.9 audio IO)
    # itself, and transformers v5 dropped isin_mps_friendly -> pin <5.
    # NB: torchcodec needs SYSTEM ffmpeg libs: sudo apt-get install -y ffmpeg
    xtts)      "$VENV/bin/pip" install "coqui-tts[codec]" torch torchaudio \
                   "transformers>=4.43,<5" ;;
    f5)        "$VENV/bin/pip" install f5-tts ;;
    cosyvoice)
      [ -d "$HOME/CosyVoice" ] || git clone --recursive \
          https://github.com/FunAudioLLM/CosyVoice.git "$HOME/CosyVoice"
      # battle-tested on Ubuntu 24.04/py3.12: the repo pins grpcio/openai-whisper
      # to versions that no longer build, and runtime code imports pkg_resources
      # (gone from setuptools>=81). Newer ones + filtered requirements work.
      "$VENV/bin/pip" install "setuptools<81" wheel
      "$VENV/bin/pip" install -U grpcio grpcio-tools openai-whisper
      grep -viE '^(grpcio|grpcio-tools|openai-whisper)' \
          "$HOME/CosyVoice/requirements.txt" > /tmp/cosy-req.txt
      "$VENV/bin/pip" install -r /tmp/cosy-req.txt
      # model: ~/CosyVoice/pretrained_models/CosyVoice2-0.5B (modelscope)
      "$VENV/bin/pip" install modelscope
      "$VENV/bin/python" - <<'PY'
from modelscope import snapshot_download
import os
snapshot_download("iic/CosyVoice2-0.5B",
                  local_dir=os.path.expanduser("~/CosyVoice/pretrained_models/CosyVoice2-0.5B"))
PY
      ;;
    mock)      "$VENV/bin/pip" install numpy ;;
    *) echo "unknown engine '$ENGINE' (xtts|cosyvoice|f5|mock)"; exit 1 ;;
  esac
fi

if [ "${3:-}" = "--install-only" ]; then
  echo "tts[$ENGINE]: venv ready at $VENV (install-only)"
  exit 0
fi

export COQUI_TOS_AGREED=1
if [ "$ENGINE" = "cosyvoice" ]; then
  export PYTHONPATH="$HOME/CosyVoice:$HOME/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/tts_server.py"
[ -f "$SERVER" ] || SERVER="$HOME/tts_server.py"
exec "$VENV/bin/python" "$SERVER" "$PORT" "$ENGINE"
