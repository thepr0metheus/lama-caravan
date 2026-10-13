#!/usr/bin/env python3
"""CI guard: every en message key (and en fieldHelp entry) must exist in all
languages of static/js/i18n-data.js — AND must actually be translated. Key
presence alone let anglicized strings ship for months (Russian grammar with
English noun phrases inline, or verbatim en copies in latin-script locales),
so the guard now also flags untranslated content:
  - non-latin-script locales: values still containing 3+ consecutive latin
    words after stripping genuine identifiers (--flags, /paths, ALLCAPS,
    snake_case, product names);
  - latin-script locales: values that are verbatim copies of the en string
    (3+ words) — short labels and shared terms pass;
  - locales with diacritics: words written plain ("modele", "uebersetzt")
    that the same file writes right elsewhere (DroppedLetters).
Deliberate exceptions live in TRANSLATION_ALLOWLIST. And no language file may
write a key twice: the later line silently wins (duplicate_keys)."""
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "static" / "js" / "i18n-data.js"
LANG_DIR = ROOT / "static" / "js" / "i18n"

NON_LATIN = {"ru", "zh", "hi", "ar", "bn", "ja", "ko", "te", "mr", "ta", "ur"}

#: Russian is the only Cyrillic language here, so Cyrillic anywhere else is a leak.
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

# Keys that are intentionally identical / partly English in every language.
TRANSLATION_ALLOWLIST = {
    "appAcronym",              # the LAMA CARAVAN acronym expansion — English by design
    "topologyServerSection",   # brand string "LAMA CARAVAN Server"
    "tmPromptGenTps",          # "prompt / gen t/s" — all identifiers, identical in latin locales
    "yarnChipAuto",            # "YaRN auto ×{factor}" — 'auto' is the same word in es/fr/pt/de/id/it
    "rtTitleOutputServer",     # "Output → server" — literally the same words in it/id
}

# Identifiers that legitimately stay latin inside any translation. Only the
# named products and terms ignore case. The ALLCAPS alternative must not:
# under one re.IGNORECASE for the whole pattern, `[A-Z]{2,}` matched every
# latin word, every word was stripped before _ENG_PHRASE looked, and the
# english-phrase rule could never fire (found 2026-10-07; a whole English
# sentence in the Chinese table passed).
_IDENT_RE = re.compile(
    r"--[a-z0-9-]+|/[A-Za-z]\w*|\b[A-Z]{2,}[A-Za-z0-9_]*\b"
    r"|[a-z_]{2,}_[a-z_]+"
    r"|(?i:\b(llama\.cpp|llama-server|Jinja|vLLM|PyPI|HuggingFace|Hugging Face|OpenClaw"
    r"|OpenAI|OpenRouter|Ollama|Qwen[\w.]*|gemma[\w.-]*|deepseek[\w.-]*|caravan[\w-]*"
    r"|GGUF|VRAM|CUDA|RoPE|flash[- ]attention|Prometheus|nvidia[\w/.-]*|whisper"
    r"|faster-whisper|Docker|systemd|launchd|token(s)?|prompt|batch|slot(s)?|cloud"
    r"|repo id|Blackwell|checkpoint|safetensors|webui|web UI|Kanban|small|default"
    r"|embeddings?|main|spill|max_tokens|FIFO|heartbeat|API|url|json|yaml|ini|Exa|MCP"
    # Names of other products' things, quoted as their owners write them: a
    # license, and a ChatGPT setting the operator has to find by its label.
    r"|Moonshine Community License|Device code authorization)\b)"
)
_ENG_PHRASE = re.compile(r"\b[A-Za-z]{3,}(\s+[A-Za-z']{2,}){2,}\b")   # 3+ latin words

