"""The files a cell's launch uses, and how they stand against Hugging Face."""
from pathlib import Path


class LaunchFiles:
    """The files a llama.cpp cell takes at launch, each under its role on the
    card: the weights, the projector, the draft.

    All three come from Hugging Face and all three get re-issued (mmproj and
    the draft alongside the model, under one commit): asking about the weights
    alone and printing the answer for the whole launch was a defect once
    already (c0b0365). The controller's own cells carried this view until
    step 6.9 took them to their machine's scout; since then every cell — on
    any machine, running or stopped — is looked at by the files it is
    configured with.
    """

    FIELDS = (("MODEL_FILE", "model"), ("MMPROJ_FILE", "mmproj"), ("SPEC_DRAFT_MODEL_FILE", "draft"))
    ROLES = tuple(role for _field, role in FIELDS)
    #: What the watcher's report says a file is, and which of those the card
    #: shows: "matches" is never drawn — a ✓ over an unchecked file was the
    #: defect the watcher exists to fix.
    SHOWN = ("size", "date", "unknown")

    def __init__(self, config, model_path=""):
        self.config = config or {}
        self.model_path = str(model_path or "")

    def files(self):
        """[(role, path)] for every file of the launch; empty and repeated ones skipped."""
        out, seen = [], set()
        for field, role in self.FIELDS:
            ref = str((self.config.get(field) or (self.model_path if field == "MODEL_FILE" else "")) or "").strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            out.append((role, ref))
        return out

    def fresh(self, report, models_dir):
        """[{"role", "file", "state"}] for the files the watcher's report says
        differ from Hugging Face or were not checked. A path the report does
        not hold is not checked — a stranger's answer is worse than silence."""
        rows = []
        for role, ref in self.files():
            state = self.state_of(ref, report, models_dir)
            if state in self.SHOWN:
                rows.append({"role": role, "file": ref.rsplit("/", 1)[-1], "state": state})
        return rows

    @staticmethod
    def state_of(ref, report, models_dir):
        """A file's state in the watcher's report, or "". The report keys files
        by their PATH relative to the models directory: by name, one quant got
        the verdict of the other quant of the same repository (2026-09-07). An
        absolute path is brought to that shape; one outside the models
        directory is not in the report."""
        ref = str(ref or "").strip()
        if not ref:
            return ""
        path = Path(ref)
        if path.is_absolute():
            try:
                ref = str(path.relative_to(Path(models_dir)))
            except ValueError:
                return ""
        for repo in ((report or {}).get("repos") or {}).values():
            row = (repo.get("files") or {}).get(ref)
            if row:
                return str(row.get("state") or "")
        return ""

    @classmethod
    def disk_newer(cls, reported):
        """The roles a scout says changed on disk after its cell started (scout
        2.11+), kept to the roles the card knows; an older scout says nothing,
        which is not "unchanged" — the card simply draws no ⟳."""
        if not isinstance(reported, list):
            return []
        return [role for role in reported if role in cls.ROLES]
