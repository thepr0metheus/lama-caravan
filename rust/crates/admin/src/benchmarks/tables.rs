//! What the scores are called and how they group.

/// One frontier model the board compares against.
pub struct FrontierModel {
    /// Its name.
    pub name: &'static str,
    /// Who made it.
    pub org: &'static str,
    /// Its page at Artificial Analysis.
    pub slug: &'static str,
    /// The index as it was last written down here.
    pub aa: f64,
}

/// The tables.
pub struct BenchTables;

impl BenchTables {
    /// The frontier models.
    pub const FRONTIER: [FrontierModel; 15] = [
        FrontierModel { name: "Claude Fable 5", org: "Anthropic", slug: "claude-fable-5", aa: 64.9 },
        FrontierModel { name: "Claude Opus 4.8", org: "Anthropic", slug: "claude-opus-4-8", aa: 61.4 },
        FrontierModel { name: "GPT-5.5", org: "OpenAI", slug: "gpt-5-5", aa: 60.2 },
        FrontierModel { name: "GPT-5.4", org: "OpenAI", slug: "gpt-5-4", aa: 56.8 },
        FrontierModel { name: "GPT-5.4-Mini", org: "OpenAI", slug: "gpt-5-4-mini", aa: 48.9 },
        FrontierModel { name: "Claude Sonnet 4.6", org: "Anthropic", slug: "claude-sonnet-4-6", aa: 44.4 },
        FrontierModel { name: "o3", org: "OpenAI", slug: "o3", aa: 38.4 },
        FrontierModel { name: "Gemini 2.5 Pro", org: "Google", slug: "gemini-2-5-pro", aa: 34.6 },
        FrontierModel { name: "o4-mini", org: "OpenAI", slug: "o4-mini", aa: 33.1 },
        FrontierModel { name: "Claude Opus 4", org: "Anthropic", slug: "claude-4-opus", aa: 33.0 },
        FrontierModel { name: "DeepSeek R1", org: "DeepSeek", slug: "deepseek-r1", aa: 27.1 },
        FrontierModel { name: "Gemini 2.5 Flash", org: "Google", slug: "gemini-2-5-flash", aa: 20.6 },
        FrontierModel { name: "Llama 4 Maverick", org: "Meta", slug: "llama-4-maverick", aa: 18.4 },
        FrontierModel { name: "Mistral Large 2", org: "Mistral", slug: "mistral-large-2", aa: 15.1 },
        FrontierModel { name: "Llama 4 Scout", org: "Meta", slug: "llama-4-scout", aa: 13.5 },
    ];

