#!/usr/bin/env python3
"""Value snapshot: the model watcher — was anything we have re-issued.

Three rules for this module, and all three are pinned:

* It NEVER downloads anything. The report holds no action and can't — only
  what was measured. This is pinned because the driver watcher has a second
  "install it yourself" checkbox, and repeating it here would be easy and
  wrong: :22011's new build is 364 MB smaller than the old one, and replacing
  it is the operator's decision.
* It stays silent while the checkbox is off. A pass with the checkbox off
  never reaches the network at all; a pressed button (force) is a direct
  request and does.
* The report stores when it was measured. A report with no timestamp would
  read as "just checked".

Plus: an unreachable repository is an error in the report, NOT "matches";
the directory layout <model>/<author>/<quant>/<file> turns into the repo_id
<author>/<model>, and a file shallower than three levels doesn't belong to
any repository.

Run: python3 scripts/test_model_watch.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.model_watch as mw  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class FakeState(dict):
    """admin_state as a dict; save_admin_state counts the writes."""
    saves = 0


def install_state():
    import caravan.admin.state as state_mod
    fake = FakeState()
    state_mod.admin_state = fake
    real_save = state_mod.save_admin_state
    state_mod.save_admin_state = lambda *a, **k: setattr(FakeState, "saves", FakeState.saves + 1)
    return fake, real_save


def main():
    fake, real_save = install_state()
    real_list = mw.local_repos

    print("галка и поход в сеть:")
    calls = []
    import caravan.admin.hf as hf_mod
    real_hf = hf_mod.hf_list_files
    hf_mod.hf_list_files = lambda repo: calls.append(repo) or {"ok": True, "files": []}
    mw.local_repos = lambda: {"unsloth/Qwen3.8-27B-GGUF": {
        "Qwen3.8-27B-GGUF/unsloth/Q4/a.gguf": {"size": 1, "mtime": 1, "name": "a.gguf"}}}
    try:
        res = mw.check_pass()
        check(res == {"checked": False, "reason": "auto-check off"},
              f"галка снята → прохода нет (got {res})")
        check(calls == [], f"и в сеть НЕ ходили ни разу (got {calls})")

        res = mw.check_pass(force=True, now=1000)
        check(res["checked"] is True and calls == ["unsloth/Qwen3.8-27B-GGUF"],
              f"нажатая кнопка ходит и при снятой галке (got {res}, {calls})")
        check(mw.freshness_report()["checkedAt"] == 1000,
              "отчёт помнит ВРЕМЯ измерения — иначе он читается как «только что»")

        mw.set_watch_settings({"check": True})
        check(mw.watch_settings()["check"] is True, "галку можно включить")
        print("три ступени:")
        # Each next tier turns on the one before it: "install it yourself"
        # with "check" off would be a promise nobody is there to keep.
        st = mw.set_watch_settings({"download": True})
        check(st["check"] is True and st["download"] is True,
              f"«обновлять само» включает «смотреть»: иначе исполнять было бы некому (got {st})")
        st = mw.set_watch_settings({"check": True})
        check(st["download"] is False,
              "и обратной силы нет: включённая проверка сама ничего не качает")
        check(st["keepPrev"] is False,
              "сохранение прежней сборки ВЫКЛЮЧЕНО по умолчанию — место дороже отката")
        st = mw.set_watch_settings({"check": True, "keepPrev": True})
        check(st["keepPrev"] is True and st["download"] is False,
              f"галка сохранения независима: она про место, а не про автоматику (got {st})")
        st = mw.set_watch_settings({})
        check(st == {**st, "check": False, "download": False, "keepPrev": False},
              "пропущенная галка означает «снять» — как у окна настроек драйвера")
        mw.set_watch_settings({"check": True})
        calls.clear()
        mw.check_pass(now=2000)
        check(calls == ["unsloth/Qwen3.8-27B-GGUF"], "с включённой галкой проход идёт сам")

        print("что попадает в отчёт:")
        hf_mod.hf_list_files = lambda repo: {
            "ok": True,
            "files": [{"name": "same.gguf", "size": 100, "date": "2020-01-01T00:00:00Z"},
                      {"name": "smaller.gguf", "size": 90, "date": "2026-08-19T00:00:00Z"},
                      {"name": "newer.gguf", "size": 100, "date": "2026-08-19T00:00:00Z"}],
        }
        day = time.mktime(time.strptime("2026-08-15", "%Y-%m-%d"))
        # The path is required: it's what the "update" button and
        # auto-download use to find where to put the new build. Without it a
        # pass would treat the file as ownerless.
        # The files are REAL: the report measures the local side on every
        # read, and a row for a file that doesn't exist drops out of it — as
        # it should.
        disk = Path(tempfile.mkdtemp(prefix="caravan-fresh-"))
        for n in ("same.gguf", "smaller.gguf", "newer.gguf", "only-ours.gguf"):
            f = disk / n
            f.write_bytes(b"x" * 100)
            os.utime(f, (int(day), int(day)))
        # The key is the path from the models directory, the way
        # local_repos() reports it; the name rides alongside it, because
        # checking against HF still goes by name.
        mw.local_repos = lambda: {"a/b": {
            f"b/a/Q4/{n}": {"size": 100, "mtime": int(day), "name": n, "path": str(disk / n)}
            for n in ("same.gguf", "smaller.gguf", "newer.gguf", "only-ours.gguf")}}
        mw.check_pass(force=True, now=3000)
        rep = mw.freshness_report()["repos"]["a/b"]
        states = {v["name"]: v["state"] for v in rep["files"].values()}
        check(states.get("same.gguf") == "same", f"совпало (got {states.get('same.gguf')})")
        check(states.get("smaller.gguf") == "size", f"размер разошёлся (got {states.get('smaller.gguf')})")
        check(states.get("newer.gguf") == "date", f"коммит новее (got {states.get('newer.gguf')})")
        # We have the file, but the repository no longer lists it: there is
        # NOTHING to compare against. The first version of this pin required
        # no entry at all — which would have hidden a file like this. "We
        # don't know" is more honest than silence.
        check(states.get("only-ours.gguf") == "unknown",
              f"файла нет в репозитории → «не знаем», не «сходится» и не молчание "
              f"(got {states.get('only-ours.gguf')!r})")
        check(rep["summary"] == {"differs": 2, "bySize": 1, "byDate": 1,
                                 "unknown": 1, "same": 1, "missing": 0},
              f"свод по репозиторию считает каждое состояние (got {rep['summary']})")
        # A row's key is the PATH. Via .get(), so a broken key turns the pin
        # red instead of crashing the snapshot on a KeyError, taking
        # everything below it down unchecked.
        smaller = rep["files"].get("b/a/Q4/smaller.gguf") or {}
        check(smaller.get("localSize") == 100 and smaller.get("remoteSize") == 90,
              f"строка отчёта лежит под ПУТЁМ, и в ней оба размера — "
              f"читателю не надо ходить в HF второй раз (got {sorted(rep['files'])})")
        check(smaller.get("localPath") == str(disk / "smaller.gguf") and smaller.get("repo") == "a/b",
              "и куда класть новую сборку — тоже здесь, а не ищется заново по имени")

        print("локальная сторона меряется, а не помнится:")
        # The whole reason this exists: a file downloaded ON TOP OF the old
        # one — and the row must stop offering "update" immediately, without
        # a trip to HF. On 2026-09-07 the operator downloaded a file and saw
        # the button sitting there unchanged.
        before = mw.freshness_report()
        check(before["repos"]["a/b"]["files"]["b/a/Q4/smaller.gguf"]["state"] == "size",
              "до подмены строка говорит «разошлось»")
        # A downloaded file gets TODAY's timestamp — mtime isn't carried
        # over, same as the downloader does it. That's exactly what resolves
        # the "date newer" state: our file is now more recent than the HF commit.
        (disk / "smaller.gguf").write_bytes(b"x" * 90)          # now matches HF
        after = mw.freshness_report(now=time.time() + 10)
        check(after["repos"]["a/b"]["files"]["b/a/Q4/smaller.gguf"]["state"] == "same",
              f"positive: файл заменён — вердикт «сходится» СРАЗУ, без новой сверки "
              f"(got {after['repos']['a/b']['files']['b/a/Q4/smaller.gguf']['state']})")
        check(after["checkedAt"] == before["checkedAt"],
              "а время сверки не двигается: оно про поход на HF, а не про локальный файл")
        check(after["repos"]["a/b"]["files"]["b/a/Q4/newer.gguf"]["state"] == "date",
              "negative: соседний файл не тронут — и вердикт у него прежний")
        os.remove(disk / "only-ours.gguf")
        gone = mw.freshness_report(now=time.time() + 20)
        check("b/a/Q4/only-ours.gguf" not in gone["repos"]["a/b"]["files"],
              "negative: файла больше нет на диске — и строки о нём тоже нет")
        # Restore to how it was: the pins below assume the original layout.
        (disk / "smaller.gguf").write_bytes(b"x" * 100)
        (disk / "only-ours.gguf").write_bytes(b"x" * 100)
        for n in ("smaller.gguf", "only-ours.gguf"):
            os.utime(disk / n, (int(day), int(day)))

        print("автономное обновление:")
        # The download itself is replaced: this snapshot pins the pass's
        # DECISIONS, and the disk work is pinned separately in test_model_staging.py.
        import caravan.admin.model_staging as st_mod
        real_start = st_mod.start_update
        started = []
        st_mod.start_update = lambda key: started.append(key) or {"ok": True}
        try:
            mw.set_watch_settings({"check": True})
            out = mw.check_pass(force=True, now=3100)
            check(started == [],
                  f"галка «обновлять» снята → в HF за файлами не ходим (got {started})")
            check("fetched" not in out or out["fetched"] == [],
                  "и в ответе прохода нечего показать")

            mw.set_watch_settings({"download": True})
            started.clear()
            out = mw.check_pass(force=True, now=3200)
            check(sorted(started) == ["b/a/Q4/newer.gguf", "b/a/Q4/smaller.gguf"],
                  f"positive: качается ровно разошедшееся и по ПУТИ, совпавшее не трогаем "
                  f"(got {sorted(started)})")
            check([r["result"] for r in out["fetched"]] == ["fetching", "fetching"],
                  f"проход отчитывается по каждому файлу (got {out['fetched']})")

            st_mod.start_update = lambda key: (_ for _ in ()).throw(RuntimeError("disk full"))
            out = mw.check_pass(force=True, now=3400)
            check(all("disk full" in r["result"] for r in out["fetched"]),
                  f"ошибка остаётся ПРИ ФАЙЛЕ, а не роняет проход (got {out['fetched']})")
            check(len(out["fetched"]) == 2,
                  "не хватило места на одну — про остальные всё равно сказано")
        finally:
            st_mod.start_update = real_start
            mw.set_watch_settings({"check": True})

        print("репозиторий недоступен:")
        hf_mod.hf_list_files = lambda repo: {"ok": False, "error": "404"}
        out = mw.check_pass(force=True, now=4000)
        rep = mw.freshness_report()["repos"]["a/b"]
        check(rep["error"] == "404" and rep["files"] == {},
              f"ошибка записана, состояний у файлов НЕТ — это не «сходится» (got {rep})")
        check(rep["summary"]["differs"] == 0 and rep["summary"]["same"] == 0,
              "и в своде ноль везде: ноль расхождений тут не значит «сверено»")
        check(out["unreachable"] == 1, f"проход называет число недоступных (got {out})")
        check(mw.watch_settings()["lastError"], "и запоминает, что не всё прочиталось")

        print("пустой отчёт:")
        fake.pop("modelFreshness", None)
        empty = mw.freshness_report()
        check(empty == {"checkedAt": 0, "repos": {}},
              f"не проверяли → пусто и время ноль (got {empty})")
        # A report taken before 1.3.334 addressed rows by the file's NAME,
        # and some of them measured the wrong file. Carrying such a report
        # forward under the new keys would preserve the lie at a new address.
        fake["modelFreshness"] = {"checkedAt": 9, "repos": {"a/b": {"files": {
            "smaller.gguf": {"state": "size", "localPath": "/m/a/b/smaller.gguf"}}}}}
        stale = mw.freshness_report()
        check(stale == {"checkedAt": 0, "repos": {}},
              f"negative: отчёт со старым ключом — «не проверяли», а не вердикты (got {stale})")
        fake["modelFreshness"] = {"checkedAt": 9, "keys": "path", "repos": {"a/b": {"files": {}}}}
        check(mw.freshness_report()["checkedAt"] == 9,
              "positive: отчёт, помеченный ключом-путём, читается как свой")

        print("чей это файл:")
        # The report is built from the CONTROLLER's models directory. A
        # client cell's weights sit on its own host, and a matching file NAME
        # says nothing about them. The first version hung a chip on a client
        # cell — reporting on a file it had never seen (found by a live check).
        import inspect
        import caravan.admin.topology as topo
        src = inspect.getsource(topo)
        check('"modelFresh": _model_fresh_state(model_path) if is_controller_slot else ""' in src,
              "поле ставится только ячейке контроллера — у клиентской остаётся пустым")
        check('def _model_fresh_state' in src and 'freshness_report()' in src,
              "и берётся из отчёта сторожа, а не из отдельной копии правила")

        print("раскладка каталога:")
        mw.local_repos = real_list
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Qwen3.8-27B-GGUF" / "unsloth" / "Q4_K_XL").mkdir(parents=True)
            (root / "Qwen3.8-27B-GGUF" / "unsloth" / "Q4_K_XL" / "m.gguf").write_bytes(b"x")
            (root / "loose.gguf").write_bytes(b"x")
            # Two levels also isn't a repository: there's nowhere to take an
            # author from, and "x.gguf/vendor" would be a made-up name (found by a mutant).
            (root / "vendor").mkdir()
            (root / "vendor" / "x.gguf").write_bytes(b"x")
            import caravan.admin.config_builder as cb
            real_dir, real_cfg = cb.models_dir_from_config, cb.parse_config
            cb.models_dir_from_config = lambda cfg: root
            cb.parse_config = lambda: {}
            try:
                repos = mw.local_repos()
            finally:
                cb.models_dir_from_config, cb.parse_config = real_dir, real_cfg
            check(list(repos) == ["unsloth/Qwen3.8-27B-GGUF"],
                  f"<модель>/<автор>/<квант> → <автор>/<модель> (got {list(repos)})")
            one = repos.get("unsloth/Qwen3.8-27B-GGUF") or {}
            check(list(one) == ["Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/m.gguf"],
                  f"ключ записи — ПУТЬ от каталога моделей, не имя (got {list(one)})")
            check((one.get("Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/m.gguf") or {}).get("name") == "m.gguf",
                  "имя тоже при записи: с HF сверяются по нему — там копия одна")
            check(all("loose" not in n for r in repos.values() for n in r),
                  "файл в корне ничьим репозиторием не считается — автора выдумывать нельзя")
            check(all("x.gguf" not in n for r in repos.values() for n in r)
                  and not any("vendor" in k for k in repos),
                  f"и файл на двух уровнях — тоже: репозиторий требует автора (got {list(repos)})")

        print("две копии одного имени:")
        # Found by a live check on 2026-09-07: on disk,
        # google_gemma-4-31B-it-GGUF/bartowski/{Q5_K_M,default}/mtp-…-Q4_0.gguf
        # is ONE name in two quants of ONE repository. The tree counted 11
        # divergences, the report counted 10.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for quant, mtime in (("Q5_K_M", 200), ("default", 100)):
                d = root / "M" / "A" / quant
                d.mkdir(parents=True)
                f = d / "dup.gguf"
                f.write_bytes(b"x" * 100)
                os.utime(f, (mtime, mtime))
            import caravan.admin.config_builder as cb
            real_dir, real_cfg = cb.models_dir_from_config, cb.parse_config
            cb.models_dir_from_config = lambda cfg: root
            cb.parse_config = lambda: {}
            try:
                # .get() everywhere: a mutant that returns a name-based key
                # must turn pins RED, not crash on the first KeyError and
                # leave the rest unchecked.
                repos = mw.local_repos().get("A/M") or {}
                check(sorted(repos) == ["M/A/Q5_K_M/dup.gguf", "M/A/default/dup.gguf"],
                      f"positive: обе копии в реестре, каждая под своим путём (got {sorted(repos)})")
                check((repos.get("M/A/default/dup.gguf") or {}).get("mtime") == 100,
                      "и у каждой СВОЁ время: раньше копия посвежее вытесняла вторую")

                hf_mod.hf_list_files = lambda repo: {
                    "ok": True,
                    "files": [{"name": "dup.gguf", "size": 90, "path": "dup.gguf",
                               "date": "2026-08-19T00:00:00Z"}]}
                mw.check_pass(force=True, now=5000)
                repo_row = mw.freshness_report()["repos"].get("A/M") or {}
                rows = repo_row.get("files") or {}
                check(sorted(rows) == ["M/A/Q5_K_M/dup.gguf", "M/A/default/dup.gguf"],
                      f"positive: сверены ОБЕ — на HF копия одна, у нас две (got {sorted(rows)})")
                check((rows.get("M/A/default/dup.gguf") or {}).get("name") == "dup.gguf",
                      "имя в строке осталось: рисовать в дереве надо его")
                check((repo_row.get("summary") or {}).get("differs") == 2,
                      "и свод считает две — столько файлов и правда разошлось")

                import caravan.admin.model_staging as st2
                def where(key):
                    try:
                        return st2.live_path_for(key)
                    except Exception as exc:  # noqa: BLE001
                        return f"<{exc}>"
                check(where("M/A/default/dup.gguf").endswith("default/dup.gguf")
                      and where("M/A/Q5_K_M/dup.gguf").endswith("Q5_K_M/dup.gguf"),
                      f"positive: каждая строка ведёт в СВОЙ файл — кнопка пишет туда, где стоит "
                      f"(got {where('M/A/default/dup.gguf')})")
                try:
                    st2.live_path_for("dup.gguf")
                    check(False, "голое имя больше не адрес — должен быть отказ")
                except Exception as exc:
                    check(getattr(exc, "status", 0) == 404,
                          f"negative: голое имя ничего не адресует — 404, а не чужая копия (got {exc})")

                # AS-IS: a cell's launch involves THREE model files —
                # MODEL_FILE, MMPROJ_FILE, and the draft — and this field's
                # freshness is computed only from the first one. The card
                # stays silent about the other two through this field.
                import inspect as _insp
                import caravan.admin.topology as topo3
                _src = _insp.getsource(topo3)
                check('"modelFresh": _model_fresh_state(model_path)' in _src,
                      "as-is: чип свежести смотрит ТОЛЬКО на MODEL_FILE")
                check("MMPROJ_FILE" in _src and "_model_fresh_state(mmproj" not in _src,
                      "as-is: mmproj в строке есть, но его свежесть не считается")

                import caravan.admin.topology as topo2
                check(topo2._model_fresh_state("M/A/default/dup.gguf") == "size"
                      and topo2._model_fresh_state("M/A/Q5_K_M/dup.gguf") == "size",
                      "карточка ячейки читает вердикт СВОЕЙ копии")
                check(topo2._model_fresh_state("M/A/Q6/dup.gguf") == "",
                      "negative: путь, которого в отчёте нет, — «не проверяли», а не вердикт соседки")
            finally:
                cb.models_dir_from_config, cb.parse_config = real_dir, real_cfg


        print("расписание сторожа:")
        # Before: the loop SLEPT a full day and only then checked, counting
        # from service start. In production the service restarted 29 times a
        # day (deploys), and a pass never once happened. Now this is a time
        # of day on the shared tick.
        import types

        def at_time(hhmm, day="2026-09-08"):
            return time.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")

        calls.clear()
        hf_mod.hf_list_files = lambda repo: calls.append(repo) or {"ok": True, "files": []}
        mw.local_repos = lambda: {"a/b": {"b/a/Q4/x.gguf": {"size": 1, "mtime": 1, "name": "x.gguf"}}}

        mw.set_watch_settings({})
        res = mw.model_watch_tick(at_time("03:00"))
        check(res == {"fired": False, "reason": "auto-check off"},
              f"negative: галка снята — тик молчит (got {res})")
        check(calls == [], "и в сеть не ходит")

        # Arranged at 02:00 — BEFORE the scheduled 03:00 — so the setting call
        # cannot stamp today as done. Without the fixed hour these pins read the
        # real clock and were green only when run before 03:00 in the morning.
        st = mw.set_watch_settings({"check": True, "at": "03:00"}, now=at_time("02:00"))
        check(st["at"] == "03:00", f"время суток сохраняется (got {st.get('at')})")
        # A day record left by an earlier arrangement is not what these pins are
        # about: they ask what the tick does BEFORE and AT the scheduled minute.
        # Yesterday, so the "first day under the schedule" branch stays out too.
        from caravan.admin.state import admin_state as _pre
        _pre["modelWatch"] = {**_pre["modelWatch"], "lastCheckDay": "2026-09-07"}
        res = mw.model_watch_tick(at_time("02:59"))
        check(res["fired"] is False and res["reason"] == "not yet",
              f"negative: до назначенной минуты ничего не происходит (got {res})")
        res = mw.model_watch_tick(at_time("03:00"))
        check(res["fired"] is True, f"positive: минута настала — проход пошёл (got {res})")
        check(calls == ["a/b"], f"и он реально сходил в сеть (got {calls})")

        calls.clear()
        res = mw.model_watch_tick(at_time("03:01"))
        check(res["fired"] is False and res["reason"] == "already checked today",
              f"negative: второй раз за день не ходим (got {res})")
        check(calls == [], "тик раз в минуту не превращается в шестьдесят проходов в час")

        # The first tick under the new scheme is NOT a reason to catch up.
        # The checkbox could have been on since before this existed, no
        # day record existed yet, and the 03:00 default had already passed
        # by deploy time: without telling these apart, an 18:47 update fired
        # the check immediately and, with auto-replace on, pulled down
        # twenty gigabytes a minute the operator never chose.
        mw.set_watch_settings({"check": True, "at": "03:00"}, now=at_time("02:00"))
        from caravan.admin.state import admin_state as _st0
        _st0["modelWatch"] = {k: v for k, v in _st0["modelWatch"].items() if k != "lastCheckDay"}
        calls.clear()
        res = mw.model_watch_tick(at_time("18:47"))
        check(res == {"fired": False, "reason": "first day under the schedule"},
              f"negative: записи о днях нет вовсе — это не «пропустили», а «впервые» (got {res})")
        check(calls == [], "и в сеть на этом тике не ходим")
        check(mw.watch_settings()["lastCheckDay"] == "2026-09-08",
              f"но день отмечен — завтра расписание пойдёт как обычно "
              f"(got {mw.watch_settings()['lastCheckDay']!r})")

        # This is the whole reason it was rebuilt: the controller had no
        # power at 03:00 and came back at 09:00. "Didn't check today" is
        # still true at nine.
        mw.set_watch_settings({"check": True, "at": "03:00"})
        from caravan.admin.state import admin_state as _st
        _st["modelWatch"] = {**_st["modelWatch"], "lastCheckDay": "2026-09-07"}
        calls.clear()
        res = mw.model_watch_tick(at_time("09:00"))
        check(res["fired"] is True,
              f"positive: пропущенное из-за простоя догоняется при первой возможности (got {res})")

        # A freshly saved setting doesn't fire retroactively. The hour is SAID,
        # not taken from the wall clock: "now + 1 hour" wraps past midnight, so
        # at 23:05 the "still ahead today" case became "already passed" and the
        # pin inverted — a snapshot going red on the hour it was run.
        st = mw.set_watch_settings({"check": True, "at": "03:00"}, now=at_time("18:00"))
        check(st["lastCheckDay"] == "2026-09-08",
              f"включение при УЖЕ прошедшем времени помечает день отработанным "
              f"(got {st.get('lastCheckDay')!r})")
        st = mw.set_watch_settings({"check": True, "at": "18:00"}, now=at_time("18:00"))
        check(st["lastCheckDay"] == "2026-09-08",
              f"boundary: РОВНО назначенная минута считается прошедшей (got {st.get('lastCheckDay')!r})")
        future = "19:00"
        st = mw.set_watch_settings({"check": True, "at": future}, now=at_time("18:00"))
        check(st["lastCheckDay"] == "",
              f"а время ВПЕРЕДИ сегодня — не помечает: выставил на потом, сработает потом "
              f"(got {st.get('lastCheckDay')!r})")

        print("разбор времени:")
        check(mw.watch_settings()["at"] == future, "время читается обратно как записано")
        try:
            mw.set_watch_settings({"check": True, "at": "25:00"})
            check(False, "25:00 — не время суток, должен быть отказ")
        except Exception as exc:
            check("out of range" in str(exc), f"negative: 25:00 отвергнуто (got {exc})")
        try:
            mw.set_watch_settings({"check": True, "at": "полночь"})
            check(False, "мусор вместо времени — должен быть отказ")
        except Exception as exc:
            check("HH:MM" in str(exc), f"negative: мусор отвергнут, а не подменён умолчанием (got {exc})")
        st = mw.set_watch_settings({"check": True, "at": ""})
        check(st["at"] == future,
              f"пропущенное время СОХРАНЯЕТ настроенное, а не сбрасывает на умолчание: "
              f"запрос без поля не должен стирать выбор оператора (got {st['at']})")
        fake.pop("modelWatch", None)
        check(mw.watch_settings()["at"] == mw.DEFAULT_WATCH_AT,
              f"а когда не настраивали ни разу — умолчание {mw.DEFAULT_WATCH_AT} "
              f"(got {mw.watch_settings()['at']})")
        fake["modelWatch"] = {"check": True, "at": "не время"}
        check(mw.watch_settings()["at"] == mw.DEFAULT_WATCH_AT,
              "испорченное значение в состоянии не роняет страницу — показываем умолчание")

        print("кто крутит расписание:")
        import inspect
        import caravan.admin.cell_schedule as sched_mod
        src = inspect.getsource(sched_mod.start_scheduler_thread)
        check("model_watch_tick()" in src,
              "сверка ездит на ОБЩЕМ тике раз в минуту — своего потока у неё больше нет")
        check(not hasattr(mw, "watch_loop") and not hasattr(mw, "start_watch_thread"),
              "и старый поток, спавший сутки, удалён, а не оставлен рядом")

    finally:
        hf_mod.hf_list_files = real_hf
        mw.local_repos = real_list
        import caravan.admin.state as state_mod
        state_mod.save_admin_state = real_save

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("model-watch snapshots hold")


if __name__ == "__main__":
    main()
