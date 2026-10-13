#!/usr/bin/env python3
"""CI guard: the text of the cell editor is shown, and translated.

The cell editor's markup (`#llamaRemoteEditOverlay` in static/index.html) is static HTML that
applyLanguage() (static/js/i18n.js) rewrites from its [data-i18n*] attributes, and that
static/css/monitor.css and applyCellKindUI() (static/js/llama-edit.js) show or hide. Three things
have gone wrong between the markup and the screen, and nothing else could see any of them:

  1. TRANSLATED. Text with no data-i18n is never translated: the label of the cache switch
     ("Cache model on host disk — keep the downloaded model in the scout's cache …") stood in
     English on every other language's page (found 2026-10-13, written by commit 0a56e16ed).
     check_i18n_calls.py proves that every key the markup ASKS for exists; a sentence that asks for
     none is invisible to it. Prose is a text node of three or more words, each with a run of three
     lowercase letters ("keep the downloaded model"). Not prose, so not asked for: the names of
     things (`<option>`, `<code>`, `<pre>`, `<textarea>`; a field's name MAX_MODEL_LEN is one word).

  2. SHOWN. The editor's CSS hid every paragraph of a field: `.topo-edit-form .field p
     { display: none }` — "info is in the ? tooltips" — and from 2026-05-31 on the notes written as
     `<p class="field-note">` (the command cell's, vLLM's, Strata's, Seamless's, the health probe's)
     were never seen. A field-note is a note its panel means to be read: the CSS leaves it
     (`p:not(.field-note)`) and this guard fails when a bare hiding rule is back or the narrow one
     is gone. Any other paragraph of a field is hidden, so it is allowed only as a help line
     (`ct-help`) whose field HAS the (?) tip it stands for — MODEL_NAME's was hidden with no tip
     anywhere until 1.3.518. An exempt paragraph needs no data-i18n: nobody reads it.

  3. NOT HIDDEN WITH A CARRIER. applyCellKindUI() hides the `.field` nearest to TRANSLATE_MODEL —
     the carrier of a value the shared picker sets — and as a bare label and input that `.field` was
     the whole NLLB panel: its languages and its note were never shown (2026-08-18 to 1.3.518).
     The carrier must have a `.field` of its own that holds none of the controls the panel shows.

EXCEPTIONS are element ids (the nearest one above the text) whose untranslated prose is known, each
with its reason. The list may only shrink: an id that no longer holds such prose fails the guard, so
an entry cannot outlive its cause.

Out of scope: attributes (`placeholder` holds examples of commands and paths; `title` and
`aria-label` have their own data-title-i18n and data-i18n-aria, checked by check_i18n_calls.py).
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "static" / "index.html"
CSS = ROOT / "static" / "css" / "monitor.css"
EDITOR_JS = ROOT / "static" / "js" / "llama-edit.js"
FORM = "llamaRemoteEditOverlay"

#: Untranslated prose that is still there, by the id of the nearest element, and why. None today: the last
#: one, the note of the model-cache panel (rewritten by purgeRemoteModelCache with English fragments of its
#: own, "file(s)" and "GB freed"), became a note and a status line with keys in 1.3.525. The list stays so
#: that the next excuse has to be written down with its reason, and goes when its prose does.
EXCEPTIONS = {}
#: A carrier the editor hides with `$(pfx + id)?.closest(".field")`, and the controls of its panel
#: that must stay shown when it is hidden.
CARRIERS = {"tr-TRANSLATE_MODEL": ("tr-TRANSLATE_SRC_LANG", "tr-TRANSLATE_TGT_LANG")}

VOID = {"input", "br", "img", "hr", "meta", "link", "source", "wbr", "col", "area", "base", "embed", "param", "track"}
#: Elements whose text names things or is code, not prose.
NOT_PROSE = {"option", "code", "pre", "textarea", "script", "style"}
#: Attributes that make applyLanguage() write the element's own text (or its tooltip's).
COVERS = {"data-i18n", "data-i18n-tip", "data-fieldhelp", "data-fieldhelp-text"}
#: Paragraphs of a field the CSS keeps shown: a note, and the line under the runner row.
SHOWN_P = {"field-note", "runner-benefits"}
#: The rule that hides the descriptions of a field, as monitor.css spells it, and the one it must not be.
HIDING_RULE = re.compile(r"\.topo-edit-form\s+\.field\s+p:not\(\.field-note\)\s*\{[^}]*display\s*:\s*none")
BARE_HIDING_RULE = re.compile(r"\.topo-edit-form\s+\.field\s+p\s*\{[^}]*display\s*:\s*none")
TIP_FIELDS = re.compile(r"const _STATIC_TIP_FIELDS = \[([^\]]*)\]", re.S)


def is_prose(text):
    words = [w for w in text.split() if re.search(r"[a-z]{3,}", w)]
    return len(words) >= 3


class FormMarkup(HTMLParser):
    """What the guard reads of the cell editor: its untranslated prose, its hidden paragraphs, and the
    `.field` chain above every id (to tell which field a carrier is hidden with)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = []        # (tag, nearest id, text): prose no data-i18n covers
        self.hidden = []       # (nearest id, classes, data-fieldhelp-text): a paragraph the CSS hides
        self.fields = {}       # id -> ids of the `.field` elements above it, self included

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        above = self.stack[-1] if self.stack else {}
        classes = set((a.get("class") or "").split())
        fields = list(above.get("fields", ()))
        if "field" in classes:
            fields.append(a.get("id") or f"(field without id above line {self.getpos()[0]})")
        hides = (tag == "p" and above.get("in_topo_form", False) and above.get("in_field", False)
                 and not classes & SHOWN_P)
        node = {
            "tag": tag,
            "id": a.get("id") or above.get("id", ""),
            "in_form": above.get("in_form", False) or a.get("id") == FORM,
            "in_topo_form": above.get("in_topo_form", False) or "topo-edit-form" in classes,
            "in_field": above.get("in_field", False) or "field" in classes,
            "covered": above.get("covered", False) or bool(COVERS & set(a)),
            "skip": above.get("skip", False) or tag in NOT_PROSE,
            "hidden_p": above.get("hidden_p", False) or hides,
            "fields": fields,
        }
        if a.get("id") and node["in_form"]:
            self.fields[a["id"]] = fields
        if hides and not above.get("hidden_p", False):
            self.hidden.append((node["id"], sorted(classes), a.get("data-fieldhelp-text", "")))
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.stack:
            return
        node = self.stack[-1]
        if not node["in_form"] or node["covered"] or node["skip"] or node["hidden_p"]:
            return
        text = " ".join(data.split())
        if is_prose(text):
            self.found.append((node["tag"], node["id"], text))


