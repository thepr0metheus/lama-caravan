#!/usr/bin/env python3
"""Only the explicit board action may spend a saved subscription reset."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402


class ResetSpendGuard:
    #: The one route that spends one, and the one object that knows the address it is spent at.
    ROUTE = "rust/crates/admin/src/routes/cloud.rs"
    DESK = "rust/crates/admin/src/cloud/resets.rs"

    def check(self):
        errors = []
        spent, known = 0, 0
        for rel, lines in RustSource.files():
            for number, line in enumerate(lines, 1):
                if "SubscriptionResetDesk" in line and ".consume(" in line:
                    if rel == self.ROUTE:
                        spent += 1
                    else:
                        errors.append(f"{rel}:{number}: automatic reset spending is forbidden")
                if "rate-limit-reset-credits" in line:
                    if rel == self.DESK:
                        known += 1
                    else:
                        errors.append(f"{rel}:{number}: reset transport belongs to SubscriptionResetDesk")
        if not spent or not known:
            errors.append("the route that spends a reset or the desk that knows its address is gone: this guard is looking at nothing")
        for path in (ROOT / "static/js").glob("*.js"):
            if '"/api/cloud-accounts/subscription-reset"' in path.read_text() and path.name != "subscription-resets.js":
                errors.append(f"{path.name}: reset POST belongs to the confirmed reset action")
        return errors


if __name__ == "__main__":
    errors = ResetSpendGuard().check()
    print("Subscription reset boundary: " + ("; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
