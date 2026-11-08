#!/usr/bin/env python3
"""Every guard must be able to fail.

Two guards were found in one day that could not. The runner-panel check passed
while the panel it guards was deleted, because the panel's name appears
elsewhere in the same file. The cell-health check passed while a required field
was deleted, because every cell server documents its own payload in a docstring
and the check was grepping the promise instead of the code.

A guard that cannot fail is worse than no guard: it reports green, so the thing
it was written to catch goes uncaught AND unlooked-for. Both of those were found
by hand, by breaking the tree on purpose and watching. This does that on
purpose, every time.

Each guard gets a breakage aimed at the exact thing it exists to catch, applied
to a COPY of the tree. Two assertions per guard: green before the breakage, red
after. The first half matters as much as the second — a guard that fails on
everything would otherwise "pass" its own negative test.

When a breakage no longer applies — the anchor text moved — that is reported as
a failure, not skipped. A silently inapplicable breakage is how this test would
itself become a guard that cannot fail.

One thing IS skipped, loudly and counted separately: a guard whose tooling the
host does not have. check_messages_i18n shells out to node, which the controller
has no reason to install. "Cannot run here" is not "cannot fail", and printing
it as a failure would teach the reader to scroll past a red line that sometimes
means something real.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS, FAIL, SKIP = [], [], []


def _missing_tool(output):
    """The name of an executable the guard needed and the host does not have.

    Two shapes, because a guard may either crash on the missing binary or —
    better — notice and stand aside. The second one exits 0, so this has to
    recognise it BEFORE the caller concludes the guard "did not notice" its
    breakage: a clean skip that reads as a silent pass is the failure mode this
    whole test exists to prevent.
    """
    m = re.search(r"No such file or directory: '([^']+)'", output or "")
    if m:
        return m.group(1)
    m = re.search(r"SKIPPED[^\n]*нет (\w+)", output or "")
    return m.group(1) if m else ""

# guard → (args, file to break, find, replace)
# The breakage is chosen to be the failure the guard is FOR, not any old syntax
# error: anything can be broken by deleting a brace.
BREAKAGES = {
    # What a request carries, named in one place (docs/vision-describe.md). Each breakage is the defect the guard is for.
    "check_media_parts": [
        # The vocabulary written a second time with no reason: a word added here and not to `MediaParts::WORDS` is the defect back.
        ([], "rust/crates/admin/src/common/model_kinds.rs",
         "const INPUTS: [&'static str; 3] = MediaParts::WORDS;",
         "const INPUTS: [&'static str; 3] = [\"text\", \"image\", \"audio\"];"),
        # The journal counting parts on its own, in the file that was supposed to read the fact.
        ([], "rust/crates/rules/src/summaries.rs",
         'summary.insert("imageParts".into(), json!(carried.count("image")));',
         'summary.insert("imageParts".into(), json!(fold.image_parts));'),
        # The classifier matching a name loosely instead of the exact name first: `image_text` stops being a picture.
        ([], "rust/crates/rules/src/media_parts.rs",
         "if Self::TEXT.contains(&said.as_str()) {",
         'if said.contains("text") {'),
        # The entry refusing nothing: a picture no row can take would go to the provider unanswered.
        ([], "rust/crates/rules/src/media_reader.rs",
         "EntryRefusal::media(&pool.name, &carried.verdict(serving, &wired)).map_or(MediaAnswer::Goes, MediaAnswer::Refused)",
         "MediaAnswer::Goes"),
        # The entry reading the part by its word instead of asking the classifier: `image_text` stops being a picture.
        ([], "rust/crates/rules/src/media_reader.rs",
         "EntryRefusal::media(&pool.name, &carried.verdict(serving, &wired)).map_or(MediaAnswer::Goes, MediaAnswer::Refused)",
         'EntryRefusal::media(&pool.name, &carried.parts.iter().find(|part| part.word == Some("image"))?).map_or(MediaAnswer::Goes, MediaAnswer::Refused)'),
        # One kind of row asking the media rule while the other passes it over: the defect the pool fix is for.
        ([], "rust/crates/proxy/src/pool_steps/rows.rs",
         "        }\n        let row = match self.sight(ask, step, asked.carried) {\n            Sight::Blind(reason) => return row.unfit(reason),\n            Sight::ReadFirst => row.read_for(),\n            Sight::Sees => row,\n        };\n        self.by_account(",
         "        }\n        let row = row;\n        self.by_account("),
        # Every row said it cannot read the word, and the pool answers "takes": an absence drawn as a promise.
        ([], "rust/crates/rules/src/model_kind.rs",
         "        } else {\n            MayRead::Cannot\n        }",
         "        } else {\n            MayRead::Takes\n        }"),
        # The pool's cases not run: the guard would then be reading its own copy of the rule.
        ([], "rust/crates/rules/tests/contract.rs",
         'rows(&table("model_kind"), "pool")',
         'rows(&table("model_kind"), "serves")'),
        # A pool case with no `why`: the table would hold the rule and not the reason.
        ([], "contract/model_kind.json",
         '"why": "the negative case: a text row takes text, and the rule must not refuse the work the row exists for"',
         '"rule": "the negative case"'),
        # A state missing from the pool's table: no row may serve, drawn as "unsaid".
        ([], "contract/model_kind.json",
         '"answer": "no row"',
         '"answer": "unsaid"'),
        # A table the program is not held to: the guard would then be reading its own copy of the rule.
        ([], "rust/crates/rules/tests/contract.rs",
         'let data = table("media_parts");',
         'let data = table("summaries");'),
        # A case with no `why`: the table would hold the rule and not the reason, and the negative case would be unreadable.
        ([], "contract/media_parts.json",
         '"word": "text", "why": "the name that means text, read as itself"',
         '"word": "text"'),
    ],
    # What a wired reader is, said in one place (docs/vision-describe.md). A reader guessed from a name is the defect.
    "check_media_reader": [
        # A capability read out of a name: `qwen3-vl-8b-instruct` whose facts say `text` becomes a reader.
        ([], "rust/crates/rules/src/media_reader.rs",
         "        if !known {\n            return Self::Unknown(name.to_string());\n        }",
         '        if name.contains("vl") {\n            return Self::Named(MediaReader::new(name, Self::PROMPT_VERSION), None);\n        }\n'
         "        if !known {\n            return Self::Unknown(name.to_string());\n        }"),
        # An absence of a promise drawn as a promise that the model cannot read: the two answers become one.
        ([], "rust/crates/rules/src/media_reader.rs",
         "                None => Reader::NotSaid(reader.model().to_string()),",
         '                None => Reader::CannotTake(reader.model().to_string(), word.to_string()),'),
        # A caption whose text can end the envelope early: the escape for `"` goes, and a reader's words become an instruction.
        ([], "rust/crates/rules/src/media_reader.rs",
         '                \'\\\'\' => out.push_str("&apos;"),',
         '                \'\\\'\' => out.push(\'\\\'\'),'),
        # The wiring built somewhere else: the promise filled by hand instead of from `ModelKind`.
        ([], "rust/crates/proxy/src/pool_steps/rows.rs",
         "carried.verdict(kind.takes(), &Wired::Nothing)",
         'carried.verdict(kind.takes(), &Wired::Named(MediaReader::new("qwen-vl", "v1"), Some(vec!["image".to_string()])))'),
        # The words built by asking the wiring a second time, instead of reading the answer the rule gave.
        ([], "rust/crates/rules/src/entry_refusal.rs",
         "        let word = part.says();",
         '        let word = Wired::Nothing.promise("image").word();'),
        # The answer that reads is refused as if it were an absence.
        ([], "rust/crates/rules/src/entry_refusal.rs",
         "            Reader::Reads => return None,",
         "            Reader::Reads => (\"media_reader_cannot\", \"entry:media-reader-cannot\", String::new()),"),
        # A caption shape said a second time, outside the file that holds it.
        ([], "rust/crates/rules/src/summaries.rs",
         'summary.insert("imageParts".into(), json!(carried.count("image")));',
         'summary.insert("imageParts".into(), json!(carried.count("image")));\n        summary.insert("caption".into(), json!("<caravan-caption prompt_version=\\"v1\\">"));'),
        # The table not run by the program: the guard would be reading its own copy of the rule.
        ([], "rust/crates/rules/tests/contract.rs",
         'let data = table("media_reader");',
         'let data = table("summaries");'),
        # A case with no `why`: the table holds the rule, not the reason.
        ([], "contract/media_reader.json",
         '"answer": "nothing", "why": "the absence of the operator\'s decision, said as an absence: a wiring that names nothing is not a reader that reads nothing"',
         '"answer": "nothing"'),
        # The case the guard exists for goes: no row where the name says vision and the promise says otherwise.
        ([], "contract/media_reader.json",
         '"takes": ["text"]}, "word": "image", "answer": {"cannot take": "qwen3-vl-8b-instruct", "word": "image"}',
         '"takes": ["image"]}, "word": "image", "answer": "reads"'),
        # Two answers share one code: the table stops telling which absence the refusal was.
        ([], "contract/media_reader.json",
         '"code": "media_reader_unverified"',
         '"code": "media_reader_cannot"'),
        # The wiring that reads is put in the refused column: a table of only refusals cannot tell a rule from a guess.
        ([], "contract/media_reader.json",
         '"refused": false, "why": "the negative case: a wiring that reads the word is not refused, and the refusal function answers `None` for it. A table of only refusals cannot tell a rule from a guess"',
         '"refused": true, "why": "the negative case: a wiring that reads the word is not refused, and the refusal function answers `None` for it. A table of only refusals cannot tell a rule from a guess"'),
        # The row that reads the picture itself is refused as if it needed a caption.
        ([], "contract/media_reader.json",
         '"refused": false, "why": "the negative case for the row: a row that reads the picture is never given a caption, and the part goes to it as it came"',
         '"refused": true, "why": "the negative case for the row: a row that reads the picture is never given a caption, and the part goes to it as it came"'),
        # What the board may write as a reader is said by the answer, not by the page: `Reads` writes and `Nothing` writes,
        # because writing nothing is clearing a wiring. Take `Nothing` away and the click that removes a reader is refused by
        # the rule written to let it through.
        ([], "rust/crates/rules/src/media_reader.rs",
         "        matches!(self, Self::Reads | Self::Nothing)",
         "        matches!(self, Self::Reads)"),
        # The word of an answer, said once, is what the block draws. A function that returns an optional word is the same word
        # in two shapes, and the page has to decide which shape it was.
        ([], "rust/crates/rules/src/media_reader.rs",
         "    pub fn word(&self) -> String {",
         "    pub fn word(&self) -> Option<String> {"),
        # A wiring that names the pool it is wired for answers as itself, before its promise is read. Without that arm the
        # self-naming row answers as a reader that reads, and a caption is written for the row that cannot read the part.
        ([], "rust/crates/rules/src/media_reader.rs",
         "            Self::Named(reader, _) if reader.is_itself() => Reader::Itself(reader.model().to_string()),",
         ""),
        # The save asks the rule before it writes. A save that decides for itself — a name is a name, whatever the answer says
        # — writes what the same rule refuses to a request, in different words.
        ([], "rust/crates/rules/src/media_reader.rs",
         "        if answer.writes() {\n            return None;\n        }",
         "        if !reader.is_empty() {\n            return None;\n        }"),
        ([], "rust/crates/admin/src/cloud/pool_edits.rs",
         "        if let Some(refusal) = self.cloud().board_names(&data).can_write(&named) {\n"
         "            return Err(AppError::with_status(refusal.error.message, refusal.error.status));\n        }",
         "        if named.is_empty() {\n            return Err(AppError::new(\"the reader is not named\"));\n        }"),
        # The word a reader is wired for is named once: `audio` is not this rule's, and `text` needs no reader.
        ([], "rust/crates/rules/src/media_reader.rs",
         "    pub const READER_WORD: &'static str = \"image\";",
         "    pub const READER_WORD: &'static str = \"audio\";"),
        # The promise is what a model's facts name. A promise filled from what a name looks like is the defect back, at the
        # one place the promise is filled.
        ([], "rust/crates/rules/src/media_reader.rs",
         "        Wired::of(name, found.is_some(), promise, for_pool)",
         "        Wired::of(name, found.is_some(), name.contains(\"vl\").then(|| vec![\"image\".to_string()]), for_pool)"),
        # The board draws the word the rule answered. A word written by hand here is the fact read a second way: the board
        # says "reads" while the entry refuses the same pool with `media_reader_cannot`.
        ([], "rust/crates/admin/src/cloud/pool_state.rs",
         '        json!({"name": named.reader(), "answer": answer.word()})',
         '        json!({"name": named.reader(), "answer": "reads"})'),
        # Rule 7: the reading the rule is asked from. A reading built from the pools alone, with no routers and no keys,
        # answered `media_reader_unknown` for every model name on the live board on 2026-11-06 — a fact about the reading.
        ([], "rust/crates/admin/src/cloud/data/reading.rs",
         "        EntryModels::read(routers, Some(data), &Credentials::read(Some(&self.secrets())), ModelCatalogue::default())",
         "        EntryModels::read(None, Some(data), &Credentials::default(), ModelCatalogue::default())"),
        # Rule 7: what the board knows and what a key can call this second are two questions, so the set is held open to the
        # flag. A model the board knows and cannot call still has facts to read against; answering `pick` makes it `unknown`.
        ([], "rust/crates/rules/src/media_reader.rs",
         "        let found = self.known_name(deny, name);",
         "        let found = self.pick(deny, name);"),
        ([], "rust/crates/rules/src/entry_models.rs",
         "        self.open_to(deny, false).into_iter().find(|pool| pool.name == wanted)",
         "        self.open_to(deny, true).into_iter().find(|pool| pool.name == wanted)"),
        # The `names` group not run by the program: the guard would then be reading its own copy of the reading.
        ([], "rust/crates/rules/tests/contract.rs",
         'rows(&data, "names")',
         'rows(&data, "caption")'),
        # A `names` case that says `unknown` for a name its reading holds: the table would then hold the defect and could not
        # tell a name the caravan does not know from a reading that looks at the pools alone.
        ([], "contract/media_reader.json",
         '"wanted": "gpt-9-mira", "board": {"outputs": [],',
         '"wanted": "gpt-9-mira", "board": {"outputs": [{"id": "mm:1", "upstreamModel": "gpt-9-mira"}],'),
        # A `names` group with nothing where a name writes: `Reader::writes` has an arm for the name that reads, and a group of
        # only refusals cannot say which name the reading reads.
        ([], "contract/media_reader.json",
         '"refused": false, "why": "the door checks a name against the facts',
         '"refused": true, "why": "the door checks a name against the facts'),
        # The other arm: the absence writes, because writing nothing is clearing a wiring. Without its own case the group says
        # one fact of `Reader::writes` and not the other.
        ([], "contract/media_reader.json",
         '"refused": false, "why": "the absence named at the door',
         '"refused": true, "why": "the absence named at the door'),
    ],
    # Routing's reader block: it says the answer the rule gave and never names a state of its own (docs/vision-describe.md).
    "check_media_reading": [
        # A link read as a picture inside the request: the caravan would hand the reader an address to fetch on a client's word.
        ([], "rust/crates/rules/src/media_reading.rs",
         'url.get(..5).is_some_and(|scheme| scheme.eq_ignore_ascii_case("data:"))',
         '!url.is_empty()'),
        # A reading that failed turned into words: the row would be sent a caption of nothing as if the picture were read.
        ([], "rust/crates/proxy/src/exchange/reading.rs",
         "let words = self.ask_reader(&reading, picture)?;",
         "let words = self.ask_reader(&reading, picture).unwrap_or_default();"),
        # Every row that cannot read a picture read for, with no reader named: a picture no row can take would be sent on.
        ([], "rust/crates/proxy/src/pool_steps/rows.rs",
         'if ask.reads { Sight::ReadFirst } else { Sight::Blind("media_unsupported") }',
         "Sight::ReadFirst"),
        # The table's negative case for the rewrite gone: it could not say what a picture left without words comes to.
        ([], "contract/media_reading.json",
         '"captions": [],\n   "rewritten": null,',
         '"captions": [],\n   "rewritten": {},'),
    ],
    "check_media_reader_board": [
        # A state the rule does not answer, named on the page: the block's table and the rule's arms stop being one fact.
        ([], "static/js/reader-block.js",
          '    "reads": "pbReaderReads",',
          '    "vision": "pbReaderReads",'),
        # A state worked out of a name — `qwen3-vl-8b-instruct` says vision in its name and `text` in its facts. This is the
        # defect the guard was written for: the board draws "reads" on a pool whose reader cannot take the picture.
        ([], "static/js/reader-block.js",
          '      state: word == null ? "" : String(word),',
          '      state: word == null ? (String(pool?.reader || "").includes("vl") ? "reads" : "") : String(word),'),
        # The same, by a word the page chose for an answer: a row that says a state the rule does not have.
        ([], "static/js/reader-block.js",
          '      state: word == null ? "" : String(word),',
          '      state: word == null ? "" : "reads",'),
        # A word missing in one language: the block falls back for one operator and not for another.
        ([], "static/js/i18n/ru.js",
          '  pbReaderReads: "читает картинку",',
          '  pbReaderReadsOld: "читает картинку",'),
        # A colour for a state the rule does not have, and none for one it does: the operator reads an answer as an ordinary
        # row.
        ([], "static/css/pool-board.css",
          '.pb .pb-reader-row[data-t-state="reads"] .pb-reader-answer { color: var(--good); }',
          '.pb .pb-reader-row[data-t-state="vision"] .pb-reader-answer { color: var(--good); }'),
        # A row read twice: the facts worked out again in the markup instead of read once in `rowFacts`, so the drawing and
        # the test that reads it can disagree about what a row says.
        ([], "static/js/reader-block.js",
          "    const facts = ReaderBlock.rowFacts(reader);",
          '    const facts = { named: reader?.name || "", shown: reader?.name || "", '
          'state: String(reader?.answer ?? ""), answer: String(reader?.answer ?? "") };'),
        # An input dot drawn on a reader row — the absence named in the module, in the table and in the pin. A reader is the
        # wiring the operator named, not a path a request runs through, so a cable pulled INTO the block goes the wrong way.
        ([], "static/js/reader-block.js",
          "      + `${ReaderBlock.dotHtml()}</li>`;",
          "      + `${ReaderBlock.dotHtml()}<span class=\"pb-dot in\" data-pb-in=\"${ReaderBlock.PREFIX}\"></span></li>`;"),
        # A reader row lit because its cable is drawn — a blink the board invented. Only what the request names lights it.
        ([], "static/js/pool-flow.js",
          "    const read = item?.readerName ? [ReaderBlock.key()] : [];",
          "    const read = pools.has(pool) ? [ReaderBlock.key()] : [];"),
        # The key said in two places: the prefix lives once in `ReaderBlock.PREFIX`.
        ([], "static/js/pool-flow.js",
          "    const read = item?.readerName ? [ReaderBlock.key()] : [];",
          "    const read = item?.readerName ? [`reader:${pool}`] : [];"),
        # The reader's own request lighting its client's cable: a request the client never sent, drawn on the board.
        ([], "static/js/pool-flow.js",
          "    if (item?.readerFor) return [ReaderBlock.key()];",
          "    if (item?.readerFor) return [`client:${id}/${pool}`, ReaderBlock.key()];"),
        # A key with a pool after it, held by the test: one board has one reader, so a key per pool names one cable per pool
        # for one fact — and the pin goes green while the module answers a different key.
        ([], "scripts/test_js_cable_flow.py",
          '"client:c23001/P", "reader", "row:P/sub-1"',
          '"client:c23001/P", "reader:P", "row:P/sub-1"'),
        # A name the page can emit that the doc no longer publishes: a suite looks for the hook and reads an empty result as
        # a broken application.
        ([], "scripts/testability_names.py",
          '    "pb-reader-block": "reader-block.js: ReaderBlock.HOOKS.block",\n',
          ""),
        # A snapshot that no longer reads the table it was written to run: the guard would be holding its own copy of the rule.
        ([], "scripts/test_js_reader_block.py",
          'TABLE = Contract.table("media_reader_board")',
          'TABLE = Contract.table("media_parts")'),
        # The negative case goes: a table with a key for every word it names cannot say what it does when the rule answers a
        # word it was not built for.
        ([], "contract/media_reader_board.json",
          '"answer": "banana", "key": null',
          '"answer": "banana", "key": "pbReaderBanana"'),
        # A negative case that names facts is no longer a negative case: the program can answer it, so the word is not the
        # word the table cannot say.
        ([], "contract/media_reader_board.json",
          '{"asked": "image", "answer": "banana", "key": null',
          '{"reader": {"name": "banana", "known": true, "takes": null}, "for_pool": null, "asked": "image", "answer": "banana", "key": null'),
        # The program stops being held to the table: the guard would be reading its own copy of the rule.
        ([], "rust/crates/rules/tests/contract.rs",
          'let data = table("media_reader_board");\n    for row in rows(&data, "answers") {',
          'let data = table("media_reader_board");\n    for row in rows(&data, "caption") {'),
        # An answer the program decides is not said to be writable or not: the save has nothing to ask.
        ([], "contract/media_reader_board.json",
          '"answer": "cannot take", "writes": false',
          '"answer": "cannot take"'),
        # A snapshot that reads a copy of the page instead of running the module: the guard would be holding the page's own
        # idea of the rule.
        ([], "scripts/test_js_reader_block.py",
          'pathToFileURL(process.env.JS_ROOT + "/reader-block.js")',
          'pathToFileURL(process.env.JS_ROOT + "/utils.js")'),
        # A row that says a word the table does not hold for its answer: the same answer read two ways, in the row and in the
        # module, which is how the board and the journal start disagreeing.
        ([], "contract/media_reader_board.json",
          '"answer": "reads", "says": {"named": "qwen-vl", "shown": "qwen-vl", "answer": "pbReaderReads", "state": "reads"}',
          '"answer": "reads", "says": {"named": "qwen-vl", "shown": "qwen-vl", "answer": "pbReaderNothing", "state": "reads"}'),
        # The order of the column, put in the CSS instead of being said once in `poolsHtml`: Direct pins itself, and the table
        # cannot see a part that holds itself in view. This is what the owner stopped on 2026-11-06.
        ([], "static/css/pool-board.css",
          '.pb-direct {\n  margin: 0 0 12px;',
          '.pb-direct {\n  position: sticky; top: 0; margin: 0 0 12px;'),
        # The same order said a second way, in the drawing: the reader block put before Direct.
        ([], "static/js/pool-board.js",
          'return PoolBoard.column("pools", head, [direct, block, empty, cards].join(""));',
          'return PoolBoard.column("pools", head, [block, direct, empty, cards].join(""));'),
        # The pin that runs the table's `column` goes: the order becomes a habit of the drawing, with nothing to hold it.
        ([], "scripts/test_js_pool_board.py",
          '("the_reader_block_sits_below_direct",',
          '("the_reading_order_of_the_column",'),
        # The pin reads a group of its own instead of the table's `save`: the guard would be holding the code to a shape no test runs.
        ([], "scripts/test_js_pool_board.py",
          'SAVE = Contract.table("media_reader_board")["save"]',
          'SAVE = Contract.table("media_reader_board")["shapes"]'),
        # The save body built by hand, and not through `PoolCards.body`: the shape of what the door takes is then said twice,
        # and the board sends a field without the pool around it — `unknown pool: None` on the live board, 2026-11-06.
        ([], "static/js/pool-board.js",
          'ReaderBlock.body(to.entry || PoolBoard.key(to.target))',
          '{ reader: to.entry || PoolBoard.key(to.target) }'),
        # The shape said in the page that calls the door, instead of in the place the page names it.
        ([], "static/js/pools.js",
          'JSON.stringify(PoolCards.body(PoolCards.payload(pool)))',
          'JSON.stringify({ pool: PoolCards.payload(pool) })'),
        # The board's answer stops carrying the reader: the block draws "not named" whatever the operator saved, and the
        # page's pins, fed `top.reader` by hand, stay green — what shipped on 2026-11-06.
        ([], "rust/crates/admin/src/topology/mod.rs",
          '"reader": PoolDesk::reader(live),',
          '"readerUnused": json!(null),'),
        # The door reads the body somewhere else: the page and the door part, and neither can be held to the other.
        ([], "rust/crates/admin/src/routes/pools.rs",
          'body.get("pool")',
          'body.get("id")'),
        # A body that names no pool stops saying so: the operator gets an answer that is not the answer the door gave.
        ([], "rust/crates/admin/src/cloud/pool_edits.rs",
          'supplied.get(EntryModels::READER_FIELD)',
          'supplied.get("name")'),
        # The negative case names a door that reads the body anyway: a table that can answer every case it names cannot say
        # what it does when the body is not a pool.
        ([], "contract/media_reader_board.json",
          '"through": false, "body": {}, "read": null',
          '"through": false, "body": {}, "read": "qwen-vl"'),
    ],
    # What a diagram in diagrams/ says about a rule, and the guard it still points at. A diagram the README does not
    # name is a diagram nobody reads; a number that is not the number the guard checks the rule at is the defect the
    # guard's own numbering is for; and a diagram pointing at a list the guard no longer has points at nothing while
    # looking like a rule. Each case below is the only place its check can go red — except rule 2, where one number is
    # said in three places (file, title, README), so a disagreeing number is also a rule left without its diagram.
    "check_diagrams": [
        # Rule 1: the folder has a diagram the README does not name.
        ([], "diagrams/README.md",
         "| `media-reader-02-may-not.md` | правило 2: что файл не может сказать | список MAY_NOT |\n",
         ""),
        # Rule 1, the other way: a row promises a diagram the folder does not have.
        ([], "diagrams/README.md",
         "один раз, и что нельзя сказать второй раз.",
         "один раз, и что нельзя сказать второй раз.\n| `media-reader-08-no-such.md` | правило 8 | проверка READING |"),
        # Rule 1: the number a row names is not the number of the diagram it lists.
        ([], "diagrams/README.md",
         "| `media-reader-05-one-answer-one-code.md` | правило 5:",
         "| `media-reader-05-one-answer-one-code.md` | правило 3:"),
        # Rule 1: a row that names a diagram and says no fact about it.
        ([], "diagrams/README.md",
         "| правило 1: словарь и те, кто его читает | список READERS |",
         "| правило 1: словарь и те, кто его читает | |"),
        # Rule 2: a number the guard does not check the rule at — it checks seven, not eight.
        ([], "diagrams/media-reader-07-the-reading.md",
         "# Правило 7: чтение, из которого спрашивается правило",
         "# Правило 8: чтение, из которого спрашивается правило"),
        # Rule 2: the same number said twice, in the file name and in the title, and twice differently.
        ([], "diagrams/media-reader-04-where-a-wiring-is-built.md",
         "# Правило 4: где строится проводка",
         "# Правило 5: где строится проводка"),
        # Rule 3: the diagram points at a guard that is not there.
        ([], "diagrams/media-reader-05-one-answer-one-code.md",
         "Проверяет: `scripts/check_media_reader.py`, список CODES",
         "Проверяет: `scripts/check_no_such_guard.py`, список CODES"),
        # Rule 3: the line is there and names no guard — it checks nothing.
        ([], "diagrams/media-reader-01-vocabulary.md",
         "Проверяет: `scripts/check_media_reader.py`, список READERS.",
         "Проверяет: список READERS."),
        # Rule 3: the line itself is gone.
        ([], "diagrams/media-reader-01-vocabulary.md",
         "Проверяет: `scripts/check_media_reader.py`, список READERS. Отрицательный тест —\n"
         "`scripts/test_guards_fail.py`.\n",
         ""),
        # Rule 3: the guard has stopped holding the list the diagram points at.
        ([], "diagrams/media-reader-02-may-not.md",
         "Проверяет: `scripts/check_media_reader.py`, список MAY_NOT.",
         "Проверяет: `scripts/check_media_reader.py`, список MAY_NOT_OLD."),
        # Rule 4: the general view drops one of the rules it says it holds.
        ([], "diagrams/media-reader.md",
         'READ["Чтение борда — правило 7: CloudData::board_names, роутеры и ключи"]',
         'READ["Чтение борда: CloudData::board_names, роутеры и ключи"]'),
        # Rule 5: prose with no block is not a diagram, and the README cannot promise one.
        ([], "diagrams/media-reader-03-caption-and-key.md",
         "```mermaid",
         "```text"),
        # Rule 6: the legend describes a shape no diagram draws.
        ([], "diagrams/media-reader-02-may-not.md",
         "    classDef absence stroke-dasharray: 4 4;\n    class B,C,E absence;\n",
         ""),
        # Rule 6: a shape the diagrams draw is not in the legend.
        ([], "diagrams/README.md",
         " Штриховая рамка — отсутствие, названное как отсутствие.",
         ""),
        # Rule 6: the dashed frame says an absence, and the diagram that draws it stops naming that absence.
        ([], "diagrams/media-reader-02-may-not.md",
         "Отсутствие, превращённое в значение",
         "Нечто, превращённое в значение"),
    ],
    # The rules of the caravan's Rust: each breakage is a defect it exists to catch, in code that looks ordinary (docs/rust-code.md).
    "check_rust_contract": [
        # A comment pointing at the tree that left: a reader takes it for a place to look.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "// See `caravan/common/request_kind.py`.\n/// One answer for the fleet"),
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "// The twin of `RequestKind`.\n/// One answer for the fleet"),
        # A function outside an impl.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "pub fn loose(path: &str) -> bool {\n    path.is_empty()\n}\n\n/// One answer for the fleet"),
        # A `#[cfg(test)]` on one item hides nothing after it.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "#[cfg(test)]\nconst X: u32 = 1;\n\npub fn loose(path: &str) -> bool {\n    path.is_empty()\n}\n\n/// One answer for the fleet"),
        # A God function: one that has grown past the limit.
        ([], "rust/crates/rules/src/request_kind.rs", "    /// True for a chat's path.\n", "    fn long() -> u32 {\n" + "        let _x = 1;\n" * 70 + "        1\n    }\n\n    /// True for a chat's path.\n"),
        # A God file.
        ([], "rust/crates/rules/src/request_kind.rs", "/// One answer for the fleet", "/// One.\n" * 450 + "/// One answer for the fleet"),
        # State at module level: a marker that outlives what set it.
        ([], "rust/crates/proxy/src/queue.rs", "/// One request waiting.", "static BUSY: Mutex<u32> = Mutex::new(0);\n\n/// One request waiting."),
        ([], "rust/crates/proxy/src/queue.rs", "/// One request waiting.", "static mut BUSY: u32 = 0;\n\n/// One request waiting."),
        # A rule that reads the clock, a file, the environment: a snapshot then depends on when it runs.
        ([], "rust/crates/rules/src/policy.rs", "use serde_json::Value;", "use serde_json::Value;\nuse std::fs;"),
        ([], "rust/crates/rules/src/policy.rs", "use serde_json::Value;", "use serde_json::Value;\nuse std::env;"),
        ([], "rust/crates/proxy/src/watch.rs", "let now = proxy.clock.epoch();", "let now = std::time::SystemTime::now();"),
        # A socket type in the crate that reads through `Read`.
        ([], "rust/crates/wire/src/lines.rs", "use std::io::{self, Read};", "use std::io::{self, Read};\nuse std::net::TcpStream;"),
        # TLS outside its crate: a second idea of what a provider's certificate must be.
        ([], "rust/crates/proxy/src/provider_call.rs", "use net::{Dial, Stream};", "use net::{Dial, Stream};\nuse rustls::ClientConfig;"),
        # Absence drawn as a value, with no word on why: the defect that cost the most here.
        ([], "rust/crates/proxy/src/record.rs", 'put("firstByteMs", json!(facts.first_byte_ms));', 'put("firstByteMs", json!(facts.first_byte_ms.unwrap_or(0)));'),
        ([], "rust/crates/proxy/src/config.rs", "// absent-ok: \"\" is \"not known\" in the state file's `sourceCommit`, as in `StartRecord`: never a guess.\n", ""),
        # unsafe outside its one crate, and an allow that does not say why.
        ([], "rust/crates/rules/src/coerce.rs", "/// How Python's `bool`, `str` and `int` read a JSON value.", "/// x\npub unsafe trait Loose {}\n\n/// How Python's `bool`, `str` and `int` read a JSON value."),
        ([], "rust/crates/proxy/src/log.rs", '#[allow(clippy::print_stderr, reason = "this is the one place the proxy prints")]', "#[allow(clippy::print_stderr)]"),
        # A new package with no reason; a listed one that is gone: the list lies either way.
        ([], "rust/Cargo.lock", 'name = "httparse"', 'name = "left-pad"'),
        # A lint taken away, and a crate that does not take them.
        ([], "rust/Cargo.toml", 'unwrap_used = "deny"', 'unwrap_used = "allow"'),
        ([], "rust/crates/wire/Cargo.toml", "[lints]\nworkspace = true\n", ""),
        # A table one language does not run.
        ([], "rust/crates/rules/tests/contract.rs", 'table("levers")', 'table("other")'),
        # Two compilers.
        ([], ".gitlab-ci.yml", "image: rust:1.99.1-slim-bookworm", "image: rust:1.98.0-slim-bookworm"),
        ([], "deploy/nas/release_ship.py", 'IMAGE = "rust:1.99.1-slim-bookworm"', 'IMAGE = "rust:1.98.0-slim-bookworm"'),
        ([], "rust/rust-toolchain.toml", 'channel = "1.99.1"', 'channel = "stable"'),
    ],
    # The public mirror refuses a machine's name or address and the home network's domain: an
    # address written into a document, and a fleet machine's name in a fixture, must turn this red.
    # Both are put together here from halves: whole, they would be a leak in this public file.
    "check_public_leaks": [
        ([], "docs/security.md", "# Security: accounts, sessions and the fleet token\n",
         "# Security: accounts, sessions and the fleet token\n\nThe controller answers at " + "192." + "168.30.20.\n"),
        ([], "scripts/test_stand.py", 'print("сам стенд:")', 'print("' + "at" + 'las")'),
    ],
    # Every program the controller runs needs a container decision, and a
    # module running a machine program must ask first: a new program without a
    # decision, and a module that stopped asking, must turn this red.
    "check_container_answers": [
        ([], "rust/crates/admin/src/fleet/host_power.rs", "use ", 'const _DISKS: fn() = || drop(std::process::Command::new("lsblk"));\nuse '),
        ([], "scripts/check_container_answers.py", '    "status.rs": "git over the checkout', '    "fleet/host_power.rs": "named here and running nothing",\n    "status.rs": "git over the checkout'),
    ],
    # The image must carry what the running code reads: a folder the COPY list
    # leaves out, or that .dockerignore drops, must turn this red.
    "check_image_contents": [
        ([], "deploy/nas/release_ship.py", '"archive", "origin/main", "static", "cells", "VERSION"', '"archive", "origin/main", "static", "VERSION"'),
        ([], "deploy/nas/release_ship.py", '"archive", "origin/main", "static", "cells", "VERSION"', '"archive", "origin/main", "cells", "VERSION"'),
        ([], "Dockerfile", "COPY cells/ cells/\n", ""),
        ([], "Dockerfile", "COPY VERSION ./\n", ""),
    ],
    # The firewall is the operator's (one rule for the proxy range): a ufw call
    # in either shape — an argv list, a command string — must turn this red.
    "check_firewall_untouched": [
        ([], "rust/crates/admin/src/proxies/config.rs", "    const OWNED_FIELDS", '    const DOOR: [&str; 2] = ["sudo", "ufw"];\n\n    const OWNED_FIELDS'),
        ([], "rust/crates/admin/src/proxies/config.rs", "    const OWNED_FIELDS", '    const DOOR: &str = "sudo -n ufw allow 23001";\n\n    const OWNED_FIELDS'),
    ],
    "check_subscription_resets": [
        ([], "rust/crates/admin/src/routes/system.rs", "    const OPENAPI:", '    fn spend(app: &App) { drop(SubscriptionResetDesk::of(app).consume("a", "credit", "key", true)); }\n\n    const OPENAPI:'),
        ([], "static/js/pools.js", 'import { t } from "./i18n.js";', 'const _automaticReset = "/api/cloud-accounts/subscription-reset";\nimport { t } from "./i18n.js";'),
    ],
    "check_oauth_owner": [
        ([], "rust/crates/proxy/src/connection.rs", "/// A client's connection.", 'const _DUPLICATE: [(&str, &str); 1] = [("grant_type", "refresh_token")];\n\n/// A client\'s connection.'),
        ([], "rust/crates/admin/src/cloud/data.rs", "        CredentialVault::new(self.app.paths.provider_secrets_file.clone())", '        drop(std::fs::write(&self.app.paths.provider_secrets_file, "{}"));\n        CredentialVault::new(self.app.paths.provider_secrets_file.clone())'),
    ],
    "check_models_dir_source": [
        ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    fn models(llama_home: &std::path::Path) -> std::path::PathBuf { llama_home.join("models") }\n\n    /// A complete, self-contained start script.'),
        ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    fn models(llama_home: &str) -> String { format!("{llama_home}/models") }\n\n    /// A complete, self-contained start script.'),
    ],
    "check_messages_i18n": [
        ([], "static/js/i18n/ru.js",
         '  grpSampling:', '  grpSamplingRENAMED:'),
        # A Russian value left standing in another language's table — neither the
        # en-copy nor the english-phrase check sees it, which is how
        # `computeAuto: "авто"` sat in the Chinese one.
        ([], "static/js/i18n/zh.js",
         'computeAuto: "\u81ea\u52a8",', 'computeAuto: "\u0430\u0432\u0442\u043e",'),
        # An English sentence left in a non-latin table. The english-phrase rule
        # could not see one until 2026-10-07: under one re.IGNORECASE the ALLCAPS
        # identifier alternative stripped every latin word before it looked.
        ([], "static/js/i18n/zh.js",
         'computeAuto: "\u81ea\u52a8",', 'computeAuto: "Pick the size automatically",'),
        # A key written twice: the later line silently wins, so the loaded table
        # looks whole and only the file's text shows it (2026-10-07, a new key
        # took a name Routing already used).
        ([], "static/js/i18n/de.js",
         '  deleteAction: "L\u00f6schen",', '  deleteAction: "L\u00f6schen",\n  deleteAction: "Entfernen",'),
        # Words written without their diacritics (found 2026-10-13): German spelled out, Spanish dropped.
        # The file is the witness: it writes «für» and «sesión» right many times beside the plain one.
        # French and Vietnamese left with their tables on 2026-11-01; their shapes stay on samples
        # (test_i18n_untranslated.py).
        ([], "static/js/i18n/de.js",
         "g\u00fcnstig genug f\u00fcr Massen", "g\u00fcnstig genug fuer Massen"),
        ([], "static/js/i18n/es.js",
         "Se requiere iniciar sesi\u00f3n", "Se requiere iniciar sesion"),
    ],
    "check_i18n_calls": [
        ([], "static/js/system-page.js",
         'function bindSettingsBundle() {',
         'function bindSettingsBundle() {\n  const _leak = t("keyThatWasNeverDefined");'),
        # The /hf modules ask their own table, not the shared one.
        ([], "static/js/hf-page.js",
         'this.toast(hfT("networkError"));', 'this.toast(hfT("networkErrorNeverDefined"));'),
        # A language of the /hf table left in English: the key is there, so only
        # the translation rule can see it.
        ([], "static/js/hf-text.js",
         '    diskFitTitle: "No hay suficiente espacio en el disco de modelos",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # …and in a non-latin language, where only the english-phrase rule looks.
        ([], "static/js/hf-text.js",
         '    diskFitTitle: "模型磁盘空间不足",',
         '    diskFitTitle: "Not enough space on the models disk",'),
        # A word of the /hf table written without its accent beside the same word written right
        # (the table's own witness): the shared rule of check_messages_i18n looks here too.
        ([], "static/js/hf-text.js",
         '    sortDesc: "Absteigend — klicken für aufsteigend",',
         '    sortDesc: "Absteigend — klicken fuer aufsteigend",'),
        # A phrase of the one rule of "time left" worded otherwise on /hf than on the board: the same wait reads two ways on two
        # screens. The key is there, in every language, with its placeholders: only the mirror rule sees it.
        ([], "static/js/hf-text.js",
         '    moveEtaMinutes: "~{n} min left",',
         '    moveEtaMinutes: "≈{n} min left",'),
        # The rule learns a phrase no table has: the label would show the key itself, and neither t("…") nor hfT("…") names it.
        ([], "static/js/pace-rule.js",
         'if (minutes < 60) return say("moveEtaMinutes", { n: String(minutes) });',
         'if (minutes < 60) return say("moveEtaMinutesAndABit", { n: String(minutes) });'),
    ],
    "check_cell_form_text": [
        # A label written as plain text again: the cache switch's stood in English on every
        # other language's page (2026-10-13), and no other guard could see a sentence that
        # asks for no key.
        ([], "static/index.html",
         '<strong data-i18n="cacheModelsTitle">Cache model on host disk</strong>',
         '<strong>Cache model on host disk</strong>'),
        # The CSS rule that hides a field's descriptions goes: they show now, and the guard's
        # exemption for them is no longer true.
        ([], "static/css/monitor.css",
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}',
         '.topo-edit-form .field p:not(.field-note) {\n  display: block;\n}'),
        # …and the bare rule is back beside it: every note of every panel hidden again, as from
        # 2026-05-31 to 1.3.518, and nobody saw it.
        ([], "static/css/monitor.css",
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}',
         '.topo-edit-form .field p:not(.field-note) {\n  display: none;\n}\n.topo-edit-form .field p {\n  display: none;\n}'),
        # MODEL_NAME's only help was a hidden line under a field with no tip.
        ([], "static/js/llama-edit.js",
         'const _STATIC_TIP_FIELDS = ["MODEL_NAME", "COMMAND",', 'const _STATIC_TIP_FIELDS = ["COMMAND",'),
        # A note written as a plain paragraph of a field: the editor's CSS hides it.
        ([], "static/index.html",
         '<p class="field-note" data-i18n="vllmPanelNote">', '<p data-i18n="vllmPanelNote">'),
        # A note that is shown but never asked for a key: English on every other page.
        ([], "static/index.html",
         '<p class="field-note" data-i18n="strataPanelNote">', '<p class="field-note">'),
        # The NLLB model carrier without a `.field` of its own: hidden, it takes the languages with it.
        ([], "static/index.html",
         '<div class="field" id="tr-translateModelField">', '<div id="tr-translateModelField">'),
        # An exception that outlived its cause: an entry for an element that holds no untranslated prose
        # (the guard has none today; the entry is written into it here).
        ([], "scripts/check_cell_form_text.py",
         "EXCEPTIONS = {}", 'EXCEPTIONS = {"tr-purgeCacheNote": "an excuse that nothing needs any more"}'),
        # The model-cache note in English again, with no key: the words that stood here untranslated for
        # two months (until 1.3.525) must turn the guard red when they come back.
        ([], "static/index.html",
         '<span data-i18n="purgeCacheNoteBefore">Deletes downloaded .gguf files from</span>',
         '<span>Deletes downloaded .gguf files from</span>'),
        # A paragraph OUTSIDE a field is shown — the CSS hides only a field's paragraphs — so prose
        # in it needs its key like any other.
        ([], "static/index.html",
         '<div style="font-size:10px;opacity:.6;margin-bottom:4px" data-i18n="remoteCmdPathsHint">Binary and model paths resolved on remote host</div>',
         '<p style="font-size:10px;opacity:.6;margin-bottom:4px">Binary and model paths resolved on remote host</p>'),
    ],
    "check_tour_i18n": [
        ([], "static/js/onboarding-strings.js",
         '  tourCfgFieldsB:', '  tourCfgFieldsBRENAMED:'),
        # A step of the /hf tour still in English in another language.
        ([], "static/js/hf-text.js",
         '       "Was ausgew\u00e4hlt ist, wohin es kommt, ob es passt und ob etwas \u00fcberschrieben w\u00fcrde \u2014 bevor Sie auf Download klicken. Laufende Downloads (mit Abbrechen) und unterbrochene (mit Fortsetzen) sind ebenfalls hier zu finden."],',
         '       "What is selected, where it lands, whether it fits and whether anything would be written over \u2014 before you press Download. Running downloads (with Cancel) and interrupted ones (with Resume) live here too."],'),
        # The sign-in page's own list drifting from the app's: a label, and a language left in its table.
        ([], "rust/crates/admin/src/web/page_shell.html", '["de","\U0001F968 Deutsch"]', '["de","\U0001F37A Deutsch"]'),
        ([], "rust/crates/admin/src/web/page_shell.html", '    de:{langLabel:', '    nl:{langLabel:'),
        # A page drawn right to left again: the direction written by the board's language switch, a rule for it in a stylesheet.
        ([], "static/js/i18n.js", "  document.documentElement.lang = lang;\n", '  document.documentElement.lang = lang;\n  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";\n'),
        ([], "static/css/base.css", ".sys-back:hover { border-color: var(--accent); }", '.sys-back:hover { border-color: var(--accent); }\n:root[dir="rtl"] .sys-back { left: 0; }'),
    ],
    "testability_names": (
        ["--check"], "static/index.html",
        '<div id="tr-placementMap"',
        '<div data-t="hook-nobody-registered"></div>\n            <div id="tr-placementMap"'),
    "check_boot_guard": [
        ([], "static/system.html", 'data-t-state', 'data-t-state-DRIFTED'),
        # The boot's first word must be the first module that runs: moved down, a graph that never loads leaves nothing.
        ([], "static/js/main.js", 'import { BootStep } from "./boot-step.js";\nimport { initDialogLlamas } from "./dialog-llamas.js";',
         'import { initDialogLlamas } from "./dialog-llamas.js";\nimport { BootStep } from "./boot-step.js";'),
        # The writer and the reader of the step name must agree.
        ([], "static/js/boot-step.js", "window.__bootWaiting = what;", "window.__bootStep = what;"),
        # A step the banner can name, dropped from the boot.
        ([], "static/js/main.js", 'BootStep.waitsFor("/api/state");', ''),
    ],
    # The bar of every page is the template's, and the way back to the main board is in it (1.3.552): a page edited by hand, the
    # machine's window without its link (the defect that started this), a second bar, a stylesheet that takes the link away
    # elsewhere, the rule keyed on a word Routing shares with the board, a page with no row, and the views' words changed.
    "check_header": [
        ([], "static/routing.html", 'data-t="header-back" href="/board"', 'data-t="header-back" href="/boards"'),
        ([], "static/index.html",
         '      <a class="sys-back topbar-back" data-t="header-back" data-view-only="machine" href="/board"><span aria-hidden="true">←</span> <span data-i18n="boardPageName">Main board</span></a>\n',
         ''),
        ([], "static/models.html", '<!-- header:end -->\n', '<!-- header:end -->\n  <header class="topbar" data-t="header"></header>\n'),
        ([], "static/css/topology-board.css", 'html[data-board-view="machine"] body .topbar { min-width: 0; }\n',
         'html[data-board-view="machine"] body .topbar { min-width: 0; }\nhtml[data-board-view="machine"] .topbar-back { display: none; }\n'),
        ([], "static/css/base.css", 'html:not([data-board-view="machine"]) .topbar-back[data-view-only="machine"] { display: none; }',
         'html[data-board-view="main"] .topbar-back { display: none; }'),
        ([], "scripts/gen_header.py",
         '        "system": Page(file="system.html", title="System &amp; settings", title_key="systemSubtitleBrand",\n                       tour=False),\n', ''),
        ([], "static/js/board-view.js", 'return this.isMachine ? "machine" : "main";', 'return this.isMachine ? "machine" : "home";'),
    ],
    # A machine-level action that the board cannot take back must ask the name TYPED: each of the three, put back to
    # a dialog a click answers (or one whose suggestion Tab takes), must turn the guard red.
    "check_typed_machine_actions": [
        ([], "static/js/topology-render.js",
         'const ok = await appConfirmTyped(\n        t(hostPowerTextKey(hostId, "reboot"))',
         'const ok = await appConfirm(\n        t(hostPowerTextKey(hostId, "reboot"))'),
        ([], "static/js/topology-render.js",
         'const ok = await appConfirmTyped(\n        t(hostPowerTextKey(hostId, "poweroff"))',
         'const ok = await appPrompt(\n        t(hostPowerTextKey(hostId, "poweroff"))'),
        ([], "static/js/remote-cells.js",
         'if (!(await appConfirmTyped(question, name,', 'if (!(await appConfirm(question, name,'),
        # Typed, but not the machine's name: the words asked for are something else.
        ([], "static/js/topology-render.js",
         'hostId,\n        { confirmLabel: t("hostRebootOk")', '"reboot",\n        { confirmLabel: t("hostRebootOk")'),
    ],
    "check_field_homes": [
        ([], "static/js/constants.js",
         '"TEMPERATURE", "TOP_K", "TOP_P", "MIN_P"] }',
         '"TOP_K", "TOP_P", "MIN_P"] }'),
        # A runner panel renamed in the markup: the loader walks nothing, and the page's address had no panel to show in.
        ([], "static/index.html", 'id="tr-pageFields"', 'id="tr-pageFieldz"'),
    ],
    "check_runner_model_fields": ([], "contract/controller.json", '"modelField": "TRANSLATE_MODEL"', '"modelField": "NO_SUCH_FIELD"'),
    "check_command_mirrors": (
        [], "static/js/llama-edit.js",
        'llama-model-cache}/translate"', 'llama-model-cache}/NOWHERE"'),
    # A field riding through rebuilds must be named in every one: drop the
    # name at one boundary — the guard must name EXACTLY that one.
    "check_static_modules": [
        # The exact defect that shipped: an import list with a doubled comma.
        # `node --check` passes this file; the board dies at parse.
        ([], "static/js/topology-render.js",
         "  startRemoteStartWatch,\n", "  startRemoteStartWatch,,\n"),
        # Nothing left to parse — a check that checks nothing must say so.
        ([], "scripts/check_static_modules.py",
         'JS_DIRS = ("static/js", "static/js/i18n")', 'JS_DIRS = ("static/nowhere",)'),
    ],
    "check_board_live_patch": [
        # The live patcher restates a fact the builder already owns — the
        # shape that let a fixed line last exactly one poll tick.
        ([], "static/js/topology-render.js",
         '_liveSet(nodeEl, "[data-live-hostage]", hostAgeText(n));',
         '_liveSet(nodeEl, "[data-live-hostage]", t("nodeScoutLastReport", { ago: `${n.ageSeconds}s` }));'),
        # The single source stops building it — nothing left to protect.
        ([], "static/js/topology-nodes.js",
         't("nodeScoutLastReport", { ago: _ageShort(age) })', '`${_ageShort(age)} ago`'),
        # 1.3.588: the patch reads a cell's request count itself — the line's work has two rules again, and the ring and `last` can disagree.
        ([], "static/js/topology-render.js",
         "const speed = new CellSpeed(s, running);", "const speed = new CellSpeed(s, running); const busyNow = s.requestsProcessing > 0;"),
        # The class stops reading the count — nothing left to protect.
        ([], "static/js/cell-speed.js",
         "this.requests = CellSpeed.count(s.requestsProcessing);", "this.requests = CellSpeed.count(s.requests);"),
        # The class goes away (renamed) — the guard says there is nothing to check, instead of staying green.
        ([], "static/js/cell-speed.js", "export class CellSpeed {", "export class CellSpeeds {"),
        # 1.3.589: the machine's token speed panel reads the count itself — a second place that says who works.
        ([], "static/js/charts.js",
         "this.running().filter((s) => new CellSpeed(s, true).working)", "this.running().filter((s) => s.requestsProcessing > 0)"),
        # 2026-11-07: the patch sums a cell's cards itself — the badge the builder drew and the one the tick writes read the report two ways.
        ([], "static/js/topology-render.js",
         "...CellMemory.measured(s, n) });",
         "...CellMemory.measured(s, n), vramBytes: Object.values(s.gpuMem || {}).reduce((a, b) => a + b, 0) * 2 ** 20 });"),
        # The class stops reading the cards' figures — nothing left to protect.
        ([], "static/js/cell-memory.js", "const mem = s.gpuMem || {};", "const mem = s.gpuMemory || {};"),
    ],
    "check_proxy_id_namespace": ([], "rust/crates/admin/src/domain/client_proxy.rs",
                                 'pub const PROXY_ID_PREFIX: &str = "skynet:proxy:";', 'pub const PROXY_ID_PREFIX: &str = "controller:proxy:";'),
    # `grep -q` on a pipe under pipefail: a machine with two cards read "no NVIDIA GPU" (2026-11-02).
    "check_shell_pipes": (
        [], "rust/crates/scout/scripts/install-llama.sh",
        'grep -i "nvidia" >/dev/null', 'grep -qi "nvidia"'),
    # A flag llama.cpp took away: a cell with it says "invalid argument" and does not start (2026-11-03).
    "check_llama_flags": (
        [], "rust/crates/admin/src/config/args/switches.rs",
        'self.push(&["--load-mode", &load_mode]);', 'self.push(&["--no-mmap", &load_mode]);'),
    # A default cell's number must be the sentence's own. Cards that name a value twice are not here; a row that
    # copies one number from another card, or names a mode, is a choice, not a fact.
    "check_model_defaults": [
        # The table says 1.2 while its sentence still says 1.0: the number is no longer read out of the sentence.
        ([], "contract/model_defaults.json",
         '"TEMPERATURE": "1.0", "TOP_P": "1.0"', '"TEMPERATURE": "1.2", "TOP_P": "1.0"'),
        # A number written into a sentence that never said it.
        ([], "contract/model_defaults.json",
         '"Сэмплинг: temperature=1.0, top_p=0.95, top_k=64 — для всех задач."',
         '"Сэмплинг: temperature=1.0, top_p=0.90, top_k=64 — для всех задач."'),
        # The same numbers, now named for one mode: which of the two to run depends on the mode, so it is a choice.
        ([], "contract/model_defaults.json",
         '"Сэмплинг: temperature 1.0, top_p 0.95, top_k 64 — для любых задач."',
         '"Сэмплинг с рассуждениями: temperature 1.0, top_p 0.95, top_k 64."'),
        # A use word is a mode word: "для текста" says the values for text, not for the model. It is read at the start
        # of a word, which is why an intact tree with "Контекст 1M токенов" is green — there "текст" is inside a word.
        ([], "contract/model_defaults.json",
         '"Сэмплинг: temperature 1.0, top_p 1.0. Контекст 1M токенов, max_tokens ≥ 256K."',
         '"Сэмплинг для текста: temperature 1.0, top_p 1.0. Контекст 1M токенов, max_tokens ≥ 256K."'),
        # A field the caravan cannot say: the cards name a penalty, the program writes no flag for one.
        ([], "contract/model_defaults.json",
         '"fields": ["TEMPERATURE", "TOP_P", "TOP_K", "MIN_P", "CTX_SIZE", "N_PREDICT"]',
         '"fields": ["TEMPERATURE", "TOP_P", "TOP_K", "MIN_P", "CTX_SIZE", "N_PREDICT", "PRESENCE_PENALTY"]'),
        # A row the program no longer states: the guard would be holding a copy, not the table.
        ([], "rust/crates/admin/src/models/defaults.rs",
         '("gemma-4-31B-it-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),', ''),
    ],
    "check_cell_self_capture": (
        [], "cells/whisper_server.py",
        '                    state["downloaded"]', '                    self.state["downloaded"]'),
    # A provider's refusal sent as the board's own 401: the page goes to /login.
    "check_board_401": ([], "rust/crates/admin/src/cloud/subscription.rs", "sign in again in the account's ⚙\"),\n                        502,", "sign in again in the account's ⚙\"),\n                        401,"),
    "check_cell_python_floor": (
        # moonshine's signatures carry `str | None`: without the deferral the cell dies on 3.9 at import.
        [], "cells/moonshine_server.py",
        "from __future__ import annotations\n", ""),
    "check_installer_assets": (
        [], "scripts/install-seamless.sh",
        'install -m 0644 "${SRC}/cell_base.py"      "${HOME}/cell_base.py"\n', ''),
    "check_undefined_names": (
        [], "cells/moonshine_server.py", "import wave\n", ""),
    "check_ci_coverage": [
        # A script exists on disk but the gate never calls it — green on the
        # author's machine, run nowhere else.
        ([], ".github/workflows/ci.yml",
         "          python3 scripts/test_engine_cell_server.py\n", ""),
        # A script IS named, but in a second `run:` of a step that already has
        # one. YAML keeps a single key, so the line never runs — and the guard
        # used to see the name and call it covered.
        ([], ".github/workflows/ci.yml",
         "        run: python3 scripts/check_boot_smoke.py\n",
         "        run: python3 scripts/check_boot_smoke.py\n"
         "        run: python3 scripts/test_engine_cell_server.py\n"),
    ],
    "check_test_ports": [
        # A test writes the eight lines again — bind to port 0, read the number, close, return it — and asks for ports the old way,
        # one number twice: the race that killed a server of test_proxy_forward.py with "Address already in use".
        ([], "scripts/test_engine_cell_server.py",
         "from _ports import free_port  # noqa: E402\n",
         "def free_port():\n    sock = socket.socket()\n    sock.bind((\"127.0.0.1\", 0))\n    port = sock.getsockname()[1]\n    sock.close()\n    return port\n"),
        # The same ask written the other way round — the empty host, as a socket is made for every address — is still a free port asked
        # of the kernel by the test itself.
        ([], "scripts/test_engine_cell_server.py", "dead_port = free_port()\n",
         "_sock = socket.socket()\n_sock.bind((\"\", 0))\ndead_port = _sock.getsockname()[1]\n_sock.close()\n"),
        # And in single quotes: the style of the quotes does not make the ask a different one.
        ([], "scripts/test_engine_cell_server.py", "dead_port = free_port()\n",
         "_sock = socket.socket()\n_sock.bind(('127.0.0.1', 0))\ndead_port = _sock.getsockname()[1]\n_sock.close()\n"),
        # A `free_port` of its own that binds nothing (a fixed number, a counter) is no pool either: it gives the same port to two servers.
        ([], "scripts/test_gr00t_server.py", "from _ports import free_port  # noqa: E402\n", "def free_port():\n    return 5000\n"),
    ],
    "check_context_window": ([], "rust/crates/admin/src/fleet/launch.rs", "    /// A complete, self-contained start script.", '    const TRAINED: &str = "n_ctx_train";\n\n    /// A complete, self-contained start script.'),
    # The old habit back: an entry written at the top of `## Unreleased` instead of a file in changelog.d/ (scripts/changelog.py).
    # The rules on single files have their cases in scripts/test_changelog.py: a file here would be gone with the next release.
    "check_changelog_fragments": ([], "CHANGELOG.md", "Записи до выпуска — файлами в `changelog.d/`",
                                  "- Новая запись, как раньше.\n\nЗаписи до выпуска — файлами в `changelog.d/`"),
    "check_why_refs": (
        [], "docs/why.md",
        "`rust/crates/admin/src/fleet/cell_ops.rs` (`client_server_slot_delete`)", "`rust/crates/admin/src/fleet/gone.rs` (`client_server_slot_delete`)"),
    "check_oop_contract": [
        # A cell forgets a member the base declares abstract: it starts fine and
        # dies on the first request. The guard must name the member.
        ([], "cells/tts_server.py", "    def handle(self, body, headers, path):", "    def handle_work(self, body, headers, path):"),
        # Logic creeps back into a class module as a fat top-level function.
        ([], "static/js/canvas.js", "export const board = new Board();",
         "export const board = new Board();\nfunction strayLogic(a) {\n  if (a) {\n    return 1;\n  }\n  return 2;\n}"),
        # The ratchet: a module that is already class-based stays on the list —
        # the list lies and rule 3 stops watching it.
        ([], "scripts/check_oop_contract.py", '    "cables.js": "scripts/test_js_cables.py",',
         '    "cables.js": "scripts/test_js_cables.py",\n    "canvas.js": "scripts/test_js_canvas.py",'),
        # A reason that names a snapshot which does not pin this module.
        ([], "scripts/check_oop_contract.py", '    "cables.js": "scripts/test_js_cables.py",', '    "cables.js": "scripts/test_js_charts.py",'),
        # The recorded decision disappears from the public module reference.
        ([], "docs/frontend.md", "- Kept as functions by decision (OOP rewrite, decision 19, 2026-09-05):", "- Was once kept as-is (OOP rewrite, decision 19, 2026-09-05):"),
    ],
    # The vocabulary itself: a cell that names its job in a word nobody else
    # uses is findable only by whoever already knows its engine.
    # The boot smoke must see a controller that does not start, and a fresh one
    # that is open again before its first account (the door be41edff closed).
    "check_boot_smoke": [
        ([], "scripts/check_boot_smoke.py", "self.signed_in(self.first_account())", "self.signed_in(self.first_account()); self.failures.append('a guard that cannot fail')"),
    ],
    "check_cell_kinds": (
        [], "cells/whisper_server.py",
        'kinds = ["asr", "stt.whisper"]', 'kinds = ["stt.whisper"]'),
    # A cell server reads a form with cell_base.Form and with nothing of its own (sinapse's ears, 2026-10-19: two of five copies of
    # the reader cut the last bytes of a recording): a copied reader, and a strip of a form's own bytes, must each turn this red.
    "check_cell_forms": [
        ([], "cells/tts_server.py", "from cell_base import CellServer, Form, Recording, Refusal   # noqa: E402\n",
         "from cell_base import CellServer, Form, Recording, Refusal   # noqa: E402\n\n\ndef _extract_file(body, ctype):\n    return None\n"),
        ([], "cells/moonshine_server.py", 'raw = Form(body, headers.get("Content-Type", "")).file()',
         'raw = Form(body, headers.get("Content-Type", "")).file().rstrip(b"\\r\\n-")'),
    ],
    "check_cell_health_contract": (
        [], "cells/whisper_server.py",
        '    engine = "faster-whisper"\n', ''),
    # A route that cannot say what it does: /openapi.json would carry an empty
    # summary, a draft left UNSURE, and the page for people that drifted from
    # the code — the hand-written list had fallen 16 paths behind.
    "check_api_spec": [
        ([], "rust/crates/admin/src/routes/openapi.json", '"summary": "This API as OpenAPI 3.1: every route, what it does, what it reads, who may call it",', '"summary": "",'),
        ([], "rust/crates/admin/src/routes/openapi.json", '"summary": "This API as OpenAPI 3.1: every route', '"summary": "UNSURE: This API as OpenAPI 3.1: every route'),
        ([], "docs/http-api.md", '| `GET /openapi.json` | open |', '| `GET /openapi.json` | admin |'),
    ],
    # A promise file keeps a day the program quoted as it was written (scripts/check_frozen_day_words.py). The intact tree is
    # green here, and that is the other half of the rule: a word of the run is right where the program computed the day
    # (`"date": "<today>"` in the journal rows). The first breakage is the defect that happened; the second shows the guard
    # reads every promise file, not only the one where the defect was found.
    "check_frozen_day_words": [
        ([], "tests/frozen/scout.jsonl", '"description": "(2026-11-03) `{path, how}`', '"description": "(<today>) `{path, how}`'),
        ([], "tests/frozen/admin.jsonl", '"date": "<today>"', '"description": "<today>"'),
        # The other half of the same rule: a promise holds `lastFired`, and the program writes that day only for a
        # schedule time the clock has already passed. A scenario time that can still be ahead of the run makes the
        # promise green only on the hours after it — pipelines #596, #603, #604, all before 03:30.
        ([], "scripts/test_rust_admin_conformance.py",
         '{"schedule": {"enabled": True, "at": "00:00", "daily": False}}',
         '{"schedule": {"enabled": True, "at": "23:59", "daily": False}}'),
    ],
    # A pin may not hold a value the controller reads from the internet (scripts/check_conformance_offline.py): the test writes its own copy, fresh for
    # its day, and the pins still answer that copy. The three ways this guard exists for: a copy taken away, a copy written with the fixture's date
    # (which the program never reads), and a copy the pins no longer answer.
    "check_conformance_offline": [
        ([], "scripts/test_rust_admin_conformance.py", "        self.codex()\n", ""),
        ([], "scripts/test_rust_admin_conformance.py", '"checkedAt": int(time.time())', '"checkedAt": self.WHEN'),
        ([], "scripts/test_rust_admin_conformance.py", '"codexNpm": {"version": "0.166.0"', '"codexNpm": {"version": "0.168.0"'),
        # The half that was already fixed before this guard existed: the copy of LiteLLM's table. Taken away, the pins hold whatever GitHub says today.
        ([], "scripts/test_rust_admin_conformance.py", "        self.pricing()\n", ""),
        # A copy with no date: nothing says when it was written, so the program goes to the internet.
        ([], "scripts/test_rust_admin_conformance.py", '"codexNpm": {"version": "0.166.0", "checkedAt": int(time.time())}', '"codexNpm": {"version": "0.166.0"}'),
    ],
    # Everything of the caravan opens in the tab the operator is in (the owner, 2026-10-17): a link of the board that asks
    # for a window of its own, a script that opens a new tab, and a page that leaves its tab through window.open in a
    # place that used to be an exception must each turn this red.
    # Every node a test starts gets NODE_FLAGS from scripts/_node.py (--single-threaded: node hung in process.exit,
    # 2026-10-21): a runner that builds its own command line again, a NODE_FLAGS without the flag, and a script that finds
    # node by itself must each turn this red. The hook is put together from halves: whole, it would be a hook written by
    # hand in this file.
    # The parts take their colours, font sizes and radii from ui.css's tokens, and the stylesheet styles every class the
    # parts draw: a raw colour in a part's rule, and a class a part draws that nothing styles, must turn this red.
    "check_ui_tokens": [
        ([], "static/css/ui.css",
         ".ui-row--live { background: color-mix(in srgb, var(--ui-good) 6%, transparent); }",
         ".ui-row--live { background: #12301f; }"),
        ([], "static/js/ui-parts.js",
         'quiet: "ui-btn ui-btn--quiet"',
         'quiet: "ui-btn ui-btn--hush"'),
    ],
    "check_node_start": [
        ([], "scripts/_js_pins.py", "probe_args(node, harness, path), capture_output=True",
         "[node, \"--import\", f\"data:text/javascript," + "import {{ register }} from 'node:module'; "
         "register('{harness.as_uri()}');\", str(path)], capture_output=True"),
        ([], "scripts/_node.py", 'NODE_FLAGS = ("--single-threaded",)', "NODE_FLAGS = ()"),
        ([], "scripts/check_static_modules.py", "    node = find_node()\n", '    node = shutil.which("node")\n'),
    ],
    # Every Rust test binary cargo starts goes through scripts/rust_test_runner.py (2026-11-04: an abandoned `cargo test` spun two
    # hung tests on a Mac for three days). The root config that stops naming the runner, a CI job that names its own, and a limit
    # the CI job's timeout would beat must each turn this red.
    "check_rust_test_start": [
        ([], ".cargo/config.toml", 'runner = "scripts/rust_test_runner.py"', ""),
        ([], ".gitlab-ci.yml", "    CARGO_TERM_COLOR: never\n",
         "    CARGO_TERM_COLOR: never\n    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER: \"\"\n"),
        ([], "scripts/rust_test_runner.py", "    LIMIT = 300.0\n", "    LIMIT = 3600.0\n"),
    ],
    "check_same_tab_links": [
        ([], "static/index.html", 'href="/models" data-t="header-models"', 'href="/models" target="caravan-models" data-t="header-models"'),
        ([], "static/js/topology-dnd.js", 'window.location.assign("/routing");', 'window.open("/routing", "_blank");'),
        ([], "static/js/hf-downloads.js", "this.go = go || ((url) => globalThis.location.assign(url));", 'this.go = go || ((url) => globalThis.open(url, "_blank"));'),
    ],
    # Every cell listens on its machine's loopback (step 7 of the owner's plan, 2026-11-08). Each breakage is a cell open to the whole
    # network again the day the owner's ufw rule is gone: a script's own address, a Python server's, a variable the environment may
    # say otherwise, a builder's word, and the two copies of the address parting.
    "check_cell_listen": [
        ([], "cells/run_vllm_omni.sh", '--host 127.0.0.1 --port "$PORT"', '--host 0.0.0.0 --port "$PORT"'),
        ([], "cells/cell_base.py", "_Server((LISTEN, self.port)", '_Server(("", self.port)'),
        ([], "cells/run_inferssd.sh", "export LLAMA_SERVER_HOST=127.0.0.1", 'export LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:-127.0.0.1}"'),
        ([], "rust/crates/admin/src/domain/runner/vllm.rs", "CellDoor::LISTEN.to_string(),", '"0.0.0.0".to_string(),'),
        ([], "cells/cell_base.py", 'LISTEN = "127.0.0.1"', 'LISTEN = "127.0.0.2"'),
    ],
    # One delivery at a time (deploy/nas/release_ship.py, DeliveryLock). Each breakage is a way two deliveries could run at once again.
    "check_delivery_lock": [
        # The delivery no longer takes the lock.
        ([], "deploy/nas/release_ship.py", '        with self.locked("ship"):\n            self.deliver()', "        self.deliver()"),
        # A subclass with an entry of its own that skips the lock: ScoutShip.ship runs its body bare.
        ([], "deploy/nas/scout_ship.py", '    def deliver(self):\n        """The scout of origin/main', '    def ship(self):\n        """The scout of origin/main'),
        # A taken lock lets the run go on.
        ([], "deploy/nas/release_ship.py", '            raise SystemExit(f"another delivery holds the lock', '            return self or SystemExit(f"another delivery holds the lock'),
    ],
}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  — ' + str(detail)[:200]}")


def run_guard(tree, guard, args):
    proc = subprocess.run([sys.executable, f"scripts/{guard}.py", *args],
                          cwd=tree, capture_output=True, text=True, timeout=180)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def tracked_files():
    """Tracked files AND untracked ones git is not ignoring.

    `git ls-files` alone misses a file that exists but has never been staged —
    which is the normal state of a tree mid-sync, and of any tree where a new
    guard was just written. The copy then lacked the very script under test and
    the failure read as "the guard is broken" rather than "the guard is not in
    the copy".
    """
    out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def main():
    files = tracked_files()
    guards = sorted(p.stem for p in (ROOT / "scripts").glob("check_*.py"))
    guards.append("testability_names")

    unlisted = sorted(set(guards) - set(BREAKAGES))
    if unlisted:
        print(f"guard self-test: FAILED — no breakage defined for {unlisted}\n"
              f"  a guard with no negative test is a guard nobody has seen fail.",
              file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="caravan-guards-") as tmp:
        tree = Path(tmp) / "tree"
        for rel in files:
            src = ROOT / rel
            if not src.is_file():
                continue
            dst = tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        for guard in guards:
            # A guard is required to fail two ways, but this harness used to try
            # only one of them — so the second way was never watched fail. A
            # value may now be a LIST of breakages; each is applied to the clean
            # tree in turn.
            spec = BREAKAGES[guard]
            breakages = spec if isinstance(spec, list) else [spec]
            args = breakages[0][0]

            code, out = run_guard(tree, guard, args)
            missing = _missing_tool(out)
            if missing:
                # "cannot run here" is not "cannot fail". check_messages_i18n
                # shells out to node, which the controller does not have; calling
                # that a guard failure would teach the reader to ignore a red
                # line that sometimes means something. Said out loud, and
                # counted apart, so a skip can never pass for a pass.
                SKIP.append(f"{guard} (нет {missing})")
                print(f"  skip {guard}: не запускается здесь — нет {missing}")
                continue
            check(f"{guard}: green on an intact tree", code == 0, out)
            if code != 0:
                continue                      # a red baseline makes the next check meaningless

            for index, (args, rel, find, replace) in enumerate(breakages):
                label = guard if len(breakages) == 1 else f"{guard} [{index + 1}]"
                target = tree / rel
                if not target.is_file():
                    # The public mirror leaves the private deployment out (deploy/nas/): a breakage of a file this tree
                    # does not have cannot be made here. Said and counted apart, so a skip never passes for a pass.
                    SKIP.append(f"{label} (нет {rel})")
                    print(f"  skip {label}: в этом дереве нет {rel}")
                    continue
                original = target.read_text(encoding="utf-8")
                if find not in original:
                    check(f"{label}: its breakage still applies", False,
                          f"{rel} no longer contains the anchor {find!r} — update BREAKAGES")
                    continue
                check(f"{label}: its breakage still applies", True)

                target.write_text(original.replace(find, replace, 1), encoding="utf-8")
                code, out = run_guard(tree, guard, args)
                check(f"{label}: RED once broken", code != 0,
                      f"exit 0 — it did not notice. Output: {out[:160]}")
                target.write_text(original, encoding="utf-8")

    tail = f", {len(SKIP)} skipped ({'; '.join(SKIP)})" if SKIP else ""
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed{tail}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
