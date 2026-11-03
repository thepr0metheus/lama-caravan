#!/usr/bin/env python3
"""Keeps a machine's NVIDIA card through kernel updates under Secure Boot.

The card needs a kernel module, and under Secure Boot only a module signed by
a key the firmware trusts is loaded — on these machines Canonical's: the
packages linux-modules-nvidia-<series>[-open]-<kernel>, one per kernel, built
for one driver series. A DKMS build is signed by the machine's own key, which
was never enrolled, and the kernel refuses it.

Three times the automatic updates installed a kernel without those modules,
and the next boot came up without the card:
- 2026-09-07: a driver update that dropped its signed companion;
- 2026-09-26: the modules' driver was in a pocket the updates were not allowed;
- 2026-10-09: Ubuntu moved the driver from 610 to 615 by renamed packages,
  unattended-upgrade read a conffile the new package takes over as a prompt
  and skipped the series — not the kernel it installed in the same run.

Two jobs, and a look:
  modules  after the automatic updates (apt-daily-upgrade.service): every
           installed kernel gets the signed modules of the machine's driver
           series when apt offers them; then `boot`.
  boot     after every dpkg run (an APT hook): GRUB boots the newest kernel
           whose module of that series is there — when the newest has none,
           the newest older one that has: never a kernel without the card
           while one with it is left. A machine with no NVIDIA driver is left
           as it is.
  status   what the two would do, changing nothing.

Installed by scripts/install-nvidia-kernel-guard.sh as
/usr/local/sbin/nvidia-kernel-guard. Standalone on purpose: root runs it, so
it is a root-owned copy that imports nothing from a folder a user can write.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


class Host:
    """The machine as the guard asks it: processes, files and the journal.
    The one door to it — the tests put a fake machine here."""

    def run(self, cmd: list[str], env: dict | None = None) -> tuple[int, str]:
        """(exit code, stdout and stderr). A tool that is not there is an
        answer too: code 127 and why."""
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                                  env=None if env is None else {**os.environ, **env})
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)
        return done.returncode, f"{done.stdout or ''}{done.stderr or ''}"

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def read(self, path: str) -> str | None:
        """A file's text, or None when it is missing or not ours to read."""
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def read_bytes(self, path: str) -> bytes | None:
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def say(self, text: str) -> None:
        """Into the run's output and the journal (journalctl -t nvidia-kernel-guard)."""
        print(f"nvidia-kernel-guard: {text}", flush=True)
        self.run(["logger", "-t", "nvidia-kernel-guard", "--", text])


class Version:
    """Dotted versions compared as numbers: 7.0.0-38 after 7.0.0-4."""

    @staticmethod
    def key(text: str) -> tuple:
        return tuple(int(n) for n in re.findall(r"\d+", str(text)))


class Packages:
    """What dpkg says is installed, and what apt would install."""

    def __init__(self, host: Host):
        self.host = host

    def installed(self, *patterns: str) -> list[str]:
        """Names installed now ("ii"), for dpkg-query patterns; a package that
        was removed with its config kept ("rc") is not installed."""
        code, out = self.host.run(["dpkg-query", "-W", "-f", "${db:Status-Abbrev} ${Package}\n", *patterns])
        names = []
        for line in out.splitlines():
            status, _, name = line.strip().partition(" ")
            if status.startswith("ii") and name:
                names.append(name.strip())
        return names

    def candidate(self, name: str) -> str | None:
        """The version apt would install, or None when apt offers none."""
        code, out = self.host.run(["apt-cache", "policy", name])
        found = re.search(r"^\s*Candidate:\s*(\S+)", out, re.M)
        if code != 0 or not found or found.group(1) == "(none)":
            return None
        return found.group(1)


