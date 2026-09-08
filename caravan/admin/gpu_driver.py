"""The GPU driver: what's installed, what's available, and a one-button update.

The driver is the one part of the fleet that could, until now, only be
updated by hand over ssh, and it's usually noticed at the worst moment:
2026-09-06 a card hung under load (`NVRM: Xid 8`, "CUDA error: the launch
timed out"), while the repository already held a version fifteen releases
newer. That's also when it turned out "driver version" is TWO different
numbers, not to be confused:

* RUNNING — the one currently in the kernel (nvidia-smi reports it);
* INSTALLED — the one sitting in packages (dpkg reports it).

Right after an update they diverge and stay different until a reboot. One
number instead of two would say "updated" in a case that's really "will
update after a reboot", and the operator would go check a fix that doesn't
exist yet.

Packages are installed ONLY from an allowlist (`nvidia-driver-<N>` and
`-open`): the name arrives from the browser, and apt must never receive
anything arbitrary from there.
"""
import os
import re
import threading
import time

from caravan.common.errors import AppError
from caravan.common.procs import run

#: The one name shape that can be passed to apt. Everything else is refused.
PACKAGE_RE = re.compile(r"^nvidia-driver-(\d{2,4})(-open)?$")
#: How often the background watcher checks the repository (seconds).
WATCH_INTERVAL_SECONDS = int(os.environ.get("LLAMA_DRIVER_WATCH_SECONDS") or 6 * 3600)

_status_cache = {"t": 0.0, "data": None}
_lock = threading.Lock()


def _version_key(text):
    """A version as a list of numbers — "610.43.02" beats "595.84" part by
    part, not as a string."""
    return [int(part) for part in re.findall(r"\d+", str(text or ""))] or [0]


def _driver_key(text):
    """Just the driver's OWN version, without the Debian revision.

    nvidia-smi says "595.84", dpkg says "595.84-0ubuntu0.24.04.1". Comparing
    those two strings as-is always makes the installed one "older" than the
    running one, and the panel would ask for a reboot right after one already
    happened (found by a pin).
    """
    return _version_key(str(text or "").split("-", 1)[0])


#: A driver version looks like "610.43.02" — and nothing else.
VERSION_RE = re.compile(r"^\d+(\.\d+)+$")


def running_version():
    """(version in the kernel, error text). An empty version is an answer, not
    a skip.

    Right after an install, nvidia-smi prints "Failed to initialize NVML:
    Driver/library version mismatch" — to stdout, on one line, exactly where a
    number is expected. The first cut took the first line as-is, and the
    "running now" badge ended up showing an error sentence (found on a
    production host right after the first update through the UI). A number
    has to look like a number; everything else is an error, and is shown as one.
    """
    res = run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], timeout=8)
    text = ((res.get("stdout") or "") + "\n" + (res.get("stderr") or "")).strip()
    for line in text.splitlines():
        if VERSION_RE.match(line.strip()):
            return line.strip(), ""
    return "", " ".join(text.split())[:200]


def installed_packages():
    """Installed driver metapackages: [{package, version}], newest first."""
    res = run(["dpkg-query", "-W", "-f=${Package} ${Version} ${Status}\\n", "nvidia-driver-*"], timeout=10)
    found = []
    for line in (res.get("stdout") or "").splitlines():
        parts = line.split()
        # dpkg's status is three words, and the THIRD one carries the value.
        # A removed package has "not-installed" there, and a check for "does
        # the status contain the word installed" counted it as installed: on
        # a production host that's how nvidia-driver-595 version "unknown"
        # showed up — a package that isn't actually there.
        if len(parts) < 5 or parts[4] != "installed":
            continue
        if PACKAGE_RE.match(parts[0]):
            found.append({"package": parts[0], "version": parts[1]})
    return sorted(found, key=lambda row: _version_key(row["version"]), reverse=True)


