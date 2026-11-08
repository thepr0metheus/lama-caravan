#!/usr/bin/env python3
"""CI guard: what a request carries is named in one place, and the row that serves it reads the same rule.

The journal counted a request's pictures in `summaries.rs`, and the entry decided a chat by its path alone. So a request
with a picture went to a model that had promised `input_modalities: ["text"]`, and its answer read as "the model looked at
the picture" while the model was given nothing it could read. The copy that looked affected nothing; the copy that decided
never looked at the content. Both halves looked right on their own, which is what made this hard to see.

The rule, held here:
1. The modality vocabulary is declared once, `MediaParts::WORDS`. A second copy is only allowed with its reason named
   here: a plan's choice is not the vocabulary, and a word added to one copy and not to the other is the same defect back.
2. Whoever needs the fact reads it: the journal counts through `Carried`, the entry decides through `Carried` and the
   pool's rows (`ModelKind::may_read`), the promise is read through `ModelKind::reads()`, and the row that serves reads
   the same rule through `Carried::verdict`. A reader that counts parts on its own is a second copy, whatever it is called.
3. Outside the classifier nobody matches a part by a modality word: `contains("image")` is the same fact read a second
   way. The files that name these words as strings are the ones putting a part into another API's shape; they are listed
   here, each with its reason.
4. The table `contract/media_parts.json` is held to by a test, and every case says `why`. It must hold an absence case
   (a part, a promise or a cable named as nothing) and a negative case (a request that is not refused): a table of only
   the happy path cannot tell a rule from a guess.
5. Both kinds of row — a provider's and a machine's — ask the media rule, so a text row on one path cannot serve a
   picture while the other path passes it over. The pool's cases in `contract/model_kind.json` keep the states apart:
   `takes`, `unsaid`, `cannot`, and `no row`.

Run: python3 scripts/check_media_parts.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _contract import Contract  # noqa: E402
from _rust_source import RustSource  # noqa: E402

CLASSIFIER = "rust/crates/rules/src/media_parts.rs"
VOCAB = RustSource.words("rules/src/media_parts.rs", "WORDS")

#: What the classifier itself must say: the fields it reads, the names it matches exactly, the word its rule decides.
CLASSIFIER_SAYS = ["Coerce::truthy", "carries_text", 'word == "image"', "Self::TEXT.contains(&said.as_str())"]

#: Who needs the fact, and what its file must say. A reader that does not say it is working the fact out again.
READERS = {
    CLASSIFIER: ("the classifier itself", CLASSIFIER_SAYS),
    "rust/crates/rules/src/summaries.rs": ("the journal's count", ["Carried::of", "carried.count("]),
    "rust/crates/rules/src/media_reader.rs": ("the entry's decision for a pool", ["Carried::of", "ModelKind::may_read(", "carried.verdict(serving, &wired)", "MayRead::Cannot => {", "EntryRefusal::media(&pool.name, &carried.verdict(serving, &wired)).map_or(MediaAnswer::Goes, MediaAnswer::Refused)"]),
    "rust/crates/rules/src/model_kind.rs": ("the promise a row is refused against", ["MediaParts::WORDS", "fn takes(", "fn may_read(", "RowKind::Said", "MayRead::Cannot"]),
    "rust/crates/proxy/src/pool_steps/rows.rs": ("the row that serves", ["row_kind(", "media_unsupported", "self.sight(ask, step, asked.carried)", "Sight::Blind(reason) => return row.unfit(reason)"]),
    "rust/crates/admin/src/common/model_kinds.rs": ("the board's facts for a cell", ["MediaParts::WORDS"]),
}

#: A word array that is not the vocabulary, each with its reason. A copy with no reason is the defect this guard is for.
EXEMPT_ARRAYS = {
    "rust/crates/rules/src/model_kind.rs": {
        "SUBSCRIPTION_INPUTS": "a plan's choice: two words of the vocabulary, not the vocabulary"
    },
}

#: Files that name a modality word as a string. They put a part into another API's shape, or read a content type: none of
#: them decides what a request carries, so the fact is not read from them. A file added here needs its reason, not a name.
EXEMPT_MATCHES = {
    "rust/crates/rules/src/anthropic_api.rs": "the name as Messages writes it: `input_text` would read differently here, so this is the shape's name and not the vocabulary",
    "rust/crates/rules/src/responses_api.rs": "the name as the Responses API writes it, the same",
    "rust/crates/admin/src/fleet/cell_talk/mode.rs": "a voice turn put together for a cell: it copies the words, it does not choose them",
    "rust/crates/admin/src/web/exchange.rs": "a content type, not a part's modality",
    "rust/crates/admin/src/fleet/cell_talk/ask.rs": "a mode's promise from the mode table, not a part read: the word says which field the request must fill",
}

WORDS = "|".join(VOCAB)
MATCHES = re.compile(
    r'(contains\("(?:' + WORDS + r')"\)|==\s*Some\("(?:' + WORDS + r')"\)|Some\("(?:' + WORDS + r')"\)\s*==|'
    r'==\s*"(?:' + WORDS + r')"|"(?:' + WORDS + r')"\s*==)'
)
ARRAY = re.compile(r"const ([A-Z_]+): \[&'static str; \d+\] = \[(.*?)\];", re.S)


def main() -> int:
    problems = []
    code = {rel: lines for rel, lines in RustSource.files(".")}

    # 1. one vocabulary; every other copy of it with its reason.
    named = 0
    for rel, lines in code.items():
        for name, words in ARRAY.findall("\n".join(lines)):
            words = re.findall(r'"([^"]*)"', words)
            if not any(word in VOCAB for word in words):
                continue
            if rel == CLASSIFIER or "MediaParts::WORDS" in "\n".join(lines):
                named += 1
                continue
            reason = EXEMPT_ARRAYS.get(rel, {}).get(name)
            if reason:
                named += 1
            else:
                problems.append(f"{rel}: {name} writes the vocabulary again with no reason ({', '.join(words)}) — "
                                f"a word added here and not to MediaParts::WORDS is the same defect back")

    # 2. the readers read it, instead of counting parts themselves.
    for rel, (what, must_have) in READERS.items():
        lines = code.get(rel)
        if lines is None:
            problems.append(f"{rel}: the file that was reading the fact is gone")
            continue
        text = "\n".join(lines)
        for phrase in must_have:
            if phrase not in text:
                problems.append(f"{rel}: {what} no longer says {phrase!r} — it is working the fact out again")

    # 3. outside the classifier a part is not matched by a word.
    for rel, lines in sorted(code.items()):
        if rel == CLASSIFIER:
            continue
        for number, line in enumerate(lines, 1):
            if MATCHES.search(line) and rel not in EXEMPT_MATCHES:
                problems.append(f"{rel}:{number}: {line.strip()} — a modality word matched as a string, "
                                f"which is the fact read a second way")

    # 4. the table is run, says why, and holds its absence and its negative case.
    table = Contract.table("media_parts")
    runner = "".join((ROOT / "rust" / "crates" / crate / "tests" / "contract.rs").read_text(encoding="utf-8")
                     for crate in ("rules", "admin"))
    if 'table("media_parts")' not in runner:
        problems.append("contract/media_parts.json: the program is not held to it")
    cases = [case for rows in table.values() for case in rows]
    if not cases:
        problems.append("contract/media_parts.json: no cases")
    if any(not case.get("why") for case in cases):
        problems.append("contract/media_parts.json: a case with no `why` — the table holds the rule, not the reason")
    # The three absences the rule names: a part that names nothing, a promise a row did not make, a cable that is not wired.
    if not any(case.get("word", 1) is None or case.get("parts") == [] for case in cases):
        problems.append("contract/media_parts.json: no case where a part is named as nothing")
    if not any(case.get("kind", 1) is None for case in cases):
        problems.append("contract/media_parts.json: no case where the promise is named as nothing")
    if not any(case.get("reader", 1) is None for case in cases):
        problems.append("contract/media_parts.json: no case where the cable is named as nothing")
    if not any(case.get("answer") == "goes" or case.get("reason") == "" for case in cases):
        problems.append("contract/media_parts.json: no case that is not refused — a table of only refusals cannot tell a rule from a guess")

    # 5. the pool is asked row by row, and both kinds of row ask the media rule.
    if "\n".join(code.get("rust/crates/proxy/src/pool_steps/rows.rs", [])).count("Sight::Blind(reason) => return row.unfit(reason)") < 2:
        problems.append("rust/crates/proxy/src/pool_steps/rows.rs: only one kind of row asks the media rule — "
                        "a text row on the other path would serve a picture the rule meant to pass over")
    pool_cases = Contract.table("model_kind").get("pool", [])
    if 'rows(&table("model_kind"), "pool")' not in runner:
        problems.append("contract/model_kind.json: the pool's cases are not run by the program")
    if not pool_cases:
        problems.append("contract/model_kind.json: no pool cases")
    if any(not case.get("why") for case in pool_cases):
        problems.append("contract/model_kind.json: a pool case with no `why` — the table holds the rule, not the reason")
    # The states the rows may answer, kept apart: a row takes the word, says nothing, cannot, or there is no row at all.
    answers = [case.get("answer") for case in pool_cases]
    for state in ("takes", "unsaid", "cannot", "no row"):
        if state not in answers:
            problems.append(f"contract/model_kind.json: no pool case says {state!r} — an absence drawn as a normal answer is the defect this rule is for")

    if problems:
        print("media parts: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  the words a part may name live in rust/crates/rules/src/media_parts.rs (MediaParts::WORDS); "
              "the journal and the entry read them there, and contract/media_parts.json holds the cases", file=sys.stderr)
        return 1
    print(f"media parts OK: {len(VOCAB)} words, {named} places that name them with their reason, {len(READERS)} readers, "
          f"{len(cases)} cases, {len(pool_cases)} pool cases, {len(EXEMPT_MATCHES)} files that name words without deciding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
