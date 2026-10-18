// What the boot is waiting for, in its own words, for the inline guard at the top of each page's body (the <script> that
// says "This page did not finish loading"): `window.__bootWaiting`, read when the page is still "loading" after 20s. It is
// the FIRST import of an entry module (main.js), so it runs before the rest of the module graph is evaluated — a graph
// that never finishes loading leaves its first word as the last one, and the banner can say "the other scripts" instead
// of nothing. Each step of the boot then says what it waits for next, and the banner says where the boot stood still.
// The name is the guard's and this file's one fact: check_boot_guard.py holds the two to it.
export class BootStep {
  static waitsFor(what) {
    window.__bootWaiting = what;
  }
}

BootStep.waitsFor("the other scripts to load");
