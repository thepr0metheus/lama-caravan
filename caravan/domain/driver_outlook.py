"""Whether a machine's NVIDIA card will be there after its next reboot.

2026-09-26: the automatic updates installed a kernel, held back the
Canonical-signed NVIDIA modules it needed (their driver was in a pocket they
were not allowed), and a reboot the next day came up without the card:
Secure Boot refused the DKMS build, signed by the machine's own key, which
had never been enrolled. Everything that said so was on the machine the
morning before. Its scout (2.19+) reports those facts as `driver`; this is
the one place that reads them.
"""
from __future__ import annotations

import re
from typing import Any


class DriverOutlook:
    """A machine's driver facts and what they mean for its next boot."""

    #: What a fact may be, as the host record keeps it.
    TEXT = 200
    KERNEL = re.compile(r"^\d[\w.+-]*$")
    VERSION = re.compile(r"^\d+(?:\.\d+)+$")
    DRIVER_PACKAGE = re.compile(r"^nvidia-driver-(\d+)(-open)?$")

    def __init__(self, facts: Any):
        self.facts = self.clean(facts)

    @classmethod
    def clean(cls, raw: Any) -> dict[str, Any] | None:
        """The facts as the host record keeps them: a kernel and a version
        only in their own shape, the rest trimmed and cut, a flag only as a
        flag. None when the report has none — an older scout, not Linux, no
        NVIDIA driver."""
        if not isinstance(raw, dict):
            return None

        def text(value, pattern=None):
            if not isinstance(value, str):
                return None
            value = value.strip()[:cls.TEXT]
            return value if value and (pattern is None or pattern.match(value)) else None

        def flag(value):
            return value if isinstance(value, bool) else None

        module = raw.get("nextModule")
        key = raw.get("dkmsKey")
        return {
            "secureBoot": flag(raw.get("secureBoot")),
            "kernelRunning": text(raw.get("kernelRunning"), cls.KERNEL),
            "kernelNext": text(raw.get("kernelNext"), cls.KERNEL),
            "loaded": text(raw.get("loaded"), cls.VERSION),
            "installed": text(raw.get("installed"), cls.VERSION),
            "nextModule": ({"path": text(module.get("path")), "version": text(module.get("version"), cls.VERSION),
                            "signer": text(module.get("signer")) or ""}
                           if isinstance(module, dict) and text(module.get("path")) else None),
            "dkmsKey": ({"signer": text(key.get("signer")), "enrolled": flag(key.get("enrolled"))}
                        if isinstance(key, dict) else None),
            "package": text(raw.get("package"), cls.DRIVER_PACKAGE),
        }

    def signed_modules_package(self, kernel: str) -> str | None:
        """The Canonical-signed modules for `kernel`, named after the driver
        installed: nvidia-driver-610-open → linux-modules-nvidia-610-open-<kernel>.
        None when the driver package is not known."""
        package = (self.facts or {}).get("package")
        found = self.DRIVER_PACKAGE.match(package or "")
        if not found:
            return None
        return f"linux-modules-nvidia-{found.group(1)}{found.group(2) or ''}-{kernel}"

    def next_module_refused(self) -> str | None:
        """Why Secure Boot will refuse the module the next kernel would load:
        "unsigned", or "untrusted-key" (signed by the machine's DKMS key,
        which the firmware does not know). None otherwise: Secure Boot off,
        a signer the kernel trusts (Canonical's, for `linux-modules-nvidia-*`),
        or one this cannot judge — a key whose enrolment is unknown, a
        vendor's it has never seen. Only what the facts prove is said."""
        facts = self.facts or {}
        module = facts.get("nextModule")
        if facts.get("secureBoot") is not True or not module:
            return None
        signer = module.get("signer") or ""
        if not signer:
            return "unsigned"
        key = facts.get("dkmsKey") or {}
        if key.get("signer") and signer == key["signer"] and key.get("enrolled") is False:
            return "untrusted-key"
        return None

    def warnings(self) -> list[dict[str, Any]]:
        """What the board says before it happens:

        - nextBootNoDriver — a new kernel boots next and the card will not
          come with it: it has no nvidia module ("missing"), or Secure Boot
          will refuse the one it has ("unsigned", "untrusted-key"); with the
          package that fixes it when the driver package is known.
        - rebootForDriver — the driver installed is not the one loaded: a new
          process cannot open the card until a reboot, the running ones keep
          working.
        """
        facts = self.facts
        if not facts:
            return []
        out = []
        following, running = facts.get("kernelNext"), facts.get("kernelRunning")
        if following and running and following != running:
            reason = "missing" if facts.get("nextModule") is None else self.next_module_refused()
            if reason:
                out.append({"kind": "nextBootNoDriver", "reason": reason, "kernel": following,
                            "package": self.signed_modules_package(following)})
        loaded, installed = facts.get("loaded"), facts.get("installed")
        if loaded and installed and loaded != installed:
            out.append({"kind": "rebootForDriver", "loaded": loaded, "installed": installed})
        return out
