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

A server that is started by a launcher script over one model of the library needs one row and one script.
`LauncherCell` (`rust/crates/admin/src/domain/runner/launcher.rs`) builds the line, names the files the scout
brings, reserves the VRAM and says the registry's words; a row says what differs:

```rust
const PERSONAPLEX: RunnerRow = RunnerRow {
    id: "personaplex",
    icon: "…",
    label_key: "runnerPersonaplex",            // the tab's name        ┐
    benefits_key: "runnerPersonaplexBenefits", // what it is good at    │ i18n keys, in all the languages
    minus_key: "runnerPersonaplexMinus",       // what it costs         │
    needs_key: "runnerNeedsPersonaplexSt",     // why its tab is grey   ┘
    artifacts: &["personaplex-st"],            // the KIND of model it takes (picking one lands here)
    st_archs: &["personaplex"],                // config.json model_type (or its first architecture)
    launcher: Some(LauncherSpec {
        launcher: "run_personaplex.sh",        // cells/run_personaplex.sh
        args: &["{model}"],                    // what it is given after the port
        folder_rule: "picked",
        vram_mib: 20480,                       // measured, rounded up; a start is refused when the card holds less
        vram_who: "PersonaPlex",
        vram_why: "the model and its codec took 19.5 GB on an RTX 5090",
        display_name: "PersonaPlex",
    }),
    ..LauncherCell::FAMILY
};
```

Then: add the row to `LauncherRunners::all` (the order is the order of the tabs), the launcher to `ASSETS` and a
group named after the runner's id to `RUNNERS` in `rust/crates/admin/src/fleet/cell_assets.rs` (the scout fetches
what the manifest says, so no scout release is needed), the words to the files of `static/js/i18n/`,
and the work it does to `RUNNER_JOBS` in `rust/crates/admin/src/common/model_jobs.rs` and its browser copy
`static/js/model-jobs.js`.

A server with settings of its own (Strata's context, GR00T's robot) is a runner with fields: its fields go to
`ConfigFields::ALL` (`rust/crates/admin/src/config/fields.rs`) and to `field_help.json` beside it, `BLOCK_KEYS` of
`rust/crates/admin/src/fleet/launch.rs` (the config block of start.sh, which the form reads back), a panel of
`static/index.html` (`tr-<name>Fields`), the panel list of `applyConfigToForm` and `_STATIC_TIP_FIELDS` in
`static/js/llama-edit.js`, `readConfigForm` in `static/js/form.js`, `check_field_homes.py`, the field's help in
the files of `static/js/i18n/`, and a preview builder in `llama-edit.js` held to the server's line by a
snapshot. `Gr00tRunner` (`runner/gr00t.rs`) is the example: a class of its own, in `RunnerRegistry::new`.

A server whose model is not a file of the library — it downloads its own, and the cell picks among a few
(`VoiceCloneRunner`, 1.3.611: XTTS-v2, CosyVoice2 or F5-TTS) — ignores the model picker (`shared_picker:
"ignored"`), keeps its choice in a field of its own (`model_field`), and names it as its model on the card.

## The launcher

`cells/run_<name>.sh` installs its engine at the first start, in a folder of its own in the user's home —
a venv, a clone, a build — without `sudo`, and marks the install done **only when it is done** (a first start
that stopped halfway must be finished by the next, not mistaken for a finished install). It takes the port
first, the model's folder last, accepts `--install-only` anywhere among the arguments, stops at the first
failed step, and refuses a model folder that lacks the files it needs, in words that say which file and where
to get it. `scripts/test_voice_launchers.py` runs the voice launchers against stand-in `uv`, `git`, `cmake` and
`python`: write the same kind of test for a new one.

## What a runner touches

The paths below stand under `rust/crates/admin/src/` unless they say otherwise.