# allMessages() rather than `messages`: since the split, i18n-data.js holds only
# English at import time and pulls the rest on demand. Loading all twenty is
# exactly what this guard is for and exactly what the page must never do.
NODE_SNIPPET = """
import(process.argv[1]).then(async ({ LANGS, allMessages }) => {
  const messages = await allMessages();
  const out = {};
  for (const { code } of LANGS) {
    const m = messages[code] || {};
    const strings = {};
    for (const [k, v] of Object.entries(m)) if (typeof v === "string") strings[k] = v;
    out[code] = { strings, fieldHelp: m.fieldHelp || {} };
  }
  console.log(JSON.stringify(out));
});
"""


def untranslated(lang, key, value, en_value, allowlist=TRANSLATION_ALLOWLIST):
    """Why a value is not a translation, or None. Shared with the /hf table's
    guard (check_i18n_calls.py), which has an allowlist of its own."""
    if key in allowlist or not value:
        return None
    if en_value and en_value.startswith("{") is False and value == en_value:
        # verbatim en copy — flag for ANY locale when it's real prose
        if len(value) > 14 and len(value.split()) >= 3 and lang not in NON_LATIN:
            return "en-copy"
    if lang in NON_LATIN and _ENG_PHRASE.search(_IDENT_RE.sub(" ", value)):
        return "english-phrase"
    if lang != "ru" and _CYRILLIC_RE.search(value):
        # A Russian value left standing in another language's table. Neither
        # check above sees it: it is not latin words, and it is not a copy of
        # the en string — so `computeAuto: "авто"` sat in the Chinese table
        # until someone read the file by eye (found 2026-09-07). Russian is
        # the only Cyrillic language here, so anywhere else it is a leak.
        return "russian-leak"
    return None


#: Plain words that ARE words of their language although the file also writes their accented twin:
#: the rule in DroppedLetters would take them for dropped letters. Each with its reason; an entry
#: that stops being true is a lie, so the list holds only what the tables really contain.
PLAIN_WORDS_ALLOWED = {
    "es": {
        "cuanto": "«en cuanto llegue»: the conjunction has no accent, «cuánto» is the question word",
        "cache": "the English word inside «KV-cache» and the spec type «ngram-cache»; Spanish is «caché»",
    },
    "fr": {
        "change": "«il change», the present tense, beside the participle «changé»",
        "configure": "«se configure», the present tense, beside «configuré»",
        "connecte": "«connecte», the present tense, beside «connecté»",
        "ferme": "«se ferme», the present tense, beside «fermé»",
        "refuse": "«refuse», the present tense, beside «refusé»",
        "supprime": "«supprime», the present tense, beside «supprimé»",
    },
    "tr": {
        "tensor": "a value of --split-mode as llama.cpp spells it: none, layer, row, tensor",
    },
}


