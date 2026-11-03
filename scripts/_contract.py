"""The tables the browser's tests are held to: contract/*.json. The program is held to the same files (rust/crates/admin/tests/contract.rs,
rust/crates/rules/tests/contract.rs), so that the browser and the program cannot part with neither going red, and no test here needs the program to run.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Contract:
    """One table, read each time it is asked for: a test takes what it names, and a name the file has not is a KeyError, not a pass."""

    FOLDER = ROOT / "contract"

    @classmethod
    def table(cls, name):
        return json.loads((cls.FOLDER / f"{name}.json").read_text(encoding="utf-8"))


class RunnerLines:
    """The line a cell starts with, for the config a test names: `contract/runner_lines.json`, the program's own words."""

    @staticmethod
    def of(runner, config, trained=None):
        for row in Contract.table("runner_lines")["lines"]:
            if row["runner"] == runner and row["config"] == config and row.get("trained") == trained:
                return row["line"]
        raise KeyError(f"contract/runner_lines.json holds no line for {runner} {config} trained={trained}")


class RunnerCards:
    """Which card a start lands on and what it holds of it: `contract/runner_cards.json`."""

    @staticmethod
    def said(table, config):
        for row in Contract.table("runner_cards")[table]:
            if row["config"] == config:
                return row["said"]
        raise KeyError(f"contract/runner_cards.json holds no {table} row for {config}")
