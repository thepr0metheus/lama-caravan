# Strata: which models, and what each one asks of the machine

Strata runs one model, Qwen3.8-Flash-Next (177 billion weights, 512 experts in each of 48 layers, 10 experts
a token), in the packs people have made of it. The engine keeps the experts in the machine's RAM and the card
holds the ones a token needs most; the pack decides how many bits an expert takes, and so how much RAM, how
much disk and how fast. The list below is Strata's own table (its `setup.py`, the same in v0.1.42 and v0.2.9): the cell's launcher
reads the family and the size of a pack from the file's NAME (`gguf_choice`), so a file with another name is
refused, and a new pack of Strata's is a Strata update, not a caravan change.

| Family | Pack (the folder of the repository) | Download | Experts in RAM | Notes |
|---|---|---|---|---|
| original (ISTA-DASLab) | `Q2_0` | 61.9 GiB | 34.0 GB | 2-bit, the fastest |
| original | `IQ2_XS` | 63.4 GiB | 35.5 GB | 2-bit i-quant, a little better, close in speed |
| original | `IQ3_XXS` | 70.6 GiB | 42.9 GB | 3-bit i-quant, better, slower (more CPU work a token) |
| original | `IQ3_S` | 77.9 GiB | 50.3 GB | 3.5-bit, the best quality (it matches the full model), the slowest |
| coder (ISTA-DASLab) | `IQ1_M` | 54.4 GiB | 23.4 GB | half the experts, the ones code, tools and images use; weaker outside coding |
| Swift 1.5 (UkisAI) | `IQ2_XS`, `IQ3_XXS`, `IQ3_S` (files in the repository's root) | 63.5 / 70.8 / 78.0 GiB | as the original's | a fine-tune that thinks much shorter (-63 % thinking tokens by its authors) |
| Unsloth | `UD-IQ4_XS` | 87.2 GiB | a budget (see below) | ~4-bit, between IQ3_S and UD-Q4_K_XL in quality |
| Unsloth | `UD-Q4_K_XL` | 103.7 GiB | a budget | 4-bit, EXPERIMENTAL in Strata |

(Swift 1.5's `Q2_0` is not on the list: its files split one layer's experts across the two parts, which Strata's
pack tool cannot prepare yet.)

## What fits

- **What the start promises** (`StrataRunner.ram_reservation`; the cell form draws it on its RAM scale): for a pack with
  all its experts in RAM, the larger of the first part's size and what Strata's own table says the pack's experts are
  (`arena_gb` in its `setup.py`, v0.2.9: `Q2_0` 34.0, `IQ2_XS` 35.5, `IQ3_XXS` 42.9, `IQ3_S` 50.3, the Coder's `IQ1_M`
  23.4 GiB), plus a GiB for the engine's own tables. The first part is not enough where the file split does not put
  every expert in it: Swift 1.5's `IQ3_S` has 41.8 GiB in its first part and the rest of its 50.3 GiB in the second.
  The scout refuses the start when that is more than the memory available less 2 GiB for the system.
- **A pack with all its experts in RAM** (every row but Unsloth's) runs in Strata's normal mode when the RAM is at
  least the experts' size plus 10 GB for the system. On a machine with 60.5 GiB of RAM that is `Q2_0`, `IQ2_XS`,
  `IQ3_XXS`, `IQ3_S` (60.3 of 60.5: with nothing else big in memory) and the Coder. Below it Strata has a
  low-RAM mode; **the caravan's launcher refuses it by name** (it is not set up here), and so does the start.
- **A budget pack** (Unsloth's) holds more experts than the RAM does: the engine keeps a budget of them in RAM and
  reads the rest from the file. The budget is Strata's own recommendation for the machine, written at every start:
  the RAM less 24 GiB for the system and the file cache the rest is read through, less the RAM a streamed KV cache
  takes (60.5 GiB: 34 at the 131072-token window). Strata says such a pack needs 48 GB of RAM, and the start promises
  that much. The more experts the card or cards can hold, the less the disk is read: a 4-bit pack on a card of 32 GB
  and an SSD ran at 7 to 8.5 tokens a second in Strata's own measurements.
- **The window.** An empty context field asks for the window the model was trained for, 262144 tokens (the owner,
  2026-10-26; it asked for 131072, Strata's figure for a 32 GB card, half of the model's); the field's placeholder says
  it. A longer window leaves less VRAM for the cached experts, and a budget pack's streamed KV cache takes its RAM from
  the budget (32 GiB at 262144 on a machine of 60.5 GiB). At 262144 with int8 KV and the draft layer, measured on such a
  machine on 2026-10-26: `UD-IQ4_XS` 101–108 tokens a second on an RTX 5090, `IQ2_XS` 128 on an RTX 3090, Swift's
  `IQ3_XXS` 152–163 on an RTX 5090 (Strata v0.1.42). On Strata v0.2.9, 2026-10-31: `IQ2_XS` 222–245 on an RTX 5090, four
  answers of 600 tokens, the first token in 0.03 to 0.2 s.
- **The memory of the start.** A pack whose experts take more than 70 % of the RAM (`IQ3_XXS` promises 43.9 GiB on a
  machine of 60.5 GiB) needs caravan-scout 2.38.2: before it, the cell's scope throttled it from 42.3 GiB, and on an
  idle machine those sleeps were the whole user session's memory pressure — systemd-oomd killed the cell, and on the
  first start after a download the scout and the desktop's shell before it (2.38.1 keeps a download out of the page
  cache). The load still runs the session's pressure up to about 47 % of oomd's 50 %: a machine of this size has little
  to spare for a pack of this size. `IQ2_XS` on v0.2.9 with 46 GiB available reached 51.7 % for about 8 s and stayed over
  40 % for 48 s, and nothing was killed: oomd asks for more than 20 s over its 50 %.
- **The card.** A cell runs on ONE card, the one `CUDA_VISIBLE_DEVICES` in its ENV names (the card chips of the
  form write it). Strata's engine is compiled for the architectures of the cards it was built for (`BUILD.json`,
  `archs`); a cell pinned to a card it has no code for is refused before the load, with the way out. Adding a card of
  another architecture to the machine means building the engine again (`setup.sh --gpus <the cards>`).

## Getting a pack

Open the Hugging Face page of the caravan (`/hf`), search the repository (`ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`,
`ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF`, `ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF`,
`unsloth/Qwen3.8-Flash-Next-GGUF`), choose the pack's files (both parts of two, all parts of three or four), and
download them into the library. The original's second part (the n-gram table, 26.8 GiB) is the same file in every
ISTA-DASLab pack, the Coder's too. In the cell's form, the **Strata** tab lists every pack of the library; choose
the first part (`…-00001-of-0000N.gguf`) and the form fills in the draft layer itself.

## The draft layer

`mtp-q2_0.gguf` is Strata's own pack of the original checkpoint's MTP tensors: about twice the output speed, and,
for an IQ pack, a condition of starting at all. Strata's setup makes it once, from the original checkpoint, for every
family; no Hugging Face repository of the packs ships it. The library holds the copy that came that way, in
`ISTA-DASLab/IQ2_XS/`.

- **How the form finds it.** A draft file's header names its architecture, the model's with `-mtp` after it
  (`mtp-q2_0.gguf` is `qwen4exp-mtp`, every pack here is `qwen4exp`). The list offers a pack the drafts of its own
  folders first (its quant folder, `default/`, the repository's other quant folders) and then every draft of its
  architecture wherever the library keeps it: the first is filled in, no more than five are offered, and a draft of
  another architecture (llama.cpp's own MTP files, `qwen35`) or a file whose header was never read goes to no pack.
  So the Coder's, Swift's and Unsloth's packs get it from `ISTA-DASLab/IQ2_XS/`. Strata's own setup does the same
  thing: its one layer serves every family.
- **An IQ pack does not start without it.** The engine answers a native IQ pack that has no `--spec` (the draft
  layer's flag) with "native (IQ) pack: it needs --native SHARD1, --spec T (T >= 2) and --prefill CHUNK" — after the
  scout has copied 54 to 90 GiB and the engine has loaded them (the Coder's IQ1_M, 2026-10-17). So the start is
  refused before the scout is sent anything, naming the pack and the way out, when the pack is `…-IQ<n>…` (IQ1_M,
  IQ2_XS, IQ3_XXS, IQ3_S, UD-IQ4_XS) and the cell names no draft layer. Q2_0 runs without it, at about half the speed
  (it was started with the layer in every live check, so the figure is Strata's, not measured here), and
  UD-Q4_K_XL is not refused either: nothing says the engine asks it for one.
- **The note in the form** says which of the two a cell is in: the layer's name, or that the library has none for
  this model — a Q2_0 pack runs without it, an IQ pack does not start.

The model is copied once to the machine's disk at its first start (a cell that caches its models keeps it there),
so a machine needs the pack's size free on its disk for each pack it runs.

## Updating Strata

A new Strata is built beside the working one, and `~/Strata` is a link to the one in use, so going back is one command and no
cell runs while it changes. It needs no sudo and no model.

    git clone --branch <tag> ~/Strata ~/Strata-<tag>
    cd ~/Strata-<tag> && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
    STRATA_NVCC=/usr/local/cuda-13.2/bin/nvcc .venv/bin/python -c 'import setup; cards = setup.gpus(); setup.build_engine({**cards[-1], "archs": [c["arch"] for c in cards]}, "none", True, setup.get_llama_cpp(), toolkit=13)'
    ln -sfn Strata-<tag> ~/Strata

The compile takes about 5 minutes and 8 of the machine's 16 threads. Check the launcher against it by running it, not by reading: the names
it needs were all still in v0.2.9's `setup.py`, and it would still have refused every start, because that file had begun to import a
package of its own. `StrataLaunch(args).config()` makes the pack and the config from the real files without starting the engine, and
`serve/server.py --lazy` answers `/health` without touching the card. What counts is a start from the board and a measured answer.

The launcher follows Strata's rules by reading them, so what a new version changes for a pack it picks up by itself; what a new version
adds to its setup's step 7 needs a line in `engine_args` or `config` of `cells/strata_launch.py`.
