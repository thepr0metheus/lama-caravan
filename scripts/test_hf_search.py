#!/usr/bin/env python3
"""Value snapshot: what /api/hf/search answers, for words and for an exact id.

Words go to Hugging Face's search: the limit is held to 5–100, every record
carries id, counts, date, pipeline tag and at most forty string tags, a record
without an id is dropped, and a failed search is a refusal with its reason.

An exact "author/repo" opens that repository without a search. It used to
answer a placeholder with downloads 0 and likes 0: the page drew a repository
nobody downloads, and saving the favorites wrote those zeros over a favorite's
real numbers (found on the live page, 2026-09-16). Now its record is read from
the model's own page, built by the same code as a search record; when that
cannot be read (a typo, a gated repository without a token) the answer is the
id alone — no counts at all, which the page shows as unknown.

Run: python3 scripts/test_hf_search.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.hf as hf  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class FakeHf:
    """Stands in for _hf_request: answers by path and remembers what was asked."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, path, timeout=12):
        self.asked.append(path)
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                return answer
        return {"_error": "not stubbed: " + path}


MODEL_PAGE = {
    "id": "bartowski/gemma-4-12B-it-GGUF", "downloads": 33831, "likes": 47,
    "createdAt": "2026-06-03T18:37:35.000Z", "pipeline_tag": "image-text-to-text",
    "tags": ["gguf", "vision", 7] + [f"t{i}" for i in range(50)], "siblings": [{"rfilename": "a.gguf"}],
}


def search_with(answers, query, limit=20):
    fake = FakeHf(answers)
    real = hf._hf_request
    hf._hf_request = fake
    try:
        return hf.hf_search(query, limit), fake.asked
    finally:
        hf._hf_request = real


def main():
    print("точный author/repo:")
    got, asked = search_with({"models/bartowski/gemma-4-12B-it-GGUF": MODEL_PAGE}, "  /bartowski/gemma-4-12B-it-GGUF/ ")
    record = got["repos"][0] if got.get("ok") and got.get("repos") else {}
    check(asked == ["models/bartowski/gemma-4-12B-it-GGUF"],
          f"спрашивает страницу модели, а не поиск; пробелы и слэши по краям срезаны (asked {asked})")
    check(len(got.get("repos") or []) == 1 and record.get("id") == "bartowski/gemma-4-12B-it-GGUF",
          "ответ — один репозиторий с этим id")
    check((record.get("downloads"), record.get("likes"), record.get("createdAt")) == (33831, 47, "2026-06-03T18:37:35.000Z"),
          f"настоящие загрузки, лайки и дата со страницы модели, а не нули (got {record.get('downloads')}, {record.get('likes')}, {record.get('createdAt')})")
    check(record.get("pipelineTag") == "image-text-to-text" and len(record.get("tags") or []) == 40 and 7 not in record.get("tags"),
          "модальность и не больше сорока строковых тегов — как у записи поиска")
    check("siblings" not in record, "лишние поля страницы модели в ответ не попадают")

    for label, answer in (("HF не ответил", {"_error": "HTTP Error 404"}), ("ответ без id", {"downloads": 5})):
        got, _ = search_with({"models/nobody/typo-GGUF": answer}, "nobody/typo-GGUF")
        check(got == {"ok": True, "repos": [{"id": "nobody/typo-GGUF"}]},
              f"{label} — только id, без нулевых чисел (got {got})")

    print("слова:")
    listing = [MODEL_PAGE, {"downloads": 1}, {"id": "acme/bare-GGUF"}]
    got, asked = search_with({"models?search=": listing}, "gemma 4", 1)
    check(asked == ["models?search=gemma%204&filter=gguf&limit=5&sort=downloads&direction=-1"],
          f"слова экранируются, лимит не меньше 5, только GGUF, по загрузкам (asked {asked})")
    ids = [r["id"] for r in got.get("repos") or []]
    check(ids == ["bartowski/gemma-4-12B-it-GGUF", "acme/bare-GGUF"], f"запись без id отброшена (got {ids})")
    bare = (got.get("repos") or [{}, {}])[-1]
    check(bare == {"id": "acme/bare-GGUF", "downloads": 0, "likes": 0, "createdAt": "", "pipelineTag": "", "tags": []},
          f"запись поиска без чисел — нули, как было (поиск HF их всегда отдаёт) (got {bare})")
    _, asked = search_with({"models?search=": []}, "gemma", 500)
    check("limit=100&" in asked[0], "лимит не больше 100")
    got, _ = search_with({"models?search=": {"_error": "HTTP Error 429"}}, "gemma")
    check(got == {"ok": False, "error": "HTTP Error 429"}, f"сбой поиска — отказ с причиной (got {got})")
    got, asked = search_with({}, "   ")
    check(got == {"ok": False, "error": "missing query"} and asked == [], "пустой запрос — отказ без обращения к HF")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf-search snapshots hold")


if __name__ == "__main__":
    main()
