// Whether a page's markup draws what a tour step stands on (static/js/onboarding-tours.js). A step whose anchor no page draws is a
// step nobody sees: the engine drops it without a word (onboarding.js), and a machine's page ran the main board's tour that way —
// three of its steps on nothing, two on the whole page (2026-10-27). The forms this reads: #id, .class, [attr], [attr="value"],
// each alone, and a list of them ("A, B": one of them drawn). Any other form throws: a check that cannot read an anchor would
// pass it. The editor's anchors, which stand inside its form, are read against index.html by scripts/test_js_onboarding_tours.py.
export function drawn(html, selector) {
  return String(selector).split(",").map((one) => one.trim()).some((one) => {
    let m;
    if ((m = one.match(/^#([\w-]+)$/))) return String(html).includes(`id="${m[1]}"`);
    if ((m = one.match(/^\.([\w-]+)$/))) return new RegExp(`class="(?:[^"]*\\s)?${m[1]}(?:\\s[^"]*)?"`).test(String(html));
    if ((m = one.match(/^\[([\w-]+)\]$/))) return new RegExp(`\\s${m[1]}(?=[\\s=>])`).test(String(html));
    if ((m = one.match(/^\[([\w-]+)=(["'])([^"']*)\2\]$/))) return String(html).includes(`${m[1]}="${m[3]}"`);
    throw new Error(`an anchor this check cannot read: ${one}`);
  });
}
