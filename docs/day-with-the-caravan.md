# A day with the caravan

A concrete walkthrough of what the caravan does for you over one day, and the
kanban that implements it. Names are made up; every mechanism is real.

## The cast

- **Controller** — an Ubuntu box running the LAMA CARAVAN admin (`:8090`),
  the proxy ports and a llama server cell on its RTX card.
- **workbench** — a desktop with a 24 GB GPU, runs
  [caravan-scout](https://github.com/thepr0metheus/caravan-scout); hosts
  coding agents.
- **shelf** — an old machine with a 12 GB GPU and scout; no agents, just spare
  compute.
- Agents: `coder-1`, `coder-2` (OpenAI-compatible coding agents), `researcher`
  (long contexts), `secretary` (reads private mail — must stay local).
- Cloud: one metered API provider as the escape valve.

Each agent points at its own proxy port on the controller — `:8101`,
`:8102`, … — and none of them will ever need reconfiguring again.

## Night (00:00–08:00)

The big GPUs are free. The schedule node sends everything local:

- `coder-1`/`coder-2` hammer a coding model on **workbench**; the queue node
  in front of it admits two requests at a time, the rest wait in line with
  priorities instead of timing out each other.
- `researcher` gets the controller's own cell with a huge context window.

Local tokens cost electricity. The spend chart for the night: ~0 $.

## Morning (08:00)

People start using the machines. The schedule window flips:

- `coder-1`/`coder-2` route to the **cloud provider** — the desktop GPU now
  belongs to its human.
- `researcher` stays local but moves to **shelf**'s smaller model via a
  request-size fork: prompts under 8k tokens go to shelf; bigger ones spill to
  the cloud.
- `secretary` doesn't participate in any of this: its route has exactly one
  output — the local cell. Private mail never leaves the LAN.

Nobody edited an agent config. The kanban did it.

## During the day

- A teammate asks for whisper: a **Command cell** on shelf runs
  `run_whisper.sh $PORT large-v3` — same lifecycle, same board card, same
  routing as any llama cell.
- You spot a new GGUF on HuggingFace, download it from `/hf` into the
  controller's models dir, click the workbench cell in the evening and swap
  the model — the editor shows it fits in VRAM before you press Start.
- One route starts throwing errors — the ⚠ badge on its card and the request
  history point at the culprit in a minute.

## The kanban that does all this

One agent port, drawn on `/kanban`:

```text
                        ┌─────────────┐
 agent :8101 ──────────►│   QUEUE     │      night 00–08
                        │ prio, 2 par │   ┌─────────────────► [workbench :8002]
                        └──────┬──────┘   │
                               ▼          │
                        ┌─────────────┐   │  day 08–24   ┌──────────────┐
                        │  SCHEDULE   ├───┤──────────────►│ REQUEST SIZE │
                        └─────────────┘   │              └──────┬───────┘
                                          │               ≤8k   │   >8k
                                          │                     ▼
                                          │        [shelf :8003]  [cloud out]
                                          │
                                          └── failover (busy/down) ──► [cloud out]
```

Nodes used: **queue** (admission + priorities), **schedule** (time windows),
and since v1.1 the cells themselves can carry start/stop windows (the cell
editor's Schedule panel) — so the night model literally turns itself on.
Also:
**request-size** fork, **failover** spill. Every edit hot-reloads in ~2 s.

## What the numbers say

Open Usage & spend in the evening:

- tokens per agent per backend — how much stayed local vs went to the cloud;
- the cloud column is the only one that costs money, and you decided when it
  is used;
- request history shows every hop with timings — including the requests the
  failover node saved when workbench was busy.

That's the pitch: **the same agents, the same API — but the tokens land where
you told them to.**
