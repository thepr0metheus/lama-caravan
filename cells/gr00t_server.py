#!/usr/bin/env python3
"""GR00T N1.7 cell: camera frames, the robot's state and an instruction in, robot actions out.

WHY THIS EXISTS. The SpiderMonkey task (visumap spider-monkey-model-servers) asks the caravan
for a robot policy beside its vision model. NVIDIA serves GR00T with Isaac-GR00T's own policy
server: ZMQ and msgpack, for Python clients of its own (gr00t/eval/run_gr00t_server.py). The
fleet's cells speak HTTP, the caravan's entry picks a pool by `model`, and a client written in
another language has neither ZMQ nor msgpack-numpy. So this cell runs the same policy class in
process (gr00t.policy.gr00t_policy.Gr00tPolicy) and answers HTTP: the adapter of numeric
actions the task asks for (visumap spider-monkey-model-api; its paths are chosen here).

WHAT IT IS NOT. A controller for any robot. A checkpoint acts for the embodiments it was trained
on, and the cell serves ONE, named at start (--embodiment). A request for another robot schema
is refused with 422: answering it with actions would be a guess that moves a robot. Adapting
the model to another robot (SpiderMonkey's OpenArm with a gripper and a rail) is fine-tuning,
not a setting.

    GET  /health            the cell contract (cells/cell_base.py)
    GET  /openapi.json      this API, built from ROUTES
    GET  /robot/schema      what a request carries and an answer gives, for the loaded embodiment
    GET  /robot/status      the model: loaded or not, its weights, runtime and adaptation status
    POST /v1/robot/predict  one observation -> a chunk of actions

The backbone the checkpoint names in its config.json (nvidia/Cosmos-Reason2-2B, a gated
repository) is loaded from the folder given by --backbone, never from the hub: the cell runs
offline and holds no token. transformers reads a model name as a local folder when one exists
under that name relative to the working directory, so the cell links the folder there, in a
working folder of its own, and works from it.

Usage: gr00t_server.py <port> <checkpoint dir> --backbone <dir> [--embodiment TAG]
                       [--denoising-steps N] [--name NAME]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer  # noqa: E402

#: The layout the caravan's downloads keep: <model>/<author>/<FORMAT>. The last segment is the
#: precision, and naming a cell "BF16" says nothing about which model runs (seamless_server.py).
_FORMAT_SEGMENTS = {"FP32", "FP16", "BF16", "INT8", "INT4", "FP8", "ST"}

#: Control rates the runtime does not record. The checkpoint keeps no rate, and an answer's time
#: step is worth nothing guessed: a client would play a chunk at the wrong speed. Only what was
#: read from the embodiment's own data is here: DROID's sample in Isaac-GR00T's demo_data says
#: fps 15 (meta/info.json). Any other embodiment answers its step as unknown (null).
CONTROL_HZ = {"oxe_droid_relative_eef_relative_joint": 15}


class Refusal(Exception):
    """A request this cell will not answer with actions, and why: status, code, message."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self):
        return {"error": {"code": self.code, "message": self.message}}


class Gr00tOptions:
    """The cell's argv after the port: the checkpoint folder and how to run it."""

    def __init__(self, args):
        ap = argparse.ArgumentParser(prog="gr00t_server.py", add_help=False)
        ap.add_argument("checkpoint")
        ap.add_argument("--backbone", default="")
        ap.add_argument("--embodiment", default="OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT")
        ap.add_argument("--denoising-steps", type=int, default=0)
        ap.add_argument("--name", default="")
        parsed, _unknown = ap.parse_known_args(list(args or []) or [""])
        self.checkpoint = parsed.checkpoint
        self.backbone = parsed.backbone
        self.embodiment = parsed.embodiment
        self.denoising_steps = parsed.denoising_steps
        self.name = parsed.name

    @staticmethod
    def folder_name(directory):
        """A model's name from its folder: <model>/<author>/<FORMAT> gives <model>."""
        parts = [p for p in str(directory or "").rstrip("/").split("/") if p]
        if parts and parts[-1].upper() in _FORMAT_SEGMENTS:
            parts = parts[:-2] if len(parts) >= 3 else parts[:-1]
        return parts[-1] if parts else ""

    @staticmethod
    def folder_repo(directory):
        """The Hugging Face repository a library folder came from: <model>/<author>/<FORMAT> is how
        the caravan lays out a download of <author>/<model>. "" for a folder laid out otherwise —
        its origin is not written anywhere the cell can read."""
        parts = [p for p in str(directory or "").rstrip("/").split("/") if p]
        if len(parts) >= 3 and parts[-1].upper() in _FORMAT_SEGMENTS:
            return f"{parts[-2]}/{parts[-3]}"
        return ""