def tip_fields():
    """The fields the editor gives a (?) tip by id (llama-edit.js `_STATIC_TIP_FIELDS`)."""
    found = TIP_FIELDS.search(EDITOR_JS.read_text(encoding="utf-8"))
    return set(re.findall(r'"([A-Z0-9_]+)"', found.group(1))) if found else set()


def main():
    problems = []
    css = CSS.read_text(encoding="utf-8")
    if BARE_HIDING_RULE.search(css):
        problems.append(f"{CSS.relative_to(ROOT)} hides every `.topo-edit-form .field p` again, the notes "
                        "(`p.field-note`) with the descriptions: write it as `p:not(.field-note)`")
    if not HIDING_RULE.search(css):
        problems.append(f"{CSS.relative_to(ROOT)} no longer hides the descriptions (`display: none` on "
                        "`.topo-edit-form .field p:not(.field-note)`): they show now, and the exemption for them "
                        "in this guard is no longer true")

    parser = FormMarkup()
    parser.feed(HTML.read_text(encoding="utf-8"))

    seen = set()
    for tag, ident, text in parser.found:
        if ident in EXCEPTIONS:
            seen.add(ident)
            continue
        problems.append(f"<{tag}> in #{ident or '(no id above)'}: \"{text[:90]}\" — give it a data-i18n key "
                        "(en.js and the 19 other languages)")
    for ident in sorted(set(EXCEPTIONS) - seen):
        problems.append(f"EXCEPTIONS lists #{ident}, but no untranslated prose is left in it: remove the entry")

    tips = tip_fields()
    for ident, classes, helps in parser.hidden:
        if "ct-help" in classes and helps in tips:
            continue            # a help line whose (?) tip is where the help is read
        what = (f"its field {helps} has no (?) tip in llama-edit.js `_STATIC_TIP_FIELDS`" if "ct-help" in classes and helps
                else "it is a paragraph of a field, and the editor's CSS hides those")
        problems.append(f"a <p> in #{ident or '(no id above)'} is never seen: {what} — write a note as "
                        "`p.field-note`, or give the field its tip")

    for carrier, shown in CARRIERS.items():
        own = (parser.fields.get(carrier) or [None])[-1]
        if own is None:
            problems.append(f"#{carrier} is not in the cell editor, or sits in no `.field`: the editor hides its nearest "
                            "`.field`, which has to exist")
            continue
        for ident in shown:
            if own in parser.fields.get(ident, []):
                problems.append(f"#{ident} sits inside #{own}, the `.field` the editor hides with #{carrier}: "
                                f"give #{carrier} a `.field` of its own")

    for line in problems:
        print(f"check_cell_form_text: {line}", file=sys.stderr)
    if problems:
        return 1
    print(f"check_cell_form_text OK: the text of the cell editor is shown and translated "
          f"({len(seen)} known exception{'s' if len(seen) != 1 else ''}, {len(parser.hidden)} hidden help "
          f"line{'s' if len(parser.hidden) != 1 else ''} with a tip, {len(CARRIERS)} carrier with a field of its own)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
