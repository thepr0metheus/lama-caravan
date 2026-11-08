# How the Rust is written

The caravan is three programs in one Cargo workspace under `rust/`: the controller
(`caravan-admin`), the entry (`caravan-proxy`) and a machine's scout (`caravan-scout`). They run
on plain threads. The cell servers in `cells/` stay in Python, beside the models, under what those
models need.

The one requirement behind everything here: code that is easy to keep up. A rule that can be broken
by accident is held by the compiler or by a guard, not by an agreement.

## Layers: a dependency goes only downwards

```text
rust/crates/
  admin     the controller: its documents, its fleet, the board's server
  proxy     the entry: every client's request, to any pool or model
  scout     one machine: its cards, its cells, its model cache, its report
  plumbing  what a program needs from its machine: HTTP out, a tool, a repeated pass
  files     the settings it reads, the journal and the state it writes
  net       connections: a model's machine over TCP, a provider over TLS
  rules     the caravan's rules, with no input or output at all
  wire      HTTP/1.1 on a socket; it knows nothing of the caravan
  os        what only the C library can say; the one place with `unsafe`
```

The compiler holds the boundary: `wire` cannot call `rules`, because it does not depend on it. The
guard holds the purity of `rules`: no file, socket, clock, thread or environment there. Time comes
in as a parameter, so a rule can be tested at any hour.

## Objects, in Rust

| The idea | In Rust |
|---|---|
| A class and its methods | `struct` and `impl`: state is a field with one owner |
| An abstract class | `trait`: a forgotten method does not compile |
| A registry of objects | a table of `Box<dyn Trait>`, not a third `else if` |
| "None", a swallowed error | `Option<T>` and `Result<T, E>`: neither can go unnoticed |
| ok, empty, don't know, broken | `enum`: a `match` has to name every case |
| A marker taken off on every way out | `Drop`: it goes by itself, on any way out |

There is no inheritance and none is missed: the caravan's rule was already "a registry, not a
hierarchy". A runner is a row or a class in `rust/crates/admin/src/domain/runner/`, in
`RunnerRegistry::new`: [adding-a-runner.md](adding-a-runner.md).

## What is forbidden, and what catches it

`scripts/check_rust_contract.py` reads these off the code, and each has a negative self-test in
`scripts/test_guards_fail.py`. The lints are in `rust/Cargo.toml`, and every crate takes them.

| Rule | Why | Caught by |
|---|---|---|
| A function lives in an `impl`; one outside needs a written reason | objects by default | guard |
| A file up to 400 lines, a function up to 60, tests aside | a 1170-line function nobody could check in parts | guard |
| No mutable state at module level | a "request running" marker that outlived its request | guard |
| The clock is a parameter; `rules` has no input or output | a test that was green only before three in the morning | guard |
| `unwrap_or_default`, `unwrap_or(0)` and their kin need `// absent-ok: why` | a card nobody measured, drawn as 0 % | guard |
| `unwrap`, `expect`, `panic!`, an unchecked index | a panic in place of a refusal | clippy |
| `let _ =` over a `Result` | a swallowed error | clippy |
| `unsafe` in one file, with its reason | memory errors | compiler, guard |
| A third-party package only with a written reason | code nobody watches | guard |
| TLS is named in `net` alone | one opinion on a provider's certificate | guard |
| Every public name is described | the reason stays with the code | compiler |
| One compiler: `rust/rust-toolchain.toml` | what CI checked is what runs | guard |
| A test binary runs under a time limit and ends with the run that started it | two hung tests of an abandoned `cargo test` spun a Mac for three days | runner, guard |
| A test that asks a reader again after a wait stops asking: `Patience` in `wire` | a test source that waited for ever met a loop with no end | test |

## Little foreign code

Plain threads and no async runtime: there are dozens of requests at a time, not thousands, a thread
does what is written, and a client's leaving is checked out loud at a point the code names. What is
left is about twenty packages, half of them for TLS, each with its reason in the guard's table:

| Package | For | Why not by hand |
|---|---|---|
| `serde_json` with `preserve_order` | the JSON of settings, journal and answers | a format with traps; a package everybody checks |
| `httparse` | HTTP headers | parsing is where attacks land |
| `libc` | a thread's processor time, local time, a file lock | the standard library does not have them |
| `rustls` with `ring` | TLS to providers, where a key goes; SHA-256 | nobody writes their own cryptography |
| `regex` | reading a cell's log, `modinfo`, package names | those rules read as expressions anyway |
| `miniz_oxide` | the controller's answers in gzip | deflate written by nobody here, in memory-safe code, with no C to build |

`serde` with `derive` is not taken. Settings are read as `Value` and coerced by hand: the coercion
is part of the contract (a port is taken as a number and as a string), and a field nobody knows is
not lost.

## One table, and answers kept in a file

`contract/*.json` are the cases of a rule that lives in both the program and the browser: input and
expected answer. The Rust tests (`rust/crates/rules/tests/contract.rs`,
`rust/crates/admin/tests/contract.rs`) and the browser's tests read the same file, so a rule changed
on one side goes red on the other. Ugly behaviour is written down as it is and says so.

`tests/frozen/*.jsonl` keep what the programs answered on some 2,900 requests against a fake world:
models, machines and providers. `scripts/test_rust_admin_conformance.py`, `test_rust_conformance.py`
and `test_rust_scout_conformance.py` hold each program to them. An answer changed on purpose is
written again with `--write`, and the file's diff in the merge request says what changed.

`scripts/test_rust_alone.py` and `scripts/test_rust_whole.py` run the real programs together: a
machine paired from the board, a model, a cell, a client's request through the entry, a new release.

A comparison sees only what it was asked. So a rule that can lose data has a permanent test beside
its code, and every such test has been seen to go red on a broken copy of the rule.

## A test that hangs is red, not quiet

On 2026-11-04 a source of bytes in the tests of `wire` waited for ever after its last piece, and the
test asked again at once after every wait. libtest only warned after 60 seconds, cargo has no time
limit, and the agent that had started `cargo test` in the background left it: the binary spun two
cores of a Mac for three days. Two things stand against that now:

- The readers of `wire` are tested against one source, `wire/src/stutter.rs`: `Stutter` waits
  before every read, keeps the rest of a long piece for the next read and ends after its last piece,
  and `Patience` asks a reader again after a wait but fails the test after 10,000 waits in a row.
- cargo starts every test binary through `scripts/rust_test_runner.py` (the root
  `.cargo/config.toml`): 300 seconds, then the binary and everything it started are stopped and the
  run fails with exit 124 and a line naming it. The same happens when the run that started it is gone
  — cargo killed, or the runner itself killed outright. `docs/operations.md` has the details.