class Driver:
    """The machine's NVIDIA driver series and flavour, from its packages: the
    highest nvidia-kernel-common-<series> installed. After a move to a new
    series the old one's packages stay, as transitional ones, so the highest
    is the one the libraries belong to. The open flavour — the one a
    Blackwell card needs — is known by its kernel source package."""

    COMMON = re.compile(r"^nvidia-kernel-common-(\d+)$")

    def __init__(self, series: int, open_modules: bool):
        self.series = series
        self.open_modules = open_modules

    @classmethod
    def of(cls, packages: Packages) -> Driver | None:
        series = [int(m.group(1)) for name in packages.installed("nvidia-kernel-common-*")
                  for m in [cls.COMMON.match(name)] if m]
        if not series:
            return None
        top = max(series)
        flavours = set(packages.installed(f"nvidia-kernel-source-{top}*", f"nvidia-driver-{top}*"))
        return cls(top, bool(flavours & {f"nvidia-kernel-source-{top}-open", f"nvidia-driver-{top}-open"}))

    @property
    def name(self) -> str:
        return f"{self.series}{'-open' if self.open_modules else ''}"

    def modules_package(self, kernel: str) -> str:
        return f"linux-modules-nvidia-{self.name}-{kernel}"

    def module_path(self, kernel: str) -> str:
        """Where the signed module of this series lies for `kernel`."""
        return f"/lib/modules/{kernel}/kernel/nvidia-{self.name}/nvidia.ko"


class Kernels:
    """The kernel images installed, newest first. Metapackages
    (linux-image-generic-hwe-24.04) name no kernel and are not counted."""

    NAME = re.compile(r"^linux-image-(\d+\.\d+\.\d+-\d+-[a-z0-9]+)$")

    def __init__(self, packages: Packages):
        self.packages = packages

    def all(self) -> list[str]:
        found = {m.group(1) for name in self.packages.installed("linux-image-*") for m in [self.NAME.match(name)] if m}
        return sorted(found, key=Version.key, reverse=True)


class SecureBoot:
    """The firmware's own word: four bytes of attributes, then 1 (on) or 0
    (off). Readable by anyone; absent on a machine that boots without EFI."""

    VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"

    def __init__(self, host: Host):
        self.host = host

    def on(self) -> bool | None:
        raw = self.host.read_bytes(self.VAR)
        if raw is None:
            return False if not self.host.exists("/sys/firmware/efi") else None
        return raw[-1:] == b"\x01" if len(raw) >= 5 else None


class Grub:
    """What GRUB boots: the menu in grub.cfg, and the entry it is told to boot.

    The guard steers only a GRUB that boots the saved entry (GRUB_DEFAULT=saved,
    set by the installer). "0" — the first entry — boots the newest kernel;
    an older one is named by its place in the "Advanced options" submenu."""

    CFG = "/boot/grub/grub.cfg"
    DEFAULTS = "/etc/default/grub"
    ENV = "/boot/grub/grubenv"
    SUBMENU = re.compile(r"^\s*submenu\s+'[^']*'.*?\$menuentry_id_option\s+'([^']+)'", re.M)
    ENTRY = re.compile(r"^\s*menuentry\s+'[^']*'.*?\$menuentry_id_option\s+'(gnulinux-(\S+?)-advanced-[^']+)'", re.M)

    def __init__(self, host: Host):
        self.host = host

    def steers(self) -> bool:
        text = self.host.read(self.DEFAULTS) or ""
        values = re.findall(r"^\s*GRUB_DEFAULT\s*=\s*\"?([^\"\s#]*)", text, re.M)
        return bool(values) and values[-1] == "saved"

    def entries(self) -> dict | None:
        """kernel → the entry that boots it ("submenu>entry"); None when grub.cfg cannot be read."""
        text = self.host.read(self.CFG)
        if text is None:
            return None
        submenu = self.SUBMENU.search(text)
        prefix = f"{submenu.group(1)}>" if submenu else ""
        return {kernel: prefix + entry for entry, kernel in self.ENTRY.findall(text)}

    def chosen(self) -> str | None:
        """The saved entry, or None when none is saved (GRUB then boots the first)."""
        code, out = self.host.run(["grub-editenv", self.ENV, "list"])
        found = re.search(r"^saved_entry=(.*)$", out, re.M)
        return found.group(1).strip() if code == 0 and found and found.group(1).strip() else None

    def choose(self, entry: str) -> bool:
        code, out = self.host.run(["grub-set-default", entry])
        return code == 0


