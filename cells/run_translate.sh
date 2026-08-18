#!/bin/bash
# NLLB text-translation cell launcher (self-installing, CARAVAN command-cell ready).
# Text in one language -> text in another. The half of the cascade that the
# speech cell deliberately does not do: whisper gives you the source words,
# this gives you the translation, and you can look at both.
#
# Usage: run_translate.sh <port> <model> [src_lang] [tgt_lang] [--install-only]
#        model:     HF repo id (facebook/nllb-200-distilled-600M) or a local dir
#        languages: FLORES-200 (eng_Latn, rus_Cyrl); short codes work too
#
#     bash run_translate.sh 22040 facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl
#
# The model downloads ITSELF on first start into the HF cache — 2.5 GB for the
# distilled 600M — so nothing has to come through the model browser.
#
# LICENCE: NLLB-200 weights are CC-BY-NC-4.0 — non-commercial, like SeamlessM4T
# and unlike whisper.
set -e
INSTALL_ONLY=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--install-only" ]; then INSTALL_ONLY=1; else ARGS+=("$a"); fi
done
PORT="${ARGS[0]:-22040}"
MODEL="${ARGS[1]:-facebook/nllb-200-distilled-600M}"
SRC="${ARGS[2]:-eng_Latn}"
TGT="${ARGS[3]:-rus_Cyrl}"

# Shares the seamless venv by default: same torch, same transformers, and this
# model needs nothing the other did not already install. A second copy would
# cost ~7 GB to hold identical wheels. Point VENV elsewhere to separate them —
# worth doing if the two runners ever need different transformers versions.
VENV="${VENV:-$HOME/seamless-venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "translate: creating venv $VENV …"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -U pip
  IDX="${TRANSLATE_TORCH_INDEX:-https://download.pytorch.org/whl/cu130}"
  "$VENV/bin/pip" install torch --index-url "$IDX" || "$VENV/bin/pip" install torch
  "$VENV/bin/pip" install "transformers>=4.36" sentencepiece protobuf numpy
fi
# sentencepiece is what NLLB's tokenizer needs; the seamless install already
# brings it, but a venv built by an older copy of that script might not have it.
"$VENV/bin/python" -c "import sentencepiece" 2>/dev/null \
  || "$VENV/bin/pip" -q install sentencepiece

SERVER=""
for cand in "$(dirname "$0")/translate_server.py" "$HOME/translate_server.py"; do
  [ -f "$cand" ] && SERVER="$cand" && break
done
if [ -z "$SERVER" ]; then
  echo "translate: translate_server.py not found beside the launcher or in \$HOME" >&2
  exit 1
fi

if [ "$INSTALL_ONLY" = "1" ]; then
  echo "translate: venv ready at $VENV (install-only)"
  exit 0
fi

exec "$VENV/bin/python" "$SERVER" "$PORT" "$MODEL" "$SRC" "$TGT"