class DroppedLetters:
    """Words a language file writes WITHOUT the letters its spelling needs, found by the file itself.

    The strings of six commits of 2026-08-15 to 08-18 (the NLLB and Seamless runners, the delete-port
    dialog and its "no key" box, the language chip, a loading-wait label) stood in seven tables with
    every diacritic dropped: German
    «uebersetzt», French «modele», Spanish «peticion», Portuguese «nao», Turkish «yalnizca»,
    Vietnamese «Ngon ngu cua van ban VAO». Nothing flagged them for two months: the key was there, the
    text was no copy of the English, and a plain Latin word is no English phrase. The file is the
    witness. It writes the same word right a hundred times beside the wrong one, so:

    * a plain word is DROPPED when its accented twin stands at least RATIO times as often. A language
      has real plain words that sit beside an accented one («mas»/«más» is no such pair, «ferme»/«fermé»
      is): there the plain word is the common one, or it is listed in PLAIN_WORDS_ALLOWED with its reason.
    * Vietnamese puts a tone mark on nearly every sentence and its plain syllables are real words
      («con», «thu», «chi»), so a twin proves nothing there. A value of SILENT_WORDS words or more with
      no letter beyond ASCII is a sentence written plain.

    Not looked at: placeholders, --flags, `code`, snake_case, paths, ALLCAPS (they are not the
    language's words).

    What it does not see, so nobody trusts it for more: a word the file writes right fewer than RATIO
    times (nothing to hold it against: German «aufgeloest»), a short Vietnamese label (4 words and
    fewer), the Spanish «¿» that dropped with the accents, and Italian «e» for «è» (both are words).
    On the 81 strings that were found by hand in 2026-10 it finds 63; a batch is what it is for.
    """

    #: How many times more often the accented twin must stand than the plain word.
    RATIO = 3
    MIN_LETTERS = 3
    SILENT_WORDS = 5
    #: Languages whose tone marks go on nearly every sentence: the silent rule, not the twin rule.
    TONAL = frozenset({"vi"})

    _SKIP = re.compile(r"\{[^}]*\}|--[\w-]+|`[^`]*`|\b\w+_\w+\b|https?://\S+|/[\w./-]+|\b[A-Z0-9]{2,}\w*\b")
    _WORD = re.compile(r"[^\W\d_]+")
    _GERMAN_SPELLED_OUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

    def __init__(self, lang, strings, allowlist=TRANSLATION_ALLOWLIST):
        """`strings`: key → value of one language (fieldHelp entries as "fieldHelp.<name>")."""
        self.lang = lang
        self.allowed_words = PLAIN_WORDS_ALLOWED.get(lang, {})
        self.strings = {key: value for key, value in strings.items()
                        if isinstance(value, str) and key.rsplit(".", 1)[-1] not in allowlist}

    def findings(self):
        """[(key, why)], one per string that holds a dropped word, in key order."""
        return sorted(self._silent() if self.lang in self.TONAL else self._twins())

    def _words(self, value):
        words = self._WORD.findall(self._SKIP.sub(" ", value))
        # Turkish capital İ is "i" and the dotted form must not look accented.
        return [word.replace("İ", "i").lower() if self.lang == "tr" else word.lower() for word in words]

    def _ascii_forms(self, word):
        """How the word looks when its letters beyond ASCII are dropped; German also spells them out."""
        dropped = word.replace("đ", "d").replace("ı", "i")
        forms = {"".join(c for c in unicodedata.normalize("NFD", dropped) if not unicodedata.combining(c))}
        if self.lang == "de":
            forms.add(word.translate(self._GERMAN_SPELLED_OUT))
        return forms

    def _twins(self):
        plain, accented, where = Counter(), defaultdict(Counter), defaultdict(list)
        for key, value in self.strings.items():
            for word in self._words(value):
                if word.isascii():
                    plain[word] += 1
                    where[word].append(key)
                else:
                    for form in self._ascii_forms(word):
                        accented[form][word] += 1
        found = {}
        for word, times in plain.items():
            twins = accented.get(word)
            if not twins or len(word) < self.MIN_LETTERS or word in self.allowed_words:
                continue
            if sum(twins.values()) >= self.RATIO * times:
                right = twins.most_common(1)[0][0]
                for key in where[word]:
                    found.setdefault(key, set()).add(f"«{word}» for «{right}»")
        return [(key, "dropped-letters " + ", ".join(sorted(words))) for key, words in found.items()]

    def _silent(self):
        found = []
        for key, value in self.strings.items():
            words = [word for word in self._words(value) if len(word) > 1]
            if len(words) >= self.SILENT_WORDS and all(word.isascii() for word in words):
                found.append((key, f"dropped-letters: no tone mark in a sentence of {len(words)} words"))
        return found


_KEY_LINE = re.compile(r"^( {2}| {4})([A-Za-z0-9_]+):")


