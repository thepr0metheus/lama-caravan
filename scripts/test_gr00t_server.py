#!/usr/bin/env python3
"""cells/gr00t_server.py by value, without a GPU, torch, numpy or an image library.

The cell's own logic is pinned here: what /robot/schema says of the loaded robot, which requests
are refused and with what words, how the policy's answer is checked before a client sees it, and
that /openapi.json is the cell's route table, every route described. The runtime is a stand-in
policy; the HTTP server is the real one (cells/cell_base.py), on a free port.

The real runtime was run live on 2026-10-13 (RTX 5090, Isaac-GR00T d2b7e75): the DROID sample
gave actions 40x9, 40x1, 40x7 in 60 ms, and the refusals below read the same there.

Run: python3 scripts/test_gr00t_server.py
"""
import base64
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))
import gr00t_server as g  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# ── a stand-in runtime ───────────────────────────────────────────────────────

class Mod:
    def __init__(self, delta, keys, configs=None):
        self.delta_indices, self.modality_keys, self.action_configs = delta, keys, configs


class Enum:
    def __init__(self, value):
        self.value = value


class Cfg:
    def __init__(self, rep, kind, fmt, state_key):
        self.rep, self.type, self.format, self.state_key = Enum(rep), Enum(kind), Enum(fmt), state_key


TAG = "oxe_droid_relative_eef_relative_joint"
KEYS = ["eef_9d", "gripper_position", "joint_position"]
SIZES = {"eef_9d": 9, "gripper_position": 1, "joint_position": 7}
MODALITY = {
    "video": Mod([-15, 0], ["exterior_image_1_left", "wrist_image_left"]),
    "state": Mod([0], KEYS),
    "action": Mod(list(range(40)), KEYS, [Cfg("relative", "eef", "xyz+rot6d", "eef_9d"),
                                         Cfg("absolute", "non_eef", "default", "gripper_position"),
                                         Cfg("relative", "non_eef", "default", "joint_position")]),
    "language": Mod([0], ["annotation.language.language_instruction"]),
}
STATS = {group: {key: {"min": [0.0] * n, "max": [1.0] * n, "mean": [0.25] * n} for key, n in SIZES.items()}
         for group in ("state", "action")}


class PlainSchema(g.RobotSchema):
    """The schema with the runtime's arrays left out: the parsed request goes to the policy."""

    def to_arrays(self, parsed):
        return parsed


class FakePolicy:
    def __init__(self, answer="good"):
        self.answer = answer
        self.seen = []

    def get_action(self, obs):
        self.seen.append(obs)
        if self.answer == "nan":
            return {k: [[[float("nan")] * SIZES[k]] * 40] for k in KEYS}, {}
        if self.answer == "short":
            return {k: [[[0.5] * SIZES[k]] * 39] for k in KEYS}, {}
        return {k: [[[round(0.1 * (i + 1), 3)] * SIZES[k] for i in range(40)]] for k in KEYS}, {}


def png(width=320, height=180):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
            + b"\x08\x02\x00\x00\x00" + b"\x00" * 4)


def jpeg(width=320, height=180):
    return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xc4\x00\x04\x00\x00\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9)


def frame(raw):
    return {"mime_type": "image/png", "data_base64": base64.b64encode(raw).decode()}


def request(**over):
    body = {"model": "gr00t", "robot_schema": "gr00t:" + TAG, "session_id": "s1", "sequence_id": 7,
            "observation_time_unix_ms": 1234, "dry_run": True, "task": "Put the blue block in the green bowl",
            "state": {k: [0.5] * n for k, n in SIZES.items()},
            "images": {"exterior_image_1_left": {"frames": [frame(png()), frame(png())]},
                       "wrist_image_left": {"frames": [frame(jpeg()), frame(jpeg())]}}}
    body.update(over)
    return body


# ── the schema, by value ─────────────────────────────────────────────────────

