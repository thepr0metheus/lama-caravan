# Adding a server (a runner)

A **runner** is a kind of server a cell can run — llama.cpp, vLLM, Strata, GR00T, whisper, moonshine,
transcribe.cpp, PersonaPlex, Qwen3-Omni… It is one tab on the Runner row of the new-cell form: the
operator picks it, picks a model, presses Start, and the board does the rest (the scout brings the
files, the card says what it takes of the GPU, the cell lives on the board like any other).

When a model needs a server the caravan does not have, **the server is added to that row first** and
started from it. It is not started by typing a command into the *Custom command* runner, not offered as a
preset or a button that pastes a command, and not run by hand over ssh. Those are the ways the owner
turned down on 2026-10-15 (the voice models of 1.3.551 were presets; 1.3.553 made them runners): a command
in a box has no VRAM account, no kind of model it takes, no words, no stale-server check, no place in the
registry — and the next person to look for the server in the list will not find it.

The custom command stays for what is truly one-off: a script somebody wants to try once.

## The shortest way: a launcher runner

A server that is started by a launcher script over one model of the library needs one class and one
script. `LauncherCellMixin` (`caravan/domain/runner.py`) builds the line, names the files the scout
brings, reserves the VRAM and says the registry's words; a subclass says what differs:

```python
class PersonaplexRunner(LauncherCellMixin, Runner):
    id = "personaplex"
    icon = "…"
    label_key = "runnerPersonaplex"           # the tab's name        ┐
    benefits_key = "runnerPersonaplexBenefits"  # what it is good at     │ i18n keys, in all 20 languages
    minus_key = "runnerPersonaplexMinus"        # what it costs         │
    needs_key = "runnerNeedsPersonaplexSt"      # why its tab is grey  ┘
    artifacts = ("personaplex-st",)           # the KIND of model it takes (picking one lands here)
    st_archs = ("personaplex",)               # config.json model_type (or its first architecture)
    launcher = "run_personaplex.sh"           # cells/run_personaplex.sh
    vram_mib = 20480                          # measured, rounded up; a start is refused when the card holds less
```

Then: add the class to `REGISTRY` (order is the order of the tabs), the launcher to `CELL_ASSETS` and a
group named after the runner's id to `RUNNER_ASSETS` in `caravan/admin/cell_assets.py` (the scout fetches
what the manifest says, so no scout release is needed), the words to the 20 files of `static/js/i18n/`,
and the work it does to `caravan/common/model_jobs.py` and its browser twin `static/js/model-jobs.js`.

A server with settings of its own (Strata's context, GR00T's robot) is a runner with fields: its fields go to
`CONFIG_FIELDS` and `FIELD_HELP` (`caravan/admin/config_builder.py`), a panel of `static/index.html`
(`tr-<name>Fields`), the panel list of `applyConfigToForm` and `_STATIC_TIP_FIELDS` in
`static/js/llama-edit.js`, `readConfigForm` in `static/js/form.js`, `check_field_homes.py`, and a preview
builder in `llama-edit.js` held to the server's line by a snapshot. `Gr00tRunner` is the example.

## The launcher

`cells/run_<name>.sh` installs its engine at the first start, in a folder of its own in the user's home —
a venv, a clone, a build — without `sudo`, and marks the install done **only when it is done** (a first start
that stopped halfway must be finished by the next, not mistaken for a finished install). It takes the port
first, the model's folder last, accepts `--install-only` anywhere among the arguments, stops at the first
failed step, and refuses a model folder that lacks the files it needs, in words that say which file and where
to get it. `scripts/test_voice_launchers.py` runs the voice launchers against stand-in `uv`, `git`, `cmake` and
`python`: write the same kind of test for a new one.

## What a runner touches

| where | what |
|---|---|
| `caravan/domain/runner.py` | the class, its place in `REGISTRY` (the only list of runners) |
| `caravan/admin/cell_assets.py` | the launcher in `CELL_ASSETS`, the group in `RUNNER_ASSETS` (named after the runner's id) |
| `caravan/common/model_jobs.py`, `static/js/model-jobs.js` | what it does: `_RUNNER_JOBS`, and `_ARCH_JOBS` for the folders it claims; the two are twins, held to one table of cases |
| `caravan/common/model_kinds.py` | only for a new kind of work (a job): its modalities and the paths of the entry it answers |
| `static/js/i18n/*.js` | label, benefits, costs, why-grey, and the job's label — 20 languages, no copy of English (`check_messages_i18n.py`) |
| `scripts/capture_golden.py` | the runner in the list of synthetic cells; `capture_golden.py --local` writes its snapshots |
| `scripts/test_<name>_runner.py` | the line, the refusals, the files the scout brings, the VRAM, the claims, the words — each a value with a negative; and mutants |
| `scripts/test_js_llama_edit.py` | the preview against the server's line, the tabs against the kinds the registry names |
| `README.md`, `CHANGELOG.md` | the *Tested versions* table (a component added or updated), the runner's section |
| `docs/testability.md` | a new `data-t` name (`scripts/testability_names.py` fails otherwise) |

Everything the browser needs to know about a runner it reads from the registry (`registry_json()` →
`state.runners`): the words (`labelKey`, `benefitsKey`, `minusKey`, `needsKey`), the model kinds (`artifacts`,
`stArchs`, `ggufArchs`), the devices (`gpuOnly`, and `oneCard` for a server that runs on one card: on a machine with two cards the form then asks which one),
the VRAM figure (`vramPlan`), the launcher and its arguments
(`launcher`, `launcherArgs`, `folderRule`). A new runner is a class, not an edit of seven files; if a place
still names runners by id, that place is the defect.

## Checking it

1. `python3 scripts/test_<name>_runner.py`, and the guards `check_oop_contract.py` (every `*Runner` class is
   in `REGISTRY`), `check_messages_i18n.py`, `check_ci_coverage.py`, `testability_names.py --check`.
2. The full CI in a clean clone (the steps of `.github/workflows/ci.yml`), the last line read: `N steps, 0 failed`.
3. Live, **from the board, not over ssh**: the new-cell form → the runner's tab → the model → Start. The cell's
   card shows its runner and its VRAM, the answer of the server is checked with a client that is not the
   server's own (a speech recognizer transcribes a voice back; a request body is compared with the reply), the
   cell is stopped from the board. A server that was only ever started by hand is not verified.

The first live check of the five voice runners (1.3.554) found two things no fixture had, which is what the
step is for. A checkpoint's `config.json` can weigh 649 KB (an AWQ quantiser lists every module it leaves
alone): a read of its first 64 KiB is a JSON cut short, it does not parse, the folder's architecture was empty
and the folder was offered to no runner that claims by architecture. And the stopped cell's chip sized
llama.cpp-omni by its 4.7 GB file while the form said 12.5. Make a fixture as big as the real thing, and where
the form and the card state one figure, read it from one place (`runnerFixedVramGb` in `llama-edit.js`).
