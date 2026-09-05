#!/usr/bin/env bash
# Prepare the public mirror. Does everything except send it.
#
# This was a recipe carried in someone's head, and twice it went wrong in the
# same way: a parallel session added the PRIVATE remote to the public copy,
# pulled 1100 commits of private history into it, and pushed five private tags
# to GitHub. One of those tags carried a thousand commits with the author's
# personal address. Both times the recovery was manual.
#
# So the steps are here, in order, with the refusals first. The last step is not
# a push — it prints the command and stops. Sending is a human's decision, and
# after two incidents it should stay one.
#
#   scripts/sync-public.sh --dry-run    everything except the commit
#   scripts/sync-public.sh              prepare a commit, print the push command
#
set -euo pipefail

PRIV="${CARAVAN_PRIVATE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PUB="${CARAVAN_PUBLIC:-$HOME/MyProjects/lama-caravan}"
PUBLIC_REMOTE="${CARAVAN_PUBLIC_REMOTE:-git@github.com:thepr0metheus/lama-caravan.git}"
IDENT_NAME="thepr0metheus"
IDENT_MAIL="thepr0metheus@users.noreply.github.com"

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# Never mirrored. Not a scrub list — these files simply do not belong to the
# public project.
# tests/golden/ is a photograph of THIS fleet: 25 real cells, their model paths,
# their hand-written commands. Useful here, meaningless publicly, and it carries
# operator names by construction — a scrub would have to rewrite the very thing
# the snapshot exists to preserve. So it stays private, and the public CI does
# not run test_golden (it never did).
EXCLUDE_RE='^(AGENTS\.md|docs/related-projects\.md|scripts/refactor/|tests/golden/)'

# Anything matching this in the public tree stops the sync. Machine names and
# addresses are the operator's, not the project's; "Revoice" is a private
# project's name; capital "Skynet" is prose, while lowercase `skynet:` is the
# controller's id in stored data and must survive.
LEAK_RE='192\.168|/home/skynet|/home/foreman|/Users/mac|[Rr]evoice|corbels|@gmail|Skynet|forgejo'
FLEET_RE='\b(cerberus|mason|mimir|foreman|crab|tyche|hephaestus|themis|talos|atlas)\b'
# Turkish "atlasın" ("to skip") is a word, not a machine.
FLEET_ALLOW='atlasın'

say()  { printf '  %s\n' "$*"; }
head1() { printf '\n== %s\n' "$*"; }
die()  { printf '\nОТКАЗ: %s\n' "$*" >&2; exit 1; }

head1 "проверки перед началом"
[[ -d "$PRIV/.git" ]] || die "приватного репозитория нет: $PRIV"
[[ -d "$PUB/.git" ]]  || die "публичной копии нет: $PUB"

# 1. The incident, twice. A public copy that can see the private repository is
#    one fetch away from carrying its history.
# Plain read loop, not mapfile: macOS ships bash 3.2 and this must run on the
# laptop that does the syncing as well as on Linux.
while IFS= read -r r; do
    [[ -z "$r" ]] && continue
    url="$(git -C "$PUB" remote get-url "$r")"
    if [[ "$url" != "$PUBLIC_REMOTE" ]]; then
        die "в публичной копии посторонний remote: $r → $url
       Это ровно то, из-за чего приватная история дважды оказывалась
       в шаге от GitHub. Удалите его: git -C $PUB remote remove $r"
    fi
done < <(git -C "$PUB" remote)
say "remote только один и правильный: $PUBLIC_REMOTE"

# 2. Mirroring an uncommitted tree publishes work the private history does not
#    have, which cannot then be traced back to a commit.
[[ -z "$(git -C "$PRIV" status --porcelain)" ]] \
    || die "в приватном дереве есть незакоммиченные изменения — сначала коммит"
say "приватное дерево чистое: $(git -C "$PRIV" log -1 --format='%h %s' | cut -c1-60)"

git -C "$PUB" fetch -q origin
say "origin/main: $(git -C "$PUB" log -1 --format='%h %s' origin/main | cut -c1-60)"

head1 "перенос файлов"
LIST="$(mktemp)"; trap 'rm -f "$LIST"' EXIT
git -C "$PRIV" ls-files | grep -vE "$EXCLUDE_RE" | sort > "$LIST"
say "к переносу: $(wc -l < "$LIST" | tr -d ' ') файлов"

BRANCH="sync-$(git -C "$PRIV" show -s --format=%h HEAD)"
git -C "$PUB" checkout -q -B "$BRANCH" origin/main
rsync -a --files-from="$LIST" "$PRIV"/ "$PUB"/

# A file that left the private list is still present publicly until removed —
# tracked OR not. The untracked half matters: a run that rsynced a file and then
# died in the leak scan leaves it on disk, where the next run's scan finds it
# again and the transfer list no longer explains why it is there. Ignored files
# (the public copy's own var/) are outside this by construction: they can never
# be committed, and sweeping them would delete someone's working state.
gone=0
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    git -C "$PUB" rm -q --cached --ignore-unmatch "$f" >/dev/null
    rm -f "$PUB/$f"
    say "убран из публичного: $f"
    gone=$((gone + 1))