    /// `(key, [label, what it measures, its scale, its group, its page])`.
    pub const META: [(&'static str, [&'static str; 5]); 18] = [
        (
            "arena_elo",
            [
                "Arena Elo",
                "Живой рейтинг: пользователи сравнивают ответы вслепую",
                "~800–1400",
                "summary",
                "https://lmarena.ai/leaderboard",
            ],
        ),
        (
            "open_llm_avg",
            [
                "Open LLM Avg",
                "Средний балл Open LLM Leaderboard v2 (IFEval+BBH+MATH+GPQA+MuSR+MMLU-Pro)",
                "0–100 %",
                "summary",
                "https://huggingface.co/open-llm-leaderboard/spaces",
            ],
        ),
        (
            "aa_intelligence",
            [
                "AA Intelligence",
                "Индекс качества Artificial Analysis: независимые прогоны на 10+ бенчмарках",
                "0–65",
                "summary",
                "https://artificialanalysis.ai/leaderboards/models",
            ],
        ),
        (
            "mmlu",
            [
                "MMLU",
                "Знания по 57 предметам: школа, вуз, наука",
                "0–100 %",
                "knowledge",
                "https://huggingface.co/datasets/cais/mmlu",
            ],
        ),
        (
            "mmlu_pro",
            [
                "MMLU-Pro",
                "Усложнённая MMLU — больше вариантов, меньше угадывания",
                "0–100 %",
                "knowledge",
                "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro",
            ],
        ),
        (
            "arc",
            [
                "ARC Challenge",
                "Логика и рассуждение на уровне школьных экзаменов",
                "0–100 %",
                "knowledge",
                "https://huggingface.co/datasets/allenai/ai2_arc",
            ],
        ),
        (
            "hellaswag",
            [
                "HellaSwag",
                "Здравый смысл: выбор правдоподобного продолжения фразы",
                "0–100 %",
                "knowledge",
                "https://rowanzellers.com/hellaswag/",
            ],
        ),
        (
            "winogrande",
            [
                "WinoGrande",
                "Понимание анафоры и контекста в предложениях",
                "0–100 %",
                "knowledge",
                "https://winogrande.allenai.org/",
            ],
        ),
        (
            "truthfulqa",
            [
                "TruthfulQA",
                "Правдивость: насколько модель избегает галлюцинаций",
                "0–100 %",
                "knowledge",
                "https://github.com/sylinrl/TruthfulQA",
            ],
        ),
        (
            "gsm8k",
            [
                "GSM8K",
                "Математика школьного уровня: 8 500 задач с пошаговым решением",
                "0–100 %",
                "math",
                "https://huggingface.co/datasets/openai/gsm8k",
            ],
        ),
        (
            "math",
            [
                "MATH",
                "Олимпиадная математика — сложные доказательства и формулы",
                "0–100 %",
                "math",
                "https://huggingface.co/datasets/lighteval/MATH",
            ],
        ),
        (
            "bbh",
            [
                "BBH",
                "BIG-Bench Hard: многошаговые рассуждения из 23 задач",
                "0–100 %",
                "math",
                "https://huggingface.co/datasets/lukaemon/bbh",
            ],
        ),
        (
            "gpqa",
            [
                "GPQA Diamond",
                "Вопросы уровня PhD по физике, химии, биологии",
                "0–100 %",
                "math",
                "https://huggingface.co/datasets/Idavidrein/gpqa",
            ],
        ),
        (
            "musr",
            [
                "MuSR",
                "Многоступенчатые рассуждения: детективы, загадки, логика",
                "0–100 %",
                "math",
                "https://huggingface.co/datasets/TAUR-Lab/MuSR",
            ],
        ),
        (
            "humaneval",
            [
                "HumanEval",
                "Написание кода на Python: pass@1 по 164 задачам",
                "0–100 %",
                "code",
                "https://huggingface.co/datasets/openai/openai_humaneval",
            ],
        ),
        (
            "ifeval",
            [
                "IFEval",
                "Точное следование форматным инструкциям (заглавные, списки, длина)",
                "0–100 %",
                "dialog",
                "https://huggingface.co/datasets/google/IFEval",
            ],
        ),
        (
            "mt_bench",
            [
                "MT-Bench",
                "Качество диалога и инструкций: оценка GPT-4 по шкале 1–10",
                "1–10",
                "dialog",
                "https://huggingface.co/spaces/lmsys/mt-bench",
            ],
        ),
        (
            "eq_bench",
            [
                "EQ-Bench",
                "Эмоциональный интеллект: понимание эмоций в литературных текстах",
                "0–100",
                "dialog",
                "https://eqbench.com/",
            ],
        ),
    ];

    /// `(id, label, keys)` in the order the card lists them.
    pub const GROUPS: [(&'static str, &'static str, &'static [&'static str]); 5] = [
        ("summary", "Сводные рейтинги", &["arena_elo", "open_llm_avg", "aa_intelligence"]),
        ("knowledge", "Знания и понимание", &["mmlu", "mmlu_pro", "arc", "hellaswag", "winogrande", "truthfulqa"]),
        ("math", "Математика и рассуждение", &["gsm8k", "math", "bbh", "gpqa", "musr"]),
        ("code", "Код", &["humaneval"]),
        ("dialog", "Диалог и инструкции", &["ifeval", "mt_bench", "eq_bench"]),
    ];

    /// The scores a row shows first.
    pub const INLINE: [&'static str; 11] = [
        "arena_elo",
        "open_llm_avg",
        "aa_intelligence",
        "mmlu",
        "mmlu_pro",
        "humaneval",
        "gsm8k",
        "ifeval",
        "bbh",
        "math",
        "gpqa",
    ];

    /// A dataset's name on a model card and the score it gives, first match wins. The ones with `-` cannot match a name whose dashes became `_`, as in Python; and `mmlu` takes `mmlu_pro` first: as it is.
    pub const DATASETS: [(&'static str, &'static str); 19] = [
        ("cais/mmlu", "mmlu"),
        ("mmlu", "mmlu"),
        ("mmlu_pro", "mmlu_pro"),
        ("mmlu-pro", "mmlu_pro"),
        ("openai_humaneval", "humaneval"),
        ("humaneval", "humaneval"),
        ("gsm8k", "gsm8k"),
        ("math", "math"),
        ("ai2_arc", "arc"),
        ("arc", "arc"),
        ("hellaswag", "hellaswag"),
        ("winogrande", "winogrande"),
        ("truthfulqa", "truthfulqa"),
        ("truthful_qa", "truthfulqa"),
        ("bbh", "bbh"),
        ("big_bench_hard", "bbh"),
        ("gpqa", "gpqa"),
        ("ifeval", "ifeval"),
        ("musr", "musr"),
    ];

    /// A column of the Open LLM Leaderboard and the score it gives.
    pub const OPEN_LLM: [(&'static str, &'static str); 7] = [
        ("Average ⬆️", "open_llm_avg"),
        ("IFEval", "ifeval"),
        ("BBH", "bbh"),
        ("MATH Lvl 5", "math"),
        ("GPQA", "gpqa"),
        ("MUSR", "musr"),
        ("MMLU-PRO", "mmlu_pro"),
    ];

    /// Who made a base model, by what its name looks like, first match wins.
    pub const AUTHOR_HINTS: [(&'static str, &'static str); 14] = [
        (r"(?i)qwen[\d]", "Qwen"),
        (r"(?i)llama[-_]?[\d]", "meta-llama"),
        (r"(?i)mistral|mixtral", "mistralai"),
        (r"(?i)gemma[-_]?[\d]", "google"),
        (r"(?i)\bphi[-_]?[\d]", "microsoft"),
        (r"(?i)falcon", "tiiuae"),
        (r"(?i)deepseek", "deepseek-ai"),
        (r"(?i)\byi[-_][\d]", "01-ai"),
        (r"(?i)command[-_r]", "CohereForAI"),
        (r"(?i)\bsolar\b", "upstage"),
        (r"(?i)\bgpt[-_]?j\b", "EleutherAI"),
        (r"(?i)\bgpt[-_]?neo", "EleutherAI"),
        (r"(?i)stablelm", "stabilityai"),
        (r"(?i)vicuna|wizard|orca", "lmsys"),
    ];
}
