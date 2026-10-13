"""Which speculative type a draft file is for, read from its path.

The rule lives twice — here and in static/js/draft-file.js — because the cell
editor names a draft's type in the browser when a model is picked, and the
command builder names it on the server for a cell whose type is left empty; the
model scanner reads the same rule here to tell a draft from a model. Both copies
are run against ONE table of cases (scripts/test_draft_file.py).

Why one rule. Until 2026-10-11 it was read five ways. The scanner filed a file
in a model's `mtp/` folder as a draft while the type rule read names only: the
editor offered such an MTP head with its model and wrote `draft-simple` next to
it. By llama.cpp's source (b10357), draft-simple runs the file as a model of
its own, on token batches without the hidden state an MTP head drafts from: the
cell would start, look healthy and draft nothing of use. The scanner wanted a
hyphen after the prefix where the type rule took `_` and `.` too. The editor's
speculation switch wrote the family's type whatever the draft was. And the
builder read the type off the path it emits, which for a scout's cell is the
`{{SPEC_PATH}}` placeholder: every scout cell with an empty type ran its draft
as draft-simple, `mtp-` and `dflash-` heads included, while both previews named
the right type.
"""
import re


class DraftFile:
    """A draft file, named by its path, and the speculative type it is for."""

    # Sidecar prefix → speculative type: upstream's own convention. llama.cpp
    # infers the type from the sidecar a draft REPO ships (PR #25989), but only
    # for -hfd downloads; a local --model-draft gets no inference and would run
    # with type NONE. Matched on the FIRST word of the name only, so a model
    # that merely contains one of these words is not taken for a sidecar.
    PREFIXES = (
        ("dflash", "draft-dflash"),
        ("dspark", "draft-dspark"),
        ("eagle3", "draft-eagle3"),
        ("mtp", "draft-mtp"),
    )
    # The layout before upstream's `mtp-` names: a model's MTP head in a folder
    # of its own, <model>/mtp/<file>. A prefix in the name still outranks it.
    MTP_FOLDER = "mtp"
    # A file that is no sidecar is a plain second model, drafted
    # autoregressively. Not draft-mtp: that aborts outright on a model with no
    # MTP head.
    PLAIN = "draft-simple"

    def __init__(self, path):
        self.path = str(path or "")

    @property
    def sidecar_type(self):
        """The type the file is a sidecar for, or "" when it is none: said, not guessed."""
        *folders, name = self.path.split("/")
        types = dict(self.PREFIXES)
        head = re.split(r"[-_.]", name.lower(), maxsplit=1)[0]
        if head in types:
            return types[head]
        if any(folder.lower() == self.MTP_FOLDER for folder in folders):
            return types[self.MTP_FOLDER]
        return ""

    @property
    def launch_type(self):
        """The type a cell with no type of its own launches the file with."""
        return self.sidecar_type or self.PLAIN
