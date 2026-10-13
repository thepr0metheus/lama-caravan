#!/usr/bin/env python3
"""The credential document has one owner: caravan/common/credential_vault.py.

It alone renews OAuth tokens: refresh tokens rotate, so two renewal
implementations destroy each other's copy.

It alone writes the document (provider-secrets.json). A writer that read the
document, changed one entry and wrote all of it back without the vault's lock
put a spent refresh token back whenever a renewal landed in between: the
board's "set key" did that until 2026-10-07, and the subscription then needed a
new login. So outside the owner, a call that writes to anything naming
PROVIDER_SECRETS_FILE, or `.write` on a store opened on it, is a failure.

What it cannot see: a path carried through a variable. The settings restore
takes the file's path from a table; it writes through CredentialVault.replace,
and scripts/test_secret_writes.py pins that.
"""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent

# Calls that change the file they are pointed at. A receiver-side write is a
# method of the path itself; an argument-side one puts content at a path it is given.
RECEIVER_WRITES = {"write_text", "write_bytes", "unlink"}
ARGUMENT_WRITES = {"atomic_write_text", "create_private_text", "replace", "rename",
                   "move", "copy", "copy2", "copyfile"}


def names_secrets(node):
    return any((isinstance(n, ast.Name) and n.id == "PROVIDER_SECRETS_FILE")
               or (isinstance(n, ast.Attribute) and n.attr == "PROVIDER_SECRETS_FILE")
               for n in ast.walk(node))


def call_name(node):
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def opens_for_writing(node):
    mode = node.args[1] if len(node.args) > 1 else next(
        (k.value for k in node.keywords if k.arg == "mode"), None)
    if mode is None:
        return False
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return True                     # a mode the reader cannot know: counted as a write
    return any(c in mode.value for c in "wax+")


class OAuthOwnerGuard:
    OWNER = "caravan/common/credential_vault.py"

    def files(self):
        for path in sorted((ROOT / "caravan").rglob("*.py")):
            yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))

    def check(self):
        errors = []
        renewals, writes = [], []
        for rel, tree in self.files():
            renewals += [(rel, line) for line in self.renewals(tree)]
            if rel != self.OWNER:
                writes += [(rel, line) for line in self.secret_writes(tree)]
        if not (len(renewals) == 1 and renewals[0][0] == self.OWNER):
            errors.append(f"OAuth renewal must live only in {self.OWNER}; found {renewals}")
        if writes:
            errors.append(f"the credential document is written only by {self.OWNER}; "
                          f"found writes at {writes}")
        return errors

    def renewals(self, tree):
        lines = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                values = {k.value: v.value for k, v in zip(node.keys, node.values)
                          if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
                if values.get("grant_type") == "refresh_token":
                    lines.append(node.lineno)
        return lines

    def secret_writes(self, tree):
        stores = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and call_name(node.value) == "CachedJsonStore" and names_secrets(node.value)):
                stores |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        lines = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
            if name == "write" and (
                    (isinstance(receiver, ast.Name) and receiver.id in stores)
                    or (isinstance(receiver, ast.Call) and call_name(receiver) == "CachedJsonStore"
                        and names_secrets(receiver))):
                lines.append(node.lineno)
            elif name in RECEIVER_WRITES and receiver is not None and names_secrets(receiver):
                lines.append(node.lineno)
            elif name in ARGUMENT_WRITES and any(names_secrets(a) for a in node.args):
                lines.append(node.lineno)
            elif name == "open" and opens_for_writing(node) and (
                    any(names_secrets(a) for a in node.args[:1])
                    or (receiver is not None and names_secrets(receiver))):
                lines.append(node.lineno)
        return lines


if __name__ == "__main__":
    errors = OAuthOwnerGuard().check()
    print("credential document owner: " + ("FAILED: " + "; ".join(errors) if errors
                                           else "OK — one renewal, one writer"))
    sys.exit(bool(errors))