def package_installed(name):
    """Whether a package with this name is installed. Same strictness about
    status as above."""
    if not name:
        return False
    res = run(["dpkg-query", "-W", "-f=${Package} ${Version} ${Status}\\n", name], timeout=10)
    for line in (res.get("stdout") or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == name and parts[4] == "installed":
            return True
    return False


def available_packages():
    """Candidates from apt: [{package, version}], newest first.

    Asks policy, not search: what's needed is the CANDIDATE version, and only
    policy knows that. Packages are taken from apt-cache's listing, filtered
    by the same allowlist as input from the browser.
    """
    listing = run(["apt-cache", "--names-only", "search", "^nvidia-driver-[0-9]+(-open)?$"], timeout=20)
    names = [line.split(" - ")[0].strip() for line in (listing.get("stdout") or "").splitlines()]
    names = [n for n in names if PACKAGE_RE.match(n)]
    if not names:
        return []
    policy = run(["apt-cache", "policy", *names], timeout=25)
    found, current = [], ""
    for line in (policy.get("stdout") or "").splitlines():
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1].strip()
        elif current and line.strip().startswith("Candidate:"):
            version = line.split(":", 1)[1].strip()
            if version and version != "(none)":
                found.append({"package": current, "version": version})
            current = ""
    return sorted(found, key=lambda row: _version_key(row["version"]), reverse=True)


def _pick_newest(available, installed_top):
    """The newest candidate of the SAME flavor as what's currently installed.

    `nvidia-driver-610` and `nvidia-driver-610-open` are one version and two
    different packages (the proprietary module and the open one). Taking
    "first by version" would silently offer to jump from the open module to
    the proprietary one: on Blackwell that isn't a nuance, it's a different
    driver. When nothing is installed, the open one is taken: it's both the
    recommendation and what we run.
    """
    if not available:
        return None
    top = _version_key(available[0]["version"])
    same = [row for row in available if _version_key(row["version"]) == top]
    want_open = str((installed_top or {}).get("package") or "").endswith("-open") or not installed_top
    for row in same:
        if row["package"].endswith("-open") == want_open:
            return row
    return same[0]


#: Package name for the SIGNED modules. Its shape is checked before apt the
#: same way the driver name is: only something built from the allowlist gets
#: through here.
MODULES_RE = re.compile(r"^linux-modules-nvidia-(\d{2,4})(-open)?-[a-z0-9.\-]+$")


def secure_boot_enabled():
    """Whether Secure Boot is on. No mokutil means we assume it's off.

    This isn't a configuration nuance — it's whether the kernel will accept
    the module at all. On 2026-09-07 the update button installed
    `nvidia-driver-610-open` — and only that. The module was built through
    DKMS and signed with an ephemeral kernel-build key that isn't registered
    in firmware; after the reboot, `modprobe nvidia` answered "Key was
    rejected by service", and the card disappeared entirely. It had worked
    until then because a Canonical package of SIGNED modules had been sitting
    alongside the driver, and our update silently removed it along with the
    old version.
    """
    res = run(["mokutil", "--sb-state"], timeout=10)
    return "secureboot enabled" in (res.get("stdout") or "").strip().lower()


def module_loaded(name="nvidia"):
    """Whether the kernel module is loaded. /proc/modules, no subprocess."""
    try:
        with open("/proc/modules", "r", encoding="utf-8", errors="replace") as fh:
            return any(line.split(" ", 1)[0] == name for line in fh)
    except OSError:
        return False


def running_kernel():
    return os.uname().release


def _kernel_series(release=None):
    """"7.0.0-31-generic" → "7.0.0-31": what a modules package's version starts with."""
    match = re.match(r"^(\d+\.\d+\.\d+-\d+)", str(release or running_kernel()))
    return match.group(1) if match else ""


