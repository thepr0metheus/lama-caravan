#!/usr/bin/env python3
"""CI guard: the board's reader reads a picture for the row that cannot, one way, and only a picture sent inside the request.

The reading changes what a model is sent (docs/vision-describe.md, "The reading"): a picture becomes words. Each way that could
go wrong without a test going red is a rule here.

The rule, held here:
1. The values live in one place. What a picture is and where its bytes are, the question the reader is asked, the words taken
   back from its answer, the request rewritten and the two refusals are `rules/src/media_reading.rs` (`Reading`). The proxy's
   reading (`proxy/src/exchange/reading.rs`) asks them from there and builds none of its own — no caption, no question, no
   words read out of an answer, no cache key. A second shape of any of them is how the row and the table come to disagree.
2. Only a picture inside the request is read. `Reading::of` says where a picture's bytes are, and only a `data:` URL — its
   scheme in any case — or base64 data in a `source` is inside. The reading fetches nothing: it reaches no upstream of its
   own, and asks the reader through the pools (`for_request`, and an `Exchange` of its own), so the reader's queue, limits,
   account and record are every request's.
3. The serving row decides. A row is read for only when the entry said the board's reader reads (`ask.reads`) and the row
   said it cannot read the picture; a row that reads it gets it as it came. Both legs take their body from one place,
   `body_for(row.read_first)`, and a machine's leg takes it before its queue, so no place is held while the reader works and
   no request is read twice.
4. A caption is kept only from words. The cache keeps what the reader said, after it said it: a failed reading is never
   turned into words and never kept.
5. Every group of `contract/media_reading.json` has its negative case, every case says `why`, and the program runs every
   group — a table nobody runs holds nothing to anything.

Run: python3 scripts/check_media_reading.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _contract import Contract  # noqa: E402
from _rust_source import RustSource  # noqa: E402

RULE = "rust/crates/rules/src/media_reading.rs"
PROXY = "rust/crates/proxy/src/exchange/reading.rs"
ROWS = "rust/crates/proxy/src/pool_steps/rows.rs"
MACHINE = "rust/crates/proxy/src/exchange/machine.rs"
CLOUD = "rust/crates/proxy/src/exchange/cloud.rs"
RUNNER = "rust/crates/rules/tests/contract.rs"
TABLE = "media_reading"

#: Rule 1 and 2: what the values must say, in the one file that holds them.
RULE_SAYS = [
    "pub fn of(payload: &Value, reader: MediaReader, pool: &str) -> Self",
    'url.get(..5).is_some_and(|scheme| scheme.eq_ignore_ascii_case("data:"))',
    "pub fn elsewhere(&self) -> Option<EntryRefusal>",
    "pub fn question(&self, picture: &Picture) -> Option<Value>",
    '{"type": "text", "text": Wired::PROMPT}',
    "pub fn words(status: u16, body: &[u8]) -> Result<String, String>",
    "pub fn rewritten(&self, payload: &Value, captions: &[String]) -> Option<Value>",
    "self.reader.caption(words)",
    "if captions.len() != self.pictures.len() {",
]

#: Rule 1, 2 and 4: what the proxy's reading must ask of the values, and how it asks the reader.
PROXY_SAYS = [
    "reading.elsewhere()",
    "reading.question(picture)",
    "Reading::words(status, &answer)",
    ".rewritten(&payload, &captions)",
    "reading.failed(picture,",
    "reading.reader.key(&Sha256::of(url.as_bytes()))",
    "self.settings.models.for_request(&self.record.route.deny, reading.reader.model(), Self::READER_PATH)",
    "Exchange::new(proxy, settings, record, pool, asked, ClientSide::new(far, clock)).run()",
    "reader_for: Some(self.record.id.clone())",
]

#: What the proxy's reading may not say.
PROXY_MAY_NOT = [
    (re.compile(r"caravan-caption|\.caption\("), "a caption built in the proxy — its shape is `MediaReader::caption`, written "
                                                  "by `Reading::rewritten`"),
    (re.compile(r'"image_url"|"messages"|"choices"|"content"'), "a question or an answer read in the proxy — they are "
                                                                "`Reading::question` and `Reading::words`"),
    (re.compile(r"\bDial\b|UpstreamCall|ProviderCall|https?://"), "an upstream reached by the reading itself — the reader is "
                                                                  "asked through its pool, and nothing is fetched for a picture"),
    (re.compile(r"ask_reader\([^)]*\)\s*\.\s*(unwrap|ok|map_or|unwrap_or)"), "a failed reading turned into words — a reading "
                                                                             "with no words ends the request, it is not a caption"),
]

#: Rule 3: the row decides, and both legs take their body from one place.
ROWS_SAYS = ['if ask.reads { Sight::ReadFirst } else { Sight::Blind("media_unsupported") }', "fn read_for(self) -> Self {"]
MACHINE_SAYS = ["let body = self.body_for(row.read_first)?;"]
CLOUD_SAYS = ["let request = self.provider_request(&row, &settings)?;", "if !row.read_first {", "let body = self.body_for(true)?;"]

#: Rule 5: each group of the table, and what its negative case is.
NEGATIVE = {
    "pictures": ("a request with no picture", lambda case: case.get("pictures") == []),
    "elsewhere": ("a request whose pictures are all inside", lambda case: case.get("refused") is False),
    "question": ("a picture with nothing to ask about", lambda case: case.get("question") is None),
    "words": ("an answer that is no reading", lambda case: "no" in (case.get("said") or {})),
    "rewritten": ("a reading with a picture left without words", lambda case: case.get("rewritten") is None),
}
#: The groups with no negative case, each with its reason: a group named here needs one, not a name.
NO_NEGATIVE = {"failed": "the refusal's words for a reading that failed: there is no failure that is not one, so the case is "
                         "its words, and the absence of a failure is `words` saying the reader's words"}


def says_all(problems, rel, text, phrases, what):
    for phrase in phrases:
        if phrase not in text:
            problems.append(f"{rel}: {what} no longer says {phrase!r}")


def main() -> int:
    problems = []
    code = {rel: "\n".join(lines) for rel, lines in RustSource.files(".")}
    for rel in (RULE, PROXY, ROWS, MACHINE, CLOUD):
        if not code.get(rel):
            problems.append(f"{rel}: the file this guard holds is gone — it is looking at nothing")

    # 1 and 2. the values in one place, and only a picture inside the request.
    says_all(problems, RULE, code.get(RULE, ""), RULE_SAYS, "the reading's values")

    # 1, 2 and 4. the proxy asks the values, asks the reader through its pool, and builds nothing of its own.
    proxy = code.get(PROXY, "")
    says_all(problems, PROXY, proxy, PROXY_SAYS, "the reading in the proxy")
    for pattern, what in PROXY_MAY_NOT:
        found = pattern.search(proxy)
        if found:
            problems.append(f"{PROXY}: {found.group(0)!r} — {what}")
    asked = proxy.find("let words = self.ask_reader(")
    kept = proxy.find("self.proxy.captions.keep(key, words.clone()")
    if asked < 0 or kept < 0 or kept < asked or proxy.count("captions.keep(") != 1:
        problems.append(f"{PROXY}: a caption is kept somewhere other than after the reader said its words — what is kept "
                        "must be what `Reading::words` gave, never a reading that failed")

    # 3. the row decides; both legs take their body from one place, a machine's before its queue.
    says_all(problems, ROWS, code.get(ROWS, ""), ROWS_SAYS, "the row's sight")
    machine = code.get(MACHINE, "")
    says_all(problems, MACHINE, machine, MACHINE_SAYS, "the machine's leg")
    if MACHINE_SAYS[0] in machine and machine.find(MACHINE_SAYS[0]) > machine.find("Admission::new("):
        problems.append(f"{MACHINE}: the pictures are read after the model's queue — a place is held while the reader works")
    says_all(problems, CLOUD, code.get(CLOUD, ""), CLOUD_SAYS, "the provider's leg")

    # 5. the table: every group with its negative, every case with its why, every group run.
    table = Contract.table(TABLE)
    runner = code.get(RUNNER, "")
    for group in list(NEGATIVE) + list(NO_NEGATIVE):
        cases = table.get(group) or []
        if not cases:
            problems.append(f"contract/{TABLE}.json: the group `{group}` is gone or empty — nothing holds it")
        for case in cases:
            if not str(case.get("why", "")).strip():
                problems.append(f"contract/{TABLE}.json: a `{group}` case says no `why` — the table holds the rule and not "
                                "the reason")
        if group in NEGATIVE and not any(NEGATIVE[group][1](case) for case in cases):
            problems.append(f"contract/{TABLE}.json: the group `{group}` has no negative case ({NEGATIVE[group][0]}) — a "
                            "table that answers every case it names cannot say what it does when the thing is not there")
        if f'rows(&data, "{group}")' not in runner:
            problems.append(f"{RUNNER}: the group `{group}` is not run — the table would hold nothing to anything")
    if 'table("media_reading")' not in runner:
        problems.append(f"{RUNNER}: contract/{TABLE}.json is not read by the program")

    if problems:
        print("media reading: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  the reading's values live in rust/crates/rules/src/media_reading.rs; the proxy asks them in "
              "rust/crates/proxy/src/exchange/reading.rs and asks the reader through its pool; contract/media_reading.json "
              "holds the cases (docs/vision-describe.md, \"The reading\")", file=sys.stderr)
        return 1
    cases = sum(len(table.get(group) or []) for group in list(NEGATIVE) + list(NO_NEGATIVE))
    print(f"media reading OK: {len(RULE_SAYS)} values said once, the proxy asks {len(PROXY_SAYS)} of them and builds none, "
          f"only a picture inside the request is read, the row decides, a caption is kept only from words, {cases} cases in "
          f"{len(NEGATIVE) + len(NO_NEGATIVE)} groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