| where | what |
|---|---|
| `domain/runner/` | the row or the class; its place in `RunnerRegistry::new` (`runner/mod.rs`) is the only list of runners |
| `talk` of the row | when its server answers one of the voice window's modes (`TalkMode::ALL`, `fleet/cell_talk/mode.rs`): `TalkSpec` (`runner/specs.rs`) — the modes, the voices of each mode and the request field that names one, the system prompt its model wants, how many messages a request carries; where its server lists its own voices (`voices_path`) and whether it speaks in the voice of a sample (`clone`). The card then offers the window on a running cell |
| `live` of the row | when its server talks over a WebSocket of its own: `LiveSpec` — the path, and the protocol the board's live window speaks there (`static/js/voice-live.js` `LIVE_PROTOCOLS`; MiniCPM-o's); the card then offers 📞 on a running cell, and the controller passes the talk on (`GET /api/cell-live`) |
| `page` of the row | when its server serves a page of its own that the operator talks in at the root of its port (PersonaPlex's): `PageSpec` — the config field that holds the page's https address on the reverse proxy in front of the cell (`PAGE_URL`, the cell form's page panel); the card then offers 🌐, a link in the same tab to that address (`static/js/cell-page.js`), and the save checks its form (`contract/cell_page.json`) |
| `fleet/cell_assets.rs` | the launcher in `ASSETS`, the group in `RUNNERS` (named after the runner's id) |
| `common/model_jobs.rs`, `static/js/model-jobs.js` | what it does: `RUNNER_JOBS`, and `ARCH_JOBS` for the folders it claims; the two are held to one table of cases, `contract/model_jobs.json` |
| `common/model_kinds.rs` | only for a new kind of work (a job): its modalities and the paths of the entry it answers |
| `static/js/i18n/*.js` | label, benefits, costs, why-grey, and the job's label — every language of `LANGS`, no copy of English (`check_messages_i18n.py`) |
| `contract/controller.json` | what the page is told of the runners. `CARAVAN_CONTRACT_WRITE=1 cargo test -p admin --test contract` writes the program's words in, and the file's diff in the merge request says what changed |
| `contract/runner_lines.json` | a row per line and per refusal: the config, and what the program says to it. The same command writes a new row's `line`; the browser's preview is held to the same rows |
| `tests/golden` | the launch line of every real cell, `rust/crates/admin/tests/golden.rs`: a new runner adds nothing here until a real cell runs it, and a line that changes is a commit of its own (`CARAVAN_GOLDEN_WRITE=1`) |
| the runner's own file | `#[cfg(test)]`: the line, the refusals, the files the scout brings, the VRAM, the claims, the words — each a value with a negative; and mutants |
| `scripts/test_js_llama_edit.py` | the preview against the server's line, the tabs against the kinds the registry names |
| `README.md`, `CHANGELOG.md` | the *Tested versions* table (a component added or updated), the runner's section |
| `docs/testability.md` | a new `data-t` name (`scripts/testability_names.py` fails otherwise) |

Everything the browser needs to know about a runner it reads from the registry (`registry_json()` →
`state.runners`): the words (`labelKey`, `benefitsKey`, `minusKey`, `needsKey`), the model kinds (`artifacts`,
`stArchs`, `ggufArchs`), the devices (`gpuOnly`, and `oneCard` for a server that runs on one card: on a machine with two cards the form then asks which one;
`autoDevice` for one that picks its device itself while nothing pins it: the form offers an "auto" tile),
the VRAM figure (`vramPlan`), the launcher and its arguments
(`launcher`, `launcherArgs`, `folderRule`), and the companion files the runner finds beside its model itself
(`ownCompanions`, the row's `own_companions`: what its `complete` fills at a save — the form keeps the cell's files
there and draws no suggestion of the model list over them). A new runner is a row, not an edit of seven files; if a place
still names runners by id, that place is the defect.

## Checking it

1. `cargo test -p admin` in `rust/`, and the guards `check_rust_contract.py`, `check_oop_contract.py` (a new
   cell server), `check_messages_i18n.py`, `check_ci_coverage.py`, `testability_names.py --check`.
2. The merge request's pipeline, every job of it.
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