def _os_release_id():
    """VERSION_ID from /etc/os-release — the HWE metapackage's suffix ("24.04")."""
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("VERSION_ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def signed_modules_package(driver_package, release=None):
    """The signed-modules metapackage for the RUNNING kernel — or "".

    The driver name ("nvidia-driver-610-open") gives the number and flavor,
    the kernel gives the suffix. There are two candidates (HWE and GA), and
    the pick isn't the first one that exists but the one whose version starts
    with the running kernel's series: a metapackage from a different series
    would drag in YET ANOTHER kernel, and a module for the current one would
    never show up. The last fallback is a package named after the exact kernel.
    """
    match = PACKAGE_RE.match(str(driver_package or "").strip())
    if not match:
        return ""
    base = f"linux-modules-nvidia-{match.group(1)}{match.group(2) or ''}"
    series = _kernel_series(release)
    version_id = _os_release_id()
    names = []
    if version_id:
        names.append(f"{base}-generic-hwe-{version_id}")
    names.append(f"{base}-generic")
    names.append(f"{base}-{release or running_kernel()}")
    policy = {row["package"]: row["version"] for row in _policy_candidates(names)}
    for name in names:
        version = policy.get(name) or ""
        if version and (not series or version.startswith(series)):
            return name
    return ""


def _policy_candidates(names):
    """apt-cache policy for the given names → [{package, version}]."""
    if not names:
        return []
    policy = run(["apt-cache", "policy", *names], timeout=25)
    found, current = [], ""
    for line in (policy.get("stdout") or "").splitlines():
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1].strip()
        elif current and line.strip().startswith("Candidate:"):
            version = line.split(":", 1)[1].strip()
            if version and version != "(none)":
                found.append({"package": current, "version": version})
            current = ""
    return found


def _update_command(driver_package, modules_package):
    """The update command line — as a pure function, so it can be pinned.

    Without signed modules it's a single apt-get. With them, it's the same
    apt-get plus two steps, without which the signed module just sits there
    unused: a DKMS build lands in updates/dkms/, and that directory ranks
    ABOVE kernel/ in the search order, so modprobe keeps picking the
    unsigned one and getting rejected. So the DKMS build for the running
    kernel is removed, and dependencies are recomputed.
    """
    apt = ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y",
           "--no-install-recommends", driver_package]
    if not modules_package:
        return ["sudo", "-n", *apt]
    kernel = running_kernel()
    script = (
        f"{' '.join(apt)} {modules_package} && "
        f"for m in $(dkms status 2>/dev/null | sed -n 's/^\\(nvidia\\/[^,: ]*\\).*/\\1/p' | sort -u); do "
        f"dkms remove \"$m\" -k {kernel} >/dev/null 2>&1 || true; done; "
        f"depmod -a {kernel}"
    )
    return ["sudo", "-n", "bash", "-c", script]


#: The marker Ubuntu itself uses to ask for a reboot, and its package list.
REBOOT_MARKER = "/var/run/reboot-required"
REBOOT_MARKER_PKGS = REBOOT_MARKER + ".pkgs"


def _reboot_pending():
    return os.path.exists(REBOOT_MARKER)


def reboot_pending_packages():
    """Packages the OS wants a reboot for. Empty means the list is unknown.

    The OS has its own reasons: the kernel, libc, anything. As long as it was
    called by the same words as ours ("the kernel will switch to the new
    driver"), the panel confidently explained someone else's reason as ours —
    and did so exactly when our two versions already matched and there was
    nothing left to explain.
    """
    try:
        with open(REBOOT_MARKER_PKGS, "r", encoding="utf-8", errors="replace") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:
        return []


