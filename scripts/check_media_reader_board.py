#!/usr/bin/env python3
"""CI guard: the board's reader row says the answer the rule gave, and never names a state of its own.

The block was written as a page that could work a state out: it had the model's name in hand, and a page holding a name can
decide what that name means. `qwen3-vl-8b-instruct` is the case: its name says vision, its facts say `text`. A block that
read the state off the name would draw "reads" for a board whose reader cannot take the picture, while the entry refused the
same request with `media_reader_cannot` — the board and the journal saying two different things about one request, which is
the same defect `check_media_reader.py` is for, moved to the page.

The block was also written as one row per pool, and that is the second defect here: the reader is a fact of the board, so a
row per pool held the same name as many times as there are pools and could answer the same name differently for two of them.
One row, for the whole board, is the fact said once.

The rule, held here:
1. The words the block can show are the arms of `Reader::word()`, in both directions. An answer the rule has and the block
   has no key for is a board that stops saying which absence it was; a word the block has and the rule does not is a state
   invented on the page. An arm the board's row cannot show is held as `board_shows: false` rather than as a key the page
   would never use, and is named in the module's own words: `itself` answers only where a pool is named, and the board's row
   names none — so the case that answers it must name a pool, or the rule would not answer it.
2. The words the module holds are read from the module (`ReaderBlock.WORDS`), not guessed: a copy on the page is the same
   vocabulary said a second time.
3. Every key the module asks `t()` for is defined in all six languages, because the block shows a state in the language the
   operator reads, and a missing key in one file is a board that falls back to English for one person and not for another.
4. The colours hold the same words: `.pb-reader-row[data-t-state="…"]` in `static/css/pool-board.css`. A state the rule has
   and the CSS cannot colour is the answer the operator would read as an ordinary row; a colour for a word the board cannot
   draw is a rule that cannot go red.
5. `data-t-state` is written from what the board says for its reader (`reader.answer`), never worked out here — not from the
   name, not from what a model promises, not from a pool's field. A page that works the state out is the fact read a second
   way. The row has no pool's id to name itself by, so it names itself `reader` in `data-t-id`.
6. The flow lights the reader's cable only by what a request names as its reader, and only when a client is named; the
   reader's own request (`readerFor`) lights the reader's cable alone, never its client's. The key is
   `ReaderBlock.key()` — the kind alone, with no pool after it, because one board has one reader. The pin that runs the flow
   names the key as the module says it, so a key invented in the test is caught too.
7. Every group of `contract/media_reader_board.json` has its absence: the answer with no key (a word the table cannot say, or
   an arm the board's row cannot show), the row that names nothing, the key with no name, the dot that is not there, the block
   that names nothing and is drawn anyway, the save body that names no name, the flow case with no reader named. A table that
   can answer every case it names cannot say what it does when a name is not there. Every case says `why`, and the flow cases
   are values, not promises: `PoolFlow.way` takes `(item, port, pools)`, so a pin that normalizes its arguments invents a
   shape of its own and the guard would be held to that.
8. The order of the Pools column is said once, in `poolsHtml`, and the table's `column` group holds it: Direct, the reader
   block, the pool cards. Nothing in that column pins itself — Direct is simply the first block (the owner, 2026-11-06) — so a
   part has no `position:` of its own, and the pin `the_reader_block_sits_below_direct` runs the group, including the parts it
   names as not drawn.
9. Two bodies, each said once: `PoolCards.body(pool)` puts the pool under `pool` for the pool's door, and
   `ReaderBlock.body(reader)` puts the name under `reader` for the board's reader door. The door reads the body under
   `EntryModels::READER_FIELD`, the same word the module writes, so the page and the door cannot name the key differently;
   and the writing keeps nothing named as nothing, not as an empty name. A cable that lands and a cable that is cut both go
   through `ReaderBlock.body`; a body built in the page is the shape said a second way.
10. The names a test finds the block by are the names published in `scripts/testability_names.py`, including the `data-t-id`
    the row names itself by — `reader`, because the row is the board's and has no pool's id — and
    `scripts/test_js_reader_block.py` runs the table.
11. The field the block reads has a writer: the board's answer carries `reader` from `PoolDesk::reader`, built from the
    reading the rest of the answer reads (`topology::cloud_part`). The block and every pin read `top.reader`, and the pins
    feed it by hand, so a board whose answer never carries it draws "not named" whatever the operator saved, while the page,
    its pins and the door all agree. That is what the merge request that made the reader the board's fact shipped on
    2026-11-06: `PoolDesk::reader` was written and called by nobody.

Run: python3 scripts/check_media_reader_board.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _contract import Contract  # noqa: E402
from _rust_source import RustSource  # noqa: E402

RULE = "rust/crates/rules/src/media_reader.rs"
BLOCK = "static/js/reader-block.js"
FLOW = "static/js/pool-flow.js"
FLOW_PINS = "scripts/test_js_cable_flow.py"
CSS = "static/css/pool-board.css"
BOARD = "static/js/pool-board.js"
POOL_MODULE = "static/js/pools.js"
DOOR = "rust/crates/admin/src/routes/pools.rs"
EDITS = "rust/crates/admin/src/cloud/pool_edits.rs"
SNAPSHOT = "scripts/test_js_reader_block.py"
COLUMN_TEST = "scripts/test_js_pool_board.py"
HOOKS = "scripts/testability_names.py"
RUNNER = "rust/crates/rules/tests/contract.rs"
TOPOLOGY = "rust/crates/admin/src/topology/mod.rs"
STATE = "rust/crates/admin/src/cloud/pool_state.rs"
#: Where the board's answer gets the row the block reads, and what that row is built from: the reading the answer reads.
TOPOLOGY_SAYS = '"reader": PoolDesk::reader(live),'
STATE_SAYS = "pub fn reader(named: &EntryModels) -> Value {"
#: The word a reader is wired for, named once in `EntryModels::READER_WORD`; the table asks the same word.
READER_WORD = "image"
LOCALES = ("en", "ru", "de", "es", "zh", "ar")

#: What the rule must say for the block to have anything to read: the answer as one word, said once.
RULE_SAYS = ["pub fn word(&self) -> String", "pub fn writes(&self) -> bool",
             "Self::Reads => \"reads\".to_string()", "Self::Itself(_) => \"itself\".to_string()",
             # `itself` is answered only where a pool is named, so the board's row cannot have it: the reading is asked with
             # `None`, and that is what the table holds to.
             "pub fn is_itself(&self) -> bool {", "self.for_pool.as_ref() == Some(&self.model)"]

#: What the block must say, and where the word comes from. `rowFacts` is the one place a row is read, so the markup and the
#: test read the same words; `key` and `body` are the one places the cable's key and the door's body are said.
BLOCK_SAYS = ["static HOOKS = { block: \"pb-reader-block\", row: \"pb-reader\", id: \"reader\" }",
              "static PREFIX = \"reader\"", "static WORDS = {", "static label(word)",
              "static rowFacts(reader)", "const facts = ReaderBlock.rowFacts(reader);", "reader?.answer",
              "static key()", "return ReaderBlock.PREFIX;", "static wiredKeys(reader)",
              "static state(reader)", "return reader?.name ? \"named\" : \"quiet\";", "static body(reader)",
              "return { reader: reader ?? null };", "static html(reader)",
              "data-t-state=\"${escapeHtml(facts.state)}\"", "data-t-id=\"${ReaderBlock.HOOKS.id}\"",
              "t(\"pbReaderNotNamed\")"]

#: What the block may not say: a state worked out of a name, a state named by hand, a pool's field read on the board's row,
#: or a word taken from the module's own table instead of the rule's.
BLOCK_MAY_NOT = [
    (re.compile(r'\.includes\("(vl|vision)"\)|startsWith\("(qwen|gpt|llama)"\)'),
     "a state worked out of a name — the answer comes from `Reader::word()`, read onto the board by `pool_state.rs`"),
    (re.compile(r'[:=]\s*"(reads|cannot take|not said|unknown|itself|nothing)"'),
     "a state named by hand in the page — the word comes from `Reader::word()`, not from here"),
    (re.compile(r'data-pb-in'), "an input dot on a reader row — the absence is named, not drawn"),
    (re.compile(r'return "";'), "the block not drawn when nothing is named — the row has to say which absence it is"),
    (re.compile(r'pool\??\.reader|pool\??\.wiring|top\??\.pools'),
     "a pool's field read on the board's row — the reader is one fact for the board, and `top.reader` is where the board says it"),
    (re.compile(r'key\([^)]+\)'), "a cable key built with a pool in it — the key is the board's, said once by "
                                  "`ReaderBlock.key()` with no argument"),
]

#: The same for the flow: the light comes from what the request names, and the key from the module, not from a pool.
FLOW_MAY_NOT = [
    (re.compile(r'\$\{ReaderBlock\.PREFIX\}:\$\{pool\}'), "the reader's key written here with a pool after it — one board, "
                                                          "one reader, one cable, so a key with a pool in it names one cable "
                                                          "per pool for one fact"),
    (re.compile(r'`reader:'), "the reader's key written by hand — it is `ReaderBlock.key()`, said once"),
]
#: The two lines that light the reader's cable: a request that names the reader that read for it, and the reader's own request,
#: which lights that cable alone.
FLOW_SAYS = ["const read = item?.readerName ? [ReaderBlock.key()] : [];", "if (item?.readerFor) return [ReaderBlock.key()];"]

#: The words the block's own table must hold to, read from the arms of `word()`.
ARM = re.compile(r'Self::\w+(?:\([^)]*\))?(?: if [^\n]*)? => "([a-z ]+)"\.to_string\(\)', re.M)
WORD_TABLE = re.compile(r'^\s+"([a-z ]+)": "(pbReader\w+)",', re.M)
#: The words the module asks a language for, so the guard checks what the module actually shows.
WORD_CALL = re.compile(r't\("(pbReader\w+)"\)')


def main() -> int:
    problems = []
    code = {rel: lines for rel, lines in RustSource.files(".")}
    rule = "\n".join(code.get(RULE, []))
    if not rule:
        problems.append(f"{RULE}: the file that holds the answers is gone")
    for phrase in RULE_SAYS:
        if phrase not in rule:
            problems.append(f"{RULE}: the rule no longer says {phrase!r} — the block has nothing to read")

    arms = ARM.findall(rule)
    if not arms:
        problems.append(f"{RULE}: `word()` has no arms the guard can read — it is looking at nothing")

    block_text = (ROOT / BLOCK).read_text(encoding="utf-8")
    if not block_text:
        problems.append(f"{BLOCK}: the block is gone")
    board_text = (ROOT / BOARD).read_text(encoding="utf-8")
    if not board_text:
        problems.append(f"{BOARD}: the column is gone")

    # 1. the table's answers, held to the arms both ways, and held to the program that runs them.
    table = Contract.table("media_reader_board")
    answers = table.get("answers", [])
    if not answers:
        problems.append("contract/media_reader_board.json: no `answers` cases")
    for case in answers:
        if not case.get("why"):
            problems.append("contract/media_reader_board.json: a case with no `why` — the table holds the rule, not the reason")
        if case.get("asked") != READER_WORD:
            problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} is asked about "
                            f"{case.get('asked')!r}, not about {READER_WORD!r} — the word a reader is wired for is named "
                            "once, in `EntryModels::READER_WORD`")
        if case.get("answer") in arms and not isinstance(case.get("writes"), bool):
            problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} does not say whether the board may "
                            "write it — `Reader::writes()` is what the save asks before it writes")
        if not isinstance(case.get("board_shows"), bool):
            problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} does not say whether the board's row "
                            "can show it — an arm the row cannot show has to be named as an absence, not as a key")
        if case.get("answer") not in arms and "reader" in case:
            problems.append("contract/media_reader_board.json: an unknown answer names reader facts — the negative case must not be runnable")
        key, shows = case.get("key"), case.get("board_shows")
        if shows:
            if not key:
                problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} says the board can show it and "
                                "has no key for it — a word the table cannot say is the word the block stops saying")
            if case.get("answer") not in arms:
                problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} is not an answer the rule has — "
                                "the table names a state `word()` does not give")
            if case.get("for_pool") is not None:
                problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} is asked with a pool named — "
                                "the board's row names no pool, so a word shown on it must be answered without a pool")
        else:
            if key:
                problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} is named as a word the board "
                                f"cannot show and still has the key {key!r} — a word the page can never draw is a state it "
                                "holds for a case it cannot have")
            if case.get("answer") in arms and case.get("for_pool") is None:
                problems.append(f"contract/media_reader_board.json: {case.get('answer')!r} is an arm the board cannot show "
                                "and is asked with no pool — the rule would not answer it this way, so the case is not the "
                                "absence it says it is")
    if not any(case.get("key") is None for case in answers):
        problems.append("contract/media_reader_board.json: no case with no key — the negative case is what tells a table "
                        "from a guess: a word the table does not have must be said as the program says it")
    if not any(case.get("board_shows") is False and case.get("answer") in arms for case in answers):
        problems.append("contract/media_reader_board.json: no arm named as a word the board cannot show — `board_shows` is "
                        "then decoration, and the row that cannot say `itself` is not held to anything")
    for arm in arms:
        if not any(case.get("answer") == arm for case in answers):
            problems.append(f"contract/media_reader_board.json: no `answers` case holds {arm!r} — the block has stopped "
                            "saying which answer that is")
    runner = (ROOT / RUNNER).read_text(encoding="utf-8")
    if 'table("media_reader_board")' not in runner or 'rows(&data, "answers")' not in runner:
        problems.append("contract/media_reader_board.json: the program is not held to its `answers` — the table would be a "
                        "copy the guard reads, not a rule the program answers")

    # 2. the block's table, read from the module, held to the same words.
    drawn = dict(WORD_TABLE.findall(block_text))
    if not drawn:
        problems.append(f"{BLOCK}: no table of words to read — the guard is looking at nothing")
    for answer, key in sorted(drawn.items()):
        if answer not in arms:
            problems.append(f"{BLOCK}: {answer!r} is a state the rule does not answer — the page named a state of its own")
        case = next((c for c in answers if c.get("answer") == answer), None)
        if case is None:
            problems.append(f"{BLOCK}: {answer!r} is not a case the table names — the block and the table are two copies of "
                            "the same rule")
            continue
        if case.get("key") != key:
            problems.append(f"{BLOCK}: the word for {answer!r} is {key!r}, not the table's {case.get('key')!r}")
        if not case.get("board_shows"):
            problems.append(f"{BLOCK}: {answer!r} is a word the table says the board's row cannot show, and the module still "
                            "has a key for it — a word held for a case the page cannot have")
    for case in answers:
        if case.get("board_shows") and drawn.get(case.get("answer")) != case.get("key"):
            problems.append(f"{BLOCK}: the key for {case.get('answer')!r} is not the table's {case.get('key')!r}")
    # An arm the row cannot show is named in the module's own words, not left as a hole in its table.
    for arm in arms:
        if arm in drawn:
            continue
        if f"`{arm}`" not in block_text:
            problems.append(f"{BLOCK}: {arm!r} is an answer the row cannot show and is not named here — the absence is a "
                            "hole in the table, not a fact the module says")

    # 3. the words the module asks a language for, in every language.
    keys = sorted({c.get("key") for c in answers if c.get("board_shows") and c.get("key")} |
                  set(WORD_CALL.findall(block_text)))
    if not keys:
        problems.append(f"{BLOCK}: the module asks no language for a word — the guard is looking at nothing")
    for key in keys:
        for lang in LOCALES:
            path = ROOT / "static" / "js" / "i18n" / f"{lang}.js"
            if f"  {key}:" not in path.read_text(encoding="utf-8"):
                problems.append(f"static/js/i18n/{lang}.js: {key} is not there — the block shows a state in one language and "
                                f"falls back to another")

    # 4. the colours hold the same words, and only the words the board can draw.
    css = (ROOT / CSS).read_text(encoding="utf-8")
    coloured = sorted(set(re.findall(r'\.pb-reader-row\[data-t-state="([a-z ]+)"\]', css)))
    if not coloured:
        problems.append(f"{CSS}: no reader row is coloured — the guard is looking at nothing")
    for word in coloured:
        if word not in arms:
            problems.append(f"{CSS}: data-t-state {word!r} is not an answer the rule has — a state coloured here is a state "
                            "invented here")
        case = next((c for c in answers if c.get("answer") == word), None)
        if case is not None and not case.get("board_shows"):
            problems.append(f"{CSS}: {word!r} is coloured as an answer the board's row cannot draw — a rule that cannot go "
                            "red is a rule that reports green")
    for case in answers:
        if case.get("board_shows") and case.get("answer") not in coloured:
            problems.append(f"{CSS}: {case.get('answer')!r} has no colour — the operator reads that answer as an ordinary row")

    # 5. the block reads the answer; it does not work it out, and it names itself.
    for phrase in BLOCK_SAYS:
        if phrase not in block_text:
            problems.append(f"{BLOCK}: the block no longer says {phrase!r} — it is working the fact out again")
    for pattern, what in BLOCK_MAY_NOT:
        for number, line in enumerate(block_text.split("\n"), 1):
            if line.lstrip().startswith("//"):
                continue
            if pattern.search(line):
                problems.append(f"{BLOCK}:{number}: {line.strip()} — {what}")
    # The absences named in the module's words, not only in its markup.
    for named in ("no input dot", "drawn whether or not anything is named"):
        if named not in block_text:
            problems.append(f"{BLOCK}: the absence is not named in its own words ({named!r}) — a hole in the markup reads as "
                            "a place one can pull to, or as a block that has nothing to say")

    # 6. the flow lights the board's cable only by what the request names.
    flow = (ROOT / FLOW).read_text(encoding="utf-8")
    flow_code = "\n".join(line for line in flow.splitlines() if not line.lstrip().startswith("//"))
    if "item?.readerName" not in flow_code:
        problems.append(f"{FLOW}: the reader cable is no longer lit by the reader the request names — it is being lit by the "
                        "cable being drawn, which is a blink the board invented")
    if "ReaderBlock.key()" not in flow_code:
        problems.append(f"{FLOW}: the reader key is written here instead of read from `ReaderBlock.key()`")
    for phrase in FLOW_SAYS:
        if phrase not in flow_code:
            problems.append(f"{FLOW}: the flow no longer says {phrase!r} — the reader's cable is lit by something other than "
                            "what a request says it went through, or the reader's own request lights its client's cable")
    for pattern, what in FLOW_MAY_NOT:
        if what and pattern.search(flow):
            problems.append(f"{FLOW}: {pattern.pattern} — {what}")
    # The pin that lights the cable is held to the same key as the module: a test that names a key of its own would go green
    # while the module answers a different one.
    prefix = re.search(r'static PREFIX = "([a-z]+)"', block_text)
    pins_flow = (ROOT / FLOW_PINS).read_text(encoding="utf-8")
    if prefix and pins_flow:
        key = prefix.group(1)
        if f'"{key}"' not in pins_flow:
            problems.append(f"{FLOW_PINS}: the reader pin names a key of its own, not the module's {key!r} — the test and the "
                            "module would be two copies of the cable's name")
        if f"{key}:" in pins_flow:
            problems.append(f"{FLOW_PINS}: the reader pin expects a key with a pool after it — the key is the board's, "
                            "said once by `ReaderBlock.key()` with no argument")
    flow_cases = table.get("flow", [])
    if not flow_cases:
        problems.append("contract/media_reader_board.json: no `flow` cases")
    if any(not case.get("why") for case in flow_cases):
        problems.append("contract/media_reader_board.json: a `flow` case with no `why`")
    if not any(not case.get("item", {}).get("readerName") for case in flow_cases):
        problems.append("contract/media_reader_board.json: no `flow` case with no reader named — a table that only lights "
                        "rows says nothing about a cable that is drawn and not walked")

    # 7. the table's groups, each with its absence.
    for group, absence in (("row", lambda case: case.get("reader") is None),
                           ("key", lambda case: case.get("reader") is None),
                           ("block", lambda case: case.get("reader") is None and case.get("drawn")),
                           ("dot", lambda case: case.get("present") is False)):
        cases = table.get(group, [])
        if not cases:
            problems.append(f"contract/media_reader_board.json: no `{group}` cases")
        if any(not case.get("why") for case in cases):
            problems.append(f"contract/media_reader_board.json: a `{group}` case with no `why`")
        if not any(absence(case) for case in cases):
            problems.append(f"contract/media_reader_board.json: no `{group}` case named as nothing — an absence drawn as a "
                            f"normal value is the defect this rule is for")
    # The key group is held to the module: the table cannot name a key the code does not say, and `wired` is what the drawing
    # asks, so it must be said both ways.
    key_cases = table.get("key", [])
    if key_cases and not all(case.get("key") == "reader" for case in key_cases):
        problems.append("contract/media_reader_board.json: a `key` case names a key `ReaderBlock.key()` does not say — the "
                        "table and the code would draw two different cables")
    if not any(case.get("wired") for case in key_cases) or not any(not case.get("wired") for case in key_cases):
        problems.append("contract/media_reader_board.json: `key` cases say nothing about a cable that is not drawn — the key "
                        "is what a cable WOULD be named, and that is not the same as a cable")
    # A row says the answer the `answers` group holds for the same name: a row that names its own word is the fact read a
    # second way, in the row instead of in the module.
    for case in table.get("row", []):
        key = next((c.get("key") for c in answers if c.get("answer") == case.get("answer")), None)
        says = case.get("says", {})
        if says.get("state") != case.get("answer"):
            problems.append(f"contract/media_reader_board.json: the row for {case.get('answer')!r} draws {says.get('state')!r} "
                            f"as its state — the word is the answer, said once, and a row cannot rename it")
        if says.get("answer") != (key or case.get("answer")):
            problems.append(f"contract/media_reader_board.json: the row for {case.get('answer')!r} says "
                            f"{says.get('answer')!r} instead of the table's word for it")

    # 8. the order of the column, held to the table's `column` group. The order is one fact, so it is said in one place:
    # `poolsHtml` names the parts and puts them in the table's order. A part that is not drawn is named as not drawn, and
    # no part pins itself — Direct is the first block, not a block held in view while the column scrolls.
    column = table.get("column", [])
    if not column:
        problems.append("contract/media_reader_board.json: no `column` cases")
    if any(not case.get("why") for case in column):
        problems.append("contract/media_reader_board.json: a `column` case with no `why`")
    if any(case.get("pinned") for case in column):
        problems.append("contract/media_reader_board.json: a `column` case says a part pins itself — the order is the only "
                        "fact about where a part sits (the owner, 2026-11-06)")
    if not any(any(not part.get("drawn") for part in case.get("parts", [])) for case in column):
        problems.append("contract/media_reader_board.json: no `column` case names a part as not drawn — a table that lists "
                        "only what stands cannot say which part is missing")
    parts = [part.get("part") for part in column[0].get("parts", [])] if column else []
    if not parts:
        problems.append("contract/media_reader_board.json: the `column` cases name no parts")
    for selector in (".pb-direct", ".pb-reader-block"):
        rule_css = re.search(rf"{re.escape(selector)} \{{([^}}]*)\}}", css)
        if not rule_css:
            problems.append(f"{CSS}: {selector} is not there — the guard is looking at nothing")
        elif "position:" in rule_css.group(1):
            problems.append(f"{CSS}: {selector} names a position of its own — a part that pins itself is the order said a "
                            f"second way, in the CSS, and the table cannot see it")
    said = re.search(r'poolsHtml\(\)[^\n]*\n(?:.*\n)*?\s*return PoolBoard\.column\("pools", head, \[([^\]]*)\]\.join', board_text)
    if not said:
        problems.append(f"{BOARD}: `poolsHtml` does not put the column's parts in one list — the order would be said in more "
                        "than one place")
    else:
        order = [x.strip() for x in said.group(1).split(",")]
        if parts and order != parts:
            problems.append(f"{BOARD}: `poolsHtml` puts the parts as {order}, not the table's {parts}")
        for name in parts:
            if not re.search(rf"const {name} =", board_text):
                problems.append(f"{BOARD}: {name!r} is not named in `poolsHtml` — a part of the table with no place in the code")
        if "ReaderBlock.html(this.top?.reader)" not in board_text:
            problems.append(f"{BOARD}: the block's row is not drawn from the board's reader — it would be read from a pool, "
                            "which is the fact held once per pool")
    pins = (ROOT / COLUMN_TEST).read_text(encoding="utf-8")
    if "the_reader_block_sits_below_direct" not in pins:
        problems.append(f"{COLUMN_TEST}: the pin that holds the column's order is gone — the order would be a habit of the drawing")
    if 'Contract.table("media_reader_board")["column"]' not in pins:
        problems.append(f"{COLUMN_TEST}: the pin reads an order of its own, not the table's `column`")

    # 9. two bodies, each said once. `PoolCards.body` puts the pool under `pool` for the pool's door; `ReaderBlock.body` puts
    # the name under `reader` for the board's reader door, and the door reads the body under the rule's own name. Nothing
    # named is written as nothing, not as an empty name.
    pools_text = (ROOT / POOL_MODULE).read_text(encoding="utf-8")
    for phrase in ("static body(pool)", "return { pool: pool };", "JSON.stringify(PoolCards.body(PoolCards.payload(pool)))"):
        if phrase not in pools_text:
            problems.append(f"{POOL_MODULE}: the shape of the save body is no longer said here — {phrase!r}")
    for phrase in ("ReaderBlock.body(to.entry || PoolBoard.key(to.target))", "ReaderBlock.body(null)"):
        if phrase not in board_text:
            problems.append(f"{BOARD}: the reader cable builds its own body instead of going through `ReaderBlock.body` — "
                            f"{phrase!r}")
    if re.search(r'"/api/pools/save", \{', board_text):
        problems.append(f'{BOARD}: a save body is built here (`"/api/pools/save", {{...`), which is the shape said a second '
                        "way; the page cannot know what the door takes")
    door = (ROOT / DOOR).read_text(encoding="utf-8")
    if 'body.get("pool")' not in door:
        problems.append(f"{DOOR}: the pool door no longer reads the body under `pool` — the page and the door would part")
    if "(\"/api/board/reader\", Self::board_reader)" not in door:
        problems.append(f"{DOOR}: the board's reader has no door of its own — a fact of the board cannot be saved through a "
                        "pool's door")
    edits = (ROOT / EDITS).read_text(encoding="utf-8")
    if "supplied.get(EntryModels::READER_FIELD)" not in edits:
        problems.append(f"{EDITS}: the writing reads the body under a name of its own instead of `EntryModels::READER_FIELD` — "
                        "the page and the door would name the same key differently")
    if "if named.is_empty() { Value::Null } else { json!(named) }" not in edits:
        problems.append(f"{EDITS}: nothing named is written as an empty name instead of as nothing — the wiring would read as "
                        "a reader called nothing")
    save_cases = table.get("save", [])
    if not save_cases:
        problems.append("contract/media_reader_board.json: no `save` cases")
    if any(not case.get("why") for case in save_cases):
        problems.append("contract/media_reader_board.json: a `save` case with no `why`")
    if not any(case.get("read") is None and case.get("through") is False for case in save_cases):
        problems.append("contract/media_reader_board.json: no `save` case named as nothing without `ReaderBlock.body` — the "
                        "body the page cannot build is the negative case, and without it the table says nothing about the "
                        "shape the door reads")
    if 'Contract.table("media_reader_board")["save"]' not in pins:
        problems.append(f"{COLUMN_TEST}: the pin that runs the `save` group is gone — the shape would be held only by the guard")
    if "ReaderBlock.body" not in pins:
        problems.append(f"{COLUMN_TEST}: the pin that runs the `save` group does not go through `ReaderBlock.body` — the body "
                        "would be held only by the guard")

    # 10. the names a test finds the block by, and the test that runs the table.
    hook_line = re.search(r"static HOOKS = \{([^}]*)\}", block_text)
    if not hook_line:
        problems.append(f"{BLOCK}: the block's hooks are not named in one place — `static HOOKS`")
    hooks_text = (ROOT / HOOKS).read_text(encoding="utf-8")
    published = set(re.findall(r'"(pb-reader[a-z0-9-]*)"', hooks_text))
    row_id = None
    for what, name in re.findall(r'(\w+): "([a-z0-9-]+)"', hook_line.group(1) if hook_line else ""):
        if what == "id":
            row_id = name
            continue
        if name not in published:
            problems.append(f"{HOOKS}: {name} is not in COMPOSED — the doc publishes fewer names than the page can emit")
    # The row's own name is not a hook: it is the `data-t-id` it names itself by, and the doc publishes it as that.
    if row_id and f"data-t-id {row_id}" not in hooks_text:
        problems.append(f"{HOOKS}: the `data-t-id` the row names itself by ({row_id}) is not published — the row is the "
                        "board's, so it has no pool's id, and a suite cannot find it by a name the doc does not publish")
    snapshot = ROOT / SNAPSHOT
    if not snapshot.exists():
        problems.append(f"{SNAPSHOT}: the test that runs the block's table is gone")
    else:
        text = snapshot.read_text(encoding="utf-8")
        if 'Contract.table("media_reader_board")' not in text:
            problems.append(f"{SNAPSHOT}: it does not run contract/media_reader_board.json — the guard would be reading its own copy")
        if 'pathToFileURL(process.env.JS_ROOT + "/reader-block.js")' not in text:
            problems.append(f"{SNAPSHOT}: it does not load the module it holds to the table — it is reading a copy of the page")

    # 11. the field the block reads has a writer: the board's answer carries `reader`, from the reading it reads.
    if TOPOLOGY_SAYS not in "\n".join(code.get(TOPOLOGY, [])):
        problems.append(f"{TOPOLOGY}: the board's answer does not carry `reader` from `PoolDesk::reader(live)` — the block "
                        "reads `top.reader`, and a field nobody writes is drawn as the reader not named, whatever the "
                        "operator saved")
    if STATE_SAYS not in "\n".join(code.get(STATE, [])):
        problems.append(f"{STATE}: `PoolDesk::reader` is not asked from the reading the board's answer is built from — a "
                        "second reading for one row is the row and the answer read from two places")
    if "top?.reader" not in board_text:
        problems.append(f"{BOARD}: the column no longer reads `top.reader` — rule 11 would be holding the answer to a field "
                        "nobody reads")

    if problems:
        print("media reader board: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  the answers live in rust/crates/rules/src/media_reader.rs (`Reader::word()`); the block reads them from the "
              "board as `pool_state.rs` puts them there, and contract/media_reader_board.json holds the cases both hold to",
              file=sys.stderr)
        return 1
    groups = sum(len(table.get(group, [])) for group in ("answers", "row", "key", "dot", "block", "save", "flow"))
    print(f"media reader board OK: {len(arms)} answers, {len(drawn)} words the board can show, {len(keys)} words in "
          f"{len(LOCALES)} languages, {len(coloured)} colours, {groups} cases, {len(arms) - len(drawn)} arms named as words "
          f"the board's row cannot show; the row reads `reader.answer`, names itself `reader` by `data-t-id`, and the block "
          "is drawn whatever the name is")
    return 0


if __name__ == "__main__":
    sys.exit(main())
