"""Runner registry — now a thin face over `caravan.domain.runner`.

Everything here used to be a dict per runner plus a chain of `if rid == "..."`
per question. Both moved into classes in the domain layer, one per runner, where
a new runner cannot be forgotten from a list somewhere else: see
`caravan/domain/runner.py` for the reasoning behind every value.

This module stays because a dozen callers import these names, and the names are
still the right ones to ask from admin code. It adds nothing of its own.
"""
from caravan.domain.runner import for_config, registry_json, runner_id  # noqa: F401
from caravan.domain.runner import MoonshineRunner as _Moonshine
from caravan.domain.runner import VllmRunner as _Vllm
from caravan.domain.runner import WhisperRunner as _Whisper

#: The registry as JSON, the shape the frontend has always received. Rendered
#: once at import: it is derived from class attributes that do not change at
#: runtime, and callers hand it straight to json.dumps.
RUNNERS = registry_json()

WHISPER_SIZES = _Whisper.sizes
MOONSHINE_LANGS = _Moonshine.langs
VLLM_VENV = _Vllm.venv
VLLM_DEFAULT_VERSION = _Vllm.default_version
VLLM_BOOTSTRAP_LINES = _Vllm().bootstrap


def uses_token_context(config) -> bool:
    """True when this cell's work is measured in tokens, so CTX_SIZE means
    something to it."""
    return for_config(config).token_context


def cell_model_ref(config) -> str:
    """The thing a cell actually serves, as its own runner names it."""
    return for_config(config).model_ref(config)


def cell_artifact_label(config) -> str:
    """What a cell RUNS, in one short phrase, for lists with no room for a card."""
    return for_config(config).artifact_label(config)


def uses_command_path(config) -> bool:
    """True when the cell launches through the generic command machinery."""
    return for_config(config).command_path


def build_whisper_command(config) -> str:
    return _Whisper().command(config)


def build_transcribe_command(config) -> str:
    from caravan.domain.runner import TranscribeRunner
    return TranscribeRunner().command(config)


def build_moonshine_command(config) -> str:
    return _Moonshine().command(config)


def build_seamless_command(config) -> str:
    from caravan.domain.runner import SeamlessRunner
    return SeamlessRunner().command(config)


def build_translate_command(config) -> str:
    from caravan.domain.runner import TranslateRunner
    return TranslateRunner().command(config)


def build_vllm_command(config) -> str:
    return _Vllm().command(config)


def effective_command(config, with_bootstrap=False) -> str:
    """Shell command a command-path cell actually runs."""
    return for_config(config).command(config, with_bootstrap)


def effective_health_path(config) -> str:
    return for_config(config).health_path(config)
