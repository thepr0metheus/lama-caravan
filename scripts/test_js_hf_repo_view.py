#!/usr/bin/env python3
"""Snapshot of static/js/hf-repo-view.js — the repository on the right of /hf.

Pinned by value. HfQuant: the rank table and its fallbacks for unlisted quants,
which quants are "low", the bit depth of a quant (NVFP4 is 4, an unreadable one
is 0), the quant read off a file name.

The shape of a repository's files: the parts of a split quant are one row with
their sizes summed; rows grouped by bit depth best first; 2- and 3-bit groups
are "low", a group of unreadable depth is not; companions (mmproj, mtp, vocab)
apart; a model file with no quant apart.

What goes with the chosen quant: nothing chosen, nothing marked; every mmproj,
and the MTP whose own quant — read off its name, since the server gives
companion files none — is nearest in rank, the better one on a tie. A copy on
disk against HF: same size and an older upload is "same", another size is a
different build, a hash result wins over the guess; a split quant takes the
worst standing of its parts.

The markup: no repository, loading, error; the header's star, the verify button
only with files on disk and its progress; the created date only when the search
gave one; low groups folded with their names listed, opened by state; a chosen
quant is checked and names what the companions are for; the recommended mark;
delete buttons only on files on disk; the checkpoint row; "no GGUF files"; the
model tree and the other files as folded cards that open by state; the test
hooks on every control.

Run: python3 scripts/test_js_hf_repo_view.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const V = await import(pathToFileURL(process.env.JS_ROOT + "/hf-repo-view.js").href);
const C = await import(pathToFileURL(process.env.JS_ROOT + "/hf-catalog.js").href);
const B = await import(pathToFileURL(process.env.JS_ROOT + "/hf-bench.js").href);
const GB = 2 ** 30;
const F = (kind, quant, size, name, date = "2026-07-27T00:00:00Z") => ({ kind, quant, size, name, path: name, date });
const FILES = () => [
  F("model", "BF16", 12 * GB, "m-BF16-00001-of-00002.gguf"), F("model", "BF16", 11 * GB, "m-BF16-00002-of-00002.gguf"),
  F("model", "Q8_0", 12669647328, "m-Q8_0.gguf"), F("model", "Q6_K", 10 * GB, "m-Q6_K.gguf"), F("model", "Q4_K_M", 7 * GB, "m-Q4_K_M.gguf"),
  F("model", "IQ4_XS", 6 * GB, "m-IQ4_XS.gguf"), F("model", "Q3_K_M", 5 * GB, "m-Q3_K_M.gguf"), F("model", "IQ2_M", 4 * GB, "m-IQ2_M.gguf"),
  F("model", "TQ1_0", 3 * GB, "m-TQ1_0.gguf"), F("model", "", 10 * 2 ** 20, "m-imatrix.gguf"),
  F("mmproj", "", 175115712, "mmproj-m-bf16.gguf", "2026-06-03T00:00:00Z"), F("mmproj", "", 120000000, "mmproj-m-f16.gguf"),
  F("mtp", "", 330000000, "mtp-m-Q4_0.gguf"), F("mtp", "", 465127968, "mtp-m-Q8_0.gguf"),
];
let bench, catalog, view;
const repo = (opts = {}) => {
  const f = catalog.repo(opts.id || "bartowski/gemma-4-12B-it-GGUF").merge({ downloads: 61351, likes: 17, tags: ["gguf"], ...(opts.record || {}) });
  f.setFiles({ files: opts.files || FILES(), lastModified: "2026-07-27T06:14:10.000Z", safetensors: opts.st || null, otherFiles: opts.other || [] });
  f.setLocal(opts.local || { localNames: [], localFiles: {} });
  if (opts.tree) f.tree = opts.tree;
  return f;
};
const LOCAL = () => ({ localNames: ["m-Q8_0.gguf", "mmproj-m-bf16.gguf", "m-BF16-00001-of-00002.gguf", "m-BF16-00002-of-00002.gguf"],
  localFiles: { "m-Q8_0.gguf": { size: 12669647328, mtime: 1788790379 }, "mmproj-m-bf16.gguf": { size: 175115712, mtime: 1781109403 },
    "m-BF16-00001-of-00002.gguf": { size: 12 * GB, mtime: 1788790379 }, "m-BF16-00002-of-00002.gguf": { size: 11 * GB - 5, mtime: 1788790379 } } });
const state = (over = {}) => ({ picks: [], lowOpen: new Set(), benchOpen: false, treeOpen: false, otherOpen: false, verify: null, verified: {}, error: "", ...over });
const reset = () => { localStorage.clear();
  bench = new B.HfBench({ getJson: async () => ({ ok: false }), wait: async () => {} });
  bench.cache.set("bartowski/gemma-4-12B-it-GGUF", { ok: true, scores: { aa_intelligence: 14.2 }, inline: ["aa_intelligence"], groups: [], meta: {}, data_from: "google/gemma-4-12B-it", from_cache: true });
  bench.frontier = { source: "default", models: [{ org: "Mistral", name: "Mistral Large 2", aa: 15.1 }, { org: "Meta", name: "Llama 4 Scout", aa: 13.5 }] };
  catalog = new C.HfCatalog(bench); view = new V.HfRepoView({ bench, catalog }); };
// A row from its <tr, class included, to its end.
const rowAt = (h, marker) => { const at = h.indexOf(marker); return at < 0 ? "" : h.slice(h.lastIndexOf("<tr", at), h.indexOf("</tr>", at)); };
const rowOf = (h, quant) => rowAt(h, `data-t="hf-quant" data-t-id="${quant}"`);
const fileRowOf = (h, path) => rowAt(h, `data-t="hf-file" data-t-id="${path}"`);
"""