def driver_status(ttl=120):
    """What's installed, what's running, what's available, and whether a
    reboot is needed."""
    now = time.time()
    if _status_cache["data"] and now - _status_cache["t"] < ttl:
        return _status_cache["data"]
    running, running_error = running_version()
    installed = installed_packages()
    available = available_packages()
    installed_top = installed[0] if installed else None
    newest = _pick_newest(available, installed_top)
    # "There's something to install" only when the candidate is NEWER than
    # what's installed. Equal versions aren't an update, they're the same
    # package, and a button over it would be lying.
    update = bool(newest and (not installed_top
                              or _version_key(newest["version"]) > _version_key(installed_top["version"])))
    # Installed is newer than running → a reboot will switch the kernel to it.
    # This is OUR reason; the OS can have its own, and the two must not be
    # mixed into one flag.
    reboot = bool(installed_top and running
                  and _driver_key(installed_top["version"]) > _driver_key(running))
    # nvidia-smi isn't answering with a number, yet packages are installed —
    # this is exactly the gap between installing and rebooting that this
    # field exists to cover.
    if installed_top and not running and running_error:
        reboot = True
    secure_boot = secure_boot_enabled()
    signed = signed_modules_package(installed_top["package"]) if installed_top else ""
    signed_ok = bool(signed) and package_installed(signed)
    rejected = bool(secure_boot and installed_top and not running and not module_loaded())
    os_reboot = _reboot_pending()
    os_packages = reboot_pending_packages() if os_reboot else []
    # A rejected module isn't fixed by a reboot — the reboot has already
    # failed to load it once.
    if rejected:
        reboot = False
        # The reason is appended to the same text the panel already shows
        # verbatim: "couldn't communicate with the NVIDIA driver" is true, but
        # names neither the culprit nor the fix, and the operator goes off to
        # reboot a second time.
        why = "Secure Boot rejected the unsigned kernel module"
        if signed and not signed_ok:
            why += f"; install {signed}"
        running_error = f"{running_error} — {why}" if running_error else why
    data = {
        "ok": True,
        "running": running,
        # Why there's no number. An empty field with no reason would read as
        # "no driver installed", when it's most often "a new one was
        # installed, the kernel is still on the old one".
        "runningError": running_error,
        "installed": installed_top,
        "installedAll": installed,
        "available": available[:8],
        "newest": newest,
        "updateAvailable": update,
        # Two reasons, two fields. One word "reboot" for both meant that, on
        # a host whose versions already matched, the panel insisted the
        # kernel still had to switch to the new driver (found by a live check
        # on 2026-09-07). rebootRequired stays their sum: earlier readers look
        # at that one.
        "rebootForDriver": reboot,
        "rebootPending": os_reboot,
        "rebootPendingPackages": os_packages,
        "rebootRequired": reboot or os_reboot,
        "auto": auto_settings(),
        "secureBoot": secure_boot,
        "signedModules": signed,
        "signedModulesInstalled": signed_ok,
        # Packages installed, module not loaded, Secure Boot on — that's not
        # "no card", it's a rejected signature. Without this field the panel
        # would show 610 installed and an empty spot where the GPU should be:
        # absence drawn as normal.
        "moduleRejected": rejected,
        "checkedAt": int(now),
    }
    _status_cache.update(t=now, data=data)
    return data


def auto_settings():
    """The watcher's settings: check on its own and install on its own are two
    separate checkboxes."""
    from caravan.admin.state import admin_state
    saved = admin_state.get("gpuDriverAuto") if isinstance(admin_state.get("gpuDriverAuto"), dict) else {}
    return {"check": bool(saved.get("check")), "install": bool(saved.get("install")),
            "lastCheckAt": int(saved.get("lastCheckAt") or 0),
            "lastInstall": saved.get("lastInstall") or None}


def set_auto_settings(payload):
    """Both checkboxes are set together: an omitted one means "off", same as
    the window setting."""
    from caravan.admin.state import admin_state, save_admin_state
    saved = dict(admin_state.get("gpuDriverAuto") or {})
    saved["check"] = bool((payload or {}).get("check"))
    saved["install"] = bool((payload or {}).get("install"))
    # Installing without looking is not allowed: installing without checking
    # means installing whatever happens to be in the repository.
    if saved["install"]:
        saved["check"] = True
    admin_state["gpuDriverAuto"] = saved
    save_admin_state()
    _status_cache.update(t=0.0, data=None)
    return auto_settings()


