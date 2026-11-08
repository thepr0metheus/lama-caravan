#!/usr/bin/env python3
"""The stand (scripts/stand): what its stand-ins say, and that it cannot eat a disk or reach a network.

A stand-in that answers differently from the real thing makes every check on the stand worthless, and it would do so
silently. So its answers are pinned by value against what the scout parses and what llama.cpp does: the columns of nvidia-smi,
whole layers under --fit, a --device it cannot see refused in llama.cpp's words. And the two ways the stand could harm the
laptop it runs on are pinned too: its models are holes that say 174 GiB, and it listens on somebody else's network.

Run: python3 scripts/test_stand.py
"""
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "scripts" / "stand"
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(ROOT)]

from cards import StandCards  # noqa: E402
from fake_llama import FakeServer, Flags, InvalidDevice, ModelFacts, Placement  # noqa: E402
from fake_smi import StandSmi  # noqa: E402
from gguf_reader import GgufHeader  # noqa: E402
from fake_vllm import FakeVllm, VllmPlacement  # noqa: E402
from models import GgufWriter, StandModels  # noqa: E402
from stand import DiskGuard, Stand  # noqa: E402

_fail = []
GIB = 1024 ** 3
FREE = {0: 24576, 1: 32348}  # the stand's two cards with nothing on them


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn):
    """The words of a SystemExit, None when `fn` went through."""
    try:
        fn()
    except SystemExit as exc:
        return str(exc.code)
    return None


def smi(cards, argv):
    out = io.StringIO()
    code = StandSmi(cards, out).run(argv)
    return code, out.getvalue().splitlines()


def section_cards(tmp):
    print("карты стенда:")
    cards = StandCards(tmp / "a")
    check(cards.claims() == [] and cards.free_mib(0, []) == 24576 and cards.free_mib(1, []) == 32348,
          "пусто: вся память свободна, на второй карте занято своё (рабочий стол)")
    me = os.getpid()
    cards.claim(me, "llama-server", {0: 6000, 1: 1000})
    check(cards.used_mib(0) == 6000 and cards.used_mib(1) == 1412 and cards.free_mib(1) == 31348, "процесс держит память на картах, чужое остаётся")
    cards.claim(me, "llama-server", {1: 500})
    check(cards.used_mib(0) == 0 and cards.used_mib(1) == 912, "новая запись процесса заменяет старую")
    check(cards.claims(alive=lambda pid: False) == [] and not list(cards.folder.glob("*.json")),
          "negative: мёртвый процесс ничего не держит, его запись уходит: как настоящая карта")
    cards.claim(me, "x", {0: 1})
    cards.release(me)
    check(cards.claims() == [], "release снимает")
    check(StandCards.alive(me) is True and StandCards.alive(2 ** 22 - 1) is False, "живость процесса по его номеру")
    words = refused(lambda: StandCards.from_env({}))
    check(words is not None and StandCards.ROOT_VAR in words, "negative: без стенда подделка не работает: отказ с именем переменной, а не запись куда попало")


