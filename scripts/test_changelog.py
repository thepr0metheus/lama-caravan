#!/usr/bin/env python3
"""Записи журнала до выпуска — файлами в changelog.d/ (scripts/changelog.py): правило и выпуск на выдуманных деревьях.

Гвард scripts/check_changelog_fragments.py проверяет настоящее дерево; здесь — что правило ловит каждое нарушение, которое
обещает, и что выпуск собирает записи в секцию, новые сверху, и убирает их файлы.

Запуск: python3 scripts/test_changelog.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from changelog import Changelog, ChangelogRefusal  # noqa: E402

HEAD = "# Changelog\n\n<!--\nThe rule.\n-->\n\n"
RELEASED = "## 2.0.0 — 2026-11-03\n\n- Old entry.\n"


class Tree:
    """A made-up repository root: CHANGELOG.md with a given section `## Unreleased`, changelog.d/ with given files."""

    def __init__(self, tmp, unreleased=Changelog.POINTER, files=None, readme=True):
        self.root = Path(tmp)
        (self.root / "CHANGELOG.md").write_text(f"{HEAD}## Unreleased\n\n{unreleased}\n\n{RELEASED}", encoding="utf-8")
        folder = self.root / Changelog.FOLDER
        folder.mkdir()
        if readme:
            (folder / Changelog.README).write_text("# The rule\n", encoding="utf-8")
        for name, text in (files or {}).items():
            (folder / name).write_text(text, encoding="utf-8")
        self.changelog = Changelog(self.root)

    def text(self):
        return (self.root / "CHANGELOG.md").read_text(encoding="utf-8")


class ChangelogCases:
    """Each case on a fresh tree; the failures, in words."""

    GOOD = {"2026-11-03-older.md": "- Older entry.\n", "2026-11-07-b.md": "- Entry B.\n  Its second line.\n", "2026-11-07-c.md": "- Entry C.\n"}

    def __init__(self):
        self.failures = []

    def check(self, cond, msg):
        print(("  ok  " if cond else " FAIL ") + msg)
        if not cond:
            self.failures.append(msg)

    def tree(self, **parts):
        self.tmp = tempfile.TemporaryDirectory(prefix="caravan-changelog-")
        return Tree(self.tmp.name, **parts)

    def caught(self, label, tree, words):
        problems = tree.changelog.problems()
        self.check(any(words in problem for problem in problems), f"{label}: пойман ({problems[:1] or 'ничего'})")
        self.tmp.cleanup()

    def rules(self):
        clean = self.tree(files=self.GOOD)
        self.check(clean.changelog.problems() == [], f"чистое дерево без замечаний ({clean.changelog.problems()})")
        wrapped = Changelog.POINTER.replace(": так", ":\nтак")
        self.check(self.tree(unreleased=wrapped).changelog.problems() == [], "указатель, перенесённый на другую строку, — тот же указатель")
        self.caught("запись в верху Unreleased, как раньше", self.tree(unreleased=f"- New entry.\n\n{Changelog.POINTER}"), "не только указатель")
        self.caught("секция без указателя", self.tree(unreleased="- New entry."), "не только указатель")
        self.caught("нет README", self.tree(readme=False), "нет changelog.d/README.md")
        self.caught("имя без дня", self.tree(files={"fix.md": "- Entry.\n"}), "имя не по образцу")
        self.caught("заглавные буквы в имени", self.tree(files={"2026-11-07-Fix.md": "- Entry.\n"}), "имя не по образцу")
        self.caught("не .md", self.tree(files={"2026-11-07-fix.txt": "- Entry.\n"}), "имя не по образцу")
        self.caught("дня нет в календаре", self.tree(files={"2026-13-01-fix.md": "- Entry.\n"}), "нет такого дня")
        self.caught("пустая запись", self.tree(files={"2026-11-07-fix.md": "\n\n"}), "пустая запись")
        self.caught("не пункт списка", self.tree(files={"2026-11-07-fix.md": "Entry.\n"}), "не пунктом списка")
        self.caught("заголовок внутри", self.tree(files={"2026-11-07-fix.md": "- Entry.\n## 2.1.0\n"}), "заголовок внутри")
        fenced = self.tree(files={"2026-11-07-fix.md": "- Entry:\n```sh\n# a shell comment\n```\n"})
        self.check(fenced.changelog.problems() == [], "решётка внутри блока кода — не заголовок")

    def release(self):
        tree = self.tree(files=self.GOOD)
        self.check(tree.changelog.pending().startswith("- Entry C.\n- Entry B.\n  Its second line.\n- Older entry.\n"), "show: новые сверху, по дню и имени")
        removed = tree.changelog.release("2.1.0", "2026-11-08")
        text = tree.text()
        section = "## 2.1.0 — 2026-11-08\n\n- Entry C.\n- Entry B.\n  Its second line.\n- Older entry.\n\n## 2.0.0"
        self.check(section in text, "выпуск: секция под Unreleased, над прошлым выпуском, новые сверху")
        self.check(text.index("## Unreleased") < text.index("## 2.1.0") < text.index("## 2.0.0"), "выпуск: порядок секций")
        self.check(len(removed) == 3 and tree.changelog.entries() == [], "выпуск: файлы записей удалены")
        self.check((tree.root / Changelog.FOLDER / Changelog.README).is_file(), "выпуск: README папки остался")
        self.check(tree.changelog.problems() == [], f"после выпуска дерево по правилу ({tree.changelog.problems()})")
        self.refused("второй выпуск той же версии", tree.changelog, "2.1.0", "нет записей")
        (tree.root / Changelog.FOLDER / "2026-11-09-d.md").write_text("- Entry D.\n", encoding="utf-8")
        self.refused("версия, что уже есть", tree.changelog, "2.1.0", "уже есть")
        self.tmp.cleanup()
        self.refused("нечего выпускать", self.tree().changelog, "2.1.0", "нет записей")
        self.tmp.cleanup()
        self.refused("дерево не по правилу", self.tree(unreleased="- New entry.", files=self.GOOD).changelog, "2.1.0", "сначала поправить")
        self.tmp.cleanup()

    def refused(self, label, changelog, version, words):
        try:
            changelog.release(version, "2026-11-08")
            self.check(False, f"{label}: выпуск отказан")
        except ChangelogRefusal as refusal:
            self.check(words in str(refusal), f"{label}: выпуск отказан ({str(refusal)[:60]})")

    def run(self):
        self.rules()
        self.release()
        return self.failures


def main():
    failures = ChangelogCases().run()
    if failures:
        print(f"\nchangelog: {len(failures)} FAILED")
        return 1
    print("\nchangelog: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