def section_schema():
    print("схема робота:")
    s = PlainSchema(TAG, MODALITY, STATS, g.CONTROL_HZ.get(TAG))
    d = s.describe()
    cams = d["observation"]["images"]
    check(d["robot_schema"] == "gr00t:" + TAG and [c["name"] for c in cams] == MODALITY["video"].modality_keys
          and cams[0]["frames"] == 2 and cams[0]["frame_offsets_steps"] == [-15, 0]
          and cams[0]["frame_offsets_s"] == [-1.0, 0.0],
          f"камеры, 2 кадра на 15 шагов и на 1.0 с раньше: частота DROID 15 Гц делится, а не умножается "
          f"на округлённый шаг (было −1.000005 с) (получено {cams[0]})")
    check([(x["name"], x["size"]) for x in d["observation"]["state"]] == [(k, SIZES[k]) for k in KEYS],
          "состояние: ключи и размеры из статистик чекпойнта (9, 1, 7)")
    a = d["action"]
    check(a["horizon"] == 40 and a["step_s"] == round(1 / 15, 6) and a["normalized"] is False
          and [(c["name"], c["size"], c["representation"], c["format"]) for c in a["components"]]
          == [("eef_9d", 9, "relative", "xyz+rot6d"), ("gripper_position", 1, "absolute", "default"),
              ("joint_position", 7, "relative", "default")],
          f"действия: 40 шагов по 1/15 с, представление каждой части как у среды выполнения (получено {a})")
    other = PlainSchema("xdof_relative_eef_relative_joint", MODALITY, STATS, g.CONTROL_HZ.get("xdof"))
    check(other.step_s() is None and other.describe()["observation"]["images"][0]["frame_offsets_s"] is None,
          "negative: у воплощения без записанной частоты шаг — null, а не догадка")
    typical = s.typical_state()
    check(typical["eef_9d"][:3] == [0.25] * 3 and typical["eef_9d"][3:] == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
          and typical["joint_position"] == [0.25] * 7,
          "defect-history: прогрев берёт средние из статистик, а поворот 6D — единичный; с нулями шаг "
          "«относительное → абсолютное» падал «SVD did not converge» (2026-10-13)")
    try:
        g.RobotSchema(TAG, MODALITY, {"state": {}, "action": {}})
        said = ""
    except ValueError as exc:
        said = str(exc)
    check("no size" in said, f"negative: статистик для ключа нет — отказ по имени, а не размер наугад ({said})")


def section_folders():
    print("папки весов:")
    names = [g.Gr00tOptions.folder_repo(p) for p in (
        "GR00T-N1.7-3B/nvidia/BF16", "/home/u/llama-model-cache/GR00T-N1.7-3B/nvidia/BF16/",
        "/srv/models/my-checkpoint", "nvidia/BF16", "GR00T-N1.7-3B/nvidia/checkpoint-2000")]
    check(names == ["nvidia/GR00T-N1.7-3B", "nvidia/GR00T-N1.7-3B", "", "", ""],
          f"репозиторий HF — из раскладки библиотеки <модель>/<автор>/<формат>; negative: папка иначе — пусто, "
          f"а не имя наугад (получено {names})")
    check([g.Gr00tOptions.folder_name(p) for p in ("GR00T-N1.7-3B/nvidia/BF16", "/srv/models/my-checkpoint")]
          == ["GR00T-N1.7-3B", "my-checkpoint"], "имя модели — из папки")


def refusal(schema, body):
    try:
        schema.parse(body)
        return None
    except g.Refusal as r:
        return r.status, r.code, r.message


def section_requests():
    print("запросы:")
    s = PlainSchema(TAG, MODALITY, STATS, 15)
    parsed = s.parse(request())
    check(parsed["task"] == "Put the blue block in the green bowl" and parsed["state"]["gripper_position"] == [0.5]
          and [len(v) for v in parsed["frames"].values()] == [2, 2],
          "верный запрос разобран: инструкция, состояние, по 2 кадра (PNG и JPEG)")
    bad_images = {"exterior_image_1_left": {"frames": [frame(png()), frame(png(640, 360))]},
                  "wrist_image_left": {"frames": [frame(jpeg()), frame(jpeg())]}}
    cases = [
        ("другой робот", request(robot_schema="spider-monkey-openarm-rail-v1"),
         (422, "unsupported_robot_schema", "not spider-monkey-openarm-rail-v1")),
        ("робот не назван", request(robot_schema=""), (422, "unsupported_robot_schema", "names none")),
        ("инструкция не текст", request(task=5), (422, "invalid_task", "task must be a string")),
        ("состояние короче", request(state={**request()["state"], "joint_position": [0.5] * 6}),
         (422, "invalid_state", "state.joint_position must be 7 finite numbers")),
        ("состояние не число", request(state={**request()["state"], "eef_9d": [0.5] * 8 + [float("nan")]}),
         (422, "invalid_state", "state.eef_9d must be 9 finite numbers")),
        ("лишний ключ состояния", request(state={**request()["state"], "rail_position_m": [0.1]}),
         (422, "invalid_state", "rail_position_m")),
        ("чужая камера", request(images={**request()["images"], "scene_cam": {"frames": []}}),
         (422, "invalid_images", "scene_cam")),
        ("один кадр вместо двух", request(images={**request()["images"],
                                                    "wrist_image_left": {"frames": [frame(jpeg())]}}),
         (422, "invalid_images", "needs 2 frame(s) under 'frames', oldest first, at -1.000 s, +0.000 s")),
        ("кадр не картинка", request(images={**request()["images"],
                                               "wrist_image_left": {"frames": [frame(b"hello"), frame(jpeg())]}}),
         (422, "invalid_images", "is not a PNG or JPEG")),
        ("кадр не base64", request(images={**request()["images"],
                                             "wrist_image_left": {"frames": [{"data_base64": "*"}, frame(jpeg())]}}),
         (422, "invalid_images", "is not base64")),
        ("кадры разного размера", request(images=bad_images), (422, "invalid_images", "320x180 and 640x360")),
        ("тело не объект", [1, 2], (400, "invalid_request", "JSON object")),
    ]
    for name, body, (status, code, words) in cases:
        got = refusal(s, body)
        check(got is not None and got[0] == status and got[1] == code and words in got[2],
              f"{name}: {status} {code} — «{words}» (получено {got})")


