// The reader block on Routing's Pools column (docs/vision-describe.md, 2026-11-06): one row for the whole board, for the
// model the operator names as the reader of a picture no pool's rows can take. The row says the name the board named, the
// answer the rule gives for that name, and the dot a cable to the model is pulled from.
//
// One row, not one per pool, because the reader is a fact of the board: the picture comes from a request, and the request's
// pool only says which row was asked to read. A row per pool would hold the same name for every pool and could give a
// different answer for the same name — the fact read a second way, one copy per pool.
//
// The answer is read from the board, never worked out here. `top.reader` is the row `Reader::word()` gave
// (rust/crates/rules/src/media_reader.rs, put on the board by rust/crates/admin/src/cloud/pool_state.rs); the table below
// only says how each word is read aloud in a language. A module that named the states itself — by looking at what a model
// promises, or at what its name looks like — would be the fact read a second way, and the board would say one thing while
// the entry refused another. That is the defect scripts/check_media_reader_board.py is for, and
// contract/media_reader_board.json is the table both this module and that guard read.
//
// `itself` is the answer the rule has and this row cannot show, and the absence is named out loud rather than left as a hole
// in the table: `itself` answers where a pool is named, and a board row names no pool, so the word cannot come from here.
// The table says it as `board_shows: false`; a key kept here for a word that can never be drawn would be a state held by the
// page for a case the page cannot have.
//
// A row has an output dot and no input dot, and the absence is named here rather than left as a hole: nothing is pulled
// INTO a reader row, because a reader is the wiring the operator named, not a path a request runs through on its way to a
// pool. A request goes through the reader only when its pictures were read for the row that serves it, and then it names
// the reader (`readerName`, rust/crates/proxy/src/exchange/reading.rs): the cable lights by what the request says, never
// because a wiring is drawn (static/js/pool-flow.js).
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

export class ReaderBlock {
  // What a test finds the block and its row by (docs/testability.md, through scripts/testability_names.py). The row names
  // itself `reader` in `data-t-id`: it is the board's row, so it has no pool's id to name itself by.
  static HOOKS = { block: "pb-reader-block", row: "pb-reader", id: "reader" };

  // The kind of cable the block draws, said once: `ask`, `source`, `cableOf` and the flow key all read it from here. The key
  // is the kind alone, with no pool after it, because the cable is the board's and not a pool's.
  static PREFIX = "reader";

  // The program's answer words, as `Reader::word()` names them, → the words of a language. `itself` is not here, and that is
  // said in the table as `board_shows: false` (see the note above). Nothing here is a state: the list is held to the arms of
  // `word()` by scripts/check_media_reader_board.py, so an answer added to the rule without a word here is a board that
  // stops saying which absence it was.
  static WORDS = {
    "reads": "pbReaderReads",
    "cannot take": "pbReaderCannot",
    "not said": "pbReaderNotSaid",
    "unknown": "pbReaderUnknown",
    "nothing": "pbReaderNothing",
  };

  // A wiring's cable key, for the drawing and for the flow: the kind alone, because one board has one reader.
  static key() {
    return ReaderBlock.PREFIX;
  }

  // What the program's answer sounds like in a language. A word the table does not have is said as the program says it,
  // never as a guess: a page cannot invent a state the rule does not have.
  static label(word) {
    const key = ReaderBlock.WORDS[word];
    return key ? t(key) : String(word ?? "");
  }

  // The cable this block draws: one, for the name the board named. No name, no cable, and that is the absence of the
  // operator's decision, not a cable to nowhere.
  static wiredKeys(reader) {
    return reader?.name ? [ReaderBlock.key()] : [];
  }

  // What the row says, as facts read from the board: the name the operator named, the word the rule answered, and the label
  // for that word. `named` is empty when nothing is named, and `shown` is what stands in the row: the absence said in words
  // rather than as an empty field, because an empty field next to a state word reads as a reader that reads nothing. Said
  // here because `row` below is the only place these facts become markup.
  static rowFacts(reader) {
    const word = reader?.answer;
    const named = reader?.name || "";
    return {
      named,
      shown: named || t("pbReaderNotNamed"),
      state: word == null ? "" : String(word),
      answer: ReaderBlock.label(word),
    };
  }

  // What the block holds: a name, or none. This is a fact about the name the board gave, and it is the only state the block
  // itself has. It is not a fact about pools: the reader is the board's, so a block that decided its state by counting pools
  // would be the same absence read a second way, and would say "no names" for a board that has one.
  static state(reader) {
    return reader?.name ? "named" : "quiet";
  }

  static row(reader) {
    const facts = ReaderBlock.rowFacts(reader);
    return `<li class="pb-reader-row" data-pb-reader data-t="${ReaderBlock.HOOKS.row}" data-t-id="${ReaderBlock.HOOKS.id}"`
      + ` data-t-state="${escapeHtml(facts.state)}">`
      + `<span class="pb-reader-named">${escapeHtml(facts.shown)}</span>`
      + `<span class="pb-reader-answer">${escapeHtml(facts.answer)}</span>`
      + `${ReaderBlock.dotHtml()}</li>`;
  }

  // The dot a cable is pulled from, and only that: a reader row has no input dot (see the note above).
  static dotHtml() {
    const hint = t("pbReaderDot");
    return `<span class="pb-dot out" data-pb-out="${ReaderBlock.PREFIX}" title="${escapeHtml(hint)}" aria-label="${escapeHtml(hint)}"></span>`;
  }

  // The whole block: its head and its row. The state is the one the block has, taken from `state` above rather than worked
  // out again here. The block is drawn whether or not anything is named: the absence is the operator's decision, and the row
  // says it in words, so a board with no reader still has to say which absence it is.
  static html(reader) {
    return `<section class="pb-reader-block" data-t="${ReaderBlock.HOOKS.block}" data-t-state="${ReaderBlock.state(reader)}">`
      + `<div class="pb-reader-head"><span>${escapeHtml(t("pbReaderHead"))}</span></div>`
      + `<ul class="pb-reader-rows">${ReaderBlock.row(reader)}</ul></section>`;
  }

  // The body the board's reader door takes: the name, under `reader` — `rust/crates/admin/src/routes/pools.rs` reads the body
  // there and nowhere else, and the key is the rule's own name (`EntryModels::READER_FIELD`). Said once, for the row and for
  // the cable. Nothing named is sent as nothing, not as an empty name, so the wiring stays the absence it is.
  static body(reader) {
    return { reader: reader ?? null };
  }
}
