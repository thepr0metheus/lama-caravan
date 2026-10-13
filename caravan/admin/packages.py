"""What the running controller is made of, named as osv.dev names it (GET /api/packages).

A check of known vulnerabilities must see what is installed, not what the project's files
ask for (visumap apps-packages.md). The controller pins no library of its own — it is
stdlib-only Python — so what there is to check is the runtime, whatever the interpreter
carries (pip, in the image) and the system under it. The image is Debian (python:3.12-slim),
and Debian's advisories name the SOURCE package: libc6 is glibc, libssl3 is openssl. Asked
by the installed name, osv.dev finds nothing, and nothing reads as "no vulnerabilities". So
a package is listed by its source, with the source's version.

The page carries no copied library (static/ is the caravan's own code): there is no page
part to list. A system whose packages this cannot read says so with `os.listed` false, and
a system it cannot tell is `os: null` — an empty list would read as "nothing to fix".
"""
import importlib.metadata
import platform
import re
from pathlib import Path


class InstalledPackages:
    """The packages of this copy of the controller, read once: a running container does not change."""

    #: What dpkg keeps of every package it knows, installed or not.
    DPKG_STATUS = "var/lib/dpkg/status"

    def __init__(self, root=Path("/"), distributions=importlib.metadata.distributions,
                 python_version=platform.python_version):
        self.root = Path(root)
        self._distributions = distributions
        self._python_version = python_version
        self._listing = None

    def listing(self):
        """{runtime, os, packages}: each package a query osv.dev answers as it is."""
        if self._listing is None:
            system = self.system()
            packages = self.python()
            if system and system["listed"]:
                packages += self.debian(system["version"])
            self._listing = {"runtime": {"name": "python", "version": self._python_version()},
                             "os": system, "packages": packages}
        return self._listing

    def system(self):
        """`ID` and `VERSION_ID` of /etc/os-release, and whether its packages are listed:
        Debian with a numbered release and dpkg's status file only — osv.dev names Debian's
        advisories by the release (`Debian:13`), and an unnumbered one (testing) has none."""
        try:
            text = (self.root / "etc" / "os-release").read_text(encoding="utf-8")
        except OSError:
            return None
        fields = {}
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                fields[key.strip()] = value.strip().strip("\"'")
        name, version = fields.get("ID"), fields.get("VERSION_ID", "")
        if not name:
            return None
        listed = (name == "debian" and bool(re.fullmatch(r"\d+(\.\d+)*", version))
                  and (self.root / self.DPKG_STATUS).is_file())
        return {"name": name, "version": version, "listed": listed}

    def python(self):
        found = {}
        for dist in self._distributions():
            raw = getattr(dist, "name", None) or dist.metadata.get("Name")
            if not raw or not dist.version:
                continue
            name = re.sub(r"[-_.]+", "-", raw).lower()        # as PyPI compares names
            found[(name, dist.version)] = {"ecosystem": "PyPI", "name": name, "version": dist.version}
        return sorted(found.values(), key=lambda p: (p["name"], p["version"]))

    def debian(self, os_version):
        """dpkg's installed packages, each by its source and the source's version: `Source:
        openssl (3.5.1-1)` beside `Version: 3.5.1-1+b1` is openssl 3.5.1-1, the version the
        advisory names. A package without `Source:` is its own source."""
        ecosystem = "Debian:" + os_version.split(".")[0]
        found = {}
        text = (self.root / self.DPKG_STATUS).read_text(encoding="utf-8", errors="replace")
        for record in text.split("\n\n"):
            fields = {}
            for line in record.splitlines():
                if line[:1] in (" ", "\t"):
                    continue                                    # the field above, continued
                key, sep, value = line.partition(":")
                if sep:
                    fields.setdefault(key.strip(), value.strip())
            if fields.get("Status", "").split()[-1:] != ["installed"]:
                continue                                        # removed, half-installed, config only
            source, _, own = (fields.get("Source") or fields.get("Package") or "").partition(" (")
            version = own.rstrip(")").strip() if own else fields.get("Version", "")
            if source and version:
                found[(source, version)] = {"ecosystem": ecosystem, "name": source, "version": version}
        return sorted(found.values(), key=lambda p: (p["name"], p["version"]))


#: The list GET /api/packages answers: this process's own packages, read on the first ask.
INSTALLED_PACKAGES = InstalledPackages()