def section_smi(tmp):
    print("nvidia-smi стенда:")
    cards = StandCards(tmp / "b")
    query = "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,uuid"
    code, lines = smi(cards, [query, "--format=csv,noheader,nounits"])
    check(code == 0 and lines == ["0, NVIDIA GeForce RTX 3090, 24576, 0, 24576, 0, 41, 31.50, GPU-stand-0",
                                  "1, NVIDIA GeForce RTX 5090, 32760, 412, 32348, 0, 41, 31.50, GPU-stand-1"],
          f"запрос карт скаута (machine.py nvidia_reading): столбцы в его порядке (получено {lines})")
    cards.claim(os.getpid(), "llama-server", {0: 700})
    apps = "--query-compute-apps=gpu_uuid,pid,process_name,used_memory"
    code, lines = smi(cards, [apps, "--format=csv,noheader,nounits"])
    check(code == 0 and lines == [f"GPU-stand-0, {os.getpid()}, llama-server, 700"], f"кто на карте: столбцы APPS_QUERY скаута (получено {lines})")
    check(smi(cards, ["--query-gpu=memory.used"])[1] == ["700", "412"], "только спрошенное")
    check(smi(cards, ["--query-gpu=driver_version", "--format=csv,noheader"])[1] == ["stand", "stand"], "версия драйвера названа: не настоящая")
    link = "--query-gpu=index,pcie.link.gen.max,pcie.link.width.current"
    check(smi(cards, [link, "--format=csv,noheader,nounits"])[1] == ["0, 4, 8", "1, 5, 8"],
          "шина карт (запрос LINK_QUERY скаута): поколение и линии как у машины дома — 3090 PCIe 4.0 x8, 5090 PCIe 5.0 x8")
    code, lines = smi(cards, ["--query-gpu=memory.reserved"])
    check(code == 2 and lines == [], "negative: поле, которому не учили: код выхода настоящего nvidia-smi, а не выдуманное значение")
    code, lines = smi(cards, [])
    check(code == 0 and len(lines) == 1 and "no hardware" in lines[0], "без запроса: говорит, что железа нет")


def section_placement():
    print("куда ложится память:")
    chat = ModelFacts(49, 3840, 16, 8, 17 * 1024)
    coder = ModelFacts(81, 5120, 16, 8, 36 * 1024)

    def laid(model, line, env=None, free=None):
        place = Placement(Flags(line.split()), env or {}, dict(free or FREE), model)
        return place, place.shares()

    check(round(chat.kv_mib(32768) / 1024, 2) == 11.48, "кэш по формуле llama.cpp: окно × слои × головы × ключ и значение × F16")
    check(ModelFacts(49, 3840, 0, 0, 1).kv_mib(32768) == 0, "negative: голов не сказали — кэша не считает")
    place, shares = laid(chat, "--ctx-size 32768 --n-gpu-layers auto --fit-target 12645,13920 --fit on")
    check(shares == {0: 11905, 1: 17262} and place.layers_on == {0: 20, 1: 29},
          f"--fit: целые слои, карта за картой, на каждой остаётся её --fit-target (получено {shares}, {place.layers_on})")
    place, shares = laid(coder, "--ctx-size 32768 --fit-target 256,256 --fit on")
    check(place.layers_on == {0: 31, 1: 41} and sum(place.layers_on.values()) == 72, f"что не влезло, остаётся в RAM: 9 слоёв из 81 (получено {place.layers_on})")
    place, _ = laid(chat, "--ctx-size 32768 --fit-target 20000 --fit on")
    check(place.margins(2) == [20000, 20000] and place.layers_on == {0: 7, 1: 20}, f"одно значение — на все карты, как читает llama.cpp (получено {place.layers_on})")
    place, _ = laid(chat, "--ctx-size 32768 --fit on")
    check(place.margins(2) == [1024, 1024], "не сказано: свой запас llama.cpp, 1024 МиБ")
    _, shares = laid(chat, "--ctx-size 16384 --n-gpu-layers auto --device CUDA0 --fit-target 16037 --fit on", {"CUDA_VISIBLE_DEVICES": "1"})
    check(list(shares) == [1], "CUDA_VISIBLE_DEVICES=1 и --device CUDA0: это настоящая карта 1: так контроллер переводит DEVICE=CUDA1")
    try:
        laid(chat, "--device CUDA1 --fit on", {"CUDA_VISIBLE_DEVICES": "1"})
        check(False, "negative: --device CUDA1 при одной видимой карте — отказ")
    except InvalidDevice as exc:
        check(str(exc) == "CUDA1", "negative: --device CUDA1 при одной видимой карте — отказ: llama.cpp считает видимые")
    check(laid(chat, "--device none --fit on")[1] == {}, "--device none: на картах ничего")
    check(laid(chat, "--n-gpu-layers 0 --fit on", {"CUDA_VISIBLE_DEVICES": ""})[1] == {}, "старт в RAM: контроллер прячет карты: ничего на картах")
    check(laid(chat, "--n-gpu-layers 0")[1] == {}, "negative: -ngl 0 без --fit: тоже ничего, а не записи по нулю")
    place, shares = laid(ModelFacts(40, 0, 0, 0, 40 * 1024), "--n-gpu-layers 40 --tensor-split 1,3")
    check(shares == {0: 10240, 1: 30720} and place.layers_on == {0: 10, 1: 30}, f"--tensor-split: доли по порядку видимых карт (получено {shares})")
    place, shares = laid(ModelFacts(40, 0, 0, 0, 40 * 1024), "--n-gpu-layers 20", {"CUDA_VISIBLE_DEVICES": "0"})
    check(shares == {0: 20480} and place.layers_on == {0: 20}, "-ngl: половина слоёв — половина памяти")
    check(place.short({0: 30000}) == (0, 30000, 24576) and place.short({0: 100}) is None, "не влезает: какая карта, сколько просят, сколько есть; влезает — None")
    check(Flags(["-m", "a", "-c", "5", "--metrics"]).values == {"--model": "a", "--ctx-size": "5"}, "короткие флаги под длинными именами; negative: флаг без значения в конце не значение")


