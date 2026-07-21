#!/bin/bash
# Launch the whisper server with faster-whisper's bundled cuDNN/cuBLAS
# on the library path. Usage: run_whisper.sh [port] [model]
VENV="${VENV:-$HOME/wsr}"
SITE=$("$VENV/bin/python" -c "import site;print(site.getsitepackages()[0])")
export LD_LIBRARY_PATH="$SITE/nvidia/cudnn/lib:$SITE/nvidia/cublas/lib:$LD_LIBRARY_PATH"
exec "$VENV/bin/python" "$HOME/whisper_server.py" "${1:-8000}" "${2:-large-v3}"