def section_answer():
    print("ответ политики:")
    s = PlainSchema(TAG, MODALITY, STATS, 15)
    good, _ = FakePolicy().get_action({})
    out = s.actions(good)
    check({k: (len(v), len(v[0])) for k, v in out.items()} == {k: (40, n) for k, n in SIZES.items()}
          and out["eef_9d"][0][0] == 0.1,
          "пачка одной партии снята: 40 строк на каждую часть, числа как есть")
    for kind, words in (("nan", "not finite"), ("short", "another shape")):
        bad, _ = FakePolicy(kind).get_action({})
        try:
            s.actions(bad)
            said = ""
        except RuntimeError as exc:
            said = str(exc)
        check(words in said, f"negative: {kind} — ошибка, а не нули или обрезанная пачка ({said})")


# ── the cell over HTTP ───────────────────────────────────────────────────────

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(port, path, body=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


class TestCell(g.Gr00tCell):
    gate = None

    def make_policy(self):
        if self.gate is not None:
            self.gate.wait(10)
        self.fake = FakePolicy()
        return self.fake, PlainSchema(TAG, MODALITY, STATS, g.CONTROL_HZ.get(TAG))

    def _warm_up(self):
        with self._lock:
            self.policy.get_action(self.schema.parse({**request(), "state": self.schema.typical_state()}))


def folders():
    base = Path(tempfile.mkdtemp(prefix="gr00t-test-"))
    ckpt, backbone = base / "GR00T-N1.7-3B" / "nvidia" / "BF16", base / "Cosmos-Reason2-2B" / "nvidia" / "BF16"
    for d in (ckpt / "experiment_cfg", backbone):
        d.mkdir(parents=True)
    (ckpt / "config.json").write_text(json.dumps({"model_name": "nvidia/Cosmos-Reason2-2B"}))
    (ckpt / "experiment_cfg" / "dataset_statistics.json").write_text(json.dumps({TAG: STATS}))
    (backbone / "config.json").write_text("{}")
    return base, ckpt, backbone


def start(cell):
    threading.Thread(target=cell.serve, daemon=True).start()
    for _ in range(200):
        try:
            code, body = call(cell.port, "/health")
            if body and body.get("status") in ("ok", "error", "loading"):
                return code, body
        except OSError:
            pass
        time.sleep(0.02)
    return None, None


def section_http():
    print("ячейка по HTTP:")
    keep = os.getcwd()
    base, ckpt, backbone = folders()
    os.environ["CARAVAN_CELL_SCRATCH"] = str(base / "scratch")
    try:
        gate = threading.Event()
        cell = TestCell([str(free_port()), str(ckpt), "--backbone", str(backbone)])
        cell.gate = gate
        code, health = start(cell)
        check(code == 503 and health.get("status") == "loading", f"пока модель грузится, /health — 503 loading ({code} {health})")
        code, body = call(cell.port, "/v1/robot/predict", request())
        check(code == 503 and body["error"]["code"] == "loading",
              f"запрос до готовности — 503 тем же видом ошибки {{code, message}}, что и 422 ({code} {body})")
        gate.set()
        for _ in range(200):
            code, health = call(cell.port, "/health")
            if health.get("status") != "loading":
                break
            time.sleep(0.02)
        check(code == 200 and health["status"] == "ok" and health["kinds"] == ["robot-policy", "robot-policy.gr00t"]
              and health["model"] == "GR00T-N1.7-3B" and health["engine"] == "isaac-gr00t",
              f"готова: вид работы robot-policy, имя модели из папки <модель>/<автор>/<формат> ({health})")
        link = base / "scratch" / "nvidia" / "Cosmos-Reason2-2B"
        check(link.is_symlink() and os.path.realpath(link) == os.path.realpath(backbone),
              "основа по имени из config.json чекпойнта — ссылка на её папку в рабочей папке ячейки: хаб не нужен")
        check(len(cell.fake.seen) == 1 and cell.fake.seen[0]["state"]["eef_9d"][3:] == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
              "до «ok» один прогон на правдоподобном состоянии")
        code, body = call(cell.port, "/v1/robot/predict", request())
        check(code == 200 and body["object"] == "robot.actions" and body["session_id"] == "s1" and body["sequence_id"] == 7
              and body["dry_run"] is True and body["robot_schema"] == "gr00t:" + TAG
              and {k: len(v) for k, v in body["actions"].items()} == {k: 40 for k in KEYS}
              and body["adaptation_status"]["spider-monkey-openarm-rail-v1"].startswith("not adapted")
              and body["action_schema"]["horizon"] == 40 and "inference" in body["timing_ms"],
              f"ответ: действия на 40 шагов, номера наблюдения, схема и статус адаптации (получено {sorted(body)})")
        code, body = call(cell.port, "/v1/robot/predict", request(robot_schema="spider-monkey-openarm-rail-v1"))
        check(code == 422 and body["error"]["code"] == "unsupported_robot_schema",
              f"негатив: чужой робот — 422 по HTTP ({code})")
        cell.fake.answer = "nan"
        code, body = call(cell.port, "/v1/robot/predict", request())
        cell.fake.answer = "good"
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        check(code == 500 and error.get("code") == "policy_failed" and "not finite" in error.get("message", "")
              and "actions" not in body,
              f"негатив: политика ответила не числом — 500 policy_failed тем же видом {{code, message}}, "
              f"действий нет ({code} {body})")
        code, body = call(cell.port, "/v1/robot/predict", raw=b"{not json")
        check(code == 400 and body["error"]["code"] == "invalid_json", f"не JSON — 400 ({code} {body})")
        code, body = call(cell.port, "/v1/other", {"x": 1})
        check(code == 404, f"POST на чужой путь — 404 ({code})")
        code, body = call(cell.port, "/nothing")
        check(code == 404, f"GET на чужой путь — 404, а не ответ здоровья ({code})")
        code, schema = call(cell.port, "/robot/schema")
        check(code == 200 and schema["robot_schema"] == "gr00t:" + TAG, f"/robot/schema ({code})")
        code, status = call(cell.port, "/robot/status")
        check(code == 200 and status["status"] == "ok" and status["weights"] == {
            "checkpoint": "GR00T-N1.7-3B", "checkpoint_repo": "nvidia/GR00T-N1.7-3B",
            "backbone": "Cosmos-Reason2-2B", "backbone_repo": "nvidia/Cosmos-Reason2-2B", "revision": None},
              f"/robot/status: веса по папкам и их репозитории HF — чекпойнт по раскладке библиотеки, основа по "
              f"config.json; ревизии папка не хранит — null, а не догадка ({status.get('weights')})")
        code, spec = call(cell.port, "/openapi.json")
        ops = [(m.upper(), p) for p, item in spec["paths"].items() for m in item]
        check(code == 200 and spec["openapi"] == "3.1.0" and sorted(ops) == sorted((m, p) for m, p, _ in g.Gr00tCell.ROUTES)
              and all(item[m]["summary"] for p, item in spec["paths"].items() for m in item),
              f"/openapi.json — та же таблица маршрутов, у каждого есть summary (получено {sorted(ops)})")
    finally:
        os.chdir(keep)


def section_refuses_without_runtime():
    print("без среды выполнения:")
    base, ckpt, backbone = folders()
    keep = os.getcwd()
    try:
        cell = g.Gr00tCell([str(free_port()), str(ckpt), "--backbone", str(backbone)])
        code, health = start(cell)
        for _ in range(200):
            code, health = call(cell.port, "/health")
            if health.get("status") != "loading":
                break
            time.sleep(0.02)
        check(code == 500 and health["status"] == "error" and "gr00t" in health.get("error", "").lower(),
              f"нет Isaac-GR00T — /health 500 с причиной, а не «ok» ({code} {health.get('error')})")
        missing = g.Gr00tCell([str(free_port()), "/nowhere", "--backbone", str(backbone)])
        code, health = start(missing)
        for _ in range(200):
            code, health = call(missing.port, "/health")
            if health.get("status") != "loading":
                break
            time.sleep(0.02)
        check(code == 500 and "no config.json" in health.get("error", ""),
              f"нет папки чекпойнта — отказ называет её ({health.get('error')})")
    finally:
        os.chdir(keep)


def main():
    section_schema()
    section_folders()
    section_requests()
    section_answer()
    section_http()
    section_refuses_without_runtime()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("gr00t server OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
