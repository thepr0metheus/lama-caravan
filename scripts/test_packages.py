#!/usr/bin/env python3
"""Value snapshot: GET /api/packages — what the running controller is made of, named as
osv.dev names it (visumap apps-packages.md), open without signing in like /healthz.

The controller is stdlib-only Python, so the vulnerability check of the home network sees
the runtime, what the interpreter carries and the system under it. The image is Debian, and
Debian's advisories name the SOURCE package: listed by the installed name (libc6, libssl3t64)
osv.dev finds nothing, and nothing reads as "no vulnerabilities". A system this cannot read
says `listed: false`; one it cannot tell is `os: null`.

Run: python3 scripts/test_packages.py
"""
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import routes  # noqa: E402
from caravan.admin.packages import InstalledPackages  # noqa: E402
from caravan.admin.route_access import ROUTE_ACCESS, RouteAccess  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


DEBIAN_13 = '''PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
ID=debian
'''

# Stanzas as dpkg writes them. libssl3t64 is a binNMU: its own version has +b1, the source's
# does not. A description's continuation line that looks like a field is NOT a field.
DPKG = '''Package: libc6
Status: install ok installed
Architecture: amd64
Multi-Arch: same
Source: glibc
Version: 2.41-12
Description: GNU C Library: Shared libraries

Package: libc6
Status: install ok installed
Architecture: i386
Source: glibc
Version: 2.41-12

Package: libssl3t64
Status: install ok installed
Source: openssl (3.5.1-1)
Version: 3.5.1-1+b1

Package: openssl
Status: install ok installed
Version: 3.5.1-1

Package: tzdata
Status: install ok installed
Description: time zone and daylight-saving time data
 Source: decoy (9.9)
Version: 2025b-4

Package: zlib1g
Status: install ok installed
Source: zlib
Version: 1:1.3.dfsg+really1.3.1-1

Package: oldpkg
Status: deinstall ok config-files
Version: 1.0-1

Package: halfpkg
Status: install reinstreq half-installed
Version: 2.0-1
'''


class Dist:
    def __init__(self, name, version, meta_name=None):
        self.name, self.version = name, version
        self.metadata = {"Name": meta_name or name}


DISTS = [Dist("pip", "25.2"), Dist("Some_Pkg.Name", "1.0"), Dist("pip", "25.2"),
         Dist(None, "1", meta_name="FromMeta"), Dist("broken", "")]
PYPI = [{"ecosystem": "PyPI", "name": "frommeta", "version": "1"},
        {"ecosystem": "PyPI", "name": "pip", "version": "25.2"},
        {"ecosystem": "PyPI", "name": "some-pkg-name", "version": "1.0"}]
DEBIAN = [{"ecosystem": "Debian:13", "name": "glibc", "version": "2.41-12"},
          {"ecosystem": "Debian:13", "name": "openssl", "version": "3.5.1-1"},
          {"ecosystem": "Debian:13", "name": "tzdata", "version": "2025b-4"},
          {"ecosystem": "Debian:13", "name": "zlib", "version": "1:1.3.dfsg+really1.3.1-1"}]


def machine(os_release=None, dpkg=None):
    root = Path(tempfile.mkdtemp(prefix="caravan-packages-"))
    if os_release is not None:
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "os-release").write_text(os_release, encoding="utf-8")
    if dpkg is not None:
        (root / "var/lib/dpkg").mkdir(parents=True)
        (root / "var/lib/dpkg/status").write_text(dpkg, encoding="utf-8")
    asked = []

    def distributions():
        asked.append(1)
        return list(DISTS)
    return InstalledPackages(root=root, distributions=distributions, python_version=lambda: "3.12.12"), asked


print("the image: Debian 13 with dpkg:")
packages, asked = machine(DEBIAN_13, DPKG)
got = packages.listing()
check(got == {"runtime": {"name": "python", "version": "3.12.12"},
              "os": {"name": "debian", "version": "13", "listed": True},
              "packages": PYPI + DEBIAN},
      "runtime, system and every package, each a query osv.dev answers as it is")
names = {p["name"] for p in got["packages"]}
check({"glibc", "openssl", "zlib"} <= names and not names & {"libc6", "libssl3t64", "zlib1g"},
      "a Debian package goes by its SOURCE: osv.dev knows glibc and openssl, not libc6 and libssl3t64")
check({"ecosystem": "Debian:13", "name": "openssl", "version": "3.5.1-1"} in got["packages"]
      and not any(p["version"] == "3.5.1-1+b1" for p in got["packages"]),
      "…with the source's version: a rebuilt binary (+b1) is the advisory's 3.5.1-1")
check(not names & {"oldpkg", "halfpkg"}, "negative: a removed or half-installed package is not on the list")
check("decoy" not in names, "negative: a description's continuation line is not a field")
check(sum(p["name"] == "glibc" for p in got["packages"]) == 1, "negative: two architectures of one package — one entry")
packages.listing()
check(len(asked) == 1, "read once: a running container does not change")

print("a system it cannot read or tell:")
for label, os_release, dpkg, expected_os in (
        ("Ubuntu: dpkg is there, osv.dev names its releases otherwise", 'ID=ubuntu\nVERSION_ID="24.04"\n', DPKG,
         {"name": "ubuntu", "version": "24.04", "listed": False}),
        ("Debian without dpkg's status file", DEBIAN_13, None, {"name": "debian", "version": "13", "listed": False}),
        ("Debian testing: no numbered release, no ecosystem", "ID=debian\n", DPKG,
         {"name": "debian", "version": "", "listed": False})):
    got = machine(os_release, dpkg)[0].listing()
    check(got["os"] == expected_os and got["packages"] == PYPI,
          f"negative: {label} — listed false, and only the Python packages (got {got['os']})")
got = machine()[0].listing()
check(got["os"] is None and got["packages"] == PYPI, "negative: no /etc/os-release — os null, not a guess")


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, body, status=200):
        self.sent.append((status, body))


def answer(path, git_info, listing):
    keep = routes.project_git_info, routes.INSTALLED_PACKAGES
    routes.project_git_info, routes.INSTALLED_PACKAGES = git_info, listing
    try:
        h = Handler()
        routes.GET_ROUTES[path](h, urlparse(path))
        return h.sent
    finally:
        routes.project_git_info, routes.INSTALLED_PACKAGES = keep


print("GET /api/packages:")
image = machine(DEBIAN_13, DPKG)[0]
sent = answer("/api/packages", lambda: {"head": "1a2b3c4"}, image)
check(sent == [(200, {"version": "1a2b3c4", "runtime": {"name": "python", "version": "3.12.12"},
                      "os": {"name": "debian", "version": "13", "listed": True}, "packages": PYPI + DEBIAN})],
      "the list with the commit as its version")
check(sent[0][1]["version"] == answer("/healthz", lambda: {"head": "1a2b3c4"}, image)[0][1]["version"],
      "negative: the same commit /healthz names — the deploy check compares them")
check(answer("/api/packages", lambda: {"head": ""}, image)[0][1]["version"] is None,
      "negative: no commit known — null, as /healthz says it")
check(ROUTE_ACCESS.kind("GET", "/api/packages") == RouteAccess.PUBLIC,
      "open without signing in, like /healthz: names and versions only")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("packages snapshot holds: runtime, system and packages — by value")
