# Robot policy API (GR00T cells)

A GR00T cell serves a robot policy: camera frames, the robot's state and an
instruction go in, a chunk of actions comes out. The caravan runs it like any
other model — a cell started by its machine's scout, a row of a pool, a model
of the entry — and the client calls it through the entry with its key.

OpenAI's API has no path for this, so the path is the caravan's own:
`POST /v1/robot/predict`. Everything else is the entry as usual: the key in
`Authorization`, `model` in the body names the pool, `GET /v1/models` lists
what the key may call.

The cell runs NVIDIA's own runtime, Isaac-GR00T, in process
(`cells/gr00t_server.py`): the same policy class as NVIDIA's ZMQ server, the
same normalization and the same conversion of relative actions to absolute
targets. The cell adds HTTP, JSON and checks that name what is wrong with a
request.

## What a checkpoint can do

A checkpoint acts for the robots it was trained on. A cell serves **one**
embodiment, named when the cell starts (`GR00T_EMBODIMENT`); the base
checkpoint GR00T N1.7 3B and its default here are the DROID arm
(`OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT`). A request for another robot is
refused with 422 `unsupported_robot_schema`: actions for a robot the model was
not trained on are a guess that moves a robot. Another robot needs its own
fine-tuned checkpoint first; the answer says so under `adaptation_status`.

## Through the entry

```
GET  https://<entry>/v1/models          the key's models; a robot policy says what it does
POST https://<entry>/v1/robot/predict   one observation -> a chunk of actions
```

A robot policy in `GET /v1/models`:

```json
{"id": "spider-monkey-action", "object": "model", "owned_by": "caravan",
 "architecture": {"modality": "image+text->actions",
                  "input_modalities": ["image", "text"], "output_modalities": ["actions"]},
 "caravan": {"jobs": ["robot-policy"]}}
```

The entry refuses work a model does not do before anything is sent: a chat
request to a robot policy, and a `/v1/robot/predict` to a chat model, are both
400 ("The model … does not serve POST …"). An unknown model is 404
`model_not_found`, as OpenAI answers it.

## The request

`POST /v1/robot/predict`, `Content-Type: application/json`. The sizes, keys and
frame offsets below are DROID's; `GET /robot/schema` of the cell says them for
the embodiment it serves.

```json
{
  "model": "spider-monkey-action",
  "robot_schema": "gr00t:oxe_droid_relative_eef_relative_joint",
  "task": "Put the blue block in the green bowl",
  "state": {
    "eef_9d": [0.4455, 0.1068, 0.5234, -0.1848, 0.1707, -0.9678, 0.9641, -0.1595, -0.2122],
    "gripper_position": [0.0],
    "joint_position": [0.0007, -0.2522, 0.2246, -2.0600, -0.0278, 1.5933, 0.3907]
  },
  "images": {
    "exterior_image_1_left": {"frames": [{"mime_type": "image/png", "data_base64": "…"},
                                         {"mime_type": "image/png", "data_base64": "…"}]},
    "wrist_image_left":      {"frames": [{"mime_type": "image/png", "data_base64": "…"},
                                         {"mime_type": "image/png", "data_base64": "…"}]}
  },
  "session_id": "droid-sample",
  "sequence_id": 1,
  "observation_time_unix_ms": 1791896061732,
  "dry_run": true
}
```

| field | what it is |
|---|---|
| `model` | the pool's name, as `GET /v1/models` lists it |
| `robot_schema` | `gr00t:<embodiment>`, exactly as `GET /robot/schema` says; another one is 422 |
| `task` | the instruction, text |
| `state` | each state key of the embodiment with its exact count of finite numbers |
| `images` | each camera of the embodiment: its `frames`, oldest first, PNG or JPEG in base64, RGB, all frames of one camera of one size |
| `session_id`, `sequence_id`, `observation_time_unix_ms` | the client's own; the answer returns them as they came |
| `dry_run` | the client's own flag, returned as it came; the cell does not move anything either way |

DROID takes two frames per camera, 15 steps apart at 15 Hz: one second ago and
now (`frame_offsets_s` of the schema: `-1.0, 0.0`). `eef_9d` is the end
effector's position (x, y, z) and its rotation in 6D: the first two rows of the
rotation matrix, flattened.

## The answer

```json
{
  "object": "robot.actions",
  "model": "gr00t-n1.7-droid",
  "robot_schema": "gr00t:oxe_droid_relative_eef_relative_joint",
  "session_id": "droid-sample", "sequence_id": 1,
  "observation_time_unix_ms": 1791896061732, "dry_run": true,
  "weights": {"checkpoint": "GR00T-N1.7-3B", "checkpoint_repo": "nvidia/GR00T-N1.7-3B",
              "backbone": "Cosmos-Reason2-2B", "backbone_repo": "nvidia/Cosmos-Reason2-2B", "revision": null},
  "runtime": {"engine": "Isaac-GR00T", "commit": "d2b7e75b937e3ec9aa5dbc798f08b89692c49734",
              "torch": "2.9.0+cu128", "transformers": "4.57.3",
              "device": "cuda:0 NVIDIA GeForce RTX 5090", "denoising_steps": 4},
  "adaptation_status": {"native": "oxe_droid_relative_eef_relative_joint",
                        "spider-monkey-openarm-rail-v1": "not adapted: needs fine-tuning"},
  "action_schema": {
    "horizon": 40, "step_s": 0.066667,
    "components": [
      {"name": "eef_9d", "size": 9, "representation": "relative", "type": "eef", "format": "xyz+rot6d", "state_key": "eef_9d"},
      {"name": "gripper_position", "size": 1, "representation": "absolute", "type": "non_eef", "format": "default", "state_key": "gripper_position"},
      {"name": "joint_position", "size": 7, "representation": "relative", "type": "non_eef", "format": "default", "state_key": "joint_position"}],
    "normalized": false},
  "actions": {
    "eef_9d": [[0.448796, 0.106387, 0.52542, -0.174561, 0.171206, -0.969648, 0.966797, -0.156854, -0.201743], "… 40 rows"],
    "gripper_position": [[0.0], [0.003906], "… 40 rows"],
    "joint_position": [[0.033663, -0.24299, 0.190272, -2.047121, -0.035541, 1.590314, 0.405932], "… 40 rows"]
  },
  "timing_ms": {"inference": 60.5}
}
```

