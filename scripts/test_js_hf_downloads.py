#!/usr/bin/env python3
"""Snapshot of static/js/hf-downloads.js — getting files onto the models disk
from /hf.

Pinned by value. Where a file lands: <model>/<author>/<quant>, "default" with
no quant, "unknown" with no author; a checkpoint in its format's folder. The
selection: spans repositories, a repository with nothing picked leaves it,
sizes summed as numbers, clearing folds the plan. The plan: grouped by
repository and folder, and which files are already on disk by name. Room: the
files plus 5 GB to assemble a split one against the free space; an unknown
disk makes no claim.

Starting: one request per repository with the folder of every file; the files
leave the selection once the job is taken; nothing is asked when it fits. Not
enough room asks once for the whole selection in the page's dialog, and a no
sends nothing. The server's "exists" asks before writing over, and only a yes
resends with replace:true; a no drops the job and keeps the selection; a
refusal or a network error is an error row. A checkpoint asks with its format,
size and folder, after the room question, and leaves the selection alone.

A gated repository (the terms are accepted on its page) refuses its files with a wall, and the failed
job then carries `access` with the page's address: the page that started the job opens it in a new
window once, a job a reload brought back does not, the row's button opens it any time, a window the
browser refuses leaves the button, and a refusal that names no page is an ordinary error row.

A job while it runs: progress by bytes, the file and its share, the speed
smoothed over polls (a step back in bytes does not count), "retrying" while
the server retries; a missed poll is shown and asked again. Its ends: done
calls back with the repository and leaves after a while; cancelled drops it
and brings back the partials; error stays with its text; a job the server does
not know is dropped; a job removed while its answer is on the way stays gone.
Cancel: a job not yet sent just leaves; otherwise the server is asked, the
state holds against the poll, and a failure puts the job back with a toast.
Dismiss removes only error rows. Resume: the server is asked, the partial
becomes a job, a failure is a toast. Restore: the server's jobs first, this
browser's list only when the server cannot be read, never twice, and the list
opens only for live jobs. Only live jobs with an id are saved.

The dock: the bar with the selection, its folders and the buttons; the plan
with remove buttons, the disk bar and what is written over; the jobs button
with how many run and their average, amber when something is interrupted or
failed; the rows with Cancel, dismiss or nothing, the partials with Resume
only when they can resume. The test hooks on every control.

Run: python3 scripts/test_js_hf_downloads.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const D = await import(pathToFileURL(process.env.JS_ROOT + "/hf-downloads.js").href);
const GIB = 2 ** 30, MIB = 2 ** 20;
const A = "bartowski/gemma-4-12B-it-GGUF", B = "unsloth/Qwen3.6-35B-A3B-GGUF";
const F = (name, quant, size) => ({ path: name, name, quant, size });
let dl, posts, gets, replies, answers, asked, toasts, timers, clock, finished, changes, store, opened;
// A reply is a value, an Error to throw, a promise to wait on, or a list served in turn (the last one stays).
const answer = (url) => { let r = replies[url]; if (Array.isArray(r)) r = r.length > 1 ? r.shift() : r[0]; if (r instanceof Error) throw r; return r === undefined ? { ok: true } : r; };
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };
const runTimers = async () => { const due = timers.splice(0); for (const t of due) await t.fn(); await settle(); };
const reset = () => { posts = []; gets = []; replies = {}; answers = []; asked = []; toasts = []; timers = []; clock = 1000000; finished = []; changes = 0; store = new Map(); opened = [];
  dl = new D.HfDownloads({ getJson: async (url) => { gets.push(url); return answer(url); },
    postJson: async (url, body) => { posts.push([url, JSON.parse(JSON.stringify(body))]); return answer(url); },
    confirm: async (...a) => { asked.push(a); return answers.length ? answers.shift() : false; }, toast: (m) => toasts.push(m),
    storage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
    later: (fn, ms) => timers.push({ fn, ms }), now: () => clock, onChange: () => { changes += 1; }, onFinished: (id) => finished.push(id),
    go: (url) => { opened.push(url); } }); };
"""

