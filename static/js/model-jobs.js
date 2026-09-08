// What a model DOES — as opposed to what launches it.
//
// Twin of caravan/common/model_jobs.py; both are run against ONE table of
// cases in scripts/test_model_jobs.py. The rule lives twice because both the
// server and the browser decide by it, and diverging twins is exactly the
// defect that put it in a file of its own.
//
// The vocabulary is about INPUT → OUTPUT, because that is what the operator is
// choosing between:
//
//     llm               text → text
//     embed             text → vectors
//     asr               speech → text
//     tts               text → speech
//     translate         text → text in another language
//     speech-translate  speech → text in another language
//
// `speech-translate` is separate from `asr` on purpose: SeamlessM4T returns the
// TARGET language only and never produces a transcript of the source, so a
// consumer picking it up as a recognizer would get a translation labelled as a
// transcription.

//: The whole vocabulary. Order is the order chips are drawn in.
export const JOBS = ["llm", "embed", "asr", "tts", "translate", "speech-translate"];

//: Words a cell may report in `kinds` that mean one of ours. Cell servers grew
//: their own spellings before there was a vocabulary, so a dotted kind is read
//: by its first segment and the aliases carry the rest.
const KIND_ALIASES = {
  stt: "asr",
  asr: "asr",
  tts: "tts",
  translate: "translate",
  "speech-translate": "speech-translate",
  llm: "llm",
  embed: "embed",
};

//: What each runner can be, when the cell itself has not said. A runner absent
//: here contributes nothing: "custom" runs whatever command a person typed, and
//: guessing its job from the runner id would be inventing a fact.
const RUNNER_JOBS = {
  "llama-server": ["llm"],
  vllm: ["llm"],
  whisper: ["asr"],
  moonshine: ["asr", "tts"],
  transcribe: ["asr"],
  seamless: ["speech-translate"],
  translate: ["translate"],
};

// The vocabulary's order, not the caller's — so two cells reporting the same
// pair of jobs draw the same pair of chips in the same places.
function ordered(found) {
  return JOBS.filter((job) => found.has(job));
}

// What a model in the picker does, from the row the picker already has. An
// unknown kind answers with nothing: a row whose job we cannot name must say
// nothing rather than guess "llm", which is how the silence started.
export function jobsForArtifact(kind, sttVariant = "", arch = "", family = "") {
  const k = String(kind || "").trim();
  if (k === "model") {
    if (String(sttVariant || "").trim()) return ["asr"];
    // `family` is what the controller already worked out from the file's own
    // pooling_type (chat models carry none) or its name — an embedding server
    // returns vectors, and llama.cpp cannot serve chat from the same instance.
    return String(family || "") === "embedding" ? ["embed"] : ["llm"];
  }
  if (k === "st") return String(arch || "").startsWith("seamless_m4t") ? ["speech-translate"] : ["llm"];
  if (k === "whisper") return ["asr"];
  if (k === "moonshine") return ["asr", "tts"];
  if (k === "translate") return ["translate"];
  return [];
}

// The canonical jobs behind whatever a cell reported in `kinds`. Read by first
// segment so "stt.whisper" counts as speech recognition without the reader
// having to know the engine; unknown words are dropped rather than shown.
export function jobsFromKinds(kinds) {
  const found = new Set();
  for (const raw of kinds || []) {
    const head = String(raw || "").trim().toLowerCase().split(".")[0];
    const job = KIND_ALIASES[head];
    if (job) found.add(job);
  }
  return ordered(found);
}

// What a RUNNING cell does. The cell's own `kinds` wins when it says anything:
// it is the live report, and the runner table is only what a runner is usually
// for. That order matters most for the custom runner, where the table knows
// nothing and the live report is the only thing that can name a TTS cell as one
// — voice cloning runs as a typed command, not as a runner of its own.
export function jobsForCell(runnerId, kinds = []) {
  const live = jobsFromKinds(kinds);
  if (live.length) return live;
  return ordered(new Set(RUNNER_JOBS[String(runnerId || "").trim().toLowerCase()] || []));
}