def section_server(tmp):
    print("llama-server стенда:")
    root = tmp / "c"
    cards = StandCards(root)
    models = StandModels(root / "models")
    models.write()
    small = root / "models" / "stand-small-8B-Q4_K_M.gguf"
    server = FakeServer(["--port", "22001", "--model", str(small), "--ctx-size", "1024", "--alias", "tiny"], {}, cards)
    server.ready_at = float("inf")
    check(server.respond(None, "GET", "/health")[0] == 503 and server.respond(None, "GET", "/v1/models")[0] == 503, "пока грузится: 503, как настоящий, на всё")
    server.ready_at = 0
    check(server.respond(None, "GET", "/health") == (200, {"status": "ok"}), "загрузился: /health")
    status, body = server.respond(None, "GET", "/v1/models?x=1")
    check(status == 200 and body["data"][0]["id"] == "tiny" and body["data"][0]["meta"]["n_ctx_train"] == 32768, "имя модели и её окно обучения из заголовка")
    check(server.respond(None, "GET", "/props")[1]["default_generation_settings"]["n_ctx"] == 1024, "окно — спрошенное")
    check(server.respond(None, "GET", "/nope")[0] == 404, "negative: чего не знает — 404")
    check("no model" in server.respond(None, "POST", "/v1/chat/completions")[1]["choices"][0]["message"]["content"], "negative: на вопрос честно говорит, что модели нет")

    open_to_all = FakeServer(["--port", "0", "--host", "0.0.0.0", "--model", str(small)], {}, cards).serve()
    check(open_to_all.server_address[0] == "127.0.0.1", "defect-guard: --host 0.0.0.0 ему не указ: стенд на ноутбуке в чужой сети, только loopback")
    open_to_all.server_close()

    said = io.StringIO()
    keep, sys.stdout = sys.stdout, said
    try:
        missing = FakeServer(["--port", "22002", "--model", str(root / "none.gguf")], {}, cards).run(root)
        invalid = FakeServer(["--port", "22003", "--model", str(small), "--device", "CUDA7"], {}, cards).run(root)
        huge = FakeServer(["--port", "22004", "--model", str(small), "--ctx-size", "9999999", "--n-gpu-layers", "99"], {"CUDA_VISIBLE_DEVICES": "0"}, cards).run(root)
    finally:
        sys.stdout = keep
    words = said.getvalue()
    check(missing == 1 and "failed to open model" in words, "negative: файла нет: падает с кодом 1")
    check(invalid == 1 and 'error while handling argument "--device": invalid device: CUDA7' in words, "negative: чужой --device: словами llama.cpp, код 1")
    check(huge == 1 and "cudaMalloc failed: out of memory" in words and cards.claims() == [], "negative: не влезает на карту: словами llama.cpp, код 1, память не заняла")
    check((root / "launches" / "22004.json").is_file(), "что запустили, записано и у упавшего: это и есть проверка команды")