def duplicate_keys(text):
    """Keys written twice in one language file, as `key` or `fieldHelp.key`.

    Read from the text, because loading the table cannot see them: in an
    object literal the later line silently wins, and the earlier one stays as
    dead text that reads like a live translation. A new key for the cloud
    account window took a name the kanban already used (2026-10-07): the new
    words were never shown, and the kanban's would have been replaced by
    them in any table where the order ran the other way.
    """
    seen, twice, block = set(), [], ""
    for line in text.splitlines():
        if block and re.match(r"^  \},?\s*$", line):
            block = ""
            continue
        found = _KEY_LINE.match(line)
        if not found:
            continue
        if len(found.group(1)) == 2:
            name = found.group(2)
            if line.rstrip().endswith("{"):
                block = name
        elif block:
            name = f"{block}.{found.group(2)}"
        else:
            continue
        if name in seen:
            twice.append(name)
        seen.add(name)
    return twice


def main() -> int:
    # Written twice is a fault of the file, not of what node loads from it:
    # checked first, and on a host without node too.
    doubled = {path.stem: duplicate_keys(path.read_text(encoding="utf-8"))
               for path in sorted(LANG_DIR.glob("*.js"))}
    doubled = {lang: keys for lang, keys in doubled.items() if keys}
    for lang, keys in doubled.items():
        print(f"{lang}: {len(keys)} keys written twice — the later line wins, the earlier is dead: "
              + ", ".join(keys[:10]), file=sys.stderr)
    if doubled:
        print("keep one line per key in static/js/i18n/<lang>.js (a new key needs a name of its own)",
              file=sys.stderr)
        return 1
    # i18n-data.js is an ES module; reading it means running it, and that needs
    # node. A host that CANNOT run this check must say so and stand aside: a
    # traceback here is indistinguishable from the check having found a missing
    # translation, which teaches the reader to ignore a red line that usually
    # means something real.
    #
    # But standing aside for a reason that is not TRUE is worse than either.
    # This comment used to say the controller has no node; it has v22.22.2,
    # installed through nvm, reachable only from an interactive zsh — so every
    # scripted shell saw nothing and this check quietly stood aside there.
    # find_node looks where version managers actually put it (scripts/_node.py).
    node = find_node()
    if node is None:
        print("i18n messages: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: "
              + ", ".join(node_search_paths()), file=sys.stderr)
        return 0
    try:
        proc = subprocess.run(
            [node, "--input-type=module", "-e", NODE_SNIPPET, str(DATA)],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        print(f"i18n messages: SKIPPED — {node} перестал запускаться", file=sys.stderr)
        return 0
    if proc.returncode != 0:
        print(f"i18n-data.js failed to load: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    data = json.loads(proc.stdout)
    en_strings, en_help = data["en"]["strings"], data["en"]["fieldHelp"]
    en_keys = set(en_strings)
    failed = False

    for lang, entry in data.items():
        if lang == "en":
            continue
        strings, fh = entry["strings"], entry["fieldHelp"]
        missing = sorted(en_keys - set(strings))
        missing_help = sorted(set(en_help) - set(fh))
        problems = []
        for k, v in strings.items():
            verdict = untranslated(lang, k, v, en_strings.get(k, ""))
            if verdict:
                problems.append((k, verdict))
        for k, v in fh.items():
            verdict = untranslated(lang, k, v, en_help.get(k, ""))
            if verdict:
                problems.append(("fieldHelp." + k, verdict))
        if lang not in NON_LATIN:
            problems += DroppedLetters(lang, {**strings, **{"fieldHelp." + k: v for k, v in fh.items()}}).findings()
        if missing or missing_help or problems:
            failed = True
            print(f"{lang}: missing {len(missing)} keys, {len(missing_help)} fieldHelp, "
                  f"{len(problems)} untranslated", file=sys.stderr)
            for k in missing[:10]:
                print(f"  - missing {k}", file=sys.stderr)
            for k, verdict in problems[:10]:
                print(f"  - {verdict}: {k}", file=sys.stderr)
    if failed:
        print("add the missing/untranslated strings to static/js/i18n-data.js "
              "(or extend TRANSLATION_ALLOWLIST for deliberate exceptions)", file=sys.stderr)
        return 1
    print(f"messages i18n OK: {len(en_keys)} keys + {len(en_help)} fieldHelp across "
          f"{len(data)} languages (translation-quality check on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