- `actions` holds `horizon` rows per component, one row per control step of
  `step_s` seconds. `step_s` is `null` for an embodiment whose control rate the
  runtime does not record: the cell does not guess it.
- The values are **absolute targets in the physical units of the
  embodiment's dataset**. The runtime denormalizes the model's output with the
  checkpoint's statistics and adds the components predicted relative to the
  request's state to that state. `representation` says how each component was
  predicted; the client gets targets either way (`normalized: false`).
- A value that is not a finite number is never sent as an action: the cell
  answers 500 `policy_failed` instead.
- `model` is the cell's own name for the model, not the pool's.
- `weights` names the Hugging Face repositories: the checkpoint's by the
  library's layout (`<model>/<author>/<FORMAT>`), the backbone's as the
  checkpoint's `config.json` names it. `revision` is `null`: a library folder
  keeps no record of the revision it was downloaded at. The revisions of a
  deployment are in its record (for the base checkpoint, 2026-10-13:
  `nvidia/GR00T-N1.7-3B` at `2fc962b973bccdd5d8ce4f67cc63b264d6886495`,
  `nvidia/Cosmos-Reason2-2B` at `9ce19a195e423419c349abfc86fd07178b230561`).

## Errors

Every error is `{"error": {"code": "…", "message": "…"}}` with a message that
names the part to fix.

| status | code | when |
|---|---|---|
| 400 | `invalid_json`, `invalid_request` | the body is not JSON, or not a JSON object |
| 422 | `unsupported_robot_schema` | `robot_schema` is not the one this cell serves |
| 422 | `invalid_task` | `task` is not text |
| 422 | `invalid_state` | a state key is missing, unknown, or has another count of numbers |
| 422 | `invalid_images` | a camera is missing or unknown, the frame count is wrong, a frame is not base64, not PNG or JPEG, or the frames of a camera differ in size |
| 500 | `policy_failed` | the runtime failed, or answered a value that is not a finite number |
| 503 | `loading` | the model is still loading, or could not load (the message says why) |

The entry's own refusals come first and are OpenAI's shape (`type`, `param`,
`code`): no key, an unknown model, a model that does other work.

A 4xx of the cell reaches the client through the entry with the cell's own `message` and `code`
(`type` is OpenAI's `invalid_request_error`), so a client can branch on `unsupported_robot_schema`,
`invalid_state` or `invalid_images`. A 5xx of the cell is told without the cell's words: 502
`upstream_error`, or 503 `model_unavailable` when no row of the pool can serve.

## The cell's own paths

A client of the caravan does not need these; they are for the operator and for
a client that wants the schema before it builds a request. The caravan's board
reaches a cell at its machine's address and port.

```
GET  /health            the cell contract: 503 while loading, 500 with the reason, 200 when ready and warm
GET  /robot/schema      cameras and their frames, state keys and sizes, the action chunk
GET  /robot/status      loaded or not, weights, runtime, robot schema, adaptation status
GET  /openapi.json      this API as OpenAPI 3.1, built from the cell's route table
POST /v1/robot/predict  as above, without the entry's key and model checks
```

## Measured (2026-10-13)

GR00T N1.7 3B with the Cosmos-Reason2-2B backbone, BF16, four denoising
steps, on one RTX 5090, the DROID sample of Isaac-GR00T:

| what | value |
|---|---|
| inference, one request | about 61 ms |
| HTTP round trip at the cell, two cameras × two PNG frames | 64–70 ms |
| VRAM of the cell | 7.0 GB (the start reserves 7.5 GB) |
| first request without the warm-up | 12.9 s — the cell warms up before `/health` says ok |

## Running a GR00T cell

1. Install the runtime on the GPU machine once: `bash scripts/install-gr00t.sh`
   (Linux x86_64, Python 3.12, ffmpeg older than 8; it pins Isaac-GR00T's
   commit and uv by checksum and checks that torch sees CUDA).
2. Put both folders into the library: the checkpoint (`nvidia/GR00T-N1.7-3B`)
   and the backbone its `config.json` names (`nvidia/Cosmos-Reason2-2B`, a
   gated repository: accept its terms on Hugging Face once).
3. In the cell editor pick 🦾 **GR00T**, choose the checkpoint folder, name
   the model (`MODEL_NAME`), and start. The scout brings both folders; the
   cell never asks the hub for anything.
4. Put the machine's model into a pool on the kanban, and the pool into the
   client's set.

Licences: the Isaac-GR00T code is Apache-2.0; the GR00T N1.7 and
Cosmos-Reason2 weights are under the NVIDIA Open Model License.