def section_vllm(tmp):
    print("vLLM стенда:")
    totals = {0: 24576, 1: 32760}

    def laid(line, env=None, weights=20 * 1024):
        place = VllmPlacement(Flags(line.split()), env or {}, totals, weights)
        cards = place.cards()
        shares = place.share_mib(cards) if cards else {}
        return place, cards, shares

    _, cards, shares = laid("--gpu-memory-utilization 0.9", {"CUDA_VISIBLE_DEVICES": "1"})
    check(cards == [1] and shares == {1: 29484}, f"закреплён на карте: её доля, как VllmPlacement каравана (получено {shares})")
    _, cards, shares = laid("--tensor-parallel-size 2")
    check(cards == [0, 1] and shares == {0: 22118, 1: 22118}, f"tensor-parallel: каждая карта берёт то, что позволяет самая маленькая (получено {shares})")
    place, cards, shares = laid("", {"CUDA_VISIBLE_DEVICES": "0"}, 40 * 1024)
    words = place.no_room(shares)
    check(words is not None and "No available memory for the cache blocks" in words, "веса больше доли: падает словами vLLM")
    place, cards, shares = laid("--cpu-offload-gb 20", {"CUDA_VISIBLE_DEVICES": "0"}, 40 * 1024)
    check(place.no_room(shares) is None and place.offload_mib(cards) == 20480 and place.on_card_mib(cards) == 20480, "--cpu-offload-gb: столько остаётся в RAM, остальное влезает")
    place, cards, shares = laid("--cpu-offload-gb 90", {"CUDA_VISIBLE_DEVICES": "0"}, 40 * 1024)
    check(place.offload_mib(cards) == 40960, "negative: в RAM не больше, чем весов")
    place, cards, shares = laid("--tensor-parallel-size 2 --cpu-offload-gb 5", None, 40 * 1024)
    check(place.offload_mib(cards) == 5120 and place.on_card_mib(cards) == 15360, "на каждую карту")
    check(laid("", {"CUDA_VISIBLE_DEVICES": ""})[1] == [], "negative: карт не видно: ничего не держит")
    root = tmp / "v"
    cards_store = StandCards(root)
    models = StandModels(root / "models")
    models.write()
    big = root / "models" / "stand-vllm-big-70B"
    argv = ["serve", str(big), "--port", "22006", "--served-model-name", "big", "--max-model-len", "2048"]
    server = FakeVllm(argv, {"CUDA_VISIBLE_DEVICES": "1"}, cards_store)
    check(server.weights_mib() == 40 * 1024 and server.model_id() == "big" and server.window() == 2048, "вес папки чекпойнта, имя и окно из флагов")
    server.ready_at = 0
    check(server.respond(None, "GET", "/v1/models")[1]["data"][0]["id"] == "big" and server.respond(None, "GET", "/health")[0] == 200, "отвечает как vLLM")
    server.ready_at = float("inf")
    check(server.respond(None, "GET", "/v1/models")[0] == 503, "negative: пока грузится — нет")
    said = io.StringIO()
    keep, sys.stdout = sys.stdout, said
    try:
        died = FakeVllm(argv, {"CUDA_VISIBLE_DEVICES": "1"}, cards_store).run(root)
        lost = FakeVllm(["download"], {}, cards_store).run(root)
    finally:
        sys.stdout = keep
    record = json.loads((root / "launches" / "22006.json").read_text(encoding="utf-8"))
    check(died == 1 and "No available memory" in said.getvalue() and cards_store.claims() == [], "negative: не влез: код 1, память не заняла")
    check(record["argv"] == argv and record["env"] == {"CUDA_VISIBLE_DEVICES": "1"} and record["ramMiB"] == 0 and record["weightsMiB"] == 40960, "что запустили, записано дословно, и что в RAM")
    check(lost == 2, "negative: не serve: код 2, а не тихая работа")
    taken = sum(path.stat().st_blocks * 512 for path in big.rglob("*") if path.is_file())
    check(taken < 1024 * 1024, f"веса чекпойнта — дыра (занято {taken} байт)")


