#!/usr/bin/env python3
"""Value snapshot: what a model of the entry does — caravan/common/model_kinds.py (1.3.502).

The defect: GET /v1/models named a model and nothing of it. The owner names the pools, so a client
cannot tell a chat model from an ear by its name: sinapse would put a recogniser into its chat
lists or a chat model into its ears, and learn of it from a 4xx in the middle of a conversation.
And a pool with a cell in it stated no window — the caravan did not know a cell's here.

Pinned. A cell's router output carries what its model does, from the board's reading of the cell:
its jobs by the record rule (settings, then what it says of itself), a chat cell's inputs by
llama.cpp's own word, its languages and longest recording by its health path, the window it
serves — each only when known, and the file's copy cleaned to the right shapes. A pool promises
what every row that may serve does: a subscription's chat takes pictures, another provider's is
promised text; rows of different work are `mixed`; a row that says nothing makes the pool unknown;
a row switched off, open or gone is no part of it. The list says it in OpenRouter's words and the
caravan's; the entry refuses a request for other work; a pool's window counts its cells'.

Run: python3 scripts/test_model_kinds.py
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="caravan-model-kinds-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for _d in ("state", "config", "secrets", "logs"):
    (TMP / _d).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caravan.common.cloud_pools import CloudPools  # noqa: E402
from caravan.common.model_kinds import ModelKind  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SUB = {"id": "sub", "accountType": "openai-subscription"}
KEY = {"id": "or", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1"}
ACCOUNTS = {"sub": SUB, "or": KEY}
OUTPUTS = {
    "srv:22007": {"id": "srv:22007", "jobs": ["llm"], "inputs": ["text", "image", "audio"], "contextLength": 60160},
    "srv:22003": {"id": "srv:22003", "jobs": ["asr"], "languages": ["ru"], "maxAudioMs": 25000},
    "srv:22004": {"id": "srv:22004", "jobs": ["asr"], "languages": ["ru", "en"], "maxAudioMs": 30000},
    "srv:22005": {"id": "srv:22005", "jobs": ["asr"]},
    "srv:22008": {"id": "srv:22008", "jobs": ["speech-translate"], "languages": ["eng", "rus"]},
    "srv:22009": {"id": "srv:22009", "jobs": ["llm"], "inputs": ["text"], "contextLength": 8192},
    "srv:22010": {"id": "srv:22010"},
    "srv:22011": {"id": "srv:22011", "jobs": ["robot-policy"]},
    # The voice servers (1.3.553): PersonaPlex speaks a page and a WebSocket; Qwen3-Omni also answers a chat over vLLM's OpenAI API.
    "srv:22021": {"id": "srv:22021", "jobs": ["voice-chat"]},
    "srv:22023": {"id": "srv:22023", "jobs": ["llm", "voice-chat"], "inputs": ["text"]},
}


def acc(account, model="m", **extra):
    return {"id": f"{account}-{model}", "kind": "account", "accountId": account, "model": model, "enabled": True, **extra}


def cell(output, **extra):
    return {"id": output, "kind": "output", "output": output, "enabled": True, **extra}


def kind(*rows):
    return ModelKind.of_pool({"steps": list(rows)}, ACCOUNTS.get, OUTPUTS.get)


def section_cell_facts():
    print("выход ячейки несёт, что делает её модель — только то, что известно:")
    llama = {"slotConfig": {"MODEL_FILE": "gemma.gguf"}, "modalities": {"vision": True, "video": True, "audio": True},
             "ctxServed": 60160}
    check(ModelKind.cell_facts(llama) == {"jobs": ["llm"], "inputs": ["text", "image", "audio"], "contextLength": 60160},
          "ячейка llama.cpp — чат; картинки и звук — по её собственному /props; окно — то, что она отдаёт")
    check(ModelKind.cell_facts({"slotConfig": {"MODEL_FILE": "q.gguf"}, "modalities": None})["inputs"] == ["text"],
          "negative: llama.cpp не сказала о картинках — обещан только текст")
    check(ModelKind.cell_facts({"slotConfig": {"ENABLE_EMBEDDINGS": "1"}, "ctxServed": 32768})
          == {"jobs": ["embed"], "contextLength": 32768}, "ячейка эмбеддингов — эмбеддинги, без входов чата")
    ear = {"slotConfig": {}, "cellMeta": {"engine": "transcribe.cpp", "kinds": ["asr"], "langs": ["ru"], "maxAudioMs": 25000}}
    check(ModelKind.cell_facts(ear) == {"jobs": ["asr"], "languages": ["ru"], "maxAudioMs": 25000},
          "ухо другого контроллера — по своим словам: работа, языки, самая длинная запись")
    check(ModelKind.cell_facts({"slotConfig": {}, "cellMeta": {}, "ctxServed": None}) == {} and ModelKind.cell_facts(None) == {},
          "negative: ячейка без настроек и без слов — ни одного факта, а не «чат» по догадке")
    raw = {"jobs": ["asr", "nonsense", 7], "inputs": ["image", "smell"], "languages": ["ru", "", 5], "maxAudioMs": True,
           "contextLength": -1, "label": "x"}
    check(ModelKind.clean_facts(raw) == {"jobs": ["asr"], "inputs": ["image"], "languages": ["ru"]},
          "копия в файле очищена: неизвестные работы, входы, пустые языки и не-числа выброшены")


def section_pools():
    print("пул обещает то, что делает каждая его строка:")
    sub = kind(acc("sub", "gpt-sol"), acc("sub", "gpt-luna"))
    check((sub.jobs, sub.inputs, sub.mixed) == (("llm",), ("text", "image"), False),
          "подписка — чат, берёт картинки")
    check(kind(acc("sub"), acc("or")).inputs == ("text",),
          "подписка и другой провайдер — только текст: о картинках другого караван не знает")
    check(kind(acc("sub"), cell("srv:22007")).inputs == ("text", "image") and kind(cell("srv:22007")).inputs == ("text", "image", "audio"),
          "подписка и ячейка с картинками — картинки; одна ячейка — и звук в чате")
    ears = kind(cell("srv:22003"), cell("srv:22004"))
    check((ears.jobs, ears.languages, ears.max_audio_ms) == (("asr",), ["ru"], 25000),
          "два уха — общий язык, самая короткая запись")
    check(kind(cell("srv:22003"), cell("srv:22005")).languages is None,
          "negative: одно ухо о языках молчит — языки не обещаны: «не знаю» не равно «никаких»")
    mixed = kind(acc("sub"), cell("srv:22003"))
    check(mixed.mixed and mixed.models_entry() == {} and mixed.state() == {"mixed": True} and mixed.serves("/v1/chat/completions"),
          "чат и ухо в одном пуле — mixed: Маршрутизация говорит, список молчит, решают строки")
    check(kind(cell("srv:22003"), cell("srv:22010")) is None and kind(cell("srv:22003"), cell("srv:99999")).jobs == ("asr",),
          "строка, которая о себе молчит, — пул неизвестен; negative: строка к пропавшей ячейке — не в счёт")
    check(kind(cell("srv:22003"), cell("srv:22007", enabled=False), {"id": "open", "kind": "open", "enabled": True},
               acc("gone")).jobs == ("asr",),
          "negative: выключенная, открытая строка и строка пропавшего аккаунта — не в счёт")
    check(kind() is None and kind({"id": "o", "kind": "open"}) is None, "negative: служить некому — вида нет")


def section_said():
    print("что говорит список и что пропускает вход:")
    chat = kind(acc("sub"))
    check(chat.architecture() == {"modality": "text+image->text", "input_modalities": ["text", "image"], "output_modalities": ["text"]},
          "чат — словами OpenRouter")
    shapes = {name: kind(cell(out)).architecture()["modality"] for name, out in
              (("asr", "srv:22003"), ("speech-translate", "srv:22008"))}
    check(shapes == {"asr": "audio->text", "speech-translate": "audio->text"}, f"ухо и ухо-переводчик — audio->text (got {shapes})")
    tts = ModelKind(("tts",))
    embed = ModelKind(("embed",))
    check((tts.architecture()["modality"], embed.architecture()["modality"]) == ("text->audio", "text->embeddings"),
          "голос — text->audio, эмбеддинги — text->embeddings")
    check(ModelKind(("asr", "tts")).architecture() is None and ModelKind(("asr", "tts")).models_entry() == {"caravan": {"jobs": ["asr", "tts"]}},
          "negative: две работы сразу — architecture не сказать одной строкой; работы названы")
    check(kind(cell("srv:22003")).models_entry() == {
        "architecture": {"modality": "audio->text", "input_modalities": ["audio"], "output_modalities": ["text"]},
        "caravan": {"jobs": ["asr"], "languages": ["ru"], "max_audio_ms": 25000}},
          "ухо в /v1/models — architecture и caravan: работа, языки, самая длинная запись")
    ear, gemma = kind(cell("srv:22003")), kind(cell("srv:22007"))
    check([ear.serves(p) for p in ("/v1/audio/transcriptions", "/v1/audio/translations", "/v1/chat/completions")] == [True, True, False]
          and [gemma.serves(p) for p in ("/v1/chat/completions?x=1", "/v1/responses", "/v1/audio/transcriptions", "/v1/embeddings")]
          == [True, True, False, False],
          "ухо делает запись, а не чат; чат — чат и Responses, а не запись и не эмбеддинги")
    check(ModelKind(("translate",)).serves("/v1/audio/translations") is False,
          "negative: перевод текста NLLB — не путь входа, и не «/audio/translations» по совпадению хвоста")
    robot = kind(cell("srv:22011"))
    check(robot.models_entry() == {
        "architecture": {"modality": "image+text->actions", "input_modalities": ["image", "text"], "output_modalities": ["actions"]},
        "caravan": {"jobs": ["robot-policy"]}},
          "политика робота в /v1/models — кадры и инструкция на входе, действия на выходе (GR00T, 2026-10-13)")
    check([robot.serves(p) for p in ("/v1/robot/predict", "/v1/robot/predict?x=1", "/v1/chat/completions", "/v1/predict")]
          == [True, True, False, False]
          and gemma.serves("/v1/robot/predict") is False,
          "робот делает /v1/robot/predict; negative: чат роботу и робот чату — отказ входа, и не «/predict» по хвосту")
    check(kind(cell("srv:22011"), cell("srv:22007")).state() == {"mixed": True},
          "negative: робот и чат в одном пуле — у строк нет общей работы, пул «mixed», а не робот и не чат")


def section_voice():
    print("голосовые серверы (1.3.553): голос — своя работа, чат — только там, где сервер его отдаёт:")
    page = kind(cell("srv:22021"))
    check(page.models_entry() == {
        "architecture": {"modality": "audio+text->audio+text", "input_modalities": ["audio", "text"], "output_modalities": ["audio", "text"]},
        "caravan": {"jobs": ["voice-chat"]}},
          "PersonaPlex в /v1/models — речь и слова на входе, речь и слова на выходе, работа voice-chat")
    check([page.serves(p) for p in ("/v1/chat/completions", "/v1/audio/speech", "/v1/audio/transcriptions", "/v1/responses")] == [False] * 4,
          "negative: пул из PersonaPlex отказывает любому запросу, для которого у входа есть путь: у него страница и WebSocket")
    omni = kind(cell("srv:22023"))
    check(omni.jobs == ("llm", "voice-chat") and omni.serves("/v1/chat/completions") and not omni.serves("/v1/audio/speech"),
          "Qwen3-Omni — и чат, и голос: чат вход отдаёт, голос приходит в message.audio этого же ответа")
    check(omni.architecture() is None and omni.models_entry() == {"caravan": {"jobs": ["llm", "voice-chat"]}},
          "negative: две работы — architecture одной строкой не сказать, работы названы по порядку словаря")
    check(kind(cell("srv:22023"), cell("srv:22009")).jobs == ("llm",),
          "negative: Qwen3-Omni и обычный чат в одном пуле — обещан чат, голос нет: его делает не каждая строка")
    check(kind(cell("srv:22021"), cell("srv:22023")).jobs == ("voice-chat",) and kind(cell("srv:22021"), cell("srv:22007")).mixed,
          "PersonaPlex с Qwen3-Omni — общий голос; с обычным чатом — нет общей работы, пул mixed")
    check(ModelKind.clean_facts({"jobs": ["voice-chat", "llm", "voice"]}) == {"jobs": ["llm", "voice-chat"]},
          "копия в файле: слово из словаря остаётся, чужое («voice») выброшено, порядок — словаря")
    check(ModelKind.WORK["voice-chat"] == (("audio", "text"), ("audio", "text")) and ModelKind.PATHS["voice-chat"] == (),
          "работа в таблицах входа: что берёт и что отдаёт, и ни одного пути OpenAI")


def section_windows():
    print("окно пула считает окна его ячеек:")
    named = lambda account, model: {"gpt-sol": 272000}.get(model)  # noqa: E731
    local = lambda output: (OUTPUTS.get(output) or {}).get("contextLength")  # noqa: E731
    auto = {"contextAuto": True, "steps": [acc("sub", "gpt-sol"), cell("srv:22007")]}
    check(CloudPools.window(auto, named, local) == 60160, "подписка 272K и ячейка 60K — пул обещает 60K")
    check(CloudPools.window(auto, named) is None, "as-is без окон ячеек: пул с ячейкой окна не называет, как до 1.3.502")
    silent = {"contextAuto": True, "steps": [cell("srv:22007"), cell("srv:22003")]}
    check(CloudPools.window(silent, named, local) is None, "negative: одна ячейка окна не назвала — пул окна не обещает")
    stated = {"contextAuto": False, "contextLength": 50000, "steps": [cell("srv:22007")]}
    check(CloudPools.window(stated, named, local) == 50000, "переключатель выключен — число оператора, как раньше")


def section_controller():
    print("контроллер: выход ячейки несёт факты, пул на доске — свой вид:")
    from caravan.admin.proxies_config import _router_local_outputs, sync_router_outputs
    from caravan.admin.topology import annotate_pool_kinds
    servers = {"llamaServers": [
        {"port": 22003, "clientIp": "10.0.0.5", "model": "gigaam.gguf", "slotConfig": {},
         "cellMeta": {"kinds": ["asr"], "langs": ["ru"], "maxAudioMs": 25000}},
        {"port": 22007, "clientIp": "10.0.0.5", "model": "gemma.gguf", "slotConfig": {"MODEL_FILE": "gemma.gguf"},
         "modalities": {"vision": True, "audio": False}, "ctxServed": 60160}]}
    outs = {o["id"]: o for o in _router_local_outputs(servers)}
    check({k: outs["srv:22003"].get(k) for k in ("jobs", "languages", "maxAudioMs")} == {"jobs": ["asr"], "languages": ["ru"], "maxAudioMs": 25000}
          and {k: outs["srv:22007"].get(k) for k in ("jobs", "inputs", "contextLength")} == {"jobs": ["llm"], "inputs": ["text", "image"], "contextLength": 60160},
          "выходы ячеек несут работу, языки, запись, входы чата и окно")
    routers = [{"id": "router:default", "outputs": [], "rules": {}}]
    sync_router_outputs(routers, servers, [])
    kept = {o["id"]: o for o in routers[0]["outputs"]}
    check(kept["srv:22003"].get("languages") == ["ru"] and kept["srv:22007"].get("contextLength") == 60160,
          "роутер хранит их, пройдя свою проверку формы")
    check(not sync_router_outputs(routers, servers, []), "negative: ничего не изменилось — файл не пишется")
    pools = [{"id": "ears", "steps": [{"id": "r1", "kind": "output", "output": "srv:22003", "enabled": True}]},
             {"id": "mixed", "steps": [{"id": "a", "kind": "account", "accountId": "sub", "model": "m", "enabled": True},
                                       {"id": "r1", "kind": "output", "output": "srv:22003", "enabled": True}]},
             {"id": "quiet", "steps": [{"id": "r1", "kind": "output", "output": "srv:99", "enabled": True},
                                       {"id": "x", "kind": "output", "output": "srv:22099", "enabled": True}]}]
    annotate_pool_kinds(pools, [SUB], {**kept, "srv:22099": {"id": "srv:22099"}})
    check([p["kind"] for p in pools] == [{"jobs": ["asr"], "languages": ["ru"]}, {"mixed": True}, None],
          "пул на доске — с видом: ухо с языком, смешанный, неизвестный (строка молчит о себе)")


def section_about():
    print("ячейка без настроек называет языки и самую длинную запись (telemetry.remote_cell_about):")
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from caravan.admin import telemetry
    answers = {"/health": {"status": "ok", "engine": "transcribe.cpp", "model": "gigaam", "kinds": ["asr"], "langs": ["ru", " "],
                           "maxAudioMs": 25000, "targetLang": "rus", "secret": "x"}}

    class Cell(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(self.server.answer).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    def about(answer):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Cell)
        server.answer = answer
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return telemetry.remote_cell_about("127.0.0.1", server.server_address[1])
        finally:
            server.shutdown()
    check(about(answers["/health"]) == {"engine": "transcribe.cpp", "model": "gigaam", "kinds": ["asr"], "langs": ["ru"],
                                        "maxAudioMs": 25000, "targetLang": "rus"},
          "работа, языки (пустой выброшен), самая длинная запись и язык записи; negative: чужое поле не несётся")
    check(about({"status": "ok", "langs": "ru", "maxAudioMs": True, "targetLang": " "}) == {},
          "negative: языки не списком, запись не числом, пустой язык — ничего, а не догадка")


def main():
    for fn in (section_cell_facts, section_pools, section_said, section_voice, section_windows, section_controller, section_about):
        fn()
    if _fail:
        print(f"\nmodel kinds FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nmodel kinds OK: выход ячейки несёт её работу; пул обещает общее для строк; список говорит, вход держится")
    return 0


if __name__ == "__main__":
    sys.exit(main())
