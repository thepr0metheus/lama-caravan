#!/bin/bash
# Moonshine cell launcher (self-installing, CARAVAN command-cell ready).
# One cell, two roles: speech recognition AND synthesis.
# Usage: run_moonshine.sh [port] [language] [--install-only]
#        language: the RECOGNIZER's language — en es zh ja ko vi uk ar
#                  (no Russian; whisper stays the RU recognizer)
# Synthesis is separate: /v1/audio/speech serves 20 locales, Russian included,
# and each voice downloads on its first request for that language.
# CPU-only — safe to run on a box whose GPUs are busy with LLMs.
#     bash run_moonshine.sh 8025 en
set -e
PORT="${1:-8025}"
LANG_="${2:-en}"
VENV="${VENV:-$HOME/moonshine-venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "moonshine: creating venv $VENV …"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -U pip
  "$VENV/bin/pip" install moonshine-voice
fi

if [ "${3:-}" = "--install-only" ]; then
  # prewarm: also fetch the model so the first cell start is instant
  "$VENV/bin/python" - <<PY
from moonshine_voice import get_model_for_language
print(get_model_for_language("${LANG_}")[0])
PY
  # Voices are NOT fetched by default: each costs ~250 MB of RSS once loaded,
  # so a recognizer-only cell never pays for one. Name the locales you actually
  # synthesize to make their first request instant instead of ~8 s:
  #     MOONSHINE_PREWARM_VOICES=ru,en run_moonshine.sh 8025 en --install-only
  if [ -n "${MOONSHINE_PREWARM_VOICES:-}" ]; then
    "$VENV/bin/python" - <<VOICES
import os
from moonshine_voice.tts import TextToSpeech
TAGS = {"en": "en-us", "ru": "ru-ru", "de": "de-de", "fr": "fr-fr",
        "es": "es-es", "it": "it-it", "ja": "ja-jp", "ko": "ko-kr",
        "zh": "zh-hans", "uk": "uk-ua", "tr": "tr-tr", "vi": "vi-vn",
        "pt": "pt-pt", "hi": "hi-in", "ar": "ar-msa", "nl": "nl-nl"}
for code in "${MOONSHINE_PREWARM_VOICES}".split(","):
    tag = TAGS.get(code.strip().split("-")[0].lower())
    if not tag:
        print("moonshine: no TTS voice for " + code.strip() + ", skipped")
        continue
    TextToSpeech(tag)                     # downloads the voice, then drops it
    print("moonshine: voice " + tag + " cached")
VOICES
  fi
  echo "moonshine: venv ready at $VENV (install-only)"
  exit 0
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/moonshine_server.py"
[ -f "$SERVER" ] || SERVER="$HOME/moonshine_server.py"
exec "$VENV/bin/python" "$SERVER" "$PORT" "$LANG_"
