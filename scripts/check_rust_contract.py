#!/usr/bin/env python3
"""Guard of how the caravan's Rust is written: the rules of docs/rust-code.md, read off the code.

The owner, 2026-11-01: "organise the architecture so that it is easy to keep up; do not write in anti-patterns". An agreement is
not kept, a guard is. Each rule here has its price on record in the `patterns` skill, and the compiler keeps the rest: the lints
in rust/Cargo.toml, which this also holds in place.

Rules, each read from the code and not from what it says of itself; tests are outside them.
1. A function lives in an `impl`. One outside is listed in FREE_FUNCTIONS with its reason, and `main` needs none.
2. No God object: a file up to FILE_LINES lines, a function up to FUNCTION_LINES. What is over is listed in LONG with its reason.
3. No mutable state at module level: no `static mut`, no `static` of a lock, a cell or an atomic, no `thread_local!`, no
   `lazy_static!`.
4. The clock is a parameter: `SystemTime::now` and `Instant::now` are read in crates/os/src/clock.rs alone. `rules` reads no
   file, socket, thread, process or environment, and `wire` no thread, process or environment; only wire/src/peer.rs holds a socket
   type, and TLS stands in `net` alone: a crate that names `rustls` has its own idea of what a provider's certificate must be.
5. Absence is named: `unwrap_or_default()`, `unwrap_or(0)` and their kin need `// absent-ok: why` on the line or just above, but for
   a slice's `get` and a `split(...).next()`, whose default cannot happen.
6. `unsafe` stands in crates/os/src/lib.rs alone. An `#[allow]` says its reason, there and everywhere.
7. Third-party packages: each one in Cargo.lock has its reason in THIRD_PARTY; one listed that is gone is an error too, or the list
   lies.
8. The lints stand in rust/Cargo.toml, and every crate takes them.
9. One table for the program and the browser: contract/*.json are the tables the program is held to, and a table it does not run holds nothing.
10. One compiler: rust-toolchain.toml's version is the version CI checks with and the live program is built with.
11. A comment does not point at the tree that left: no `caravan/*.py`, no "Python side", no "twin of". A pointer there leads nowhere, and a reader takes it for a place to look.

Fails on any of them. Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_rust_contract.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUST = ROOT / "rust"
CRATES = RUST / "crates"

FILE_LINES = 400
FUNCTION_LINES = 60

#: Functions outside an `impl`: path relative to rust/crates, then name, with the reason. None yet, and that is how it should stay.
FREE_FUNCTIONS = {}

#: What is over the length limits: "path" or "path::function", with the reason.
LONG = {
    "os/src/lib.rs": "every unsafe call of the workspace, in the one file rule 6 allows them: each is short, and each stands by itself",
    "scout/src/scout.rs::new": "the assembly of a scout's parts: a flat list, no branch and no loop, one part to a line",
    "admin/src/paths.rs::from_env": "the controller's paths: a flat list, one environment variable to a line",
    "admin/src/app.rs::new": "the assembly of the controller's parts: a flat list, one part to a line",
}

#: Each third-party package, with why it is here. A new one fails until it says.
THIRD_PARTY = {
    "serde_json": "JSON of the settings, the journal and the answers: a format full of traps, and the package everyone checks",
    "serde_core": "serde_json's own traits",
    "itoa": "serde_json's integers",
    "zmij": "serde_json's floats",
    "memchr": "serde_json's search for a string's end",
    "indexmap": "serde_json's preserve_order: a body the caravan rewrites keeps its fields' order",
    "equivalent": "indexmap's own",
    "hashbrown": "indexmap's own",
    "foldhash": "hashbrown's own",
    "regex": "the scout's reading of a dead process's log and the scrubbing of keys out of it: patterns ported whole, with no engine of our own to get wrong",
    "regex-automata": "regex's own",
    "regex-syntax": "regex's own",
    "miniz_oxide": "the controller's answers in gzip: deflate written by nobody here, in memory-safe code, with no C to build",
    "adler2": "miniz_oxide's own",
    "httparse": "HTTP heads: where attacks live, and what hyper itself parses with",
    "libc": "a thread's processor time, the local time and a lock shared between processes: the standard library has none of them",
    "rustls": "TLS to the providers: written by nobody here, and in memory-safe code; the one crate net uses it",
    "rustls-pki-types": "rustls's certificate types, and the reading of the system's certificate file",
    "rustls-webpki": "rustls's check of a provider's certificate",
    "ring": "rustls's cryptography: the provider without a build tool beyond a C compiler",
    "untrusted": "ring's and webpki's parsing of what comes from outside",
    "subtle": "rustls's comparisons in constant time",
    "zeroize": "rustls's wiping of keys from memory",
    "once_cell": "ring's and rustls's one-time setup",
    "getrandom": "ring's random numbers from the system",
    "cfg-if": "getrandom's own",
    "cc": "ring's build: it compiles a little C and assembly, on the build machine only",
    "find-msvc-tools": "cc's own, never run off Windows",
    "shlex": "cc's own",
}

#: Named in Cargo.lock and never built: serde_json and serde hold each other's versions in step under a `cfg(any())`, a target that
#: never is. `cargo tree` does not show them, and GET /api/packages names what is built.
LOCKED_NOT_BUILT = {"aho-corasick", "serde", "serde_derive", "proc-macro2", "quote", "syn", "unicode-ident", "wasi", "windows-sys", "windows-targets",
                    "windows_aarch64_gnullvm", "windows_aarch64_msvc", "windows_i686_gnu", "windows_i686_gnullvm", "windows_i686_msvc",
                    "windows_x86_64_gnu", "windows_x86_64_gnullvm", "windows_x86_64_msvc"}

#: The lints every crate takes, as rust/Cargo.toml must keep them.
LINTS = ("missing_docs", "unsafe_code", "unused_must_use", "expect_used", "indexing_slicing", "let_underscore_must_use", "panic",
         "print_stderr", "print_stdout", "todo", "unimplemented", "unwrap_used", "dbg_macro")

#: The files that name the compiler's image.
COMPILER_HOMES = (".gitlab-ci.yml", "Dockerfile", "deploy/nas/release_ship.py")

CLOCK_READS = re.compile(r"\b(SystemTime|Instant)::now\b")
CLOCK_HOME = "os/src/clock.rs"
UNSAFE_HOME = "os/src/lib.rs"
SOCKET_HOME = "wire/src/peer.rs"
TLS_HOME = "net"
GLOBAL_STATE = [
    (re.compile(r"\bstatic\s+mut\b"), "static mut"),
    (re.compile(r"\bstatic\s+[A-Z_0-9]+\s*:[^=]*\b(Mutex|RwLock|OnceLock|LazyLock|Atomic\w+|RefCell|Cell|Condvar)\b"), "a static of a lock, a cell or an atomic"),
    (re.compile(r"\bthread_local!"), "thread_local!"),
    (re.compile(r"\blazy_static!"), "lazy_static!"),
]
#: What a layer may not touch, by its crate.
LAYERS = {
    "rules": [("std::fs", "files"), ("std::net::Tcp", "sockets"), ("std::net::Udp", "sockets"), ("std::io", "input and output"),
              ("std::thread", "threads"), ("std::process", "processes"), ("std::env", "the environment"), ("std::time", "the clock")],
    "wire": [("std::fs", "files"), ("std::thread", "threads"), ("std::process", "processes"), ("std::env", "the environment"), ("std::time", "the clock")],
}
ABSENCE = re.compile(r"\.unwrap_or_default\(\)|\.unwrap_or\(0(\.0)?\)|\.map_or\(0(\.0)?,|\.unwrap_or_else\(\|\|\s*0(\.0)?\)")
ABSENCE_REASON = "// absent-ok:"
#: Where a comment must not point: the Python tree left the repository (2026-11-02).
GONE_TREE = re.compile(r"caravan/[a-z_/*]+\.py|the Python side|\b[Tt]wins? of\b")
#: A slice read within its bounds and the first piece of a split have a default that cannot happen.
NO_ABSENCE_THERE = re.compile(r"\.get(_mut)?\(\.\.|\.get(_mut)?\([a-z_.]+\.\.|\.split\(.*\)\.next\(\)")
FN_LINE = re.compile(r"^(\s*)(?:pub(?:\([a-z]+\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([a-z_0-9]+)")


class Source:
    """One Rust file with its comments and the insides of its strings blanked, so that braces and words count only as code. Lines stay
    where they were."""

    def __init__(self, path):
        self.path = path
        self.rel = path.relative_to(CRATES).as_posix()
        self.text = path.read_text(encoding="utf-8")
        self.code = self.blanked(self.text)
        self.lines = self.code.split("\n")
        self.raw_lines = self.text.split("\n")
        self.end = self.tests_start()

    @staticmethod
    def blanked(text):
        out, at, size = [], 0, len(text)
        while at < size:
            two = text[at:at + 2]
            letter = text[at]
            if two == "//":
                stop = text.find("\n", at)
                stop = size if stop < 0 else stop
                at = stop
            elif two == "/*":
                stop = text.find("*/", at + 2)
                stop = size if stop < 0 else stop + 2
                out.append(re.sub(r"[^\n]", " ", text[at:stop]))
                at = stop
            elif letter == '"' or (letter == "r" and re.match(r'r#*"', text[at:at + 8]) and not (at and (text[at - 1].isalnum() or text[at - 1] == "_"))):
                at = Source.skip_string(text, at, out)
            elif letter == "b" and two == 'b"':
                out.append("b")
                at += 1
            elif letter == "'":
                literal = re.match(r"'(\\.[^']*|[^\\'])'", text[at:at + 12])
                if literal:
                    out.append(" " * literal.end())
                    at += literal.end()
                else:
                    out.append(letter)
                    at += 1
            else:
                out.append(letter)
                at += 1
        return "".join(out)

    @staticmethod
    def skip_string(text, at, out):
        raw = re.match(r'r(#*)"', text[at:at + 8])
        if raw:
            closing = '"' + raw.group(1)
            stop = text.find(closing, at + raw.end())
            stop = len(text) if stop < 0 else stop + len(closing)
        else:
            stop = at + 1
            while stop < len(text) and text[stop] != '"':
                stop += 2 if text[stop] == "\\" else 1
            stop = min(stop + 1, len(text))
        out.append(re.sub(r"[^\n]", " ", text[at:stop]))
        return stop

    def tests_start(self):
        """The line where the file's tests begin: the rules stop there. Only a block of tests hides what follows it: a `#[cfg(test)]` on one
        item, or on `mod tests;` whose tests stand in a file of their own, does not. That file is all tests."""
        if self.rel.endswith("/tests.rs"):
            return 0
        for number, line in enumerate(self.lines[:-1]):
            if line.strip() == "#[cfg(test)]" and self.lines[number + 1].rstrip().endswith("{") and self.lines[number + 1].startswith("mod "):
                return number
        return len(self.lines)

    def working_lines(self):
        return list(enumerate(self.lines[:self.end]))

    def functions(self):
        """(name, line, length, column) of each function in the working part, by its braces."""
        found = []
        for number, line in self.working_lines():
            match = FN_LINE.match(line)
            if not match:
                continue
            depth, opened, at = 0, False, number
            while at < self.end:
                for letter in self.lines[at]:
                    if letter == "{":
                        depth += 1
                        opened = True
                    elif letter == "}":
                        depth -= 1
                if opened and depth <= 0:
                    break
                if not opened and self.lines[at].rstrip().endswith(";"):
                    break     # a trait's method without a body
                at += 1
            found.append((match.group(2), number + 1, at - number + 1, len(match.group(1))))
        return found


def sources():
    return [Source(path) for path in sorted(CRATES.glob("*/src/**/*.rs"))]


def check_functions(source, problems):
    lines = source.end
    if lines > FILE_LINES and source.rel not in LONG:
        problems.append(f"{source.rel}: {lines} lines, the limit is {FILE_LINES}: split it by what changes for one reason, or say why in LONG")
    for name, line, length, column in source.functions():
        if length > FUNCTION_LINES and f"{source.rel}::{name}" not in LONG:
            problems.append(f"{source.rel}:{line}: fn {name} is {length} lines, the limit is {FUNCTION_LINES}: this is how proxy() reached 1170")
        if column == 0 and name != "main" and name not in FREE_FUNCTIONS.get(source.rel, {}):
            problems.append(f"{source.rel}:{line}: fn {name} stands outside an impl: objects by default, or its reason in FREE_FUNCTIONS")


def check_state(source, problems):
    for number, line in source.working_lines():
        for pattern, words in GLOBAL_STATE:
            if pattern.search(line):
                problems.append(f"{source.rel}:{number + 1}: {words}: state is a field of an object with one owner")


def check_layers(source, problems):
    crate = source.rel.split("/", 1)[0]
    for number, line in source.working_lines():
        if CLOCK_READS.search(line) and source.rel != CLOCK_HOME:
            problems.append(f"{source.rel}:{number + 1}: reads the clock: the clock is a parameter (os/src/clock.rs)")
        for word, what in LAYERS.get(crate, ()):
            if word in line:
                problems.append(f"{source.rel}:{number + 1}: {crate} touches {what}: {word}")
        if "rustls" in line and crate != TLS_HOME:
            problems.append(f"{source.rel}:{number + 1}: names rustls: TLS stands in crates/{TLS_HOME} alone")
        if crate == "wire" and "std::net" in line and source.rel != SOCKET_HOME:
            problems.append(f"{source.rel}:{number + 1}: a socket type outside {SOCKET_HOME}: this crate's reading is generic over Read")


def check_gone_tree(source, problems):
    for number, line in enumerate(source.raw_lines):
        said = GONE_TREE.search(line)
        if said:
            problems.append(f"{source.rel}:{number + 1}: points at the Python tree that left the repository: {said.group()!r}")


def check_absence(source, problems):
    for number, line in source.working_lines():
        if not ABSENCE.search(line) or NO_ABSENCE_THERE.search(line):
            continue
        said = source.raw_lines[number] + " " + (source.raw_lines[number - 1] if number else "")
        if ABSENCE_REASON not in said:
            problems.append(f"{source.rel}:{number + 1}: a default stands in for what is absent: {line.strip()[:90]} — name the state, or say `{ABSENCE_REASON} why`")


def check_unsafe(source, problems):
    for number, line in source.working_lines():
        if re.search(r"\bunsafe\b", line) and source.rel != UNSAFE_HOME:
            problems.append(f"{source.rel}:{number + 1}: unsafe outside {UNSAFE_HOME}")
        if re.search(r"#!?\[allow\(", line) and "reason" not in line and source.rel != UNSAFE_HOME:
            problems.append(f"{source.rel}:{number + 1}: an allow with no reason: #[allow(lint, reason = \"…\")]")


def check_third_party(problems):
    lock = RUST / "Cargo.lock"
    if not lock.exists():
        problems.append("rust/Cargo.lock is missing: a build would take whatever is newest")
        return
    packages = re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "[^"]+"\nsource = "registry', lock.read_text(encoding="utf-8"))
    if not packages:
        problems.append("Cargo.lock names no third-party package: this reading of it is broken")
    for name in sorted(set(packages) - set(THIRD_PARTY) - LOCKED_NOT_BUILT):
        problems.append(f"Cargo.lock has {name}, with no reason in THIRD_PARTY: a new package is other people's code to watch")
    for name in sorted((set(THIRD_PARTY) | LOCKED_NOT_BUILT) - set(packages)):
        problems.append(f"THIRD_PARTY names {name}, which Cargo.lock no longer has: the list lies")


def check_lints(problems):
    workspace = (RUST / "Cargo.toml").read_text(encoding="utf-8")
    for lint in LINTS:
        if not re.search(rf'^{lint} = "deny"$', workspace, re.M):
            problems.append(f'rust/Cargo.toml: {lint} is not "deny"')
    for manifest in sorted(CRATES.glob("*/Cargo.toml")):
        if not re.search(r"^\[lints\]\nworkspace = true$", manifest.read_text(encoding="utf-8"), re.M):
            problems.append(f"{manifest.relative_to(ROOT)}: does not take the workspace's lints")


def check_tables(problems):
    on_disk = {path.stem for path in (ROOT / "contract").glob("*.json")}
    rust_half = "".join((CRATES / crate / "tests" / "contract.rs").read_text(encoding="utf-8") for crate in ("rules", "admin"))
    in_rust = set(re.findall(r'table\("([a-z_]+)"\)', rust_half))
    if not on_disk:
        problems.append("contract/ has no table")
    for name in sorted(on_disk - in_rust):
        problems.append(f"contract/{name}.json: the program is not held to it")
    for name in sorted(in_rust - on_disk):
        problems.append(f"the program's half names contract/{name}.json, which is not there")


def check_compiler(problems):
    said = re.search(r'^channel = "([0-9.]+)"$', (RUST / "rust-toolchain.toml").read_text(encoding="utf-8"), re.M)
    if not said:
        problems.append("rust/rust-toolchain.toml names no exact version: two builds could compile two ways")
        return
    version = said.group(1)
    for rel in COMPILER_HOMES:
        # The public mirror leaves deploy/nas/ out (scripts/sync-public.sh): where it stands, it is held; where it does not, there is nothing to hold.
        if rel.startswith("deploy/nas/") and not (ROOT / "deploy/nas").is_dir():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        images = re.findall(r"\brust:([0-9.]+[0-9])", text)
        if not images:
            problems.append(f"{rel}: builds no Rust image: the program would not be built or checked there")
        for image in images:
            if image != version:
                problems.append(f"{rel}: builds with rust:{image}, rust-toolchain.toml says {version}")


def main():
    problems = []
    found = sources()
    if not found:
        problems.append("rust/crates holds no source: nothing is guarded")
    for source in found:
        check_functions(source, problems)
        check_state(source, problems)
        check_layers(source, problems)
        check_absence(source, problems)
        check_gone_tree(source, problems)
        check_unsafe(source, problems)
    check_third_party(problems)
    check_lints(problems)
    check_tables(problems)
    check_compiler(problems)
    if problems:
        print(f"rust contract: FAILED, {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"rust contract: ok, {len(found)} files, {sum(len(s.functions()) for s in found)} functions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