done < <(comm -13 "$LIST" <(git -C "$PUB" ls-files -c -o --exclude-standard | sort -u))
[[ $gone -eq 0 ]] && say "лишних файлов нет"

head1 "лик-скан"
# Everything `git add -A` could stage: tracked files AND untracked ones that are
# not ignored. Not the whole directory — the public copy accumulates local junk
# under an ignored var/, which cannot be committed and only buries the real
# findings. Not the diff either: "Revoice" lived in the public copy from the
# very first sync, and a diff-only scan never looked at it again.
#
# This script is the one exemption: the forbidden strings are its search
# patterns. The limit is real — a leak written INTO this file would not be
# caught here — and it is the file most likely to be read before it is changed.
SCAN="$(mktemp)"; trap 'rm -f "$LIST" "$SCAN"' EXIT
( cd "$PUB" && git ls-files -c -o --exclude-standard ) \
    | grep -v '^scripts/sync-public\.sh$' > "$SCAN"
say "под сканом: $(wc -l < "$SCAN" | tr -d ' ') файлов (отслеживаемые + неигнорируемые)"

scan() {   # scan <regex> <allow-regex-or-empty> <message>
    local hits
    hits="$(cd "$PUB" && tr '\n' '\0' < "$SCAN" | xargs -0 grep -InE "$1" 2>/dev/null || true)"
    [[ -n "$2" ]] && hits="$(printf '%s\n' "$hits" | grep -v "$2" || true)"
    if [[ -n "${hits//[[:space:]]/}" ]]; then
        printf '%s\n' "$hits" | head -20 | sed 's|^|       |'
        die "$3"
    fi
}
scan "$LEAK_RE" "" "найдены запретные строки (см. выше)"
scan "$FLEET_RE" "$FLEET_ALLOW" "имена машин флота (чинить в ПРИВАТЕ — иначе rsync вернёт)"
say "чисто"

head1 "гварды и тесты на публичном дереве"
( cd "$PUB"
  python3 -m py_compile $(git ls-files '*.py') && echo "  py_compile ✓"
  for g in check_messages_i18n check_i18n_calls check_tour_i18n check_boot_guard \
           check_field_homes check_runner_model_fields check_command_mirrors check_installer_assets check_cell_python_floor check_cell_self_capture check_cell_card_keys check_proxy_id_namespace \
           check_cell_health_contract; do
      printf '  %-30s ' "$g"; python3 "scripts/$g.py" >/dev/null 2>&1 && echo "✓" || { echo "✗"; exit 1; }
  done
  printf '  %-30s ' "testability_names"
  python3 scripts/testability_names.py --check >/dev/null 2>&1 && echo "✓" || { echo "✗"; exit 1; }
  for t in test_guards_fail test_cell_servers test_settings_bundle test_download_retry test_auto_provision test_admin_store test_topology_store test_proxy_store test_auth_store test_cloud_store test_slot_artifacts test_scout_errors test_query_flags; do
      printf '  %-30s ' "$t"; python3 "scripts/$t.py" >/dev/null 2>&1 && echo "✓" || { echo "✗"; exit 1; }
  done
) || die "проверки на публичном дереве не прошли"

if [[ $DRY -eq 1 ]]; then
    head1 "сухой прогон"
    git -C "$PUB" add -A
    say "изменений: $(git -C "$PUB" diff --cached --stat | tail -1)"
    git -C "$PUB" reset -q
    git -C "$PUB" checkout -q -- . 2>/dev/null || true
    say "коммит НЕ создан, ветка $BRANCH оставлена"
    exit 0
fi

head1 "коммит"
# add -A, never `commit -am`: -am stages only files git already tracks, so a NEW
# module is silently left behind. That happened once — the public CI went red on
# an import of a file that had never been committed.
git -C "$PUB" add -A
if git -C "$PUB" diff --cached --quiet; then
    say "нечего синхронизировать — публичная копия уже совпадает"
    exit 0
fi
MSG="$(mktemp)"; trap 'rm -f "$LIST" "$SCAN" "$MSG"' EXIT
{
    git -C "$PRIV" log --format='%s' "$(git -C "$PUB" rev-parse origin/main)..HEAD" 2>/dev/null \
        | head -1 || echo "Sync from private"
    echo
    echo "Сводка правок — при необходимости переписать перед пушем."
} > "$MSG"
git -C "$PUB" -c user.name="$IDENT_NAME" -c user.email="$IDENT_MAIL" \
    -c commit.gpgsign=false commit -q -F "$MSG"
say "$(git -C "$PUB" log -1 --format='%h %s')"
say "файлов: $(git -C "$PUB" diff --stat origin/main HEAD | tail -1)"

head1 "отправка — вручную"
cat <<EOF
  Скрипт НЕ пушит: после двух инцидентов это решение человека.
  Проверьте сообщение коммита, затем:

      git -C "$PUB" push origin $BRANCH:main

  Ветку по имени. Никогда --tags: так однажды на GitHub уехали пять приватных
  тегов, один с тысячей коммитов и личным адресом в авторах.

  После пуша сверить, что на той стороне ровно то, что ожидалось:

      git -C "$PUB" ls-remote --heads origin
EOF
