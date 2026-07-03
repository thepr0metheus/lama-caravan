"""Model quality metadata: Artificial Analysis scores, Open LLM Leaderboard,
arena ELO and the on-disk bench cache (.bench_cache/)."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from caravan.admin.hf import _hf_request
from caravan.admin.paths import PROJECT_ROOT, _BENCH_CACHE_DIR
from caravan.admin.state import admin_state
from caravan.common.fsio import atomic_write_text
from caravan.common.ttl_cache import MISS, TtlCache


_BENCH_URL_TTL = 3600  # benchmark data rarely changes
_bench_url_cache = TtlCache(_BENCH_URL_TTL)

def _fetch_json_cached(url: str, timeout: int = 15, token: str = "") -> "dict | list":
    """Generic HTTPS JSON fetch with 1-hour cache."""
    cache_key = url + ("|auth" if token else "")
    hit = _bench_url_cache.get(cache_key)
    if hit is not MISS:
        return hit
    headers = {"User-Agent": "lama-caravan/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        _bench_url_cache.put(cache_key, data)
        return data
    except Exception as exc:
        return {"_error": str(exc)}

_aa_html_cache = TtlCache(_BENCH_URL_TTL)

def _fetch_html_cached(url: str, timeout: int = 20) -> str:
    """Fetch HTML page with 1-hour in-memory cache."""
    hit = _aa_html_cache.get(url)
    if hit is not MISS:
        return hit
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read().decode("utf-8", errors="replace")
        _aa_html_cache.put(url, data)
        return data
    except Exception:
        return ""

def _aa_slug(model_id: str) -> str:
    """Convert HF model ID to Artificial Analysis URL slug.
    e.g. google/gemma-4-12b-it → gemma-4-12b
         Qwen/Qwen3.6-27B      → qwen3-6-27b
    """
    name = model_id.split("/")[-1].lower()
    name = re.sub(r"[._]", "-", name)
    # Strip instruction/chat suffixes
    name = re.sub(r"[-_](it|instruct|chat|hf|tulu)$", "", name)
    # Strip version like -v0-2
    name = re.sub(r"-v\d+(-\d+)*$", "", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name

_FRONTIER_MODELS = [
    # name, org, aa_slug, hardcoded_aa (AA Intelligence Index, ~June 2026)
    ("Claude Fable 5",    "Anthropic", "claude-fable-5",    64.9),
    ("Claude Opus 4.8",   "Anthropic", "claude-opus-4-8",   61.4),
    ("GPT-5.5",           "OpenAI",    "gpt-5-5",           60.2),
    ("GPT-5.4",           "OpenAI",    "gpt-5-4",           56.8),
    ("GPT-5.4-Mini",      "OpenAI",    "gpt-5-4-mini",      48.9),
    ("Claude Sonnet 4.6", "Anthropic", "claude-sonnet-4-6", 44.4),
    ("o3",                "OpenAI",    "o3",                38.4),
    ("Gemini 2.5 Pro",    "Google",    "gemini-2-5-pro",    34.6),
    ("o4-mini",           "OpenAI",    "o4-mini",           33.1),
    ("Claude Opus 4",     "Anthropic", "claude-4-opus",     33.0),
    ("DeepSeek R1",       "DeepSeek",  "deepseek-r1",       27.1),
    ("Gemini 2.5 Flash",  "Google",    "gemini-2-5-flash",  20.6),
    ("Llama 4 Maverick",  "Meta",      "llama-4-maverick",  18.4),
    ("Mistral Large 2",   "Mistral",   "mistral-large-2",   15.1),
    ("Llama 4 Scout",     "Meta",      "llama-4-scout",     13.5),
]

# Artificial Analysis embeds model data inline as
#   {"label":"…","artificialAnalysisIntelligenceIndex":56.8,"detailsUrl":"/models/gpt-5-4"}
# (it used to be wrapped in <script type="application/ld+json"> — that wrapper is
# gone, but the field triplet is intact). One model page carries its own score plus
# ~12 comparison models, so a single fetch harvests scores for several models at once.
_AA_PAIR_RE = re.compile(
    r'"artificialAnalysisIntelligenceIndex":([0-9.]+)[^}]{0,80}?"detailsUrl":"/models/([a-z0-9.\-]+)"'
)

def _aa_extract_scores(html: str) -> dict:
    """Parse all {slug: AA Intelligence Index} pairs embedded in an AA page."""
    out: dict = {}
    for score, slug in _AA_PAIR_RE.findall(html or ""):
        if slug in out:
            continue
        try:
            out[slug] = round(float(score), 1)
        except Exception:
            pass
    return out

def _aa_resolve_slug(model_id: str) -> str:
    """Best-effort map of a provider/HF model id to an AA URL slug.
    e.g. nvidia/nemotron-3-nano-30b-a3b:free → nemotron-3-nano-30b-a3b
         openai/gpt-5.4-mini                 → gpt-5-4-mini
    """
    name = model_id.split("/")[-1].lower()
    name = re.sub(r":.*$", "", name)                       # strip :free / :nitro / …
    name = re.sub(r"[._]", "-", name)
    name = re.sub(r"-(it|instruct|chat|hf|tulu)$", "", name)
    name = re.sub(r"-v\d+(-\d+)*$", "", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name

def _fetch_aa_by_slug(slug: str) -> "float | None":
    """Fetch AA Intelligence Index for an exact AA slug. Returns float or None."""
    html = _fetch_html_cached(f"https://artificialanalysis.ai/models/{slug}")
    return _aa_extract_scores(html).get(slug) if html else None

_frontier_cache_lock = threading.Lock()

_frontier_cache: "list | None" = None

_frontier_cache_ts: float = 0

_FRONTIER_TTL = 12 * 3600  # 12 hours

_frontier_refresh_running = False

def hf_get_reference_models(force: bool = False) -> dict:
    """Return AA Intelligence scores for curated frontier models.

    Returns hardcoded defaults immediately. When force=True, fetches fresh
    data from AA synchronously (called explicitly by the user via 🔄).
    Background auto-refresh updates the cache after startup.
    """
    global _frontier_cache, _frontier_cache_ts, _frontier_refresh_running

    if force:
        # Synchronous refresh on explicit user request
        results = []
        for name, org, slug, default_aa in _FRONTIER_MODELS:
            score = _fetch_aa_by_slug(slug)
            results.append({"name": name, "org": org, "slug": slug,
                            "aa": score if score is not None else default_aa})
        with _frontier_cache_lock:
            _frontier_cache = results
            _frontier_cache_ts = time.time()
        return {"ok": True, "models": results, "source": "aa"}

    # Return cached live data if fresh
    with _frontier_cache_lock:
        if _frontier_cache is not None and time.time() - _frontier_cache_ts < _FRONTIER_TTL:
            return {"ok": True, "models": _frontier_cache, "source": "cache"}

    # Return hardcoded defaults instantly; kick off a background refresh
    defaults = [{"name": n, "org": o, "slug": s, "aa": aa}
                for n, o, s, aa in _FRONTIER_MODELS]

    # No background fetch — hardcoded values are stable; user can force-refresh via 🔄
    return {"ok": True, "models": defaults, "source": "default"}

def _fetch_aa_score(model_id: str) -> dict:
    """Fetch Artificial Analysis Intelligence Index for a model.
    Returns {"aa_intelligence": float} or {} if not found.
    """
    slug = _aa_slug(model_id)
    html = _fetch_html_cached(f"https://artificialanalysis.ai/models/{slug}")
    score = _aa_extract_scores(html).get(slug) if html else None
    return {"aa_intelligence": score} if score is not None else {}

# ── AA scores for arbitrary models (Kanban server list) ───────────────────────
# A persistent {slug: AA Intelligence Index} map, seeded from the curated frontier
# list and grown opportunistically: every model page we fetch contributes its own
# score plus its comparison neighbours, so the map fills fast. Misses (no AA page →
# 404) are negative-cached so we don't re-hammer them.
_AA_MAP_PATH = PROJECT_ROOT / "logs" / "aa-scores-cache.json"

_AA_MAP_TTL = 7 * 86400

_AA_NEG_TTL = 86400

_AA_FETCH_CAP = 12              # max live page fetches per /api/aa-scores request

_aa_map_lock = threading.Lock()

_aa_map: "dict | None" = None   # {slug: score}

_aa_neg: dict = {}              # slug → ts of last empty/404 fetch

def _aa_map_load() -> dict:
    global _aa_map
    if _aa_map is not None:
        return _aa_map
    seeded = {slug: aa for _n, _o, slug, aa in _FRONTIER_MODELS}
    try:
        raw = json.loads(_AA_MAP_PATH.read_text("utf-8"))
        if time.time() - raw.get("cached_at", 0) < _AA_MAP_TTL:
            for k, v in (raw.get("scores") or {}).items():
                seeded.setdefault(k, v)  # curated frontier values stay authoritative
            # Restore the negative cache so models with no AA page aren't re-scraped
            # on every restart (freshness is still checked per-use against _AA_NEG_TTL).
            for slug, ts in (raw.get("neg") or {}).items():
                _aa_neg.setdefault(slug, ts)
    except Exception:
        pass
    _aa_map = seeded
    return _aa_map

def _aa_map_save():
    try:
        _AA_MAP_PATH.parent.mkdir(exist_ok=True)
        atomic_write_text(_AA_MAP_PATH, json.dumps(
            {"cached_at": time.time(), "scores": _aa_map, "neg": _aa_neg},
            ensure_ascii=False))
    except Exception:
        pass

def hf_get_aa_scores(model_ids: "list[str]", do_fetch: bool = True) -> dict:
    """Resolve AA Intelligence Index for the given model ids.

    Returns {"ok": True, "scores": {id: score}, "misses": [ids with no AA page]}.
    Looks up the in-memory map first (instant); for misses, fetches up to
    _AA_FETCH_CAP pages per call (in request order, so callers should list the
    models they care about most first). "misses" are ids confirmed to have no AA
    page (negative-cached) — callers can stop asking for those. Ids that were
    neither resolved nor confirmed-bad were skipped by the per-call cap and should
    be requested again to load progressively."""
    with _aa_map_lock:
        amap = _aa_map_load()
        now = time.time()
        result: dict = {}
        miss_pairs: list = []
        for mid in model_ids:
            if not isinstance(mid, str) or not mid.strip():
                continue
            slug = _aa_resolve_slug(mid)
            if slug in amap:
                result[mid] = amap[slug]
            else:
                miss_pairs.append((mid, slug))

        dirty = False
        if do_fetch and miss_pairs:
            fetched = 0
            for mid, slug in miss_pairs:
                if fetched >= _AA_FETCH_CAP:
                    break
                if now - _aa_neg.get(slug, 0) < _AA_NEG_TTL:
                    continue  # already known-bad this cycle; skip without spending budget
                fetched += 1
                html = _fetch_html_cached(f"https://artificialanalysis.ai/models/{slug}")
                harvested = _aa_extract_scores(html) if html else {}
                if harvested:
                    amap.update(harvested)
                    dirty = True
                if slug in amap:
                    result[mid] = amap[slug]
                else:
                    _aa_neg[slug] = now
                    dirty = True
        if dirty:
            _aa_map_save()
        # Confirmed-bad: requested, still unresolved, and negative-cached (fresh).
        bad = [mid for mid, slug in miss_pairs
               if mid not in result and now - _aa_neg.get(slug, 0) < _AA_NEG_TTL]
        return {"ok": True, "scores": result, "misses": bad}

_BASE_AUTHOR_HINTS = [
    # (pattern in model name, canonical HF author)
    (re.compile(r"(?i)qwen[\d]"), "Qwen"),
    (re.compile(r"(?i)llama[-_]?[\d]"), "meta-llama"),
    (re.compile(r"(?i)mistral|mixtral"), "mistralai"),
    (re.compile(r"(?i)gemma[-_]?[\d]"), "google"),
    (re.compile(r"(?i)\bphi[-_]?[\d]"), "microsoft"),
    (re.compile(r"(?i)falcon"), "tiiuae"),
    (re.compile(r"(?i)deepseek"), "deepseek-ai"),
    (re.compile(r"(?i)\byi[-_][\d]"), "01-ai"),
    (re.compile(r"(?i)command[-_r]"), "CohereForAI"),
    (re.compile(r"(?i)\bsolar\b"), "upstage"),
    (re.compile(r"(?i)\bgpt[-_]?j\b"), "EleutherAI"),
    (re.compile(r"(?i)\bgpt[-_]?neo"), "EleutherAI"),
    (re.compile(r"(?i)stablelm"), "stabilityai"),
    (re.compile(r"(?i)vicuna|wizard|orca"), "lmsys"),
]

def _hf_infer_base_models(gguf_repo_id: str) -> "list[str]":
    """
    Return candidate base-model IDs for a GGUF repo.
    1. Checks model card base_model field.
    2. Falls back to name heuristics with known-author hints.
    Returns list of candidates to try in order.
    """
    if "/" not in gguf_repo_id:
        return [gguf_repo_id]
    author, name = gguf_repo_id.split("/", 1)
    # Strip common suffixes
    clean = re.sub(r"[-_](gguf|q[\d]+|imatrix|exl2)$", "", name, flags=re.IGNORECASE)
    clean = re.sub(r"[-_]gguf$", "", clean, flags=re.IGNORECASE)

    encoded = urllib.parse.quote(gguf_repo_id, safe="/")
    card = _hf_request(f"models/{encoded}")
    if isinstance(card, dict) and not card.get("_error"):
        cd = card.get("cardData") or {}
        bm = cd.get("base_model") or card.get("base_model")
        if bm:
            bm_list = [bm] if isinstance(bm, str) else [b for b in bm if b]
            # Discard card metadata where base_model author == GGUF repo author
            # (common in quantizer repos: bartowski/X-GGUF → base_model: bartowski/X)
            bm_list = [b for b in bm_list if b.split("/")[0].lower() != author.lower()]
            if bm_list:
                return bm_list

    candidates = []
    # Try hints: if the cleaned model name matches a known family, prepend canonical author
    for pat, hint_author in _BASE_AUTHOR_HINTS:
        if pat.search(clean):
            candidates.append(f"{hint_author}/{clean}")
            break
    # Always include same-author fallback (may be correct for first-party repos)
    same_author = f"{author}/{clean}"
    if same_author not in candidates:
        candidates.append(same_author)
    return candidates

def _normalize_score(val) -> "float | None":
    """Normalize a score value to 0-100 range (converts 0-1 fractions)."""
    if val is None:
        return None
    try:
        f = float(val)
        if 0 < f <= 1.0:
            f = round(f * 100, 1)
        return round(f, 1)
    except (TypeError, ValueError):
        return None

# ── Benchmark metadata ────────────────────────────────────────────────────────
# key → [english_name, russian_description, scale, group, url]
BENCH_META: "dict[str, list]" = {
    "arena_elo":    ["Arena Elo",      "Живой рейтинг: пользователи сравнивают ответы вслепую",                "~800–1400", "summary",  "https://lmarena.ai/leaderboard"],
    "open_llm_avg": ["Open LLM Avg",   "Средний балл Open LLM Leaderboard v2 (IFEval+BBH+MATH+GPQA+MuSR+MMLU-Pro)", "0–100 %", "summary", "https://huggingface.co/open-llm-leaderboard/spaces"],
    "aa_intelligence": ["AA Intelligence", "Индекс качества Artificial Analysis: независимые прогоны на 10+ бенчмарках", "0–65",  "summary",  "https://artificialanalysis.ai/leaderboards/models"],
    "mmlu":         ["MMLU",           "Знания по 57 предметам: школа, вуз, наука",                            "0–100 %",  "knowledge","https://huggingface.co/datasets/cais/mmlu"],
    "mmlu_pro":     ["MMLU-Pro",       "Усложнённая MMLU — больше вариантов, меньше угадывания",               "0–100 %",  "knowledge","https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro"],
    "arc":          ["ARC Challenge",  "Логика и рассуждение на уровне школьных экзаменов",                    "0–100 %",  "knowledge","https://huggingface.co/datasets/allenai/ai2_arc"],
    "hellaswag":    ["HellaSwag",      "Здравый смысл: выбор правдоподобного продолжения фразы",               "0–100 %",  "knowledge","https://rowanzellers.com/hellaswag/"],
    "winogrande":   ["WinoGrande",     "Понимание анафоры и контекста в предложениях",                         "0–100 %",  "knowledge","https://winogrande.allenai.org/"],
    "truthfulqa":   ["TruthfulQA",     "Правдивость: насколько модель избегает галлюцинаций",                  "0–100 %",  "knowledge","https://github.com/sylinrl/TruthfulQA"],
    "gsm8k":        ["GSM8K",          "Математика школьного уровня: 8 500 задач с пошаговым решением",        "0–100 %",  "math",     "https://huggingface.co/datasets/openai/gsm8k"],
    "math":         ["MATH",           "Олимпиадная математика — сложные доказательства и формулы",            "0–100 %",  "math",     "https://huggingface.co/datasets/lighteval/MATH"],
    "bbh":          ["BBH",            "BIG-Bench Hard: многошаговые рассуждения из 23 задач",                 "0–100 %",  "math",     "https://huggingface.co/datasets/lukaemon/bbh"],
    "gpqa":         ["GPQA Diamond",   "Вопросы уровня PhD по физике, химии, биологии",                        "0–100 %",  "math",     "https://huggingface.co/datasets/Idavidrein/gpqa"],
    "musr":         ["MuSR",           "Многоступенчатые рассуждения: детективы, загадки, логика",             "0–100 %",  "math",     "https://huggingface.co/datasets/TAUR-Lab/MuSR"],
    "humaneval":    ["HumanEval",      "Написание кода на Python: pass@1 по 164 задачам",                      "0–100 %",  "code",     "https://huggingface.co/datasets/openai/openai_humaneval"],
    "ifeval":       ["IFEval",         "Точное следование форматным инструкциям (заглавные, списки, длина)",   "0–100 %",  "dialog",   "https://huggingface.co/datasets/google/IFEval"],
    "mt_bench":     ["MT-Bench",       "Качество диалога и инструкций: оценка GPT-4 по шкале 1–10",            "1–10",     "dialog",   "https://huggingface.co/spaces/lmsys/mt-bench"],
    "eq_bench":     ["EQ-Bench",       "Эмоциональный интеллект: понимание эмоций в литературных текстах",    "0–100",    "dialog",   "https://eqbench.com/"],
}

BENCH_GROUPS = [
    ("summary",   "Сводные рейтинги",         ["arena_elo", "open_llm_avg", "aa_intelligence"]),
    ("knowledge", "Знания и понимание",        ["mmlu", "mmlu_pro", "arc", "hellaswag", "winogrande", "truthfulqa"]),
    ("math",      "Математика и рассуждение",  ["gsm8k", "math", "bbh", "gpqa", "musr"]),
    ("code",      "Код",                       ["humaneval"]),
    ("dialog",    "Диалог и инструкции",       ["ifeval", "mt_bench", "eq_bench"]),
]

# Keys to show inline on the repo card (priority order, up to 3 shown)
BENCH_INLINE_KEYS = ["arena_elo", "open_llm_avg", "aa_intelligence", "mmlu", "mmlu_pro", "humaneval", "gsm8k", "ifeval", "bbh", "math", "gpqa"]

def _parse_hf_eval_results(model_data: dict) -> dict:
    """Extract benchmark scores from HF model card eval_results."""
    scores: dict = {}
    card = model_data.get("cardData") or {}
    evals = card.get("eval_results") or model_data.get("eval_results") or []
    if not isinstance(evals, list):
        return scores

    DATASET_TO_KEY = {
        "cais/mmlu": "mmlu", "mmlu": "mmlu",
        "mmlu_pro": "mmlu_pro", "mmlu-pro": "mmlu_pro",
        "openai_humaneval": "humaneval", "humaneval": "humaneval",
        "gsm8k": "gsm8k",
        "math": "math",
        "ai2_arc": "arc", "arc": "arc",
        "hellaswag": "hellaswag",
        "winogrande": "winogrande",
        "truthfulqa": "truthfulqa", "truthful_qa": "truthfulqa",
        "bbh": "bbh", "big_bench_hard": "bbh",
        "gpqa": "gpqa",
        "ifeval": "ifeval",
        "musr": "musr",
    }

    for entry in evals:
        if not isinstance(entry, dict):
            continue
        dataset = entry.get("dataset") or {}
        ds_name = (dataset.get("name") or dataset.get("type") or "").lower().replace("-", "_")
        key = None
        for pattern, mapped in DATASET_TO_KEY.items():
            if pattern in ds_name:
                key = mapped
                break
        if not key:
            continue
        for metric in (entry.get("metrics") or []):
            if not isinstance(metric, dict):
                continue
            val = _normalize_score(metric.get("value"))
            if val is not None:
                scores.setdefault(key, val)
                break
    return scores

_llm_lb: dict = {}              # fullname.lower() → {metric_key: float}

_llm_lb_loaded_at: float = 0

_llm_lb_loading = False

_LLM_LB_TTL = 86400            # refresh once a day

_LLM_LB_FIELDS = {
    "Average ⬆️": "open_llm_avg",  # Average ⬆️
    "IFEval":    "ifeval",
    "BBH":       "bbh",
    "MATH Lvl 5":"math",
    "GPQA":      "gpqa",
    "MUSR":      "musr",
    "MMLU-PRO":  "mmlu_pro",
}

def _load_llm_lb_bg():
    global _llm_lb, _llm_lb_loaded_at, _llm_lb_loading
    token = admin_state.get("hfToken") or ""
    result: dict = {}
    offset = 0
    limit = 100   # datasets-server hard cap
    total = None
    while True:
        url = (
            "https://datasets-server.huggingface.co/rows"
            "?dataset=open-llm-leaderboard%2Fcontents"
            f"&config=default&split=train&offset={offset}&limit={limit}"
        )
        data = _fetch_json_cached(url, timeout=30, token=token)
        if not isinstance(data, dict) or data.get("_error"):
            break
        if total is None:
            total = data.get("num_rows_total") or 0
        rows = data.get("rows") or []
        for r in rows:
            row = r.get("row") or {}
            fullname = (row.get("fullname") or "").lower().strip()
            if not fullname:
                continue
            scores = {}
            for field, key in _LLM_LB_FIELDS.items():
                v = _normalize_score(row.get(field))
                if v is not None:
                    scores[key] = v
            if scores:
                result[fullname] = scores
        offset += len(rows)
        if not rows or (total and offset >= total):
            break
    if result:
        _llm_lb.clear()
        _llm_lb.update(result)
        _llm_lb_loaded_at = time.time()
    _llm_lb_loading = False

def _ensure_llm_lb():
    global _llm_lb_loading
    if _llm_lb_loading:
        return
    if _llm_lb and time.time() - _llm_lb_loaded_at < _LLM_LB_TTL:
        return
    _llm_lb_loading = True
    threading.Thread(target=_load_llm_lb_bg, daemon=True).start()

def _fetch_open_llm_scores(model_id: str) -> dict:
    """Fetch scores from Open LLM Leaderboard v2 (background-cached dataset)."""
    _ensure_llm_lb()
    return dict(_llm_lb.get(model_id.lower()) or {})

def _llm_lb_status() -> dict:
    return {"loaded": bool(_llm_lb), "count": len(_llm_lb), "loading": _llm_lb_loading,
            "age_hours": round((time.time() - _llm_lb_loaded_at) / 3600, 1) if _llm_lb_loaded_at else None}

def _fetch_arena_elo(model_id: str) -> dict:
    """
    Try to fetch Chatbot Arena Elo via datasets-server.
    Requires HF token because lmsys/chatbot-arena-leaderboard is gated.
    """
    token = admin_state.get("hfToken") or ""
    if not token:
        return {}
    model_name = model_id.split("/")[-1] if "/" in model_id else model_id
    url = (
        "https://datasets-server.huggingface.co/search"
        "?dataset=lmsys%2Fchatbot-arena-leaderboard"
        "&config=default&split=train"
        f"&query={urllib.parse.quote(model_name)}&limit=5"
    )
    raw = _fetch_json_cached(url, timeout=12, token=token)
    if not isinstance(raw, dict) or raw.get("_error"):
        return {}
    rows = raw.get("rows") or []
    for r in rows:
        row = r.get("row") or {}
        row_key = (row.get("key") or row.get("model") or row.get("Model") or "").lower()
        if model_name.lower() in row_key or row_key in model_id.lower():
            elo = _normalize_score(
                row.get("elo") or row.get("Elo") or row.get("elo_rating") or row.get("rating")
            )
            if elo is not None:
                return {"arena_elo": elo}
    return {}

_BENCH_RESULT_TTL = 90 * 86400  # 3 months

def _bench_cache_path(repo_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "_", repo_id)
    return _BENCH_CACHE_DIR / f"{safe}.json"

def _bench_cache_load(repo_id: str) -> "dict | None":
    try:
        p = _bench_cache_path(repo_id)
        if not p.exists():
            return None
        raw = json.loads(p.read_text("utf-8"))
        if time.time() - raw.get("cached_at", 0) > _BENCH_RESULT_TTL:
            return None
        return raw.get("data")
    except Exception:
        return None

def _bench_cache_save(repo_id: str, data: dict):
    try:
        _BENCH_CACHE_DIR.mkdir(exist_ok=True)
        p = _bench_cache_path(repo_id)
        atomic_write_text(p, json.dumps({"cached_at": time.time(), "data": data}, ensure_ascii=False))
    except Exception:
        pass

def hf_bench_search(query: str) -> dict:
    """Find cached bench scores for a locally-running model by fuzzy name match."""
    import re as _re
    q = query.strip().lower()
    if len(q) < 3:
        return {"ok": False, "error": "query too short"}
    if not _BENCH_CACHE_DIR.exists():
        return {"ok": False}
    # Normalize separators: collapse _, --, - variants so "qwen_qwen3.6-27b"
    # matches a cache file named "qwen--qwen3.6-27b-gguf"
    def _norm(s: str) -> str:
        return _re.sub(r'[-_]+', '-', s)
    q_norm = _norm(q)
    for p in sorted(_BENCH_CACHE_DIR.glob("*.json")):
        stem = p.stem.lower()
        if q not in stem and q_norm not in _norm(stem):
            continue
        try:
            raw = json.loads(p.read_text("utf-8"))
            data = raw.get("data") or {}
            if data.get("scores"):
                return {"ok": True, **data}
        except Exception:
            pass
    return {"ok": False}

def hf_get_benchmarks(repo_id: str, force: bool = False) -> dict:
    """
    Fetch all available benchmark scores for a GGUF repo.
    Combines HF model card eval_results, Open LLM Leaderboard, and Chatbot Arena.
    Results are cached on disk for 3 months; pass force=True to bypass cache.
    """
    repo_id = repo_id.strip().strip("/")
    if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo_id):
        return {"ok": False, "error": "invalid repo id"}

    if not force:
        cached = _bench_cache_load(repo_id)
        if cached:
            return {**cached, "from_cache": True}

    scores: dict = {}
    data_from: str = ""
    base_models = _hf_infer_base_models(repo_id)
    if not base_models:
        base_models = [repo_id]

    for base_id in base_models[:3]:
        encoded = urllib.parse.quote(base_id, safe="/")
        model_data = _hf_request(f"models/{encoded}")
        if isinstance(model_data, dict) and not model_data.get("_error"):
            for k, v in _parse_hf_eval_results(model_data).items():
                scores.setdefault(k, v)

        for k, v in _fetch_open_llm_scores(base_id).items():
            scores.setdefault(k, v)

        for k, v in _fetch_arena_elo(base_id).items():
            scores.setdefault(k, v)

        if scores:
            data_from = base_id
            break

    # Fallback: try Artificial Analysis Intelligence Index
    if not scores:
        for base_id in base_models[:2]:
            aa = _fetch_aa_score(base_id)
            if aa:
                scores.update(aa)
                data_from = base_id
                break
        if not scores:
            aa = _fetch_aa_score(repo_id)
            if aa:
                scores.update(aa)
                data_from = repo_id

    inline = [k for k in BENCH_INLINE_KEYS if k in scores][:3]

    result = {
        "ok": True,
        "repo": repo_id,
        "base_models": base_models,
        "data_from": data_from,
        "scores": scores,
        "inline": inline,
        "groups": [
            {
                "id": gid,
                "label": glabel,
                "keys": [k for k in keys if k in scores],
            }
            for gid, glabel, keys in BENCH_GROUPS
        ],
        "meta": {k: BENCH_META[k] for k in scores if k in BENCH_META},
    }
    if scores:
        _bench_cache_save(repo_id, result)
    return result
