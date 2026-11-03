# The stand: a whole caravan on one laptop

For checking the board with no machine at hand: on the road, with the home network out of reach, or before anything reaches
a real fleet.

```bash
(cd rust && cargo build --release -p admin -p proxy -p scout)
python3 scripts/stand/stand.py
```

The board is at `http://127.0.0.1:8799`. The account is in `<folder>/account.json`, made on the first start, for here only.
The stand stays in the foreground until it gets SIGTERM, and then ends everything it started.

## What is real and what is stood in for

| Part | On the stand |
|---|---|
| The controller and its proxy | real, built from this tree (`CARAVAN_STAND_PROGRAMS` says where else) |
| The scout | real, built from this tree |
| The way they talk | real: pairing, pulses, a start with its command line |
| GGUF headers | real format, read by the controller's own reader and by `scripts/stand/gguf_reader.py` for the fake engine |
| The cards | `scripts/stand/bin/nvidia-smi`: two cards (24 and 32 GB) and a folder of who holds what |
| The engines | `scripts/stand/bin/llama-server` and `bin/vllm`: take the real command line and compute nothing |
| The machine's RAM and address | the scout's config (`standRam`, `standAddress`): 60.5 GB, and 127.0.0.1 |
| The weights | none: a model is its header and a hole |

The fake engine follows llama.cpp's rules closely enough to catch a wrong plan: `CUDA_VISIBLE_DEVICES`, `--device` counted
over the visible cards (a card it cannot see is refused, in llama.cpp's words), `--fit` dealing whole layers card after card
and keeping each `--fit-target` free, `--tensor-split`, `-ngl`, and what does not fit dies with `out of memory`. The fake vLLM
reserves its `--gpu-memory-utilization` of a card, keeps `--cpu-offload-gb` of the weights in RAM, and dies in vLLM's words when
the weights leave no room for its cache.

## What it checks

What a stand-in in a unit test cannot: that the page, the controller and the scout agree. What a start would have run on a real
machine is written word for word to `<folder>/launches/<port>.json`, with the environment and where each layer went.

It found three defects in the machine page's dragging (1.3.695) that every pin had passed, because the pins stood in for exactly
the part that was wrong: `scripts/test_js_machine_plan.py` had `stop` and `act` of its own. See `CHANGELOG.md`, 1.3.696.

## What it does not check

Anything about a real engine: speed, real memory, a real load, whether llama.cpp's `--fit` deals as the fake one does, a
driver. A change that depends on those still gets its live check on a machine.

## Keeping the laptop safe

Its models say they weigh 174 GiB and take a few KB. That is safe only while nothing copies them byte by byte, so:

- The folder is the system's temporary one (`CARAVAN_STAND_DIR` says otherwise), never `var/` of this tree: whatever copies a
  working tree (a mutant run, an rsync, a backup) would write those zeros out.
- A library file that did not come out as a hole is deleted at once and the stand does not start.
- `DiskGuard` stops the stand when less than 8 GiB is left on the disk, or when the stand itself takes more than 2 GiB.
- The scout reads the library in place, as the scout on a controller's own machine does. It copies nothing.

Every listener is on 127.0.0.1, the fake engine's too, whatever `--host` it is given: a laptop away from home is on somebody
else's network.

The folder is safe to delete when the stand is not running; the next start makes it anew, with a new account.