class RobotSchema:
    """What the loaded embodiment takes and gives, and the one place a request is held to it.

    Built from the policy's modality config (keys, which frames, how each action is represented)
    and the checkpoint's statistics (how many numbers each state and action key has). A request
    is turned into the observation Gr00tPolicy takes, or refused by name: a missing camera, a
    state of another length, a frame that is not an image. The runtime's own checks would refuse
    most of these too, but with an assertion from deep inside numpy that a client cannot act on.
    """

    def __init__(self, tag, modality, stats, control_hz=None):
        self.tag = str(tag)
        self.id = f"gr00t:{self.tag}"
        video, state, action, language = (modality[k] for k in ("video", "state", "action", "language"))
        self.cameras = list(video.modality_keys)
        self.frame_offsets = [int(i) for i in video.delta_indices]
        self.state_keys = list(state.modality_keys)
        self.action_keys = list(action.modality_keys)
        self.horizon = len(action.delta_indices)
        self.language_key = list(language.modality_keys)[0]
        self.stats = stats
        self.sizes = self.sizes_of(stats)
        self.control_hz = control_hz
        configs = list(action.action_configs or [])
        self.action_reps = {}
        for key, cfg in zip(self.action_keys, configs):
            self.action_reps[key] = {
                "representation": _value(getattr(cfg, "rep", "")),
                "type": _value(getattr(cfg, "type", "")),
                "format": _value(getattr(cfg, "format", "")),
                "state_key": getattr(cfg, "state_key", None) or key,
            }
        missing = [k for k in self.state_keys + self.action_keys if not self.sizes.get(k)]
        if missing:
            raise ValueError(f"the checkpoint's statistics give no size for {missing} ({self.tag})")

    @staticmethod
    def statistics(checkpoint, tag):
        """The embodiment's statistics in the checkpoint (experiment_cfg/dataset_statistics.json):
        the numbers the runtime denormalizes with, and the only record of each key's size."""
        path = os.path.join(checkpoint, "experiment_cfg", "dataset_statistics.json")
        with open(path, encoding="utf-8") as fh:
            stats = json.load(fh).get(tag)
        if not isinstance(stats, dict):
            raise ValueError(f"the checkpoint has no statistics for the embodiment {tag}")
        return stats

    @staticmethod
    def sizes_of(stats):
        """{key: size} of the embodiment's state and action keys."""
        sizes = {}
        for group in ("state", "action"):
            for key, row in (stats.get(group) or {}).items():
                if isinstance(row, dict) and isinstance(row.get("min"), list):
                    sizes[key] = len(row["min"])
        return sizes

    def typical_state(self):
        """A state the runtime can turn into actions: each key's mean from the statistics, a
        rotation in 6D the identity. Zeros are not one: a 6D rotation of zeros is no rotation,
        and the relative-to-absolute step failed on it (SVD did not converge, 2026-10-13)."""
        rot6d = {cfg["state_key"] for cfg in self.action_reps.values() if cfg.get("format") == "xyz+rot6d"}
        state = {}
        for key in self.state_keys:
            mean = (self.stats.get("state") or {}).get(key, {}).get("mean")
            row = [float(v) for v in mean] if isinstance(mean, list) and len(mean) == self.sizes[key] else [0.0] * self.sizes[key]
            if key in rot6d and len(row) >= 6:
                row[-6:] = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
            state[key] = row
        return state

    def step_s(self):
        return round(1.0 / self.control_hz, 6) if self.control_hz else None

    def describe(self):
        """/robot/schema: the request's parts and the answer's, in the loaded embodiment's words."""
        step = self.step_s()
        return {
            "robot_schema": self.id,
            "embodiment": self.tag,
            "observation": {
                "task": "the instruction, as text (the runtime's key " + self.language_key + ")",
                "images": [{"name": cam, "frames": len(self.frame_offsets),
                            "frame_offsets_steps": self.frame_offsets,
                            "frame_offsets_s": [round(o / self.control_hz, 6) for o in self.frame_offsets]
                            if self.control_hz else None,
                            "encoding": "RGB, image/jpeg or image/png, base64; oldest frame first"}
                           for cam in self.cameras],
                "state": [{"name": key, "size": self.sizes[key]} for key in self.state_keys],
            },
            "action": self.action_schema(),
        }

    def action_schema(self):
        return {
            "horizon": self.horizon,
            "step_s": self.step_s(),
            "components": [{"name": key, "size": self.sizes[key], **self.action_reps.get(key, {})}
                           for key in self.action_keys],
            "values": ("absolute targets in the physical units of the embodiment's dataset: the runtime "
                       "denormalizes the model's output with the checkpoint's statistics "
                       "(experiment_cfg/dataset_statistics.json, " + self.tag + ") and adds the "
                       "components predicted relative to the request's state to that state"),
            "normalized": False,
            "rotation_6d": "the first two rows of the rotation matrix, flattened (Isaac-GR00T pose.py)",
        }

    def observation(self, body):
        """The request as Gr00tPolicy's observation, or a Refusal naming what is wrong."""
        return self.to_arrays(self.parse(body))

    def parse(self, body):
        """The request checked against this robot, before any library is touched: the schema it
        names, the instruction, each state key's numbers, each camera's frames — their count and
        that each is a PNG or JPEG of one size. A Refusal says which part is wrong."""
        if not isinstance(body, dict):
            raise Refusal(400, "invalid_request", "the body must be a JSON object")
        asked = str(body.get("robot_schema") or "").strip()
        if asked != self.id:
            raise Refusal(422, "unsupported_robot_schema",
                          (f"this cell serves robot_schema {self.id}" + (f", not {asked}" if asked else
                           "; the request names none")) + ". A checkpoint acts for the robot it was "
                          "trained on; another robot needs its own adaptation (fine-tuning) first.")
        task = body.get("task", "")
        if not isinstance(task, str):
            raise Refusal(422, "invalid_task", "task must be a string")
        state_in = body.get("state")
        if not isinstance(state_in, dict):
            raise Refusal(422, "invalid_state", f"state must be an object with {self.state_keys}")
        unknown = sorted(set(state_in) - set(self.state_keys))
        if unknown:
            raise Refusal(422, "invalid_state", f"state has keys this robot does not: {unknown}")
        state = {}
        for key in self.state_keys:
            row = state_in.get(key)
            row = [row] if isinstance(row, (int, float)) and not isinstance(row, bool) else row
            if not isinstance(row, list) or len(row) != self.sizes[key] or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in row):
                raise Refusal(422, "invalid_state", f"state.{key} must be {self.sizes[key]} finite numbers")
            state[key] = [float(v) for v in row]
        images_in = body.get("images")
        if not isinstance(images_in, dict):
            raise Refusal(422, "invalid_images", f"images must be an object with {self.cameras}")
        unknown = sorted(set(images_in) - set(self.cameras))
        if unknown:
            raise Refusal(422, "invalid_images", f"images has cameras this robot does not: {unknown}")
        frames = {cam: self._frames(cam, images_in.get(cam)) for cam in self.cameras}
        return {"task": task, "state": state, "frames": frames}

    def _frames(self, cam, given):
        want = len(self.frame_offsets)
        if isinstance(given, dict) and "frames" in given:
            given = given["frames"]
        elif isinstance(given, dict) and want == 1:
            given = [given]
        if not isinstance(given, list) or len(given) != want:
            when = (", ".join(f"{o / self.control_hz:+.3f} s" for o in self.frame_offsets) if self.control_hz
                    else ", ".join(f"{o:+d} steps" for o in self.frame_offsets))
            raise Refusal(422, "invalid_images",
                          f"images.{cam} needs {want} frame(s) under 'frames', oldest first, at {when}")
        out, size = [], None
        for index, frame in enumerate(given):
            data = frame.get("data_base64") if isinstance(frame, dict) else None
            try:
                raw = base64.b64decode(str(data or ""), validate=True)
            except ValueError as exc:
                raise Refusal(422, "invalid_images", f"images.{cam} frame {index} is not base64: {exc}") from exc
            found = ImageHeader.size(raw)
            if found is None:
                raise Refusal(422, "invalid_images", f"images.{cam} frame {index} is not a PNG or JPEG")
            if size is not None and found != size:
                raise Refusal(422, "invalid_images",
                              f"images.{cam}: the frames differ in size ({size[0]}x{size[1]} and {found[0]}x{found[1]})")
            size = found
            out.append(raw)
        return out

    def to_arrays(self, parsed):
        """A parsed request as the runtime's arrays: (1, T, H, W, 3) uint8 frames, (1, 1, D)
        float32 states, the instruction as [[text]]. A frame whose header passed but whose
        pixels do not decode is still the client's to fix: 422."""
        import numpy as np
        from PIL import Image

        video = {}
        for cam, raws in parsed["frames"].items():
            images = []
            for index, raw in enumerate(raws):
                try:
                    images.append(np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8))
                except Exception as exc:  # noqa: BLE001 - a broken image is the client's to fix
                    raise Refusal(422, "invalid_images", f"images.{cam} frame {index} does not decode: {exc}") from exc
            video[cam] = np.stack(images)[None]
        state = {key: np.asarray(row, dtype=np.float32).reshape(1, 1, -1) for key, row in parsed["state"].items()}
        return {"video": video, "state": state, "language": {self.language_key: [[parsed["task"]]]}}

    def actions(self, action):
        """The policy's answer as lists, checked: a value that is not finite is an error, never
        an action, and a component of the wrong shape is the runtime's fault, said as such."""
        out = {}
        for key in self.action_keys:
            value = action.get(key) if isinstance(action, dict) else None
            rows = value.tolist() if hasattr(value, "tolist") else value
            if (isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list)
                    and rows[0] and isinstance(rows[0][0], list)):
                rows = rows[0]                      # a batch of one
            if not (isinstance(rows, list) and len(rows) == self.horizon and all(
                    isinstance(r, list) and len(r) == self.sizes[key] for r in rows)):
                raise RuntimeError(f"the policy answered {key} of another shape than "
                                   f"({self.horizon}, {self.sizes[key]})")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for r in rows for v in r):
                raise RuntimeError(f"the policy answered {key} with values that are not finite")
            out[key] = [[round(float(v), 6) for v in r] for r in rows]
        return out