def section_models(tmp):
    print("модели стенда:")
    folder = tmp / "d"
    models = StandModels(folder)
    models.write()
    names = sorted(path.name for path in folder.iterdir())
    check(names == sorted([row[0] for row in StandModels.LIBRARY] + [row[0] for row in StandModels.CHECKPOINTS]), "вся библиотека на месте: файлы и папки чекпойнтов")
    chat = folder / "stand-chat-27B-Q4_K_M.gguf"
    header = GgufHeader.read(chat, 256)
    check(header["llama.block_count"] == 49 and header["llama.context_length"] == 131072 and header["general.architecture"] == "llama"
          and header["llama.attention.head_count_kv"] == 8, "настоящий читатель заголовков контроллера читает то, что написано")
    check(chat.stat().st_size == 17 * GIB, "файл говорит, что весит 17 ГиБ")
    taken = sum(path.stat().st_blocks * 512 for path in folder.rglob("*") if path.is_file())
    check(taken < 1024 * 1024, f"а занимает на диске меньше мегабайта на всех (занято {taken} байт)")
    stamp = chat.stat().st_mtime_ns
    models.write()
    check(chat.stat().st_mtime_ns == stamp, "negative: есть — не переписывает: заголовок помнится по времени файла")
    victim = folder / "victim"
    victim.write_bytes(b"x")
    words = refused(lambda: StandModels.refuse_unless_hole(victim, on_disk=StandModels.HOLE_CEILING_BYTES + 1))
    check(words is not None and "fill the disk" in words and not victim.exists(),
          "defect-guard: файловая система пишет нули: файл удалён сразу, стенд не стартует")
    victim.write_bytes(b"x")
    check(refused(lambda: StandModels.refuse_unless_hole(victim, on_disk=StandModels.HOLE_CEILING_BYTES)) is None and victim.exists(), "boundary: на границе ещё дыра")
    check(GgufWriter.header({"a": 1})[:4] == b"GGUF", "магия формата")


def section_disk(tmp):
    print("сторож диска:")

    def guard(free_gib, own_gib):
        return DiskGuard(tmp, free_bytes=lambda: free_gib * GIB, own_bytes=lambda: own_gib * GIB)

    check(guard(20, 0.1).why_stop() is None, "место есть: молчит")
    check(guard(8, 2).why_stop() is None, "boundary: ровно пол и ровно потолок ещё можно")
    words = guard(7.9, 0.1).why_stop()
    check(words == "7.9 GiB left on the disk, the floor is 8", f"мало места: стоп, с цифрами (получено {words})")
    words = guard(20, 2.5).why_stop() or ""
    check("2.5 GiB" in words and "copied a model" in words, "сам стенд разросся: кто-то скопировал модель: стоп")
    folder = tmp / "e"
    folder.mkdir()
    (folder / "plain").write_bytes(b"x" * 1024 * 1024)
    with (folder / "hole").open("wb") as fh:
        fh.truncate(50 * GIB)
    walked = DiskGuard(folder).walk()
    check(1024 * 1024 <= walked < 2 * 1024 * 1024, f"считает блоки на диске, а не размер, который файл говорит (получено {walked})")
    check(DiskGuard(folder / "no" / "such").free_bytes() > 0, "папки ещё нет: смотрит на диск, где она будет")


