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
    (3+ words) — short labels and shared terms pass.
Deliberate exceptions live in TRANSLATION_ALLOWLIST."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "static" / "js" / "i18n-data.js"

NON_LATIN = {"ru", "zh", "hi", "ar", "bn", "ja", "ko", "te", "mr", "ta", "ur"}

# Keys that are intentionally identical / partly English in every language.
TRANSLATION_ALLOWLIST = {
    "appAcronym",              # the LAMA CARAVAN acronym expansion — English by design
    "topologyServerSection",   # brand string "LAMA CARAVAN Server"
    "tmPromptGenTps",          # "prompt / gen t/s" — all identifiers, identical in latin locales
    "rtTitleOutputServer",     # "Output → server" — literally the same words in it/id
}

# Identifiers that legitimately stay latin inside any translation.
_IDENT_RE = re.compile(
    r"--[a-z0-9-]+|/[A-Za-z]\w*|\b[A-Z]{2,}[A-Za-z0-9_]*\b"
    r"|[a-z_]{2,}_[a-z_]+"
    r"|\b(llama\.cpp|llama-server|Jinja|vLLM|PyPI|HuggingFace|Hugging Face|OpenClaw"
    r"|OpenAI|OpenRouter|Ollama|Qwen[\w.]*|gemma[\w.-]*|deepseek[\w.-]*|caravan[\w-]*"
    r"|GGUF|VRAM|CUDA|RoPE|flash[- ]attention|Prometheus|nvidia[\w/.-]*|whisper"
    r"|faster-whisper|Docker|systemd|launchd|token(s)?|prompt|batch|slot(s)?|cloud"
    r"|repo id|Blackwell|checkpoint|safetensors|webui|web UI|Kanban|small|default"
    r"|embeddings?|main|spill|max_tokens|FIFO|heartbeat|API|url|json|yaml|ini|Exa|MCP)\b",
    re.IGNORECASE,
)
_ENG_PHRASE = re.compile(r"\b[A-Za-z]{3,}(\s+[A-Za-z']{2,}){2,}\b")   # 3+ latin words

NODE_SNIPPET = """
import(process.argv[1]).then(({ LANGS, messages }) => {
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


def main() -> int:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_SNIPPET, str(DATA)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"i18n-data.js failed to load: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    data = json.loads(proc.stdout)
    en_strings, en_help = data["en"]["strings"], data["en"]["fieldHelp"]
    en_keys = set(en_strings)
    failed = False

    def untranslated(lang, key, value, en_value):
        if key in TRANSLATION_ALLOWLIST or not value:
            return None
        if en_value and en_value.startswith("{") is False and value == en_value:
            # verbatim en copy — flag for ANY locale when it's real prose
            if len(value) > 14 and len(value.split()) >= 3 and lang not in NON_LATIN:
                return "en-copy"
        if lang in NON_LATIN and _ENG_PHRASE.search(_IDENT_RE.sub(" ", value)):
            return "english-phrase"
        return None

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
