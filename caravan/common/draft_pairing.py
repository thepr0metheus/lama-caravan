"""Which draft files a model may be drafted by, found by what their headers say.

A draft file's architecture is its model's with `-mtp` after it: Strata's `mtp-q2_0.gguf` is `qwen4exp-mtp`, and
every pack it serves is `qwen4exp`. The scanner (models.py) used to find a model's drafts by folder alone — its own
quant folder, `default/`, the other quant folders of the same repository (the way an HF repository ships ONE sidecar for
all its quants). That is right for a repository's own sidecar and wrong for Strata, whose draft layer is made ONCE, from
the original checkpoint's MTP tensors (Strata's setup.py, step 6: "comes from the original Qwen checkpoint"), and serves
the Coder's pack, the fine-tunes' and Unsloth's as well: no repository of theirs ships it. Found by folder, these packs
got no draft, the form said "Strata runs without it", and the start failed after the scout had copied 54 GiB — the
engine does not start an IQ pack without one (the Coder's IQ1_M, 2026-10-17). The same layer, filled in by hand, started
that pack and it answered (English and code; 184-236 tok/s of the engine).

The header names the pairing, so the pairing is read from the header: an architecture with no `-mtp` partner in the
library gets nothing from this class, and a draft of another architecture (llama.cpp's own MTP files, `qwen35`) is
never offered to a model it was not made for.
"""


class DraftPairing:
    """The drafts of a library by the architecture of the model each is a draft of."""

    SUFFIX = "-mtp"

    def __init__(self):
        self._by_model_arch = {}

    def add(self, path, architecture):
        """Takes a draft file by the architecture its header names; a file whose header names none, or none of the
        form `<model's>-mtp`, is paired with no model."""
        arch = str(architecture or "")
        base = arch[:-len(self.SUFFIX)] if arch.endswith(self.SUFFIX) else ""
        if base:
            self._by_model_arch.setdefault(base, []).append(path)

    def of(self, architecture):
        """The drafts made for models of this architecture, in the order they were added; none for an architecture
        the headers did not name."""
        return list(self._by_model_arch.get(str(architecture or ""), []))
