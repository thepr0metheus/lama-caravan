"""What a cell server says about itself, in one place.

Three hand-written lists of field names had to agree and did not: the keys each
cell server emits, the keys telemetry copies out of the reply, and the keys the
board reads back. Nothing checked them against each other, so a mismatch cost
nothing at the time and showed up later as a panel that quietly said less than
it knew:

  - `targetLang` was never copied, so the language chip's live value never
    arrived. It looked correct because a config fallback produced the same
    answer — the failure was invisible precisely because the fallback worked.
  - Cells report `langs`; the copier looked for `languages`. Neither name
    reached the board from the two runners that have a language list.

So the names live here, once, and both sides read them from here. A cell can
still report anything it likes — extra keys are simply not carried — but a key
the board wants is a key this file names.
"""

# Every cell server must answer with these. They are what the board needs to
# tell one running cell from another and to decide whether the process is
# serving the code we ship:
#   status  — ok / loading / downloading / error, the phase
#   engine  — which engine is inside (a LAN scan picks cells by this)
#   model   — what it loaded, as the cell itself names it
#   source  — digest of the server file the process is RUNNING, which is how a
#             cell older than cells/ is told apart from a current one
REQUIRED = ("status", "engine", "model", "source")

# Carried when present. This list is the contract's whole surface: a field a
# cell reports and the board wants has to be named here, or it is dropped in
# transit and the board renders the absence as if the cell had said nothing.
OPTIONAL = (
    "backend",             # engine variant, when one engine has several
    "kinds",               # what it can do: stt.*, tts.*, translate.* — LAN discovery
    "langs",               # languages it accepts/produces
    "codeset",             # how to read those codes (iso639-3, flores-200…)
    "srcLang", "targetLang",   # what a translating cell reads and writes
    "srcLangRequired", "acceptsShortCodes", "acceptsIso639_1",
    "maxAudioMs",          # a speech cell's window, in audio not tokens
    "maxNewTokens",
    "device", "dtype", "deviceReason",   # where it actually landed, and why
    "downloadedBytes", "totalBytes",     # start-up progress
    "error",               # why it is not ok — never omitted when it is not
)

CARRIED = REQUIRED + OPTIONAL


def carry(payload):
    """The subset of a cell's reply that travels to the board."""
    if not isinstance(payload, dict):
        return {}
    return {k: payload[k] for k in CARRIED if k in payload}