PINS = [
    ("quant_ranks_low_and_bits", "",
     r"""[["Q8_0", "Q4_K_M", "IQ4_XS", "Q5_K_XL", "IQ3_WEIRD", "Q3_NEW", "IQ4_NEW", "", "TQ1_0"].map((q) => V.HfQuant.rank(q)),
        ["IQ2_M", "Q3_K_S", "IQ1_S", "IQ4_XS", "Q4_K_M", "", "Q6_K"].map((q) => V.HfQuant.isLow(q)),
        ["F32", "BF16", "F16", "Q8_K_XL", "IQ4_XS", "NVFP4", "Q2_K", "TQ1_0", ""].map((q) => V.HfQuant.bits(q))]""",
     '[[8,4.5,3.8,5.8,2.8,3.5,3.9,5,5],[true,true,true,false,false,false,false],[32,16,16,8,4,4,2,0,0]]',
     "кванты: ранги из таблицы, запасные для незнакомых (IQ3_*, Q3_*, IQ4_*), пустой и нечитаемый — 5; низкие — IQ1–3 и Q2–3; битность, нечитаемая — 0"),

    ("quant_read_off_a_file_name", "",
     r"""["mtp-gemma-4-12B-it-Q8_0.gguf", "mmproj-BF16.gguf", "mtp-gemma-4-31B-it.gguf", "x-UD-Q4_K_XL.gguf", "x-nvfp4.gguf"].map((n) => V.HfQuant.fromName(n))""",
     '["Q8_0","BF16","","Q4_K_XL","NVFP4"]',
     "квант из имени файла: Q8_0, BF16, в имени нет — пусто, Q4_K_XL из UD-, NVFP4 в любом регистре"),

    ("shape_folds_parts_groups_by_bits", "",
     r"""(() => { const s = V.HfRepoView.shape(repo());
        return [s.groups.map((g) => [g.bits, g.low, g.rows.map((r) => [r.quant, r.files.length, Math.round(r.size / GB)])]),
                s.companions.map((f) => f.name), s.loose.map((f) => f.name)]; })()""",
     '[[[16,false,[["BF16",2,23]]],[8,false,[["Q8_0",1,12]]],[6,false,[["Q6_K",1,10]]],[4,false,[["Q4_K_M",1,7],["IQ4_XS",1,6]]],[3,true,[["Q3_K_M",1,5]]],[2,true,[["IQ2_M",1,4]]],[0,false,[["TQ1_0",1,3]]]],["mmproj-m-bf16.gguf","mmproj-m-f16.gguf","mtp-m-Q4_0.gguf","mtp-m-Q8_0.gguf"],["m-imatrix.gguf"]]',
     "форма: части BF16 — одна строка с суммой; группы по битности от лучшей; 3 и 2 бит — низкие, нечитаемая битность — нет; спутники и файл без кванта отдельно"),

    ("companions_for_the_chosen_quant", "",
     r"""(() => { const f = repo(); const rec = (qs) => [...V.HfRepoView.recommended(f, qs)].sort();
        const odd = repo({ id: "acme/odd-GGUF", files: [F("model", "Q4_K_M", 1, "a.gguf"), F("mtp", "", 1, "mtp-a-Q8_0.gguf"), F("mtp", "", 1, "mtp-a.gguf")] });
        return [rec([]), rec(["Q8_0"]), rec(["Q6_K"]), rec(["Q4_K_M", "Q8_0"]), [...V.HfRepoView.recommended(odd, ["Q4_K_M"])]]; })()""",
     '[[],["mmproj-m-bf16.gguf","mmproj-m-f16.gguf","mtp-m-Q8_0.gguf"],["mmproj-m-bf16.gguf","mmproj-m-f16.gguf","mtp-m-Q8_0.gguf"],["mmproj-m-bf16.gguf","mmproj-m-f16.gguf","mtp-m-Q8_0.gguf"],["mtp-a.gguf"]]',
     "спутники: без выбора — ничего; к Q8_0 — все mmproj и mtp-Q8_0 (не первый в списке Q4_0); Q6_K на равном расстоянии — лучший Q8_0; несколько — по лучшему; MTP без кванта в имени — ранг 5, ближе к Q4_K_M"),

    ("our_copy_against_hf", "",
     r"""(() => { const f = repo({ local: LOCAL() }); const files = f.files; const by = (n) => files.find((x) => x.name === n);
        const plain = V.HfRepoView.fresh(f, by("m-Q8_0.gguf"), {}).state;
        const part2 = V.HfRepoView.fresh(f, by("m-BF16-00002-of-00002.gguf"), {}).state;
        const hashed = V.HfRepoView.fresh(f, by("m-Q8_0.gguf"), { "m-Q8_0.gguf": { state: "differs" } });
        const shape = V.HfRepoView.shape(f); const bf16 = shape.groups[0].rows[0];
        const worst = V.HfRepoView.rowFresh(f, bf16, {}).state;
        const q6 = V.HfRepoView.rowFresh(f, shape.groups[2].rows[0], {});
        return [plain, part2, [hashed.state, hashed.verified], worst, q6]; })()""",
     '["same","size",["size","differs"],"size",null]',
     "копия на диске: тот же размер и загрузка старше — совпадает; другой размер — другая сборка; хэш побеждает догадку; у квант-строки — худшая из частей; не на диске — null"),

    ("nothing_loading_and_error", "",
     r"""(() => { const none = view.html(null, {}); const f = catalog.repo("a/b"); const loading = view.html(f, state()); const failed = view.html(f, state({ error: "404 Not Found" }));
        return [none.includes("Select a repository on the left"), loading.includes('class="hfp-empty">Loading…'), failed.includes('hfp-error">404 Not Found'), failed.includes("hfp-files")]; })()""",
     '[true,true,true,false]',
     "без репозитория — «выберите слева»; файлы ещё не пришли — «загрузка»; ошибка — текст ошибки и никакой таблицы"),

    ("header_star_verify_and_dates", "",
     r"""(() => { const bare = view.html(repo(), state());
        catalog.setFavorites([{ id: "bartowski/gemma-4-12B-it-GGUF" }]);
        const f = repo({ local: LOCAL(), record: { createdAt: "2026-04-01T00:00:00Z" } });
        const withLocal = view.html(f, state());
        const running = view.html(f, state({ verify: { running: true, pct: 37 } }));
        const dates = (h) => (h.slice(0, h.indexOf("</header>")).match(/<span title="[^"]*">/g) || []);
        return [dates(bare), dates(withLocal), bare.includes('data-t="hf-verify"'), bare.includes('aria-pressed="false"'), bare.includes("mo ago</span><span class=\"hfp-dot\">·</span><span title=\"2026-07-27"),
                withLocal.includes('data-t="hf-verify"'), withLocal.includes('aria-pressed="true"') && withLocal.includes(">★</button>"),
                withLocal.includes('title="2026-04-01T00:00:00Z"'), running.includes("Verifying… 37%") && running.includes(" disabled>")]; })()""",
     '[["<span title=\\"2026-07-27T06:14:10.000Z\\">"],["<span title=\\"2026-04-01T00:00:00Z\\">","<span title=\\"2026-07-27T06:14:10.000Z\\">"],false,true,false,true,true,true,true]',
     "шапка: без файлов на диске кнопки проверки нет, звезда пустая; с файлами — кнопка, звезда полная; дата создания — только если поиск её дал (иначе одна дата — обновления); проверка идёт — процент и кнопка неактивна"),

    ("header_counts_known_or_dash", "",
     r"""(() => { const known = view.html(repo(), state());
        const bare = catalog.repo("x/uncounted-GGUF"); bare.setFiles({ files: FILES(), lastModified: "" }); bare.setLocal({ localNames: [], localFiles: {} });
        const unknown = view.html(bare, state());
        const meta = (h) => (h.match(/<span class="hfp-meta">(↓ [^<]*)<span class="hfp-dot">·<\/span>(♥ [^<]*)</) || []).slice(1);
        return [meta(known), meta(unknown)]; })()""",
     '[["↓ 61.4k","♥ 17"],["↓ —","♥ —"]]',
     "шапка: известные загрузки и лайки — числами, неизвестные — «—», а не нулём"),

    ("library_copies_on_the_rows", "",
     r"""(() => { const day = 1785153600; const A = { id: "lib-a", name: "lama-caravan-models" }, B = { id: "lib-b", name: "second-shelf" };
        const f = repo({ local: { ...LOCAL(), libraryFiles: { "m-Q6_K.gguf": [{ store: A, size: 10 * GB, mtime: day }], "m-Q8_0.gguf": [{ store: A, size: 12669647328 - 100, mtime: day }],
          "mtp-m-Q8_0.gguf": [{ store: A, size: 465127968, mtime: 0 }, { store: B, size: 465127968, mtime: day }],
          "m-BF16-00001-of-00002.gguf": [{ store: A, size: 12 * GB, mtime: day }], "m-BF16-00002-of-00002.gguf": [{ store: B, size: 11 * GB, mtime: day }] } } });
        const h = view.html(f, state()); const q6 = rowOf(h, "Q6_K"), q8 = rowOf(h, "Q8_0"), q4 = rowOf(h, "Q4_K_M"), mtp = fileRowOf(h, "mtp-m-Q8_0.gguf");
        const title = (row) => (row.match(/data-t="hf-file-in-library" title="([^"]*)"/) || [])[1];
        return [q6.startsWith('<tr class="hfp-q is-library" data-t="hf-quant" data-t-id="Q6_K">'), q6.includes('>📚 ✓ matches</span>'), title(q6), q6.includes('data-t="hf-file-delete"'),
                q8.startsWith('<tr class="hfp-q is-local"'), q8.includes('✓ matches</span> <span class="hfp-fresh hfp-in-lib is-differs" data-t="hf-file-in-library"'), q8.includes('>📚 ⇪</span>'),
                mtp.startsWith('<tr class="hfp-q is-library"'), mtp.includes(">📚 ? can't compare</span>") || mtp.includes(">📚 ? can&#39;t compare</span>"), (title(mtp) || "").split("\n")[0],
                q4.includes("hf-file-in-library"), q4.startsWith('<tr class="hfp-q" '), (title(rowOf(h, "BF16")) || "").split("\n")[0]]; })()""",
     '[true,true,"In a library: lama-caravan-models\\nMatches what is on HF\\nours: 10.0 GB · 2026-07-27\\non HF: 10.0 GB · 2026-07-27",false,true,true,true,true,true,"In a library: lama-caravan-models, second-shelf",false,true,"In a library: lama-caravan-models, second-shelf"]',
     "копии в библиотеках на строках: только в библиотеке — сиреневая строка и «📚 ✓ совпадает» с названием библиотеки и сверкой в подсказке, без 🗑; здесь и в библиотеке — метка диска и короткая «📚 ⇪», если сборка другая; спутник в двух библиотеках — обе названы, сверяется первая копия; квант, чьи части в разных библиотеках, называет обе; нигде нет — метки нет"),

    ("low_groups_fold_and_open", "",
     r"""(() => { const f = repo(); const folded = view.html(f, state()); const opened = view.html(f, state({ lowOpen: new Set([3]) }));
        return [folded.includes('data-t="hf-low-toggle" data-t-id="3" aria-expanded="false"'), folded.includes("Q3_K_M</span>"), !!rowOf(folded, "Q3_K_M"),
                !!rowOf(opened, "Q3_K_M"), !!rowOf(opened, "IQ2_M"), opened.includes('data-t-id="3" aria-expanded="true"'), !!rowOf(folded, "TQ1_0")]; })()""",
     '[true,true,false,true,false,true,true]',
     "низкие группы свёрнуты и перечисляют кванты; раскрытая группа 3 бит показывает строки, 2 бит остаётся свёрнутой; группа нечитаемой битности не прячется"),

    ("a_chosen_quant_and_its_companions", "",
     r"""(() => { const f = repo({ local: LOCAL() }); const q8 = f.files.filter((x) => x.quant === "Q8_0").map((x) => x.path);
        const none = view.html(f, state()); const picked = view.html(f, state({ picks: q8 }));
        const mm = fileRowOf(picked, "mmproj-m-bf16.gguf"); const q4 = fileRowOf(picked, "mtp-m-Q4_0.gguf");
        return [rowOf(picked, "Q8_0").includes(" checked"), rowOf(none, "Q8_0").includes(" checked"), none.includes("select a quant, and what goes with it is marked"),
                picked.includes("for the selected Q8_0"), mm.includes("hfp-rec"), mm.includes("is-local"), q4.includes("hfp-rec"),
                rowOf(picked, "BF16").includes('data-paths="[&quot;m-BF16-00001-of-00002.gguf&quot;,&quot;m-BF16-00002-of-00002.gguf&quot;]"')]; })()""",
     '[true,false,true,true,true,true,false,true]',
     "выбранный квант отмечен; без выбора — «выберите квант»; с выбором — «к выбранному Q8_0», метка на mmproj (он же на диске), не на mtp-Q4_0; квант из частей выбирает все пути"),

    ("delete_only_what_is_on_disk", "",
     r"""(() => { const h = view.html(repo({ local: LOCAL() }), state());
        const bf = rowOf(h, "BF16"); const q6 = rowOf(h, "Q6_K"); const mm = fileRowOf(h, "mmproj-m-f16.gguf");
        return [bf.includes('data-names="[&quot;m-BF16-00001-of-00002.gguf&quot;,&quot;m-BF16-00002-of-00002.gguf&quot;]"'), bf.includes("hfp-fresh is-differs"),
                rowOf(h, "Q8_0").includes('data-t="hf-file-delete" data-t-id="m-Q8_0.gguf"'), rowOf(h, "Q8_0").includes("✓ matches"),
                q6.includes("hf-file-delete"), mm.includes("hf-file-delete")]; })()""",
     '[true,true,true,true,false,false]',
     "🗑 — только у файлов на диске (у квант-строки — все её части, и она «другая сборка» из-за части); у того, чего нет на диске, — ни кнопки, ни отметки"),

    ("checkpoint_and_no_gguf", "",
     r"""(() => { const st = { format: "BF16", totalSize: 62578656585, files: [{ name: "model-00001.safetensors", path: "model-00001.safetensors", size: 1 }] };
        const withSt = view.html(repo({ files: [], st }), state()); const empty = view.html(repo({ files: [] }), state());
        return [withSt.includes('data-t="hf-checkpoint-download"'), withSt.includes("safetensors · 1 files"), withSt.includes("58.3 GB"), withSt.includes("No GGUF files found"),
                empty.includes("No GGUF files found"), empty.includes("hf-checkpoint")]; })()""",
     '[true,true,true,false,true,false]',
     "safetensors — одна строка с форматом, числом файлов, размером и кнопкой; при нём «GGUF нет» не пишется; нет ничего — «GGUF-файлов не найдено»"),

    ("tree_and_other_files_cards", "",
     r"""(() => { const tree = { base: "google/gemma-4-12B-it", quantizations: [{ id: "x/q1", format: "GGUF", downloads: 73, likes: 0 }], siblings: [{ id: "y/s1", format: "NVFP4", downloads: 1635415, likes: 566 }] };
        const other = [{ name: "README.md", size: 13722 }, { name: ".gitattributes", size: 3410 }];
        const f = repo({ tree, other }); const closed = view.html(f, state()); const open = view.html(f, state({ treeOpen: true, otherOpen: true }));
        return [closed.includes('data-t="hf-tree-toggle" aria-expanded="false"'), closed.includes("hf-tree-repo"), closed.includes("README.md"),
                open.includes('data-act="open-repo" data-repo="y/s1"'), open.includes("Other quants of google/gemma-4-12B-it · 1"), open.includes("↓ 1.6M · ♥ 566"),
                open.includes("README.md"), closed.includes("Other files <span class=\"hfp-muted\">· 2 · 1 MB")]; })()""",
     '[true,false,false,true,true,true,true,true]',
     "дерево модели и прочие файлы — свёрнутые карточки; раскрытые показывают версии, кванты базы (клик открывает репозиторий) и файлы; в заголовке — счёт и размер"),
]


if __name__ == "__main__":
    sys.exit(run("js hf-repo-view", ".probe_js_hf_repo_view.tmp.mjs", PREAMBLE, PINS))
