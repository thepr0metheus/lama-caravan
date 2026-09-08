// Our copy of a file against the one on Hugging Face.
//
// A twin of caravan/common/model_freshness.py — one rule, three readers: the
// repository row on /hf, the on-disk models page, and the scheduled watcher.
// There used to be one answer — "a file with this name exists" — and the row
// set a ✓, printing the size and date of the file ON HF NEXT TO IT. The
// operator read a single coherent claim about their own file, and it was
// actually about someone else's. A 2026-09-07 fleet check: 11 files across 5
// repositories had diverged, including both Qwen3.8-27B builds, one of which
// was running in a cell at the time.
//
// Five states, and `unknown` is separate from `same`: turning not-knowing
// into a claim was the original defect.

export const DIFFERS = ["size", "date"];

export function compareLocalFile(local, remote) {
  if (!local || typeof local !== "object") return { state: "missing", detail: {} };
  const localSize = Number(local.size || 0);
  const remoteSize = Number((remote || {}).size || 0);
  const localDate = dayFromEpoch(local.mtime);
  const remoteDate = String((remote || {}).date || "").slice(0, 10);
  const detail = { localSize, remoteSize, localDate, remoteDate };
  if (!localSize || !remoteSize) return { state: "unknown", detail };
  if (localSize !== remoteSize) return { state: "size", detail };
  // Dates are compared by calendar day: the upload hour and the commit hour
  // are in different time zones, and a same-day difference means nothing —
  // but "four days later" does.
  if (localDate && remoteDate && remoteDate > localDate) return { state: "date", detail };
  if (!localDate || !remoteDate) return { state: "unknown", detail };
  return { state: "same", detail };
}

export function dayFromEpoch(mtime) {
  const seconds = Number(mtime || 0);
  if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return "";
  const d = new Date(seconds * 1000);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
}

// ⇪ — the same icon the board has long used to mark a cell server's stale
// binary: the operator already reads it on sight. "?" is not "✓": there's
// nothing to compare against.
export function freshMark(fresh) {
  const state = (fresh || {}).state;
  if (state === "size" || state === "date") return "⇪";
  if (state === "unknown") return "?";
  return "✓";
}

// Repository rollup. A zero in `differs` means "checked, and matches" — not
// "wasn't looked at": anything unchecked counts separately, under `unknown`.
export function repoSummary(states) {
  const out = { differs: 0, bySize: 0, byDate: 0, unknown: 0, same: 0, missing: 0 };
  for (const state of states || []) {
    if (DIFFERS.includes(state)) {
      out.differs += 1;
      out[state === "size" ? "bySize" : "byDate"] += 1;
    } else if (state in out) {
      out[state] += 1;
    }
  }
  return out;
}
