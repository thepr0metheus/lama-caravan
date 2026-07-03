# Changelog

## 1.0.0 — 2026-07-03

First public release.

- Fleet topology board: controller, clients (via caravan-scout), llama server
  cells, cloud providers; live traffic on the cables.
- Per-agent proxy ports with queueing/priorities and visual routing pipelines
  (kanban): schedule, weighted, round-robin, failover, request-size fork.
- Remote server cells on client hosts: reserve → configure (memory estimate,
  exact command preview, backups) → start; command cells for non-llama
  workloads (whisper, embeddings).
- HuggingFace GGUF browser with multi-part downloads.
- Usage & spend statistics, request history, incident badges, GPU/CPU/token
  monitors, System panel (llama.cpp build, controller services, models disk).
- Onboarding tours (? Tour) with an interface-language picker; EN/RU + 18
  more UI languages.
- Stdlib-only Python backend (admin + routing proxy), native ES-module
  frontend, no build step.
