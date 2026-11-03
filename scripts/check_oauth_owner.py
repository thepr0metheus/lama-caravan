#!/usr/bin/env python3
"""The credential document has one owner: rust/crates/files/src/credential_vault.rs.

It alone renews OAuth tokens: refresh tokens rotate, so two renewal implementations destroy each other's copy.

It alone writes the document (provider-secrets.json). A writer that read the document, changed one entry and wrote all of it back without the vault's lock put a spent refresh
token back whenever a renewal landed in between: the board's "set key" did that until 2026-10-07, and the subscription then needed a new login. So outside the owner, a call
that writes to anything naming the secrets' file is a failure.

What it cannot see: a path carried through a variable. The settings restore takes the file's path from a table, and writes through `CredentialVault`.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402


class OAuthOwnerGuard:
    OWNER = "rust/crates/files/src/credential_vault.rs"
    RENEWS = re.compile(r'"grant_type",\s*"refresh_token"|grant_type=refresh_token')
    NAMES = r"(?:provider_secrets_file|secrets_file|PROVIDER_SECRETS_FILE)"
    WRITES = re.compile(rf"(?:\b(?:write|remove_file|rename|copy|create)\([^;]*{NAMES})|(?:{NAMES}[^;]*\.(?:write|replace)\()")

    def check(self):
        renewals, writes = [], []
        for rel, lines in RustSource.files():
            for number, line in enumerate(lines, 1):
                if self.RENEWS.search(line):
                    renewals.append((rel, number))
                if rel != self.OWNER and self.WRITES.search(line):
                    writes.append((rel, number))
        errors = []
        if not renewals or any(rel != self.OWNER for rel, _ in renewals):
            errors.append(f"OAuth renewal must live only in {self.OWNER}; found {renewals}")
        if writes:
            errors.append(f"the credential document is written only by {self.OWNER}; found writes at {writes}")
        return errors


if __name__ == "__main__":
    errors = OAuthOwnerGuard().check()
    print("credential document owner: " + ("FAILED: " + "; ".join(errors) if errors else "OK — one renewal, one writer"))
    sys.exit(bool(errors))