PINS = [
    ("where_files_land", "",
     r"""[D.HfDownloads.destDir(A, { quant: "Q4_K_M" }), D.HfDownloads.destDir(A, { quant: "" }), D.HfDownloads.destDir("solo-GGUF", { quant: "Q8_0" }),
        D.HfDownloads.checkpointDir("google/gemma-4-12B-it", "safetensors"), D.HfDownloads.checkpointDir("solo", "safetensors")]""",
     '["gemma-4-12B-it-GGUF/bartowski/Q4_K_M","gemma-4-12B-it-GGUF/bartowski/default","solo-GGUF/unknown/Q8_0","gemma-4-12B-it/google/safetensors","solo/unknown/safetensors"]',
     "путь: <модель>/<автор>/<квант>; без кванта — default; без автора — unknown; чекпойнт — в папке формата"),

    ("selection_spans_repositories", "",
     r"""(() => { dl.toggle(A, [F("a-Q4.gguf", "Q4_K_M", 7 * GIB), F("a-Q8.gguf", "Q8_0", 12 * GIB)], true); dl.toggle(B, [F("b-Q4.gguf", "Q4_K_M", 20 * GIB)], true);
        dl.toggle(A, [F("a-Q4.gguf", "Q4_K_M", 7 * GIB)], false); const afterOff = [dl.picks(A), dl.count(), dl.bytes() / GIB];
        dl.remove(B, "b-Q4.gguf"); const afterRemove = [[...dl.selection.keys()], dl.picks(B)];
        dl.remove("nobody/none", "x"); dl.toggle(A, [F("a-Q8.gguf", "Q8_0", 12 * GIB)], false); const emptied = [[...dl.selection.keys()], dl.count(), dl.bytes()];
        dl.toggle(A, [F("a.gguf", "Q4_K_M", "3")], true); const bytesOfText = dl.bytes(); dl.detailsOpen = true; dl.clear();
        return [afterOff, afterRemove, emptied, bytesOfText, dl.count(), dl.detailsOpen, changes]; })()""",
     '[[["a-Q8.gguf"],2,32],[["bartowski/gemma-4-12B-it-GGUF"],[]],[[],0,0],3,0,false,7]',
     "выбор: через репозитории; снятое уходит, репозиторий без файлов — из выбора; удаление чужого — ничего и без перерисовки; размер строкой суммируется числом; очистка сворачивает план"),

    ("plan_groups_and_overwrite", "",
     r"""(() => { dl.toggle(A, [F("a-Q4-00001-of-00002.gguf", "Q4_K_M", GIB), F("a-Q4-00002-of-00002.gguf", "Q4_K_M", GIB), F("mmproj-a.gguf", "", 100 * MIB)], true);
        dl.toggle(B, [F("b-Q8.gguf", "Q8_0", 2 * GIB)], true);
        const p = dl.plan((id) => (id === A ? new Set(["mmproj-a.gguf"]) : null));
        return [p.groups.map((g) => [g.repoId, g.dirs.map((d) => [d.dir, d.files.map((f) => f.name)])]), p.count, p.bytes, p.overwrite, dl.plan().overwrite]; })()""",
     '[[["bartowski/gemma-4-12B-it-GGUF",[["gemma-4-12B-it-GGUF/bartowski/Q4_K_M",["a-Q4-00001-of-00002.gguf","a-Q4-00002-of-00002.gguf"]],["gemma-4-12B-it-GGUF/bartowski/default",["mmproj-a.gguf"]]]],'
     '["unsloth/Qwen3.6-35B-A3B-GGUF",[["Qwen3.6-35B-A3B-GGUF/unsloth/Q8_0",["b-Q8.gguf"]]]]],4,4399824896,["gemma-4-12B-it-GGUF/bartowski/default/mmproj-a.gguf"],[]]',
     "план: по репозиториям и папкам; что уже на диске по имени — в списке перезаписи; без сведений о диске — пусто"),

    ("room_with_assembly_slack", "",
     r"""(() => { const unknown = dl.fit(GIB); dl.setDisk({ ok: false, freeGb: 100 }); const refused = dl.fit(GIB);
        dl.setDisk({ ok: true, freeGb: "20", totalGb: "100" }); const edge = dl.fit(15 * GIB); const over = dl.fit(15 * GIB + MIB);
        return [unknown, refused, edge, [over.fits, over.needGb > 20]]; })()""",
     '[{"known":false},{"known":false},{"known":true,"needGb":20,"freeGb":20,"totalGb":100,"fits":true,"leftGb":5},[false,true]]',
     "место: файлы + 5 GB на сборку против свободного; ровно впритык — влезает, на мегабайт больше — нет; диск неизвестен или отказ — без суждения"),

    ("start_one_request_per_repository", "",
     r"""await (async () => { await dl.start(); const idle = [posts.length, dl.jobs.length];
        replies["/api/hf/download"] = [{ ok: true, jobId: "j1" }, { ok: true, jobId: "j2" }];
        dl.toggle(A, [F("a-Q4.gguf", "Q4_K_M", 7 * GIB), F("mmproj-a.gguf", "", 100 * MIB)], true); dl.toggle(B, [F("b-Q8.gguf", "Q8_0", 2 * GIB)], true);
        await dl.start(); await settle();
        return [idle, posts, dl.jobs.map((j) => [j.uid, j.jobId, j.title, j.totalFiles, j.state]), dl.count(), asked.length, dl.jobsOpen,
                JSON.parse(store.get("hfDlJobs")), gets, timers.map((t) => t.ms)]; })()""",
     '[[0,0],[["/api/hf/download",{"repo":"bartowski/gemma-4-12B-it-GGUF","files":[{"path":"a-Q4.gguf","name":"a-Q4.gguf","size":7516192768,"destDir":"gemma-4-12B-it-GGUF/bartowski/Q4_K_M"},'
     '{"path":"mmproj-a.gguf","name":"mmproj-a.gguf","size":104857600,"destDir":"gemma-4-12B-it-GGUF/bartowski/default"}]}],'
     '["/api/hf/download",{"repo":"unsloth/Qwen3.6-35B-A3B-GGUF","files":[{"path":"b-Q8.gguf","name":"b-Q8.gguf","size":2147483648,"destDir":"Qwen3.6-35B-A3B-GGUF/unsloth/Q8_0"}]}]],'
     '[["dlj1","j1","bartowski/gemma-4-12B-it-GGUF",2,"running"],["dlj2","j2","unsloth/Qwen3.6-35B-A3B-GGUF",1,"running"]],0,0,true,'
     '[{"jobId":"j1","title":"bartowski/gemma-4-12B-it-GGUF","repoId":"bartowski/gemma-4-12B-it-GGUF","totalFiles":2},{"jobId":"j2","title":"unsloth/Qwen3.6-35B-A3B-GGUF","repoId":"unsloth/Qwen3.6-35B-A3B-GGUF","totalFiles":1}],'
     '["/api/hf/download/status?job=j1","/api/hf/download/status?job=j2"],[600,600]]',
     "старт: пустой выбор — ничего; по запросу на репозиторий с папкой каждого файла; принятые файлы уходят из выбора; список открыт, сохранён, опрос раз в 600 мс; влезает — без вопросов"),

    ("no_room_asks_once", "",
     r"""await (async () => { dl.setDisk({ ok: true, freeGb: 10, totalGb: 100 }); dl.toggle(A, [F("a-Q8.gguf", "Q8_0", 8 * GIB)], true);
        answers = [false]; await dl.start(); await settle(); const declined = [posts.length, dl.jobs.length, dl.count(), asked];
        asked = []; replies["/api/hf/download"] = { ok: true, jobId: "j1" }; answers = [true]; await dl.start(); await settle();
        const accepted = [posts.length, dl.jobs.length, dl.count(), asked.length];
        asked = []; dl.setDisk({ ok: true, freeGb: 20, totalGb: 100 }); dl.toggle(B, [F("b.gguf", "Q8_0", 8 * GIB)], true); await dl.start(); await settle();
        return [declined, accepted, [posts.length, asked.length]]; })()""",
     '[[0,0,1,[["Not enough space on the models disk","This download needs about 13.0 GB, and the models disk has 10 GB free.","Download anyway",true]]],[1,1,0,1],[2,0]]',
     "не влезает: спрашивает окном страницы (опасное действие); «нет» — ничего не уходит, выбор цел; «да» — качает; влезает — не спрашивает"),

    ("writing_over_asks_first", "",
     r"""await (async () => { const EXISTS = { ok: false, code: "exists", files: ["gemma-4-12B-it-GGUF/bartowski/Q8_0/a-Q8.gguf"] };
        replies["/api/hf/download"] = [EXISTS, { ok: true, jobId: "j7" }]; dl.toggle(A, [F("a-Q8.gguf", "Q8_0", GIB)], true); answers = [true];
        await dl.start(); await settle();
        const yes = [posts.map(([, b]) => b.replace === true), asked, dl.jobs.map((j) => [j.jobId, j.state]), dl.count()];
        reset(); replies["/api/hf/download"] = EXISTS; dl.toggle(A, [F("a-Q8.gguf", "Q8_0", GIB)], true); answers = [false]; await dl.start(); await settle();
        const no = [posts.length, dl.jobs.length, dl.count()];
        reset(); replies["/api/hf/download"] = { ok: false, error: "no space" }; dl.toggle(A, [F("a-Q8.gguf", "Q8_0", GIB)], true); await dl.start(); await settle();
        const refused = [asked.length, dl.jobs.map((j) => [j.jobId, j.state, j.error]), dl.count(), store.has("hfDlJobs")];
        reset(); replies["/api/hf/download"] = new Error("network down"); dl.toggle(A, [F("a-Q8.gguf", "Q8_0", GIB)], true); await dl.start(); await settle();
        return [yes, no, refused, dl.jobs.map((j) => [j.state, j.error])]; })()""",
     '[[[false,true],[["Download over files already on disk?","Will be replaced: 1\\ngemma-4-12B-it-GGUF/bartowski/Q8_0/a-Q8.gguf","Replace",true]],[["j7","running"]],0],'
     '[1,0,1],[0,[[null,"error","no space"]],1,false],[["error","network down"]]]',
     "перезапись: сервер «exists» — вопрос со списком; «да» — повтор с replace:true; «нет» — задания нет, выбор цел; отказ и сетевая ошибка — строка ошибки, без вопроса, выбор цел"),

    ("checkpoint_asks_with_its_folder", "",
     r"""await (async () => { const G = "google/gemma-4-12B-it";
        const ST = { format: "safetensors", totalSize: 24e9, files: [{ path: "model-00001-of-00002.safetensors", name: "model-00001-of-00002.safetensors", size: 12e9 }, { path: "config.json", name: "config.json", size: 1000 }] };
        dl.toggle(G, [F("keep.gguf", "Q4_K_M", GIB)], true); replies["/api/hf/download"] = { ok: true, jobId: "c1" };
        answers = [false]; await dl.startCheckpoint(G, ST); const no = [posts.length, dl.jobs.length, asked];
        asked = []; answers = [true]; await dl.startCheckpoint(G, ST); await settle();
        const yes = [posts, dl.jobs.map((j) => [j.jobId, j.title, j.totalFiles]), dl.picks(G)];
        reset(); dl.setDisk({ ok: true, freeGb: 20, totalGb: 100 }); answers = [false, true]; await dl.startCheckpoint(G, ST);
        return [no, yes, [asked.map((a) => a[0]), posts.length]]; })()""",
     '[[0,0,[["⬇ safetensors · 22.4 GB","google/gemma-4-12B-it → gemma-4-12B-it/google/safetensors/","Download",false]]],'
     '[[["/api/hf/download",{"repo":"google/gemma-4-12B-it","files":[{"path":"model-00001-of-00002.safetensors","name":"model-00001-of-00002.safetensors","size":12000000000,"destDir":"gemma-4-12B-it/google/safetensors"},'
     '{"path":"config.json","name":"config.json","size":1000,"destDir":"gemma-4-12B-it/google/safetensors"}]}]],[["c1","google/gemma-4-12B-it",2]],["keep.gguf"]],'
     '[["Not enough space on the models disk"],0]]',
     "чекпойнт: вопрос с форматом, размером (в тех же GB, что строка) и папкой; «нет» — ничего; «да» — одно задание, все файлы в одну папку, выбор не тронут; не влезает — сначала вопрос о месте, «нет» — дальше не идёт"),

    ("checkpoint_keeps_its_subfolders", "",
     r"""await (async () => { const G = "nvidia/GR00T-N1.7-3B";
        const ST = { format: "BF16", totalSize: 7e9, files: [{ path: "model-00001-of-00002.safetensors", name: "model-00001-of-00002.safetensors", size: 5e9 },
          { path: "experiment_cfg/conf.yaml", name: "conf.yaml", size: 31159 }, { path: "a/../b/./c.json", name: "c.json", size: 1 }] };
        replies["/api/hf/download"] = { ok: true, jobId: "g1" }; answers = [true]; await dl.startCheckpoint(G, ST); await settle();
        return [posts[0][1].files.map((f) => [f.name, f.destDir]), D.HfDownloads.checkpointFileDir("x/y/BF16", "top.json")]; })()""",
     '[[["model-00001-of-00002.safetensors","GR00T-N1.7-3B/nvidia/BF16"],["conf.yaml","GR00T-N1.7-3B/nvidia/BF16/experiment_cfg"],'
     '["c.json","GR00T-N1.7-3B/nvidia/BF16/a/b"]],"x/y/BF16"]',
     "defect-history: файл чекпойнта ложится в свою подпапку репозитория — experiment_cfg/ у GR00T терялась, всё ложилось в одну папку; "
     "файл в корне — в папке чекпойнта; «..» и «.» в пути не выводят наружу"),

    ("poll_progress_speed_retrying", "",
     r"""await (async () => { const job = dl.addJob({ jobId: "j1", repoId: A, title: A, totalFiles: 2, state: "resuming" });
        const S = (over) => ({ ok: true, status: "running", total_bytes: 100 * MIB, total_bytes_done: 0, current_idx: 0, total_files: 2, current_file: "a-00001.gguf", file_bytes_total: 50 * MIB, file_bytes_done: 0, ...over });
        const seen = []; const look = () => seen.push([job.state, job.pct, job.idx, job.file, job.filePct, Math.round(job.speed), dl.jobLabel(job)]);
        const URL = "/api/hf/download/status?job=j1";
        replies[URL] = S({ total_bytes_done: 10 * MIB, file_bytes_done: 10 * MIB }); dl.poll(job); await settle(); look();
        clock += 2000; replies[URL] = S({ total_bytes_done: 14 * MIB, file_bytes_done: 14 * MIB }); await runTimers(); look();
        clock += 2000; replies[URL] = S({ status: "retrying", total_bytes_done: 14 * MIB, file_bytes_done: 14 * MIB }); await runTimers(); look();
        clock += 2000; replies[URL] = S({ total_bytes_done: 60 * MIB, current_idx: 1, current_file: "a-00002.gguf", file_bytes_done: 10 * MIB }); await runTimers(); look();
        clock += 1000; replies[URL] = S({ total_bytes_done: 50 * MIB, current_idx: 5 }); await runTimers(); look();
        return [seen, timers.map((t) => t.ms), gets.length]; })()""",
     '[[["running",10,1,"a-00001.gguf",20,0,"File 1/2 — a-00001.gguf (20%)"],["running",14,1,"a-00001.gguf",28,2097152,"File 1/2 — a-00001.gguf (28%) — 2.0 MB/s — ~45 s left"],'
     '["retrying",14,1,"a-00001.gguf",28,1468006,"Connection dropped — retrying — File 1/2 — a-00001.gguf (28%) — 1.4 MB/s"],'
     '["running",60,2,"a-00002.gguf",20,8262779,"File 2/2 — a-00002.gguf (20%) — 7.9 MB/s — ~15 s left"],["running",50,2,"a-00001.gguf",0,8262779,"File 2/2 — a-00001.gguf (0%) — 7.9 MB/s — ~20 s left"]],[600],5]',
     "опрос: доля по байтам, файл и его доля; скорость — со второго ответа, сглаженная 0.7/0.3; шаг назад по байтам скорость не трогает; «повтор соединения» — всё ещё идёт; номер файла не больше числа файлов; в подписи бегущей строки — «~N s left» словами страницы /models (осталось байт ÷ медленный темп: 86 MiB при 2 MiB/s — 43 s, и секунды идут шагом 5 — «~45 s»), у повтора соединения и у первого ответа — без него"),

    ("resumed_speed_ignores_the_part_on_disk", "",
     r"""await (async () => { const job = dl.addJob({ jobId: "r1", repoId: A, title: A, totalFiles: 1, state: "resuming" });
        const S = (done) => ({ ok: true, status: "running", total_bytes: 1700 * MIB, total_bytes_done: done, current_idx: 0, total_files: 1, current_file: "q.gguf", file_bytes_total: 1700 * MIB, file_bytes_done: done });
        const URL = "/api/hf/download/status?job=r1"; const speeds = [];
        replies[URL] = S(0); dl.poll(job); await settle(); speeds.push(Math.round(job.speed));
        clock += 600; replies[URL] = S(640 * MIB); await runTimers(); speeds.push(Math.round(job.speed));
        clock += 1000; replies[URL] = S(660 * MIB); await runTimers(); speeds.push(Math.round(job.speed));
        return [speeds, dl.jobLabel(job)]; })()""",
     '[[0,0,20971520],"File 1/1 — q.gguf (39%) — 20.0 MB/s — ~55 s left"]',
     "продолжение: скачок от нуля до уже скачанной части — не скорость; скорость считается со следующего шага (20 MB/s, а не 1 GB/s), и время до конца — от неё же: 1040 MiB при 20 MiB/s — 52 s, то есть «~55 s»"),

    ("follow_adopts_a_job_started_elsewhere", "",
     r"""await (async () => { dl.follow(); const armed = timers.map((t) => t.ms);
        replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "x1", status: "running", repo: A, title: "t1", total_files: 3 }] };
        replies["/api/hf/download/status?job=x1"] = { ok: true, status: "running", total_bytes: 100 * MIB, total_bytes_done: 10 * MIB, current_idx: 0, total_files: 3, current_file: "a.gguf", file_bytes_total: 50 * MIB, file_bytes_done: 10 * MIB };
        await runTimers();
        const first = [dl.jobs.map((j) => [j.jobId, j.title, j.repoId, j.totalFiles, j.state]), dl.jobsOpen, gets.filter((g) => g.includes("status")).length, store.get("hfDlJobs")];
        await runTimers();
        return [armed, first, dl.jobs.length, timers.map((t) => t.ms).sort((a, b) => a - b)]; })()""",
     '[[10000],[[["x1","t1","bartowski/gemma-4-12B-it-GGUF",3,"running"]],true,1,'
     '"[{\\"jobId\\":\\"x1\\",\\"title\\":\\"t1\\",\\"repoId\\":\\"bartowski/gemma-4-12B-it-GGUF\\",\\"totalFiles\\":3}]"],1,[600,10000]]',
     "сверка со списком сервера: через 10000 мс страница спрашивает список заданий и подхватывает чужое (запущено другой вкладкой или скриптом): "
     "оно в доке, список заданий открыт, сохранено в браузере, опрашивается; второй просмотр списка не делает копию; сверка ставит следующую сама"),

    ("follow_takes_only_live_jobs_it_does_not_hold", "",
     r"""await (async () => { dl.follow(); dl.addJob({ jobId: "k1", repoId: A, title: "k", totalFiles: 1, state: "running" });
        replies["/api/hf/download/jobs"] = { ok: true, jobs: [
          { jobId: "k1", status: "running", repo: A, title: "k", total_files: 1 },
          { jobId: "d1", status: "done", repo: A, title: "d", total_files: 1 }, { jobId: "e1", status: "error", repo: A, title: "e", total_files: 1 },
          { jobId: "c1", status: "cancelled", repo: A, title: "c", total_files: 1 }, { jobId: "r1", status: "retrying", repo: B, title: "r", total_files: 2 },
          { jobId: "i1", status: "interrupted", repo: A, title: "i", current_file: "x.gguf", resumable: true }, { status: "running", repo: A }] };
        replies["/api/hf/download/status?job=r1"] = { ok: true, status: "retrying", total_bytes: 10, total_bytes_done: 1, current_idx: 0, total_files: 2, current_file: "b.gguf", file_bytes_total: 5, file_bytes_done: 1 };
        await runTimers();
        return [dl.jobs.map((j) => j.jobId), dl.interrupted.map((r) => r.jobId), gets.filter((g) => g.includes("status")).length]; })()""",
     '[["k1","r1"],["i1"],1]',
     "negative: сверка берёт только идущие задания (running, retrying), которых страница не держит; свои (k1), готовые, упавшие, отменённые, "
     "задание без номера не берёт — иначе готовое задание вставало бы в док снова на каждой сверке; прерванные идут в список «продолжить»"),

    ("follow_waits_for_a_job_it_is_starting", "",
     r"""await (async () => { dl.follow(); dl.addJob({ jobId: null, repoId: A, title: "starting", totalFiles: 1, state: "starting" });
        replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "n1", status: "running", repo: A, title: "n", total_files: 1 }] };
        await runTimers(); const during = dl.jobs.map((j) => j.jobId);
        dl.jobs[0].jobId = "n1";
        replies["/api/hf/download/status?job=n1"] = { ok: true, status: "running", total_bytes: 10, total_bytes_done: 1, current_idx: 0, total_files: 1, current_file: "a", file_bytes_total: 10, file_bytes_done: 1 };
        await runTimers();
        return [during, dl.jobs.map((j) => j.jobId)]; })()""",
     '[[null],["n1"]]',
     "defect-guard: пока своё задание без номера (старт ещё не ответил), а сервер его уже перечисляет, сверка ничего не берёт — иначе оно встало бы в док дважды; "
     "когда номер пришёл, сверка узнаёт своё и копии не делает"),

    ("follow_survives_a_missed_answer", "",
     r"""await (async () => { dl.follow();
        replies["/api/hf/download/jobs"] = new Error("offline"); await runTimers(); const missed = [dl.jobs.length, timers.map((t) => t.ms)];
        replies["/api/hf/download/jobs"] = { ok: false }; await runTimers(); const refused = [dl.jobs.length, timers.map((t) => t.ms)];
        replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "i2", status: "interrupted", repo: A, title: "i", current_file: "y.gguf" }] };
        const before = changes; await runTimers();
        return [missed, refused, dl.interrupted.map((r) => r.jobId), timers.map((t) => t.ms), changes > before]; })()""",
      '[[0,[10000]],[0,[10000]],["i2"],[10000],true]',
     "сверка и промах, и отказ переживает: заданий не прибавилось, следующая уже в очереди (10000 мс); дальше список прерванных обновляется и страница узнаёт об этом (перерисовка)"),

    ("time_left_is_named_only_when_it_can_be_said", "",
     r"""(() => { const eta = (over) => D.HfDownloads.etaSeconds({ state: "running", pace: MIB, bytesDone: 10 * MIB, bytesTotal: 100 * MIB, ...over });
        return [eta({}), eta({ state: "retrying" }), eta({ state: "resuming" }), eta({ state: "done" }), eta({ pace: 0 }), eta({ pace: 1023 }),
                eta({ pace: 1024 }), eta({ bytesTotal: 0 }), eta({ bytesDone: 100 * MIB }), eta({ bytesDone: 101 * MIB }), eta({ pace: undefined })]; })()""",
     '[90,null,null,null,null,null,92160,null,null,null,null]',
     "время до конца: осталось байт ÷ темп (90 MiB при 1 MiB/s — 90 s); не бежит (повтор соединения, продолжение, готово), темпа ещё нет, "
     "стоит (меньше 1 KiB/s; ровно 1 KiB/s — ещё считается), сервер не назвал итог, ничего не осталось — null: «неизвестно», а не «0 s» и не «∞»"),

    ("time_left_pace_moves_slower_than_the_speed", "",
     r"""await (async () => { const job = dl.addJob({ jobId: "e1", repoId: A, title: A, totalFiles: 1, state: "resuming" });
        const S = (done) => ({ ok: true, status: "running", total_bytes: 1000 * MIB, total_bytes_done: done * MIB, current_idx: 0, total_files: 1, current_file: "m.gguf", file_bytes_total: 1000 * MIB, file_bytes_done: done * MIB });
        const URL = "/api/hf/download/status?job=e1"; const seen = []; const r2 = (v) => Math.round(v / MIB * 100) / 100;
        const look = () => seen.push([r2(job.speed), r2(job.pace), Math.round(D.HfDownloads.etaSeconds(job))]);
        replies[URL] = S(100); dl.poll(job); await settle();
        for (const done of [101, 102, 103]) { clock += 1000; replies[URL] = S(done); await runTimers(); look(); }
        clock += 1000; replies[URL] = S(113); await runTimers(); look();
        return seen; })()""",
     '[[1,1,899],[1,1,898],[1,1,897],[3.7,1.45,612]]',
     "темп времени до конца сдвигается на 0.05 за ответ, а скорость в строке — на 0.3: скачок с 1 до 10 MiB/s даёт скорость 3.7, темп 1.45 и время 612 s, "
     "а не 887 ÷ 3.7 = 240 s — оценка не прыгает за каждым всплеском линии"),

    ("time_left_on_the_label_in_every_scale", "",
     r"""(() => { const lab = (pace, done, total) => dl.jobLabel({ state: "running", idx: 1, totalFiles: 1, file: "m.gguf", filePct: 0, speed: pace, pace,
          bytesDone: done, bytesTotal: total, pollError: "" });
        return [lab(10 * MIB, 0, 450 * MIB), lab(10 * MIB, 0, 600 * MIB), lab(10 * MIB, 0, 36000 * MIB), lab(10 * MIB, 0, 36100 * MIB),
                lab(10 * MIB, 0, 900000 * MIB), lab(0, 0, 100)]; })()""",
     '["File 1/1 — m.gguf (0%) — 10.0 MB/s — ~45 s left","File 1/1 — m.gguf (0%) — 10.0 MB/s — ~1 min left",'
     '"File 1/1 — m.gguf (0%) — 10.0 MB/s — ~1 h 0 min left","File 1/1 — m.gguf (0%) — 10.0 MB/s — ~1 h 1 min left",'
     '"File 1/1 — m.gguf (0%) — 10.0 MB/s — ~25 h 0 min left","File 1/1 — m.gguf (0%)"]',
     "подпись строки — правило и слова страницы /models: «~45 s left», ровно 60 s — «~1 min», час — «~1 h 0 min», за час — минуты вверх («~1 h 1 min»), "
     "суток нет («~25 h 0 min»); "
"нет ни скорости, ни темпа — подпись без обеих приписок, как до 1.3.565"),

    ("poll_miss_is_shown_and_asked_again", "",
     r"""await (async () => { const job = dl.addJob({ jobId: "j1", repoId: A, title: A, totalFiles: 1, state: "running" });
        replies["/api/hf/download/status?job=j1"] = new Error("socket hang up"); dl.poll(job); await settle();
        const missed = [job.state, job.pollError, dl.jobLabel(job), timers.map((t) => t.ms), dl.jobs.length];
        replies["/api/hf/download/status?job=j1"] = { ok: true, status: "running", total_bytes: 0, total_files: 0 }; await runTimers();
        return [missed, [job.pollError, dl.jobLabel(job), timers.length]]; })()""",
     '[["running","socket hang up","File 1/1 —  (0%) · No status: socket hang up",[600],1],["","File 1/1 —  (0%)",1]]',
     "промах опроса: задание живо, промах в подписи, спрашивает снова; следующий ответ стирает промах (as-is: без имени файла — двойной пробел)"),

    ("poll_endings", "",
     r"""await (async () => {
        const end = async (status, extra = {}) => { reset(); const job = dl.addJob({ jobId: "j1", repoId: A, title: A, totalFiles: 3, state: "running" });
          replies["/api/hf/download/status?job=j1"] = status === null ? { ok: false } : { ok: true, status, repo: extra.repo, error: extra.error, total_bytes: 10, total_bytes_done: 5 };
          replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ status: "interrupted", current_file: "a.gguf", destDir: "d" }] };
          dl.poll(job); await settle();
          const seen = [job.state, job.pct, job.error, dl.jobs.length, finished, gets, timers.map((t) => t.ms), dl.interrupted.length];
          if (timers.length) { await runTimers(); seen.push(dl.jobs.length); }
          return seen; };
        const results = [await end("done", { repo: "x/y" }), await end("done"), await end("cancelled"), await end("error", { error: "disk full" }), await end("error"), await end(null)];
        reset(); let release; const job = dl.addJob({ jobId: "j1", repoId: A, title: A, totalFiles: 1, state: "running" });
        replies["/api/hf/download/status?job=j1"] = new Promise((r) => { release = r; }); dl.poll(job); await settle();
        dl.dropJob(job); release({ ok: true, status: "done" }); await settle();
        return [...results, [dl.jobs.length, finished, timers.length]]; })()""",
     '[["done",100,"",1,["x/y"],["/api/hf/download/status?job=j1"],[4000],0,0],["done",100,"",1,["bartowski/gemma-4-12B-it-GGUF"],["/api/hf/download/status?job=j1"],[4000],0,0],'
     '["running",50,"",0,[],["/api/hf/download/status?job=j1","/api/hf/download/jobs"],[],1],["error",50,"disk full",1,[],["/api/hf/download/status?job=j1"],[],0],'
     '["error",50,"unknown",1,[],["/api/hf/download/status?job=j1"],[],0],["running",0,"",0,[],["/api/hf/download/status?job=j1"],[],0],[0,[],0]]',
     "концы: готово — 100%, обратный вызов с репозиторием (или своим), уходит через 4 с; отменено — задание уходит, прерванные перечитываются; ошибка — остаётся с текстом; неизвестное серверу — уходит; убранное во время ответа не воскресает"),

    ("gated_refusal_goes_nowhere_by_itself", "",
     r"""await (async () => { const PAGE = "https://huggingface.co/nvidia/personaplex-7b-v1", REPO = "nvidia/personaplex-7b-v1";
        const access = (tokenSet) => ({ kind: "gated", url: PAGE, repo: REPO, status: 403, tokenSet });
        const refuse = async (extra, fields = {}) => { reset(); const job = dl.addJob({ jobId: "j1", repoId: REPO, title: REPO, totalFiles: 7, state: "running", ...fields });
          replies["/api/hf/download/status?job=j1"] = { ok: true, status: "error", error: "HTTP Error 403: Forbidden", total_bytes: 10, total_bytes_done: 0, ...extra };
          dl.poll(job); await settle(); return job; };
        const job = await refuse({ access: access(true) });
        const first = [job.state, job.error, job.access.url, [...opened], timers.length];
        const byButton = [dl.openPageOf(job.uid), [...opened]];
        const again = [dl.openPageOf(job.uid), opened.length];
        const noToken = await refuse({ access: access(false) });
        const noTokenOpened = [...opened];
        const plain = await refuse({}); const plainOpened = opened.length;
        const unnamed = await refuse({ access: { kind: "gated", url: "", repo: REPO } }); const unnamedOpened = opened.length;
        return [first, byButton, again, [noToken.access.tokenSet, noTokenOpened], [plain.state, plain.access, plainOpened, dl.openPageOf(plain.uid)], [unnamed.access, unnamedOpened, dl.openPageOf(unnamed.uid)],
                dl.openPageOf("dlj404"), dl.openAccessPage(null)]; })()""",
     '[["error","HTTP Error 403: Forbidden","https://huggingface.co/nvidia/personaplex-7b-v1",[],0],'
     '[true,["https://huggingface.co/nvidia/personaplex-7b-v1"]],[true,2],[false,[]],["error",null,0,false],[null,0,false],false,false]',
     "закрытый репозиторий (2026-10-17: ничего не открывается в новой вкладке): отказ с access остаётся строкой с кнопкой, страница САМА не открывается и вкладку не уводит; "
     "кнопка строки ведёт на страницу в этой же вкладке — каждый нажим, а не один раз; negative: без токена — то же, без access (обычный отказ) и без адреса страницы кнопка ничего не делает, чужой uid и пустое задание — тоже"),

    ("gated_refusal_of_a_restored_job_waits_for_the_button", "",
     r"""await (async () => { const REPO = "nvidia/personaplex-7b-v1", PAGE = "https://huggingface.co/" + REPO;
        replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "j1", title: REPO, repo: REPO, total_files: 7, status: "error" }] };
        replies["/api/hf/download/status?job=j1"] = { ok: true, status: "error", error: "HTTP Error 403: Forbidden", total_bytes: 10, total_bytes_done: 0,
          access: { kind: "gated", url: PAGE, repo: REPO, status: 403, tokenSet: true } };
        await dl.restore(); await settle(); const job = dl.jobs[0];
        return [dl.jobs.length, job.state, !!job.access, opened.length, dl.openPageOf(job.uid), [...opened]]; })()""",
     '[1,"error",true,0,true,["https://huggingface.co/nvidia/personaplex-7b-v1"]]',
     "задание, вернувшееся после перезагрузки: строка с отказом и кнопкой есть, страница сама не открывается; кнопка строки ведёт на неё в этой же вкладке"),

    ("the_button_goes_to_the_page_of_its_own_row", "",
     r"""(() => { const a = dl.addJob({ jobId: "j1", state: "error", access: { kind: "gated", url: "https://huggingface.co/a/one", repo: "a/one", status: 403, tokenSet: true } });
        const b = dl.addJob({ jobId: "j2", state: "error", access: { kind: "gated", url: "https://huggingface.co/b/two", repo: "b/two", status: 403, tokenSet: true } });
        dl.openPageOf(b.uid); dl.openPageOf(a.uid); return [...opened]; })()""",
     '["https://huggingface.co/b/two","https://huggingface.co/a/one"]',
     "кнопка строки ведёт на страницу своего репозитория, а не соседнего"),

    ("gated_row_words_and_button", "",
     r"""(() => { const REPO = "nvidia/personaplex-7b-v1";
        const gated = (tokenSet) => dl.addJob({ jobId: tokenSet ? "j1" : "j2", repoId: REPO, title: REPO, state: "error", error: "HTTP Error 403: Forbidden",
          access: { kind: "gated", url: "https://huggingface.co/" + REPO, repo: REPO, status: 403, tokenSet } });
        const withToken = gated(true), withoutToken = gated(false);
        const plain = dl.addJob({ jobId: "j3", repoId: REPO, title: "other/repo", state: "error", error: "HTTP Error 404: Not Found" });
        dl.jobsOpen = true; const h = dl.html(() => null);
        const row = (id) => { const at = h.indexOf(`data-t="hf-download-job" data-t-id="${id}"`); const next = h.indexOf('<div class="hfp-job ', at); return h.slice(h.lastIndexOf("<div", at), next < 0 ? h.length : next); };
        const a = row("j1"), b = row("j2"), c = row("j3");
        return [dl.jobLabel(withToken), dl.jobLabel(withoutToken), dl.jobLabel(plain),
          a.startsWith('<div class="hfp-job is-error is-gated"'), a.includes('data-act="job-open-page" data-uid="dlj1" data-t="hf-download-open-page" data-t-id="j1">Open the page</button>'),
          a.includes('data-act="job-dismiss"'), a.indexOf("job-open-page") < a.indexOf("job-dismiss"), b.includes("job-open-page"),
          c.startsWith('<div class="hfp-job is-error"'), c.includes("job-open-page"), c.includes('data-act="job-dismiss"')]; })()""",
     '["nvidia/personaplex-7b-v1 is gated: Hugging Face wants its terms accepted first. Press “Open the page”, accept them there, then download again.",'
     '"nvidia/personaplex-7b-v1 is gated: Hugging Face wants its terms accepted first, and a token. Press “Open the page”, accept the terms, save a token in “HF token”, then download again.",'
     '"Error: HTTP Error 404: Not Found",true,true,true,true,true,true,false,true]',
     "строка закрытого репозитория: слова по-английски с именем репозитория, названием кнопки и названием поля токена; без токена — ещё и про токен; кнопка «Open the page» перед ✕; обычная ошибка — старые слова и без кнопки"),

    ("cancel_holds_and_fails_back", "",
     r"""await (async () => {
        const unsent = dl.addJob({ repoId: A, title: A, state: "starting" }); await dl.cancel(unsent.uid); const notSent = [posts.length, dl.jobs.length];
        const job = dl.addJob({ jobId: "j5", repoId: A, title: A, totalFiles: 1, state: "running" });
        replies["/api/hf/download/cancel"] = { ok: true, jobId: "j5" }; await dl.cancel(job.uid);
        const pressed = [JSON.parse(JSON.stringify(posts)), job.state, job.cancelling, toasts.length, dl.jobLabel(job)];
        replies["/api/hf/download/status?job=j5"] = { ok: true, status: "running", total_bytes: 0 }; dl.poll(job); await settle(); const heldAgainstPoll = job.state;
        replies["/api/hf/download/cancel"] = { ok: false, error: "job not found or already finished" }; await dl.cancel(job.uid); const failed = [job.state, job.cancelling, [...toasts]];
        replies["/api/hf/download/cancel"] = new Error("offline"); await dl.cancel(job.uid); await dl.cancel("dlj404");
        return [notSent, pressed, heldAgainstPoll, failed, toasts.slice(1), posts.length]; })()""",
     '[[0,0],[[["/api/hf/download/cancel",{"jobId":"j5"}]],"cancelling",true,0,"Cancelling…"],"cancelling",["running",false,["Could not cancel: job not found or already finished"]],["Could not cancel: offline"],3]',
     "отмена: неотправленное просто уходит; иначе запрос на сервер, «отменяю» держится против опроса; отказ или сеть — задание снова идёт, тост с причиной; чужой uid — ничего"),

    ("dismiss_only_error_rows", "",
     r"""(() => { const running = dl.addJob({ jobId: "j1", state: "running" }); const failed = dl.addJob({ jobId: "j2", state: "error", error: "x" }); const done = dl.addJob({ jobId: "j3", state: "done" });
        dl.dismiss(running.uid); dl.dismiss(done.uid); dl.dismiss("dlj404"); const kept = dl.jobs.map((j) => j.jobId); dl.dismiss(failed.uid);
        return [kept, dl.jobs.map((j) => j.jobId)]; })()""",
     '[["j1","j2","j3"],["j1","j3"]]',
     "✕ убирает только строку ошибки; идущее и готовое не трогает"),

    ("resume_turns_a_partial_into_a_job", "",
     r"""await (async () => { const rowA = { destDir: "gemma/bartowski/Q4_K_M", current_file: "a.gguf", repo: A, title: "t", resumable: true };
        const rowB = { destDir: "other/x/Q8_0", current_file: "b.gguf", repo: "", title: "Title B", resumable: true };
        dl.interrupted = [rowA, rowB]; const hang = new Promise(() => {});
        replies["/api/hf/download/status?job=j8"] = hang; replies["/api/hf/download/status?job=j9"] = hang;
        replies["/api/hf/download/resume"] = { ok: false, error: "no manifest" }; await dl.resume(rowA.destDir, "a.gguf");
        const refused = [dl.interrupted.length, dl.jobs.length, [...toasts]];
        replies["/api/hf/download/resume"] = new Error("offline"); await dl.resume(rowA.destDir, "a.gguf");
        replies["/api/hf/download/resume"] = { ok: false }; await dl.resume(rowA.destDir, "a.gguf");
        replies["/api/hf/download/resume"] = [{ ok: true, jobId: "j8" }, { ok: true, jobId: "j9" }];
        await dl.resume(rowB.destDir, "b.gguf"); await dl.resume("nowhere", "c.gguf"); await settle();
        return [refused, toasts.slice(1), posts[0], dl.interrupted.map((r) => r.current_file), dl.jobs.map((j) => [j.jobId, j.title, j.repoId, j.totalFiles, j.state]),
                dl.jobsOpen, JSON.parse(store.get("hfDlJobs")).map((j) => j.jobId), gets]; })()""",
     '[[2,0,["no manifest"]],["offline","resume failed"],["/api/hf/download/resume",{"destDir":"gemma/bartowski/Q4_K_M","name":"a.gguf"}],["a.gguf"],'
     '[["j8","Title B","",1,"resuming"],["j9","c.gguf","",1,"resuming"]],true,["j8","j9"],["/api/hf/download/status?job=j8","/api/hf/download/status?job=j9"]]',
     "продолжить: запрос с папкой и именем; отказ — тост с причиной (или «resume failed»), прерванное остаётся; успех — прерванное становится заданием (заголовок: репозиторий, название, имя файла), список открыт, сохранён, опрос"),

    ("restore_server_first", "",
     r"""await (async () => { const hang = new Promise(() => {}); const hangStatus = () => { for (const id of ["j1", "j2", "j9"]) replies[`/api/hf/download/status?job=${id}`] = hang; };
        hangStatus(); replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "j1", title: "T1", repo: A, total_files: 3, status: "running" }, { jobId: "p1", title: "old", status: "interrupted", current_file: "x.gguf" }] };
        store.set("hfDlJobs", JSON.stringify([{ jobId: "j9", title: "stale" }]));
        await dl.restore(); const server = [dl.jobs.map((j) => [j.jobId, j.title, j.repoId, j.totalFiles, j.state]), dl.interrupted.map((r) => r.jobId), dl.jobsOpen];
        await dl.restore(); const again = dl.jobs.length;
        reset(); hangStatus(); replies["/api/hf/download/jobs"] = { ok: true, jobs: [{ jobId: "p1", status: "interrupted", current_file: "x.gguf" }] };
        await dl.restore(); const onlyPartials = [dl.jobs.length, dl.interrupted.length, dl.jobsOpen];
        reset(); hangStatus(); replies["/api/hf/download/jobs"] = new Error("offline");
        store.set("hfDlJobs", JSON.stringify([{ jobId: "j2", title: "Saved", repoId: B, totalFiles: 2 }, { title: "no id" }, null]));
        await dl.restore(); const fromStorage = [dl.jobs.map((j) => [j.jobId, j.title, j.repoId, j.totalFiles, j.state]), dl.jobsOpen, gets];
        reset(); replies["/api/hf/download/jobs"] = { ok: false }; store.set("hfDlJobs", "{broken"); await dl.restore();
        return [server, again, onlyPartials, fromStorage, [dl.jobs.length, dl.jobsOpen, changes]]; })()""",
     '[[[["j1","T1","bartowski/gemma-4-12B-it-GGUF",3,"resuming"]],["p1"],true],1,[0,1,false],'
     '[[["j2","Saved","unsloth/Qwen3.6-35B-A3B-GGUF",2,"resuming"]],true,["/api/hf/download/jobs","/api/hf/download/status?job=j2"]],[0,false,1]]',
     "после перезагрузки: задания сервера (свой список браузера не нужен); повтор не дублирует; только прерванные — список не открывается; сервер недоступен — свой список, записи без id пропускаются; битый список — пусто"),

    ("only_live_jobs_saved", "",
     r"""(() => { for (const [jobId, state] of [[null, "starting"], ["j1", "running"], ["j2", "done"], ["j3", "error"], ["j4", "cancelling"], ["j5", "resuming"], ["j6", "retrying"]])
          dl.addJob({ jobId, state, title: `T-${state}`, repoId: A, totalFiles: 2 });
        dl.persist(); const saved = JSON.parse(store.get("hfDlJobs")).map((j) => [j.jobId, j.title]);
        let threw = false; dl.storage = { setItem: () => { throw new Error("quota"); } }; try { dl.persist(); } catch { threw = true; }
        dl.storage = null; try { dl.persist(); } catch { threw = true; }
        return [saved, threw]; })()""",
     '[[["j1","T-running"],["j4","T-cancelling"],["j5","T-resuming"],["j6","T-retrying"]],false]',
     "сохраняются только живые задания с id; без хранилища или с его отказом — без исключения"),

    ("dock_bar_and_plan", "",
     r"""(() => { const empty = [dl.visible(), dl.html(() => null)];
        dl.toggle(A, [F("a-Q4.gguf", "Q4_K_M", 7 * GIB), F("mmproj-a.gguf", "", 100 * MIB)], true); dl.toggle(B, [F("b-Q8.gguf", "Q8_0", 2 * GIB)], true);
        const closed = dl.html(() => new Set(["mmproj-a.gguf"]));
        dl.detailsOpen = true; const open = dl.html((id) => (id === A ? new Set(["mmproj-a.gguf"]) : new Set()));
        const clean = dl.html(() => new Set());
        dl.setDisk({ ok: true, freeGb: 50, totalGb: 200 }); const known = dl.html(() => new Set());
        dl.setDisk({ ok: true, freeGb: 10, totalGb: 200 }); const tight = dl.html(() => new Set());
        return [empty, dl.visible(),
          closed.includes('<span class="hfp-sel">Selected 3 · 9.1 GB</span>'), closed.includes("→ gemma-4-12B-it-GGUF/bartowski/Q4_K_M/ · gemma-4-12B-it-GGUF/bartowski/default/ +1<"),
          closed.includes('aria-expanded="false">Details ▾'), closed.includes('data-act="download" data-t="hf-download-start">Download<'), closed.includes("hf-selection-plan"), closed.includes("hf-downloads-toggle"),
          open.includes('aria-expanded="true">Hide ▴'), open.includes('<div class="hfp-plan-dir">Qwen3.6-35B-A3B-GGUF/unsloth/Q8_0/</div>'),
          open.includes('data-act="sel-remove" data-repo="bartowski/gemma-4-12B-it-GGUF" data-path="mmproj-a.gguf" data-t="hf-selection-remove" data-t-id="mmproj-a.gguf"'),
          open.includes("free space unknown"), open.includes("⚠ writes over 1 file(s) on disk — you will be asked first"), open.includes("nothing on disk is written over"),
          open.includes('data-act="sel-clear" data-t="hf-selection-clear">Clear selection<'), clean.includes("✓ nothing on disk is written over"),
          known.includes('<i class="used" style="width:75.0%"></i><i class="plan" style="left:75.0%;width:4.5%"></i>'), known.includes('<span class="hfp-good">fits</span>'),
          known.includes("50 GB free of 200 GB · about 40.9 GB left after"), tight.includes('<span class="hfp-bad">does not fit</span>'), tight.includes("10 GB free of 200 GB · about 4.1 GB short"), tight.includes("left after")]; })()""",
     '[[false,"<div class=\\"hfp-dock-bar\\"><span class=\\"grow\\"></span></div>"],true,true,true,true,true,false,false,true,true,true,true,true,false,true,true,true,true,true,true,true,false]',
     "док: пусто — пустая полоса; выбор — сколько и сколько весит, первые две папки и +N, «подробнее»/«скрыть», «скачать»; план — папки, ✕ на файлах, диск неизвестен, что перезапишется или ничего, очистка; диск известен — полоса занято|план, влезает/не влезает, сколько останется или сколько не хватает (с местом на сборку), а не отрицательный остаток"),

    ("dock_jobs_and_partials", "",
     r"""(() => { dl.interrupted = [{ title: "a/m", current_file: "m-Q4.gguf", destDir: "m/a/Q4_K_M", total_bytes: 4 * GIB, total_bytes_done: GIB, resumable: true },
          { title: "b/n", current_file: "n.gguf", total_bytes: 0, total_bytes_done: 300 * MIB, resumable: false }];
        const onlyPartials = [dl.jobsButtonHtml(), dl.html(() => null).includes('data-t="hf-downloads"')];
        dl.addJob({ jobId: "j1", title: "run/one", totalFiles: 2, state: "running", pct: 40, idx: 1, file: "a.gguf", filePct: 80 });
        dl.addJob({ jobId: null, title: "start/two", state: "starting", pct: 0 });
        const failed = dl.addJob({ jobId: "j3", title: "err/three", state: "error", error: "disk full", pct: 30 });
        dl.addJob({ jobId: "j4", title: "done/four", state: "done", totalFiles: 5, pct: 100 });
        dl.addJob({ jobId: "j5", title: "cancel/five", state: "cancelling", pct: 150 });
        dl.jobsOpen = true; const h = dl.html(() => null); const button = dl.jobsButtonHtml();
        const row = (hook, id) => { const at = h.indexOf(`data-t="${hook}" data-t-id="${id}"`); if (at < 0) return ""; const next = h.indexOf('<div class="hfp-job ', at); return h.slice(h.lastIndexOf("<div", at), next < 0 ? h.length : next); };
        const r1 = row("hf-download-job", "j1"), r2 = row("hf-download-job", "dlj2"), r3 = row("hf-download-job", "j3"), r4 = row("hf-download-job", "j4"), r5 = row("hf-download-job", "j5");
        const p1 = row("hf-download-interrupted", "m-Q4.gguf"), p2 = row("hf-download-interrupted", "n.gguf");
        dl.interrupted = []; dl.dropJob(failed);
        return [onlyPartials, button, h.includes('<div class="hfp-jobs" data-t="hf-downloads">'),
          r1.startsWith('<div class="hfp-job is-running"') && r1.includes('<div class="hfp-job-title">run/one</div>') && r1.includes('<i style="width:40%"></i>') && r1.includes('<div class="hfp-job-label">File 1/2 — a.gguf (80%)</div>'),
          r1.includes('data-act="job-cancel" data-uid="dlj1" data-t="hf-download-cancel" data-t-id="j1" aria-label="Cancel download">Cancel</button>'),
          r2.includes('data-t="hf-download-cancel" data-t-id="dlj2"') && r2.includes(">Starting…<"),
          r3.includes('data-act="job-dismiss" data-uid="dlj3" data-t="hf-download-dismiss" aria-label="Close">✕</button>') && r3.includes(">Error: disk full<"), r3.includes("hf-download-cancel"),
          r4.includes(">Done — files: 5<") && !r4.includes("<button"), r5.includes(">Cancelling…<") && r5.includes("width:100%") && !r5.includes("<button"),
          p1.includes('<div class="hfp-job-title">a/m · m-Q4.gguf</div>') && p1.includes('<span class="hfp-bar is-stalled"><i style="width:25%"></i></span>') && p1.includes('<div class="hfp-job-label hfp-warn">Interrupted — 1.0 GB / 4.0 GB downloaded</div>'),
          p1.includes('data-act="resume" data-dest="m/a/Q4_K_M" data-name="m-Q4.gguf" data-t="hf-download-resume" data-t-id="m-Q4.gguf">Resume</button>'),
          p2.includes(">Interrupted — 300 MB on disk, source unknown<"), p2.includes("hf-download-resume"), dl.jobsButtonHtml(), dl.visible()]; })()""",
     '[["<button type=\\"button\\" class=\\"hfp-btn is-warn\\" data-act=\\"jobs\\" data-t=\\"hf-downloads-toggle\\" aria-expanded=\\"false\\">⬇ Downloads · 2 interrupted ▾</button>",false],'
     '"<button type=\\"button\\" class=\\"hfp-btn is-warn\\" data-act=\\"jobs\\" data-t=\\"hf-downloads-toggle\\" aria-expanded=\\"true\\">⬇ Downloads · 3 running · 63% · 2 interrupted ▴</button>",'
     'true,true,true,true,true,false,true,true,true,true,true,false,'
     '"<button type=\\"button\\" class=\\"hfp-btn\\" data-act=\\"jobs\\" data-t=\\"hf-downloads-toggle\\" aria-expanded=\\"true\\">⬇ Downloads · 3 running · 63% ▴</button>",true]',
     "задания: кнопка — сколько идёт и средний %, прерванные, янтарная при прерванных или ошибке; только прерванные — список закрыт; строки: «Отмена» у идущих (id или uid), ✕ у ошибки, пусто у готового и отменяемого; полоса не шире 100%; прерванные — «Продолжить» только при манифесте"),
]


if __name__ == "__main__":
    sys.exit(run("js hf-downloads", ".probe_js_hf_downloads.tmp.mjs", PREAMBLE, PINS))