def driver_update(package):
    """Install the named driver metapackage. Returns the background job id."""
    from caravan.admin.status import _start_shared_job
    name = str(package or "").strip()
    if not PACKAGE_RE.match(name):
        raise AppError(f"not a driver package: {name!r}", 400)
    # The name must be IN THE CANDIDATE LIST, not merely shaped like a real
    # one: the allowlist rules out the shape, this rules out non-existence.
    if not any(row["package"] == name for row in available_packages()):
        raise AppError(f"no such driver package in apt: {name}", 404)
    # Under Secure Boot, a driver without signed modules is a driver the
    # kernel will refuse to load. Install both in one transaction.
    modules = signed_modules_package(name) if secure_boot_enabled() else ""
    if modules and not MODULES_RE.match(modules):
        raise AppError(f"not a modules package: {modules!r}", 500)
    _status_cache.update(t=0.0, data=None)
    return _start_shared_job(_update_command(name, modules), tag=f"driver:{name}")


def driver_watch_pass(now=None):
    """One watcher pass: refresh the data, and install if permitted.

    Returns what it did — for the log and for the snapshot. Does nothing
    while both checkboxes are off: a watcher that reaches into apt without
    being asked isn't a setting anymore, it's a decision made for the operator.
    """
    from caravan.admin.state import admin_state, save_admin_state
    auto = auto_settings()
    if not auto["check"]:
        return {"checked": False, "installed": None, "reason": "auto-check off"}
    _status_cache.update(t=0.0, data=None)
    status = driver_status(ttl=0)
    saved = dict(admin_state.get("gpuDriverAuto") or {})
    saved["lastCheckAt"] = int(now or time.time())
    admin_state["gpuDriverAuto"] = saved
    save_admin_state()
    if not (auto["install"] and status["updateAvailable"] and status["newest"]):
        return {"checked": True, "installed": None,
                "reason": "up to date" if not status["updateAvailable"] else "auto-install off"}
    name = status["newest"]["package"]
    try:
        driver_update(name)
    except AppError as exc:
        return {"checked": True, "installed": None, "reason": str(exc)}
    saved["lastInstall"] = {"package": name, "version": status["newest"]["version"],
                            "at": int(now or time.time())}
    admin_state["gpuDriverAuto"] = saved
    save_admin_state()
    return {"checked": True, "installed": name, "reason": "started"}


def watch_wait_seconds(now=None, last=None):
    """Seconds to wait before the next pass; 0 means it is due right now.

    The loop used to sleep FIRST and check after, so every restart pushed the
    first check a whole interval away. The service restarts on every deploy,
    and deploys are more frequent than the six-hour interval — so the watcher
    looked switched on, reported no trouble, and had never run a single pass.
    Absence drawn as normality, in the one place meant to notice absence.

    A missing record is NOT "overdue". The first time under this schedule (the
    checkbox was already on when the caravan updated) we wait a full interval
    instead of reaching into apt in the first second after a deploy: with
    auto-install on, an immediate pass would start a driver install in a minute
    the operator never chose. Same rule as the model watch, for the same
    reason — "we weren't running when it came due" and "we have only just
    started counting" are different things.

    A record dated in the future (a clock jump) waits one interval, not until
    that future arrives: a wrong clock must not switch the watcher off.
    """
    if not last:
        return WATCH_INTERVAL_SECONDS
    elapsed = (now if now is not None else time.time()) - last
    remaining = WATCH_INTERVAL_SECONDS - elapsed
    if remaining <= 0:
        return 0
    return min(remaining, WATCH_INTERVAL_SECONDS)


def watch_loop():
    """Daemon: one pass every WATCH_INTERVAL_SECONDS. Silent while the
    checkboxes are off.

    Only the FIRST wait consults the schedule — after that a full interval,
    which is also what keeps this loop from spinning: a pass that does nothing
    (checkboxes off) stamps nothing, so re-asking the schedule every turn would
    answer "overdue" forever.
    """
    wait = watch_wait_seconds(last=auto_settings().get("lastCheckAt"))
    while True:
        if wait > 0:
            time.sleep(wait)
        try:
            driver_watch_pass()
        except Exception:
            pass
        wait = WATCH_INTERVAL_SECONDS


def start_watch_thread():
    thread = threading.Thread(target=watch_loop, name="gpu-driver-watch", daemon=True)
    thread.start()
    return thread