def section_stand(tmp):
    print("сам стенд:")
    stand = Stand(root=tmp / "f", programs=tmp / "no-programs")
    env = stand.controller_env()
    check(env["LLAMACPP_ADMIN_HOST"] == "127.0.0.1" and env["CARAVAN_DATA_DIR"] == str(stand.data) and env["HOME"] == str(stand.home),
          "контроллер: только loopback, свои данные, свой HOME: от настоящего флота ничего")
    scout = stand.scout_config()
    check(scout["listenHost"] == "127.0.0.1" and scout["standAddress"] == "127.0.0.1", "скаут: только loopback, и свой адрес в чужой сети он не называет")
    check(scout["standRam"] == {"usedGb": 8.4, "totalGb": 60.5}, "память — как на машине, которую он изображает")
    check(scout["llamaServerBin"].endswith("scripts/stand/bin/llama-server"), "скаут запускает подделку")
    check(stand.scout_env()["PATH"].split(os.pathsep)[0].endswith("scripts/stand/bin") and stand.scout_env()["HOME"] == str(stand.home), "у скаута первым в PATH подделка nvidia-smi")
    check(stand.scout_env()[StandCards.ROOT_VAR] == str(stand.root), "подделки знают свой стенд")
    default = Stand().root.resolve()
    check(ROOT not in default.parents and default != ROOT,
          f"defect-guard: данные стенда вне рабочей копии: прогон мутантов копирует её, и дыры стали бы 174 ГиБ нулей (сейчас {default})")
    words = refused(stand.prepare)
    check(words is not None and "cargo build" in words, "negative: программ нет: отказ с указанием, что делать")
    (tmp / "programs").mkdir()
    for name in ("caravan-admin", "caravan-proxy", "caravan-scout"):
        (tmp / "programs" / name).write_text("", encoding="utf-8")
    full = Stand(root=tmp / "g", programs=tmp / "programs")
    full.disk = DiskGuard(tmp, free_bytes=lambda: GIB, own_bytes=lambda: 0)
    words = refused(full.prepare)
    check(words is not None and "not started" in words and not (tmp / "g" / "data").exists(), "negative: на диске мало места: не стартует и ничего не пишет")
    home = Stand(root=tmp / "i", programs=tmp / "no-programs")
    home.venv()
    shim = home.home / "vllm-venv" / "bin" / "vllm"
    check(os.access(shim, os.X_OK) and sys.executable in shim.read_text(encoding="utf-8") and os.access(home.home / "vllm-venv" / "bin" / "ninja", os.X_OK),
          "vLLM там, где его ищет караван, под HOME стенда: настоящая строка запуска идёт через него; со своим Python: login-shell собирает PATH заново")
    version = subprocess.run([str(HERE / "bin" / "llama-server"), "--version"], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check(version.returncode == 0 and "version: 9999 (stand)" in version.stdout, "bin/llama-server исполняется и говорит, что это стенд")
    no_root = {key: value for key, value in os.environ.items() if key != StandCards.ROOT_VAR}
    run = subprocess.run([str(HERE / "bin" / "nvidia-smi"), "--query-gpu=index"], capture_output=True, text=True, env={**no_root, "PYTHONDONTWRITEBYTECODE": "1"})
    check(run.returncode != 0 and StandCards.ROOT_VAR in run.stderr, "negative: bin/nvidia-smi вне стенда отказывается")
    run = subprocess.run([str(HERE / "bin" / "nvidia-smi"), "--query-gpu=index"], capture_output=True, text=True,
                         env={**os.environ, StandCards.ROOT_VAR: str(tmp / "h"), "PYTHONDONTWRITEBYTECODE": "1"})
    check(run.returncode == 0 and run.stdout.split() == ["0", "1"], "bin/nvidia-smi на стенде отвечает")


def main():
    # A stand-in that should have died and did not goes on serving its port for ever: the run ends here instead of hanging CI.
    signal.alarm(120)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        section_cards(tmp)
        section_smi(tmp)
        section_placement()
        section_server(tmp)
        section_vllm(tmp)
        section_models(tmp)
        section_disk(tmp)
        section_stand(tmp)
    if _fail:
        print(f"stand FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg[:200])
        sys.exit(1)
    print("stand OK: подделки отвечают как настоящие, диск и сеть в безопасности — значениями")


if __name__ == "__main__":
    main()
