#!/usr/bin/env python3
"""The changelog's entries before a release: one file per merge request in changelog.d/ (changelog.d/README.md).

Every merge request used to add its entry at the top of `## Unreleased` in CHANGELOG.md, so each merge made every other open merge request
conflict on the same lines: on 2026-11-07 eleven merge requests, each merged with main again by hand before it could land. An entry is now a
file of its own, named by its day and its branch, and two merge requests never touch the same file. A release folds the files into a section
of CHANGELOG.md and removes them, the way towncrier, changesets and GitLab's own changelog do.

Run: python3 scripts/changelog.py show                       the entries not yet released, newest first
     python3 scripts/changelog.py release <version> [<day>]  a section `## <version> — <day>` of them in CHANGELOG.md; the files go
"""
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ChangelogRefusal(Exception):
    """A release that must not happen: what is wrong, in words."""


class Changelog:
    """CHANGELOG.md and the entries that wait for a release: what they say, what is wrong with them, and the release that folds them in."""

    FILE = "CHANGELOG.md"
    FOLDER = "changelog.d"
    README = "README.md"
    #: The day the entry was written and the words of its branch, `2026-11-07-delivery-lock.md`. The day orders a release, newest first.
    NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
    UNRELEASED = "## Unreleased"
    #: What `## Unreleased` says in place of entries. The guard holds the section to these words: an entry written there is the old habit back.
    POINTER = ("Записи до выпуска — файлами в `changelog.d/`, один файл на merge request (`changelog.d/README.md`): так merge request "
               "не спорят за верх этой секции. Прочитать их подряд, новые сверху: `python3 scripts/changelog.py show`.")

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.file = self.root / self.FILE
        self.folder = self.root / self.FOLDER

    @staticmethod
    def words(text):
        """The text with its line breaks and runs of spaces as single spaces: wrapping a paragraph changes nothing."""
        return " ".join(text.split())

    def lines(self):
        return self.file.read_text(encoding="utf-8").splitlines(keepends=True)

    def unreleased(self, lines):
        """The section's bounds: the index of its heading and of the line that ends it. None when there is no such heading."""
        heads = [index for index, line in enumerate(lines) if line.rstrip("\n") == self.UNRELEASED]
        if len(heads) != 1:
            return None
        start = heads[0]
        end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
        return start, end

    def entries(self):
        """The files that wait for a release, newest first; the folder's README is not one."""
        if not self.folder.is_dir():
            return []
        return sorted((one for one in self.folder.iterdir() if one.name != self.README), key=lambda one: one.name, reverse=True)

    def entry_problems(self, path):
        """What is wrong with one file of the folder; empty when nothing is."""
        name = f"{self.FOLDER}/{path.name}"
        if not path.is_file():
            return [f"{name}: не файл — в {self.FOLDER}/ лежат только записи"]
        named = self.NAME.match(path.name)
        if not named:
            return [f"{name}: имя не по образцу ГГГГ-ММ-ДД-слова-ветки.md (строчные латинские буквы, цифры, «-»)"]
        try:
            datetime.date.fromisoformat(named.group(1))
        except ValueError:
            return [f"{name}: в имени нет такого дня, {named.group(1)}"]
        text = path.read_text(encoding="utf-8")
        said = [line for line in text.splitlines() if line.strip()]
        if not said:
            return [f"{name}: пустая запись"]
        problems = []
        if not said[0].startswith("- "):
            problems.append(f"{name}: запись начинается не пунктом списка «- », как в {self.FILE}")
        fenced = False
        for line in said:
            if line.lstrip().startswith("```"):
                fenced = not fenced
            elif not fenced and line.startswith("#"):
                problems.append(f"{name}: заголовок внутри записи («{line[:40]}») — при выпуске он разорвал бы секцию")
        return problems

    def problems(self):
        """Everything that is not as the rule says, in words; empty when all is."""
        if not self.file.is_file():
            return [f"нет {self.FILE}"]
        lines = self.lines()
        bounds = self.unreleased(lines)
        problems = []
        if bounds is None:
            problems.append(f"в {self.FILE} не одна строка «{self.UNRELEASED}»: секция с указателем на {self.FOLDER}/ должна быть одна")
        else:
            start, end = bounds
            body = "".join(lines[start + 1:end])
            if self.words(body) != self.words(self.POINTER):
                problems.append(f"в секции «{self.UNRELEASED}» файла {self.FILE} не только указатель на {self.FOLDER}/: запись merge request — "
                                f"отдельным файлом в {self.FOLDER}/ ({self.FOLDER}/{self.README}), а не в {self.FILE}. Текст указателя — Changelog.POINTER")
        if not (self.folder / self.README).is_file():
            problems.append(f"нет {self.FOLDER}/{self.README}: правило папки")
        for path in self.entries():
            problems.extend(self.entry_problems(path))
        return problems

    def pending(self):
        """The entries not yet released, as a section would carry them, newest first; "" when none waits."""
        return "".join(path.read_text(encoding="utf-8").rstrip("\n") + "\n" for path in self.entries())

    def release(self, version, day):
        """Folds the entries into a section `## <version> — <day>` under `## Unreleased` and removes their files. Returns the files removed."""
        problems = self.problems()
        if problems:
            raise ChangelogRefusal("сначала поправить:\n  - " + "\n  - ".join(problems))
        entries = self.entries()
        if not entries:
            raise ChangelogRefusal(f"в {self.FOLDER}/ нет записей: выпускать нечего")
        datetime.date.fromisoformat(day)
        lines = self.lines()
        if any(re.match(rf"^## {re.escape(version)}( |$)", line) for line in lines):
            raise ChangelogRefusal(f"секция «## {version}» в {self.FILE} уже есть")
        _, end = self.unreleased(lines)
        section = [f"## {version} — {day}\n", "\n", self.pending(), "\n"]
        before = lines[:end]
        if before and before[-1].strip():
            before.append("\n")
        self.file.write_text("".join(before + section + lines[end:]), encoding="utf-8")
        for path in entries:
            path.unlink()
        return entries


def main(argv):
    changelog = Changelog()
    if argv[:1] == ["show"] and len(argv) == 1:
        said = changelog.pending()
        print(said if said else f"в {Changelog.FOLDER}/ нет записей до выпуска", end="" if said else "\n")
        return 0
    if argv[:1] == ["release"] and len(argv) in (2, 3):
        day = argv[2] if len(argv) == 3 else datetime.date.today().isoformat()
        try:
            removed = changelog.release(argv[1], day)
        except (ChangelogRefusal, ValueError) as refusal:
            print(f"выпуск не сделан: {refusal}", file=sys.stderr)
            return 1
        print(f"{Changelog.FILE}: секция «## {argv[1]} — {day}», записей {len(removed)}; их файлы удалены — закоммитьте выпуск через merge request")
        return 0
    print(__doc__.split("Run: ", 1)[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
