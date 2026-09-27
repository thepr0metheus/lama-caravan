"""Keeps each cloud account's model blocks in step with what its provider lists."""
import re
import time

from caravan.admin import model_catalog
from caravan.admin.cloud import load_cloud_data, save_cloud_data
from caravan.admin.cloud_refs import CloudModelRefs

# Model ids that make no sense as chat routing targets: TTS/STT, embeddings,
# moderation, image/video/audio generators, legacy completion bases. Matched as
# a delimited token so chat models like "...-instruct" or "chat-latest" pass.
NON_CHAT_MODEL_RE = re.compile(
    r"(?:^|[-/_.:])(tts|whisper|embed|embedding|embeddings|moderation|dall-e|dalle|sora|image"
    r"|audio|transcribe|realtime|search|babbage|davinci|computer-use)(?:$|[-/_.:0-9])", re.I)


class CloudModelSync:
    """One successful model list for one account, applied to its blocks.

    The operator's word (2026-09-27): the lists keep themselves — new models
    appear by themselves, and a model the provider dropped, that nothing points
    at, goes by itself. So a list:

    - adds a block for a chat model no block names, hidden from the kanban and
      stamped `newSince` — unless the account had no blocks at all, where a
      first fill is not "new";
    - counts, on each block whose model it lacks, one more list in a row
      without it (`goneCount`); a list that has the model again clears it;
    - removes a block that has been missing from GONE_AFTER lists in a row when
      nothing points at it (CloudModelRefs) and the operator did not add it by
      hand (`manual`); the removal is kept for a day (model_catalog), so the
      board can say so and bring it back. A block something points at stays.

    What is not a verdict: an empty list — a provider answering with nothing is
    not every model gone; it counts nothing. A list that drops more than half
    of the account's blocks at once (and more than five) may be a partial
    answer, so it counts but removes only after GONE_AFTER_MASS lists in a
    row: a glitch does not last that long, while a provider that really
    renamed its catalogue (Ollama's cloud, 2026-09-27: 17 models listed, 31 of
    39 old names gone) gives the same answer every time — blocking that
    forever would leave the list for the operator to clean by hand.
    """

    GONE_AFTER = 2
    GONE_AFTER_MASS = 6
    MASS_GONE_SHARE = 0.5
    MASS_GONE_MIN = 5

    def __init__(self, load=load_cloud_data, save=save_cloud_data, refs=CloudModelRefs.load, now=time.time,
                 record_removed=model_catalog.record_removed_blocks, take_removed=model_catalog.take_removed_block):
        self._load = load
        self._save = save
        self._refs = refs
        self._now = now
        self._record_removed = record_removed
        self._take_removed = take_removed
        self._last = {}   # accountId -> the report of its latest list

    def last(self, account_id):
        """What the account's latest list did — for "↻ check now" to say."""
        return dict(self._last.get(str(account_id)) or {"created": [], "gone": [], "removed": [], "believed": False,
                                                        "skipped": 0, "total": 0})

    @staticmethod
    def _slug(model_id, taken):
        slug = re.sub(r"[^A-Za-z0-9_-]", "-", model_id)[:40].strip("-") or "model"
        bid, n = slug, 1
        while bid in taken:
            bid, n = f"{slug}-{n}", n + 1
        return bid

    def apply(self, account_id, models):
        account_id = str(account_id)
        models = [m for m in (models or []) if isinstance(m, dict) and m.get("id")]
        listed = [m for m in models if not NON_CHAT_MODEL_RE.search(str(m["id"]))]
        report = {"created": [], "gone": [], "removed": [], "believed": bool(listed),
                  "skipped": len(models) - len(listed), "total": len(listed)}
        self._last[account_id] = report
        if not listed:
            return report
        data = self._load()
        mine = [b for b in data["blocks"] if b.get("accountId") == account_id]
        # Everything the provider lists is still offered — the chat filter
        # decides what gets a block, not what counts as gone: a block made by
        # hand for an embedding model the provider lists is not missing.
        named = {str(m["id"]) for m in models}
        now = int(self._now())
        taken = {b["id"] for b in data["blocks"]}
        have = {b.get("model") for b in mine}
        for m in listed:
            if m["id"] in have:
                continue
            bid = self._slug(m["id"], taken)
            taken.add(bid)
            block = {"id": bid, "accountId": account_id, "name": m["id"], "model": m["id"], "modelMode": "rewrite"}
            if mine:
                block["newSince"] = now
            data["blocks"].append(block)
            report["created"].append(bid)
        missing = [b for b in mine if b.get("model") not in named]
        believed = not (len(missing) > self.MASS_GONE_MIN and len(missing) > self.MASS_GONE_SHARE * len(mine))
        report["believed"] = believed
        needed = self.GONE_AFTER if believed else self.GONE_AFTER_MASS
        changed = bool(report["created"])
        for b in mine:
            if b.get("model") in named and b.pop("goneCount", None) is not None:
                changed = True
        removed = []
        if missing:
            refs = self._refs()
            for b in missing:
                b["goneCount"] = int(b.get("goneCount") or 0) + 1
                changed = True
                if b["goneCount"] >= needed and not b.get("manual") and not refs.in_use(b["id"]):
                    removed.append(b)
            gone_ids = {b["id"] for b in removed}
            data["blocks"] = [b for b in data["blocks"] if b.get("id") not in gone_ids]
            report["gone"] = [b["id"] for b in missing if b["id"] not in gone_ids]
            report["removed"] = [b["id"] for b in removed]
        if changed:
            self._save(data)
        if removed:
            self._record_removed(account_id, removed, now)
        return report

    def restore(self, account_id, block_id):
        """Bring back a block the sync removed ("↶" on the board). It comes back
        as the operator's own (`manual`): the provider still does not list it,
        and the next list would otherwise take it away again. None when there
        is nothing to bring back."""
        block = self._take_removed(str(account_id), str(block_id))
        if not block:
            return None
        data = self._load()
        taken = {b["id"] for b in data["blocks"]}
        block = {k: v for k, v in block.items() if k not in ("goneCount", "newSince")}
        if block["id"] in taken:
            block["id"] = self._slug(str(block.get("model") or block["id"]), taken)
        block["manual"] = True
        data["blocks"].append(block)
        self._save(data)
        return block

