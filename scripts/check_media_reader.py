#!/usr/bin/env python3
"""CI guard: what a wired reader is, said in one place — and never read out of a model's name.

The reader was written as a rule that looked at names. `qwen3-vl-8b-instruct` was stopped on the board and its facts said
`llm` with `inputs: ["text"]`: a rule that read the name would have called it a reader and sent it a picture, and the
answer would have read as if a model had looked at the picture while it was given nothing it could read. This is the same
defect `check_media_parts.py` is for, one layer up: the fact had a second copy, and the copy that decided never looked at
the facts.

The rule, held here:
1. The vocabulary of what a wiring says lives once, in `media_reader.rs`: `Wired` is what the operator named, `Reader` is
   what that says about a word, `MediaReader` is the reader itself. `Reader::word` is the only place an answer becomes the word
   the board draws, `Reader::writes` the only place that says which answer the board may save, and `READER_WORD` names which
   word of `MediaParts::WORDS` a reader is wired for, so a request and a save ask the same rule about the same word. Every file
   that needs the fact reads it — the journal through `Carried::verdict`, the words through the answer, the board through
   `Reader::word()`. A second copy is the fact read a second way.
2. What a file may not say: a capability read out of a model's name, an absence quietly turned into a value, a state named by
   hand in a file that only reads the answer, the wiring asked a second time instead of read through `Carried::verdict`, and a
   reading built without the names the board has.
3. The shape of a caption, the fields of a cache key and the version of the words are said once, in `media_reader.rs`. A
   caption built anywhere else is a second shape, and a version written by hand is a cache that keeps answering with the
   words it was built for.
4. `Wired::of` is the only place a wiring is built, and `EntryModels::wired_for` is the only place that calls it — because
   that is where `ModelKind` gives the promise. Nobody reads a capability out of a name. `for_pool` is `Option<&str>`: the pool
   of the request, or nothing when the rule is asked from the board's row, which names no pool.
5. One answer, one code, each with what the journal calls it: one sentence for all of them is wrong advice — "wire a reader"
   is wrong where a reader is already wired, and wrong for a name the caravan cannot check. An answer that is not a refusal
   (`Reads`) must answer `None`, and an absence of a promise must answer as the absence it is. A pool that names itself is not
   a reader at all: the caption would come from the row that cannot read the part, so `Itself` is answered before the promise
   is read. The save asks the same rule before it writes (`EntryModels::can_write`), so a board and a client cannot be told
   two different things about one answer.
6. `contract/media_reader.json` is held to by a test, every case says `why`, and the table holds the six answers, a case
   where the name and the promise disagree, a case named as nothing, a case where the wiring names the pool it is wired for,
   a case asked with no pool (the board's own row, where `itself` cannot answer), and a case that is not refused: a table of
   only refusals cannot tell a rule from a guess. The `names` group is run against the board's reading, and holds a name the
   reading has facts about, a name it has no facts about, a name that writes, and words that name the board rather than a
   pool: a group where every name answers `unknown` cannot tell the two apart.
7. The rule is asked from the reading that holds the names the board has: its pools, the models it knows, the routers that say
   which name is a machine's model and the keys that say which account is signed in. That reading is built once, in
   `CloudData::board_names`, and the save asks the rule from it. A reading of the pools alone answered `media_reader_unknown`
   for every model name on the live board on 2026-11-06, which is a fact about the reading and not about the model — so the
   guard holds that the reading is not cut down to part of the names, and that no second way of reading them is left. And the
   rule asks what the board knows (`EntryModels::known_name`), not what a key can call this second (`pick`): a name the board
   knows and cannot call still has facts to read against, and `pick` is the answer for what a client may call now.

Run: python3 scripts/check_media_reader.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _contract import Contract  # noqa: E402
from _rust_source import RustSource  # noqa: E402

HOME = "rust/crates/rules/src/media_reader.rs"
RUNNER = "rust/crates/rules/tests/contract.rs"

#: What the one vocabulary must say. A file that names these without reading them is working the fact out again.
SAYS = [
    "pub enum Wired",
    "pub enum Reader",
    "pub struct MediaReader",
    'pub const PROMPT_VERSION: &\'static str = "v1";',
    "pub fn of(name: &str, known: bool, takes: Option<Vec<String>>, for_pool: Option<&str>) -> Self",
    "pub fn promise(&self, word: &str) -> Reader",
    'pub fn caption(&self, text: &str) -> String',
    'pub fn key(&self, part: &str) -> String',
    '"<caravan-caption by=\\"{}\\" prompt_version=\\"{}\\">{}</caravan-caption>"',
    "json!([part, &self.model, &self.prompt_version])",
    "Self::Named(MediaReader::new(name, Self::PROMPT_VERSION, for_pool), takes)",
    "None => Reader::NotSaid(reader.model().to_string()),",
    # The wiring read from the config, kept with the vocabulary it fills: the only place a promise is filled.
    "pub fn wired(&self, deny: &ClientDeny, for_pool: Option<&str>) -> Wired",
    # The word the reader is wired for and the key the board keeps the name under, each named once here.
    'pub const READER_FIELD: &\'static str = "reader";',
    "pub fn is_itself(&self) -> bool {",
    "self.for_pool.as_ref() == Some(&self.model)",
    "Wired::of(name, found.is_some(), promise, for_pool)",
    "pub fn media(&self, deny: &ClientDeny, pool: &Pool, payload: &Value) -> MediaAnswer",
    # The board's reader that reads the word is asked by its answer, and only `Reads` names someone to ask.
    "if let Some(reader) = wired.reads(Self::READER_WORD) {",
    "MediaAnswer::Readable(Reading::of(payload, reader.clone(), &pool.name))",
    # The word the board draws and the answer the board may write: said once, so a page cannot name the states again.
    'pub const READER_WORD: &\'static str = "image";',
    "pub fn word(&self) -> String",
    "pub fn writes(&self) -> bool",
    "matches!(self, Self::Reads | Self::Nothing)",
    "Self::Named(reader, _) if reader.is_itself() => Reader::Itself(reader.model().to_string()),",
    # Asked with no pool: the reader is one fact for the whole board, so the words name the board and not a pool.
    "pub fn can_write(&self, reader: &str) -> Option<EntryRefusal>",
    'format!("The board asked to save `{reader}` as its reader.")',
    'EntryRefusal::wiring("the board", &answer, &here, Self::READER_WORD)',
    "if answer.writes() {",
    "MayRead::Cannot => {",
    "EntryRefusal::media(&pool.name, &carried.verdict(serving, &wired)).map_or(MediaAnswer::Goes, MediaAnswer::Refused)",
]

#: Who needs the fact, and what its file must say. A reader that does not say it is working the fact out again.
READERS = {
    HOME: ("the vocabulary itself", SAYS),
    "rust/crates/rules/src/media_parts.rs": (
        "the part's own word, asked of the wiring",
        ["use crate::media_reader::{Reader, Wired};", "Verdict::Reading(part.clone(), wired.promise(word))"],
    ),
    "rust/crates/rules/src/entry_refusal.rs": (
        "the words, read from the answer",
        ["let Verdict::Reading(part, reader) = answer else", "Reader::Reads => return None", "Reader::Nothing =>",
         "Reader::Unknown(reader) =>", "Reader::NotSaid(reader) =>", "Reader::CannotTake(reader, taken) =>",
         "Reader::Itself(reader) =>", "pub fn wiring(model: &str, answer: &Reader, here: &str, word: &str) -> Option<Self>",
         "Self::wiring(model, reader, &here, &word)"],
    ),
    "rust/crates/proxy/src/pool_steps/rows.rs": (
        "the row that serves, with the wiring named as an absence",
        ["carried.verdict(kind.takes(), &Wired::Nothing)", "self.sight(ask, step, asked.carried)",
         "if ask.reads { Sight::ReadFirst } else { Sight::Blind(\"media_unsupported\") }"],
    ),
    # The reader is the board's fact, so the reading holds it once. A pool that kept one would be the same name read once per
    # pool, and the board would answer differently for two pools that name the same model.
    "rust/crates/rules/src/entry_models.rs": ("the board's reader, read as an absence",
        ["reader: Option<String>", "file.get(Self::READER_FIELD)", "(!named.is_empty()).then_some(named)"]),
    # The board asks the same rule for the same word: the save before it writes, and the drawing before it draws a state.
    "rust/crates/admin/src/cloud/pool_edits.rs": ("the save's answer, asked before the write",
        ["self.cloud().board_names(&data).can_write(&named)",
         'let named = Coerce::word(supplied.get(EntryModels::READER_FIELD));',
         'if named.is_empty() { Value::Null } else { json!(named) }']),
    "rust/crates/admin/src/cloud/pool_state.rs": ("the word the board draws for its reader, from the rule's answer",
        ["named.wired(&operator, None)", "named.reader()", "answer.word()"]),
    # The entry is asked for the request it took: it does not decide the part by itself.
    "rust/crates/proxy/src/front.rs": ("the entry's answer for a request",
                                       ["settings.models.media(&route.deny, &pool, &payload)", "MediaAnswer::Refused(refusal) => WithBody::Refuse(refusal)"]),
    RUNNER: ("the table's runner, asked for the wiring the way the entry builds it", ["Wired::of(", "wired.promise(",
                                             "reader.caption(", "reader.key(", "reader.word()", "verdict_json", "reader_json",
                                             # The `names` group is run against the reading the door builds, not against the pools.
                                             'rows(&data, "names")', "EntryModels::read(", "Credentials::read(", "routers_of("]),
}

#: Rule 7: the reading the rule is asked from — the names the board has, read once. A reading of the pools alone answers
#: `unknown` for every model name, which is a fact about the reading and not about the model.
READING = {
    "rust/crates/admin/src/cloud/data/reading.rs": ("the board's reading, built once",
        ["pub fn board_names(&self, data: &Value) -> EntryModels",
         "let payload = ProxiesConfig::of(self.app).read_payload();",
         'self.read_names(data, payload.get("routers"))',
         "self.read_names(&self.load(), routers)",
         "EntryModels::read(routers, Some(data), &Credentials::read(Some(&self.secrets())), ModelCatalogue::default())"]),
    "rust/crates/rules/src/entry_models.rs": ("what the board knows, held apart from what a key can call now",
        ["fn open_to(&self, deny: &ClientDeny, runs_only: bool) -> Vec<&Pool>",
         "pub fn known_name(&self, deny: &ClientDeny, wanted: &str) -> Option<&Pool>",
         "self.open_to(deny, false)", "self.open_to(deny, true)"]),
    # The key the board keeps the reader under, and its shape, named once in the table that writes the file — the same word
    # the reading reads, so the door and the reading cannot name it differently.
    "rust/crates/admin/src/common/misc.rs": ("the file's table, holding the reader as a word",
        ["EntryModels::READER_FIELD, Shape::Word", "Shape::Word => !Coerce::word(Some(*said)).is_empty()"]),
    HOME: ("the save's answer, asked of what the board knows", ["let found = self.known_name(deny, name);"]),
}

#: What a file may not say. A state named by hand, a capability read out of a name, or an absence quietly turned into a
#: value is the defect this guard is for.
MAY_NOT = {
    HOME: [
        (re.compile(r'\.contains\("(vl|vision|vision-language)"\)|looks like|starts_with\("(qwen|gpt|llama)"\)'),
         "a capability read out of a name — the promise comes from `ModelKind`"),
        (re.compile(r"\(\)\.unwrap_or"), "an absence quietly turned into a value"),
        # The rule asks what a name's facts promise; a call being possible this second is a different question, and answering
        # it here is what turned a name the board knows into `unknown`.
        (re.compile(r"self\.pick\("), "the rule asked what a key can call now — a reader is checked against what the board knows"),
    ],
    "rust/crates/rules/src/entry_models.rs": [
        (re.compile(r"\bpromise\("), "the wiring asked a second time — the decision is read through `Carried::verdict`"),
    ],
    "rust/crates/rules/src/entry_refusal.rs": [
        (re.compile(r"\bpromise\("), "the wiring asked a second time — the words must come from the answer the rule gave"),
        (re.compile(r"carried\.first\(|Carried::of\("), "the part picked by hand instead of read from the answer"),
    ],
    # A state written by hand in a file that only reads the answer: the board says one thing and the entry another.
    "rust/crates/admin/src/cloud/pool_state.rs": [
        (re.compile(r'"(reads|unknown|not said|cannot take|nothing|itself)"'),
         "an answer named by hand — the word the board draws comes from `Reader::word()`"),
    ],
    # The reading cut to part of the names: with the pools alone every model name answered `unknown`, and the table could not
    # tell a name the caravan does not know from a reading that does not look at models.
    "rust/crates/admin/src/cloud/data/reading.rs": [
        (re.compile(r"pools_only|Credentials::default\(\)|EntryModels::read\(None"),
         "a reading built without the board's names — the board's reading is one, with its routers and its keys"),
    ],
    "rust/crates/rules/src/entry_models/board.rs": [
        (re.compile(r"pools_only"), "the names read a second way, as the pools alone"),
    ],
    # A reader on a pool is the same name held once per pool. The board names one reader, so a pool that keeps one answers
    # the same fact differently for two pools — and a door that takes a pool cannot say which answer the board meant.
    "rust/crates/rules/src/cloud_pools.rs": [
        (re.compile(r"pub reader: Option<String>"), "a reader kept on a pool — the reader is the board's, said once in the "
                                                    "reading (`EntryModels::reader`), not once per pool"),
    ],
}

#: One answer, one code, each with what the journal calls it.
CODES = {
    "nothing": ("media_unsupported", "entry:media-unsupported"),
    "unknown": ("media_reader_unknown", "entry:media-reader-unknown"),
    "not said": ("media_reader_unverified", "entry:media-reader-unverified"),
    "cannot take": ("media_reader_cannot", "entry:media-reader-cannot"),
    "itself": ("media_reader_self", "entry:media-reader-self"),
}

STATES = ["nothing", "unknown", "not said", "cannot take", "itself", "reads"]

#: What only `media_reader.rs` may say: the shape of a caption, the fields of a key, the version of the words.
ONCE = ["<caravan-caption", "prompt_version", "json!([part,"]


def main() -> int:
    problems = []
    code = {rel: lines for rel, lines in RustSource.files(".")}
    home = "\n".join(code.get(HOME, []))
    if not home:
        problems.append(f"{HOME}: the file that holds the vocabulary is gone")

    # 1. the vocabulary, and the readers that read it instead of working it out again.
    for rel, (what, must_have) in READERS.items():
        lines = code.get(rel)
        if lines is None:
            problems.append(f"{rel}: the file that was reading the fact is gone")
            continue
        text = "\n".join(lines)
        for phrase in must_have:
            if phrase not in text:
                problems.append(f"{rel}: {what} no longer says {phrase!r} — it is working the fact out again")

    # 2. what a file may not say.
    for rel, lines in sorted(code.items()):
        text = "\n".join(lines)
        for pattern, what in MAY_NOT.get(rel, []):
            found = pattern.search(text)
            if found:
                problems.append(f"{rel}: {found.group(0)} — {what}")

    # 3. the shape of a caption, the fields of a key and the version of the words are said once.
    for rel, lines in sorted(code.items()):
        if rel == HOME:
            continue
        text = "\n".join(lines)
        for phrase in ONCE:
            if phrase in text:
                problems.append(f"{rel}: {phrase!r} — a second shape, or a version written by hand. A caption built "
                                f"anywhere else cannot be read back as the words of a different reader.")

    # 4. where a wiring is built: the constructor here, filled by the entry's reading in this same file, and by the table's
    # runner when it runs the table.
    built = sorted(rel for rel, lines in code.items() if "Wired::of(" in "\n".join(lines))
    if built != [HOME, RUNNER]:
        problems.append(f"a wiring is built in {built or 'no file'} — the only places are `Wired::of` and the entry's "
                        f"reading in {HOME}, and the table's runner, and the promise comes from `ModelKind`")

    # 5. the words: one code per answer, said once, with the journal's name for it.
    refusal = "\n".join(code.get("rust/crates/rules/src/entry_refusal.rs", []))
    for answer, (code_word, reason) in CODES.items():
        if refusal.count(f'"{code_word}"') != 1:
            problems.append(f"rust/crates/rules/src/entry_refusal.rs: {code_word!r} said {refusal.count(f'\"{code_word}\"')} "
                            f"times — one code for one answer is what tells the operator which absence the refusal was "
                            f"({answer})")
        if f'"{reason}"' not in refusal:
            problems.append(f"rust/crates/rules/src/entry_refusal.rs: {reason!r} is not there — the journal's name for {answer}")

    # 6. the table: run, says why, holds the answers, the disagreement, and the cases that are not refused.
    table = Contract.table("media_reader")
    runner = code.get(RUNNER, [])
    if 'table("media_reader")' not in "\n".join(runner):
        problems.append("contract/media_reader.json: the program is not held to it")
    cases = [case for rows in table.values() for case in rows]
    if not cases:
        problems.append("contract/media_reader.json: no cases")
    if any(not case.get("why") for case in cases):
        problems.append("contract/media_reader.json: a case with no `why` — the table holds the rule, not the reason")
    answers = [json_word(case.get("answer")) for case in table.get("wired", [])]
    for state in STATES:
        if not any(state in answer for answer in answers):
            problems.append(f"contract/media_reader.json: no case says {state!r} — an absence drawn as a normal answer is "
                            f"the defect this rule is for")
    # The name and the promise disagreeing: the case the guard exists for. A `vl` name that promised the word is not that case.
    if not any("vl" in str(case.get("reader", "")) and json_word(case.get("answer")) == "cannot take"
               and "image" not in promised(case, "reader", "takes") for case in table.get("wired", [])):
        problems.append("contract/media_reader.json: no case where the name says vision and the promise says otherwise — "
                        "a reader guessed from a name is the defect this rule must not ship")
    if not any(case.get("reader") is None for case in table.get("wired", [])):
        problems.append("contract/media_reader.json: no case where the wiring is named as nothing")
    # A wiring that names the pool it is wired for: the name is read, so the table must say what a self-naming answers.
    if not any(str(case.get("for_pool", "")) == str((case.get("reader") or {}).get("name", "")) for case in table.get("wired", [])):
        problems.append("contract/media_reader.json: no case where the wiring names the pool it is wired for — a pool that "
                        "answers as its own reader is a caption from the row that cannot read the part")
    # And the other side of the same rule: asked with no pool, a name cannot be the board, so `itself` cannot answer. Without
    # a case like this the table holds the answers for a request only, and the board's row is outside the rule.
    if not any(case.get("for_pool") is None and case.get("reader") for case in table.get("wired", [])):
        problems.append("contract/media_reader.json: no case asks the rule with no pool — the board's own row, where "
                        "`itself` cannot be the answer, is the case that says which answers belong to the board")
    # One case per code, and the two answers that are not refusals, kept apart: the wiring that reads and the row that reads.
    words = table.get("words", [])
    for answer, (code_word, _) in CODES.items():
        if not any(case.get("code") == code_word for case in words):
            problems.append(f"contract/media_reader.json: no `words` case says {code_word!r} — the table has stopped "
                            f"holding the words for {answer}")
    if not any(case.get("refused") is False and "image" in promised(case, "reader", "takes") for case in words):
        problems.append("contract/media_reader.json: no case where the wiring reads and the request is not refused — "
                        "a table of only refusals cannot tell a rule from a guess")
    if not any(case.get("refused") is False and "image" in promised(case, "kind", "inputs") for case in words):
        problems.append("contract/media_reader.json: no case where the row reads the picture itself — a table that only "
                        "refuses the wiring says nothing about the row that never needed a caption")
    # The door's reading: a name the caravan does not know and a reading that does not look at models must stay two answers,
    # so the group needs one case of each. A group where every name answers `unknown` cannot tell them apart.
    names = table.get("names", [])
    if not names:
        problems.append("contract/media_reader.json: no `names` group — the reading the save door asks the rule from is not "
                        "held to by the table")
    if not any(case.get("code") == "media_reader_unknown" for case in names):
        problems.append("contract/media_reader.json: no `names` case answers `unknown` — that is the only answer for a name "
                        "no place in the reading has")
    if not any(case.get("code") in {code for code, _ in CODES.values()} for case in names):
        problems.append("contract/media_reader.json: no `names` case is answered from a name the reading holds facts about — "
                        "the group would then say only what a reading with no models says, which is the defect rule 7 is for")
    # The two answers that write are two facts: a name the reading reads, and the absence the operator named. Each needs its
    # own case, or the group holds one fact and the door writes the other.
    writing = [case for case in names if case.get("refused") is False]
    if not any(case.get("wanted") for case in writing):
        problems.append("contract/media_reader.json: no `names` case where a name writes — `Reader::writes` has its arm for "
                        "the name that reads, and the group would hold only refusals")
    if not any(not case.get("wanted") for case in writing):
        problems.append("contract/media_reader.json: no `names` case where the absence writes — writing nothing is clearing "
                        "a wiring, which is a different fact from a name that reads")
    for case in names:
        if case.get("code") == "media_reader_unknown" and (case.get("board") or {}).get("outputs"):
            problems.append(f"contract/media_reader.json: a `names` case answers `unknown` while its reading names a model "
                            f"({case.get('wanted')}) — the answer is said for a name the reading has")
    # The words name the board, not a pool: the reader is one fact for the whole board, so a sentence that named a pool would
    # be the same fact said once per pool.
    if not any("the board" in str(case.get("answer", "")) for case in names):
        problems.append("contract/media_reader.json: no `names` case names the board the name was asked for — a door that "
                        "holds no pool cannot name a pool in its words")
    # The five characters an envelope can end on, named in the code that escapes them.
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&apos;"):
        if f'"{entity}"' not in home:
            problems.append(f"{HOME}: {entity!r} is not there — a caption whose text can end the envelope early is a "
                            f"caption that becomes an instruction")

    # 7. the reading the rule is asked from: the names the board has, built once, and no second way of reading them.
    for rel, (what, must_have) in READING.items():
        lines = code.get(rel)
        if lines is None:
            problems.append(f"{rel}: the file that builds the reading the rule is asked from is gone")
            continue
        text = "\n".join(lines)
        for phrase in must_have:
            if phrase not in text:
                problems.append(f"{rel}: {what} no longer says {phrase!r} — the reading is built a second way, or asked of "
                                f"fewer names than the board has")

    if problems:
        print("media reader: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  the vocabulary of a wired reader lives in rust/crates/rules/src/media_reader.rs; a wiring is built by "
              "`EntryModels::wired_for` from `ModelKind`, the words read the answer, the word the board draws comes from "
              "`Reader::word()`, the rule is asked from the board's reading built in `CloudData::board_names` and against "
              "what the board knows (`known_name`), and contract/media_reader.json holds the cases", file=sys.stderr)
        return 1
    print(f"media reader OK: {len(STATES)} answers, {len(READERS)} readers, {len(CODES)} codes, {len(cases)} cases, "
          f"a wiring built in {', '.join(built)}, the rule asked from {len(READING)} places that hold the board's names")
    return 0


def promised(case, field, key) -> list:
    """The words a case names under `field.key`. A field named as nothing names no words, and that is the answer it says."""
    value = case.get(field)
    return value.get(key) if isinstance(value, dict) else []


def json_word(value) -> str:
    """The table's answer as a word: `"reads"` or `{"cannot take": ...}`, so an answer can be looked for in either shape."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return next(iter(value))
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
