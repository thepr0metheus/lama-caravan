// When a model is open, as the board paints and edits it: windows of weekdays and times of day.
//
// The rule is caravan/common/week_windows.py, and this is its twin for the page. A window is
// {days, from, to}: days 0..6 with Monday 0, none meaning every day; open from `from`, closed again
// at `to`; a window whose `to` is not after its `from` runs past midnight and belongs to the day it
// starts on; `from` equal to `to` is a whole day from that time. Both read a window as the same
// minutes of the week, and scripts/test_week_windows.py holds the two to one table of cases.
//
// The page edits a week of minutes (a mask) — an hour painted on the grid opens or closes its
// sixty — and writes the windows back from it, the same week always as the same windows
// (`fromMask`), so painting an hour twice gives back what was there.
export class WeekWindows {
  static DAY = 1440;
  static WEEK = 7 * 1440;

  // "HH:MM" → minutes after midnight, or null for anything else.
  static minutes(text) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(String(text ?? "").trim());
    if (!m) return null;
    const hour = Number(m[1]);
    const minute = Number(m[2]);
    return hour > 23 || minute > 59 ? null : hour * 60 + minute;
  }

  static hhmm(minutes) {
    const m = ((Number(minutes) % WeekWindows.DAY) + WeekWindows.DAY) % WeekWindows.DAY;
    return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  }

  // The days a window names, or null when it names one that is no day: such a window does not read
  // at all, as the server reads it (WeekWindows.clean drops it whole). None, or no list, is every day.
  static days(raw) {
    if (raw === undefined || raw === null) return [0, 1, 2, 3, 4, 5, 6];
    if (!Array.isArray(raw)) return null;
    if (raw.some((day) => !Number.isInteger(day) || day < 0 || day > 6)) return null;
    return raw.length ? raw : [0, 1, 2, 3, 4, 5, 6];
  }

  // The open minutes of the week as sorted, merged [start, end) runs, Monday 00:00 being 0 — the
  // rule's own reading (WeekWindows.runs in Python). A window that does not read opens nothing.
  static runs(windows) {
    const pieces = [];
    for (const w of Array.isArray(windows) ? windows : []) {
      const start = WeekWindows.minutes(w?.from);
      const end = WeekWindows.minutes(w?.to);
      const days = WeekWindows.days(w?.days);
      if (start === null || end === null || !days) continue;
      const length = (((end - start) % WeekWindows.DAY) + WeekWindows.DAY) % WeekWindows.DAY || WeekWindows.DAY;
      for (const day of days) {
        const begin = day * WeekWindows.DAY + start;
        const stop = begin + length;
        if (stop <= WeekWindows.WEEK) pieces.push([begin, stop]);
        else pieces.push([begin, WeekWindows.WEEK], [0, stop - WeekWindows.WEEK]);
      }
    }
    pieces.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const out = [];
    for (const [begin, stop] of pieces) {
      if (out.length && begin <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], stop);
      else out.push([begin, stop]);
    }
    return out;
  }

  // The week as one flag per minute: 1 open, 0 closed.
  static mask(windows) {
    const mask = new Uint8Array(WeekWindows.WEEK);
    for (const [begin, stop] of WeekWindows.runs(windows)) mask.fill(1, begin, stop);
    return mask;
  }

  // How many of an hour's sixty minutes are open: the grid draws an hour full, part or empty.
  static share(mask, day, hour) {
    const begin = day * WeekWindows.DAY + hour * 60;
    let open = 0;
    for (let m = begin; m < begin + 60; m += 1) open += mask[m];
    return open;
  }

  // An hour of the grid opened or closed, all sixty minutes of it.
  static paint(mask, day, hour, open) {
    const begin = day * WeekWindows.DAY + hour * 60;
    mask.fill(open ? 1 : 0, begin, begin + 60);
    return mask;
  }

  // The windows a week of minutes is, one way for one week: each open stretch of a day or less is
  // one window, overnight if it crosses midnight; a longer one is cut at the midnights it crosses.
  // Stretches with the same times on several days are one window of those days; all seven days are
  // every day (no days). Windows go by their first day, then by their time.
  static fromMask(mask) {
    const { WEEK } = WeekWindows;
    if (mask.every((x) => x === 1)) return [{ days: [], from: "00:00", to: "00:00" }];
    const closed = mask.indexOf(0);
    if (closed < 0) return [];
    const pieces = [];
    let start = null;
    for (let step = 1; step <= WEEK; step += 1) {
      const m = (closed + step) % WEEK;
      if (mask[m] && start === null) start = m;
      if (!mask[m] && start !== null) {
        const length = ((m - start) % WEEK + WEEK) % WEEK;
        WeekWindows.cut(start, length, pieces);
        start = null;
      }
    }
    const byTimes = new Map();
    for (const piece of pieces) {
      const key = `${piece.from}-${piece.to}`;
      if (!byTimes.has(key)) byTimes.set(key, { days: [], from: piece.from, to: piece.to });
      const entry = byTimes.get(key);
      if (!entry.days.includes(piece.day)) entry.days.push(piece.day);
    }
    const out = [...byTimes.values()].map((w) => ({ ...w, days: w.days.sort((a, b) => a - b) }));
    for (const w of out) if (w.days.length === 7) w.days = [];
    const first = (w) => (w.days.length ? w.days[0] : -1);
    return out.sort((a, b) => first(a) - first(b) || WeekWindows.minutes(a.from) - WeekWindows.minutes(b.from)
      || WeekWindows.minutes(a.to) - WeekWindows.minutes(b.to));
  }

  // One open stretch as the pieces fromMask writes: whole when a day or shorter, else cut at midnights.
  static cut(start, length, pieces) {
    const { DAY, WEEK } = WeekWindows;
    const day = (m) => Math.floor((m % WEEK) / DAY);
    if (length <= DAY) {
      pieces.push({ day: day(start), from: WeekWindows.hhmm(start), to: WeekWindows.hhmm(start + length) });
      return;
    }
    let at = start;
    let left = length;
    while (left > 0) {
      const toMidnight = DAY - (at % DAY);
      const take = Math.min(left, toMidnight);
      pieces.push({ day: day(at), from: WeekWindows.hhmm(at), to: WeekWindows.hhmm(at + take) });
      at = (at + take) % WEEK;
      left -= take;
    }
  }
}
