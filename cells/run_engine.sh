#!/bin/bash
# A cell whose model runs inside an engine next to it (Ollama, LM Studio).
# The cell server is plain Python — the standard library only, no venv — so
# this launcher only starts it. It exists because a scout brings a cell's
# files into $HOME by the launcher its command names (run_<name>.sh): with
# none, the server would never reach the machine.
# Usage: run_engine.sh <port> <engine> <engine-port> <model>
#     bash run_engine.sh 22031 ollama 11434 qwen3:8b
set -euo pipefail
exec python3 "$HOME/engine_cell_server.py" "$@"