class ImageHeader:
    """The size of a PNG or JPEG from its header, read without an image library: frames are
    checked before anything is decoded, and the cell's checks run where no image library is."""

    PNG = b"\x89PNG\r\n\x1a\n"
    #: JPEG start-of-frame markers that carry the size (baseline, progressive and the rest),
    #: not DHT (C4), JPG (C8) or DAC (CC), which share the range.
    SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

    @classmethod
    def size(cls, raw):
        """(width, height), or None when the bytes are neither."""
        if raw[:8] == cls.PNG and len(raw) >= 24 and raw[12:16] == b"IHDR":
            return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
        if raw[:2] != b"\xff\xd8":
            return None
        at = 2
        while at + 4 <= len(raw):
            if raw[at] != 0xFF:
                return None
            marker = raw[at + 1]
            if marker == 0xFF:
                at += 1
                continue
            length = int.from_bytes(raw[at + 2:at + 4], "big")
            if marker in cls.SOF and at + 9 <= len(raw):
                return int.from_bytes(raw[at + 7:at + 9], "big"), int.from_bytes(raw[at + 5:at + 7], "big")
            at += 2 + length
        return None


def _value(item):
    """An enum's value, or the thing itself."""
    return getattr(item, "value", item)


class Gr00tCell(CellServer):
    """GR00T N1.7 behind HTTP: one embodiment, one policy, one request at a time on the card."""

    default_port = 8040
    engine = "isaac-gr00t"
    kinds = ["robot-policy", "robot-policy.gr00t"]
    work_path = "/v1/robot/predict"
    health_paths = ("/health",)
    protocol_version = "HTTP/1.1"

    #: Method, path, handler name. /openapi.json is built from this table and the handlers'
    #: docstrings; test_gr00t_server.py holds the table, the description and the code together.
    ROUTES = (
        ("GET", "/health", "route_health"),
        ("GET", "/openapi.json", "route_openapi"),
        ("GET", "/robot/schema", "route_schema"),
        ("GET", "/robot/status", "route_status"),
        ("POST", "/v1/robot/predict", "route_predict"),
    )

    def __init__(self, argv=None):
        super().__init__(argv)
        self.options = Gr00tOptions(self.args)
        self.schema = None
        self.policy = None
        self.versions = {}
        self.workdir = ""
        self.backbone_repo = ""
        self._lock = threading.Lock()

    # ── what this cell says of itself ────────────────────────────────────────
    @property
    def model_name(self):
        return self.options.name or Gr00tOptions.folder_name(self.options.checkpoint) or "gr00t"

    def weights(self):
        """The weights behind the cell: each folder's name and the Hugging Face repository it holds
        — the checkpoint's by the library's layout, the backbone's as the checkpoint's config.json
        names it. The revision is null: a library folder keeps no record of it, and a guessed one
        would claim a check nobody made (the revisions downloaded are in the deployment record)."""
        return {"checkpoint": Gr00tOptions.folder_name(self.options.checkpoint) or None,
                "checkpoint_repo": Gr00tOptions.folder_repo(self.options.checkpoint) or None,
                "backbone": Gr00tOptions.folder_name(self.options.backbone) or None,
                "backbone_repo": self.backbone_repo or None,
                "revision": None}

    def extra_health(self):
        return {"device": self.versions.get("device", "")}

    # ── loading ──────────────────────────────────────────────────────────────
    def load(self):
        opts = self.options
        for what, folder in (("checkpoint", opts.checkpoint), ("backbone", opts.backbone)):
            if not folder or not os.path.isfile(os.path.join(folder, "config.json")):
                raise FileNotFoundError(f"the {what} folder has no config.json: {folder or '(none given)'}")
        with open(os.path.join(opts.checkpoint, "config.json"), encoding="utf-8") as fh:
            backbone_name = str(json.load(fh).get("model_name") or "")
        if "/" not in backbone_name:
            raise ValueError(f"the checkpoint names no backbone repository (model_name {backbone_name!r})")
        self.backbone_repo = backbone_name
        self.workdir = self._link_backbone(backbone_name, opts.backbone)
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        self.policy, self.schema = self.make_policy()
        self.versions = self._versions()
        self._warm_up()

    def _link_backbone(self, name, folder):
        """A working folder where `name` (owner/repo) is a link to the backbone's folder."""
        base = os.environ.get("CARAVAN_CELL_SCRATCH") or tempfile.mkdtemp(prefix="gr00t-cell-")
        os.makedirs(base, exist_ok=True)
        link = os.path.join(base, *name.split("/"))
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(os.path.abspath(folder), link)
        os.chdir(base)
        return base

    def make_policy(self):
        """The runtime's policy and the schema of its embodiment. The only place the runtime is
        imported: a machine without it fails here, and /health says so."""
        from gr00t.data.embodiment_tags import EmbodimentTag
        from gr00t.policy.gr00t_policy import Gr00tPolicy

        tag = EmbodimentTag.resolve(self.options.embodiment)
        self.log(f"[gr00t] loading {self.options.checkpoint} as {tag.value}")
        policy = Gr00tPolicy(embodiment_tag=tag, model_path=self.options.checkpoint,
                             device="cuda", strict=True)
        if self.options.denoising_steps > 0:
            policy.model.action_head.num_inference_timesteps = self.options.denoising_steps
        stats = RobotSchema.statistics(self.options.checkpoint, tag.value)
        return policy, RobotSchema(tag.value, policy.get_modality_config(), stats, CONTROL_HZ.get(tag.value))

    def _versions(self):
        found = {"engine": "Isaac-GR00T", "commit": None}
        home = os.environ.get("GR00T_HOME", "")
        if home:
            try:
                found["commit"] = subprocess.run(["git", "-C", home, "rev-parse", "HEAD"], capture_output=True,
                                                 text=True, timeout=10).stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                found["commit"] = None
        for module in ("torch", "transformers"):
            try:
                found[module] = __import__(module).__version__
            except Exception:  # noqa: BLE001 - a fake runtime in tests has neither
                found[module] = None
        try:
            import torch
            found["device"] = f"cuda:{torch.cuda.current_device()} {torch.cuda.get_device_name()}"
        except Exception:  # noqa: BLE001
            found["device"] = ""
        model = getattr(self.policy, "model", None)
        head = getattr(model, "action_head", None)
        found["denoising_steps"] = getattr(head, "num_inference_timesteps", None)
        return found

    def _warm_up(self):
        """One inference on black frames and a typical state before /health says ok: the first
        request after a start took 12.9 s (kernel selection, 2026-10-13), and a cell that called
        itself ready would hand that wait to the first client."""
        import numpy as np

        s = self.schema
        obs = {"video": {cam: np.zeros((1, len(s.frame_offsets), 180, 320, 3), dtype=np.uint8) for cam in s.cameras},
               "state": {key: np.asarray(row, dtype=np.float32).reshape(1, 1, -1)
                         for key, row in s.typical_state().items()},
               "language": {s.language_key: [[""]]}}
        started = time.monotonic()
        with self._lock:
            self.policy.get_action(obs)
        self.log(f"[gr00t] warmed up in {time.monotonic() - started:.1f} s")

    # ── HTTP ─────────────────────────────────────────────────────────────────
    def handle_get(self, path, query):
        for method, route, name in self.ROUTES:
            if method == "GET" and route == path and route != "/health":
                return getattr(self, name)()
        return None

    def ready_required(self, path):
        # Never the base's call: its 503 says {"error": "<text>"}, and this API answers every
        # error as {"error": {code, message}}. route_predict refuses an unready model itself.
        return False

    def handle(self, body, headers, path):
        if path != self.work_path:
            return 404, {"error": {"code": "not_found", "message": f"no POST {path} here"}}, None
        return self.route_predict(body)

    def route_health(self):
        """The cell's health: 200 ok once the model is loaded and warm, 503 while it loads, 500 with
        the reason when it could not load."""
        code, payload = self.health()
        return code, payload, None

    def route_openapi(self):
        """This API, built from the cell's own route table and its handlers' descriptions."""
        return 200, OpenApi(self).spec(), None

    def route_schema(self):
        """What a request carries and an answer gives for the loaded embodiment: cameras and their
        frames, state keys and sizes, the action chunk and how its values are meant."""
        if self.schema is None:
            return 503, {"error": {"code": "loading", "message": self._not_ready()}}, None
        return 200, self.schema.describe(), None

    def route_status(self):
        """The model behind the cell: loaded or not, its weights, the runtime and its adaptation
        status. The process answering is not the model being ready; this says which."""
        status = "ok" if self.state["ready"] else ("error" if self.state["error"] else self.state["phase"])
        return 200, {
            "status": status,
            "error": self.state["error"] or None,
            "model": self.model_name,
            "weights": self.weights(),
            "runtime": self.versions or None,
            "robot_schema": self.schema.id if self.schema else None,
            "embodiment": self.schema.tag if self.schema else self.options.embodiment,
            "adaptation_status": self._adaptation(),
        }, None

    def route_predict(self, raw):
        """One observation in, a chunk of actions out. 422 names what is wrong with a request,
        and a robot schema this cell does not serve is one of those: no actions are guessed. A
        policy that fails, or answers a value that is not finite, is 500 policy_failed."""
        if not self.state["ready"]:
            return 503, {"error": {"code": "loading", "message": self._not_ready()}}, None
        try:
            body = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        except (ValueError, UnicodeDecodeError) as exc:
            return 400, Refusal(400, "invalid_json", f"the body is not JSON: {exc}").body(), None
        try:
            obs = self.schema.observation(body)
        except Refusal as refusal:
            return refusal.status, refusal.body(), None
        try:
            started = time.monotonic()
            with self._lock:
                action, _info = self.policy.get_action(obs)
            took = (time.monotonic() - started) * 1000
            actions = self.schema.actions(action)
        except Exception as exc:  # noqa: BLE001 - the runtime's failure is a 500 in this API's shape
            # The base would answer {"error": "<text>"}; a client of this API reads {code, message}.
            self.log(f"[gr00t] predict failed: {type(exc).__name__}: {exc}")
            return 500, {"error": {"code": "policy_failed", "message": f"{type(exc).__name__}: {exc}"}}, None
        return 200, {
            "object": "robot.actions",
            "model": self.model_name,
            "robot_schema": self.schema.id,
            "session_id": body.get("session_id"),
            "sequence_id": body.get("sequence_id"),
            "observation_time_unix_ms": body.get("observation_time_unix_ms"),
            "dry_run": bool(body.get("dry_run", False)),
            "weights": self.weights(),
            "runtime": self.versions,
            "adaptation_status": self._adaptation(),
            "action_schema": self.schema.action_schema(),
            "actions": actions,
            "timing_ms": {"inference": round(took, 1)},
        }, None

    def _adaptation(self):
        tag = self.schema.tag if self.schema else self.options.embodiment
        return {"native": tag, "spider-monkey-openarm-rail-v1": "not adapted: needs fine-tuning"}

    def _not_ready(self):
        return self.state["error"] or f"model {self.state['phase']}"


class OpenApi:
    """OpenAPI 3.1 of a cell, from its ROUTES and the handlers' docstrings (visumap apps-openapi)."""

    def __init__(self, cell):
        self.cell = cell

    def spec(self):
        paths = {}
        for method, route, name in self.cell.ROUTES:
            doc = " ".join((getattr(self.cell, name).__doc__ or "").split())
            summary = doc.split(". ")[0].rstrip(".")
            paths.setdefault(route, {})[method.lower()] = {
                "summary": summary,
                "description": doc,
                "security": [],
                "responses": {"200": {"description": "the answer, JSON"},
                              "default": {"description": "an error: {error: {code, message}}"}},
            }
        return {"openapi": "3.1.0",
                "info": {"title": f"GR00T cell ({self.cell.model_name})", "version": self.cell.source or "unknown"},
                "paths": paths}


if __name__ == "__main__":
    Gr00tCell().serve()