class Guard:
    """Decides which kernels can bring the card up, fetches the modules that
    are missing, and points GRUB at the newest kernel that has them."""

    DPKG = ["-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]

    def __init__(self, host: Host | None = None):
        self.host = host or Host()
        self.packages = Packages(self.host)
        self.grub = Grub(self.host)

    def plan(self) -> dict:
        """Everything the two jobs decide from, read once; changes nothing."""
        driver = Driver.of(self.packages)
        kernels = Kernels(self.packages).all()
        secure = SecureBoot(self.host).on()
        good = [k for k in kernels if driver and self._carries(driver, k, secure)]
        return {"driver": driver, "kernels": kernels, "good": good, "secureBoot": secure,
                "target": good[0] if good else None, "newest": kernels[0] if kernels else None}

    def _carries(self, driver: Driver, kernel: str, secure: bool | None) -> bool:
        """Whether `kernel` would load the card's module of the driver series.
        A DKMS build counts only where Secure Boot is known to be off."""
        if self.host.exists(driver.module_path(kernel)):
            return True
        return secure is False and self.host.exists(f"/lib/modules/{kernel}/updates/dkms/nvidia.ko")

    def boot(self) -> int:
        plan = self.plan()
        if not plan["driver"]:
            return 0
        if not plan["target"]:
            self.host.say(f"no installed kernel has the {plan['driver'].name} module: GRUB is left as it is")
            return 1
        if not self.grub.steers():
            self.host.say("GRUB_DEFAULT is not 'saved': the guard cannot choose the kernel; run its installer")
            return 1
        if plan["target"] == plan["newest"]:
            wanted = "0"
        else:
            entry = (self.grub.entries() or {}).get(plan["target"])
            if not entry:
                self.host.say(f"grub.cfg has no entry for {plan['target']}: GRUB is left as it is")
                return 1
            wanted = entry
        if (self.grub.chosen() or "0") == wanted:
            return 0
        if not self.grub.choose(wanted):
            self.host.say(f"grub-set-default {wanted} failed")
            return 1
        if wanted == "0":
            self.host.say(f"GRUB boots the newest kernel again, {plan['target']}: it has the {plan['driver'].name} module")
        else:
            self.host.say(f"GRUB boots {plan['target']}, not the newest {plan['newest']}: "
                          f"{plan['newest']} has no {plan['driver'].name} module yet")
        return 0

    def modules(self) -> int:
        plan = self.plan()
        driver = plan["driver"]
        if not driver:
            return 0
        missing = [k for k in plan["kernels"] if k not in plan["good"]]
        offered, absent = [], []
        for kernel in missing:
            package = driver.modules_package(kernel)
            (offered if self.packages.candidate(package) else absent).append(package)
        # An older kernel without the series' modules is no news after a move to
        # a new series - it is never booted while a newer one carries the card.
        # A kernel newer than every one that carries it is: it is the one a
        # boot would have picked.
        newest_good = Version.key(plan["good"][0]) if plan["good"] else ()
        for kernel in missing:
            package = driver.modules_package(kernel)
            if package in absent and Version.key(kernel) > newest_good:
                self.host.say(f"apt offers no {package}: {kernel} would come up without the card")
        code = 0
        if offered:
            self.host.say(f"installing the signed modules: {' '.join(offered)}")
            code, out = self.host.run(["apt-get", "install", "-y", "--no-install-recommends", *self.DPKG, *offered],
                                      env={"DEBIAN_FRONTEND": "noninteractive"})
            if code != 0:
                last = (out.strip().splitlines() or [""])[-1]
                self.host.say(f"apt-get install failed ({code}): {last}")
        return max(code, self.boot())

    def status(self) -> int:
        plan = self.plan()
        driver = plan["driver"]
        if not driver:
            print("no NVIDIA driver installed: nothing to guard")
            return 0
        print(f"driver series: {driver.name}; Secure Boot: {plan['secureBoot']}")
        for kernel in plan["kernels"]:
            mark = "card" if kernel in plan["good"] else "NO CARD"
            print(f"  {kernel}: {mark}{' (newest)' if kernel == plan['newest'] else ''}")
        print(f"GRUB steered: {self.grub.steers()}; saved entry: {self.grub.chosen() or '(none: the first, newest)'}")
        print(f"boot should go to: {plan['target'] or '(no kernel with the card)'}")
        return 0


def main(argv: list[str]) -> int:
    jobs = {"modules": Guard.modules, "boot": Guard.boot, "status": Guard.status}
    if len(argv) != 1 or argv[0] not in jobs:
        print(f"usage: nvidia-kernel-guard {'|'.join(jobs)}", file=sys.stderr)
        return 2
    return jobs[argv[0]](Guard())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
