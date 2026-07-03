// /models page: tree of downloaded GGUFs (model → author → quant → files)
// with size rollups, which cells reference each file, and deletion of the
// unreferenced ones. Data: /api/models/unused + /api/models/disk; deletion:
// /api/models/gc (refuses referenced files server-side too).
import { appConfirm, settleAppConfirm } from "./dialogs.js";
import { applyLanguage, applyTheme, setupLangSelect, t } from "./i18n.js";
import { ui } from "./state.js";
import { $, api, escapeHtml, toast } from "./utils.js";

function fmtGb(bytes) {
  const gb = bytes / 2 ** 30;
  return gb >= 100 ? `${Math.round(gb)} GB` : `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`;
}

function stat(label, value, kind = "") {
  return `<div class="mdl-stat ${kind}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
}

function updatePicked() {
  const picked = [...document.querySelectorAll("#mdlTree input[data-del-path]:checked")];
  const bytes = picked.reduce((a, el) => a + Number(el.dataset.size || 0), 0);
  $("mdlPicked").textContent = picked.length ? `${picked.length} · ${fmtGb(bytes)}` : "";
  $("mdlDelete").disabled = !picked.length;
}

async function refresh() {
  const tree = $("mdlTree");
  tree.innerHTML = `<p class="muted">…</p>`;
  let data, disk = null;
  try {
    [data, disk] = await Promise.all([
      api("/api/models/unused"),
      api("/api/models/disk").catch(() => null),
    ]);
  } catch (err) {
    tree.innerHTML = `<p class="muted">${escapeHtml(String(err.message || err))}</p>`;
    return;
  }
  if (!data.ok) {
    tree.innerHTML = `<p class="muted">${escapeHtml(data.error || "models dir not found")}</p>`;
    return;
  }
  const files = data.files || [];
  const totalBytes = files.reduce((a, f) => a + f.sizeBytes, 0);
  $("mdlPath").textContent = data.path || "";
  const hero = $("mdlHeroStats");
  const tiles = [
    stat("GGUF", String(files.length)),
    stat(t("ctrlModels"), fmtGb(totalBytes)),
    stat(t("gcTitle"), `${data.unusedCount} · ${data.unusedGb} GB`, data.unusedCount ? "warn" : "good"),
  ];
  if (disk && disk.ok) tiles.push(stat(t("ctrlDisk"), `${disk.freeGb} GB ${t("ctrlDiskFree")}`, (disk.freeGb || 0) < 50 ? "warn" : "good"));
  hero.innerHTML = tiles.join("");

  // Group flat rel-paths into model → author → quant → files. Each level also
  // rolls up the FRESHEST file age inside it — the collapsed row answers
  // "when was anything in here last touched" without expanding.
  const grouped = new Map();
  files.forEach((f) => {
    const segs = f.path.split("/");
    const model = segs.length > 1 ? segs[0] : "(root)";
    const author = segs.length > 2 ? segs[1] : "·";
    const quant = segs.length > 3 ? segs[2] : "·";
    if (!grouped.has(model)) grouped.set(model, { bytes: 0, minAge: Infinity, children: new Map() });
    const l1 = grouped.get(model); l1.bytes += f.sizeBytes; l1.minAge = Math.min(l1.minAge, f.ageDays);
    if (!l1.children.has(author)) l1.children.set(author, { bytes: 0, minAge: Infinity, children: new Map() });
    const l2 = l1.children.get(author); l2.bytes += f.sizeBytes; l2.minAge = Math.min(l2.minAge, f.ageDays);
    if (!l2.children.has(quant)) l2.children.set(quant, { bytes: 0, minAge: Infinity, files: [] });
    const l3 = l2.children.get(quant); l3.bytes += f.sizeBytes; l3.minAge = Math.min(l3.minAge, f.ageDays);
    l3.files.push(f);
  });
  const fileRow = (f) => {
    const name = f.path.split("/").pop();
    const usedBy = (f.referencedBy || []).join(", ");
    const used = f.referenced
      ? `<span class="mdl-used" title="${escapeHtml(usedBy)}">✓ ${escapeHtml(usedBy || "used")}</span>`
      : `<input type="checkbox" data-del-path="${escapeHtml(f.path)}" data-size="${f.sizeBytes}">`;
    return `<div class="mdl-file">${used}<code title="${escapeHtml(f.path)}">${escapeHtml(name)}</code>` +
      `<span class="meta">${fmtGb(f.sizeBytes)} · ${f.ageDays}d</span></div>`;
  };
  const freshness = (age) => (age === Infinity ? "" : ` · ${age}d`);
  const lvl = (label, node, inner) => `
    <details>
      <summary><span class="tw"></span><span class="mdl-name">${escapeHtml(label)}</span>
        <span class="mdl-size">${fmtGb(node.bytes)}${freshness(node.minAge)}</span></summary>
      <div class="mdl-lvl">${inner}</div>
    </details>`;
  tree.innerHTML = [...grouped.entries()]
    .sort((a, b) => b[1].bytes - a[1].bytes)
    .map(([model, l1]) => lvl(model, l1,
      [...l1.children.entries()].map(([author, l2]) => lvl(author, l2,
        [...l2.children.entries()].map(([quant, l3]) =>
          lvl(quant, l3, l3.files.map(fileRow).join(""))).join(""))).join("")))
    .join("") || `<p class="muted">${escapeHtml(t("gcNoUnused"))}</p>`;
  updatePicked();
}

function bindUserChip() {
  const doLogout = async () => {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch { /* ignore */ }
    window.location = "/login";
  };
  api("/api/auth/me").then((me) => {
    if (!me.enabled || !me.authenticated) return;
    $("userChipName").textContent = me.user + (me.role === "viewer" ? " · viewer" : "");
    $("userChip").hidden = false;
    const menu = $("userMenu");
    const closeMenu = () => { menu.hidden = true; $("userChipBtn").setAttribute("aria-expanded", "false"); };
    $("userChipBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      $("userChipBtn").setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", (e) => { if (!$("userChip").contains(e.target)) closeMenu(); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) closeMenu(); });
    $("userMenuLogout").addEventListener("click", doLogout);
  }).catch(() => {});
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme();
  applyLanguage();
  setupLangSelect();
  bindUserChip();

  $("confirmCancel").addEventListener("click", () => settleAppConfirm(false));
  $("confirmDelete").addEventListener("click", () => { if (ui.pendingConfirm) ui.pendingConfirm(); });
  $("confirmOverlay").addEventListener("click", (e) => {
    if (e.target.id === "confirmOverlay") settleAppConfirm(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("confirmOverlay").hidden) settleAppConfirm(false);
  });

  // Models-dir editing: same contract as the board's MODELS bar — /api/config
  // replaces the WHOLE saved config, so merge over the current one (fetched
  // at save time; it is the only consumer of the heavy /api/state here).
  $("mdlPathEdit").addEventListener("click", () => {
    $("mdlPathInput").value = $("mdlPath").textContent.trim();
    $("mdlPathEditRow").hidden = false;
    $("mdlPathInput").focus();
  });
  $("mdlPathCancel").addEventListener("click", () => { $("mdlPathEditRow").hidden = true; });
  $("mdlPathInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("mdlPathSave").click(); }
    if (e.key === "Escape") { e.preventDefault(); $("mdlPathCancel").click(); }
  });
  $("mdlPathSave").addEventListener("click", async () => {
    const newPath = $("mdlPathInput").value.trim();
    if (!newPath) return;
    const btn = $("mdlPathSave");
    btn.disabled = true; btn.classList.add("btn-busy");
    try {
      const st = await api("/api/state");
      const config = Object.assign({}, st.config || {}, { LLAMA_MODELS_DIR: newPath });
      await api("/api/config", { method: "POST", body: JSON.stringify({ config, restart: false }) });
      $("mdlPathEditRow").hidden = true;
      toast(t("saved"));
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false; btn.classList.remove("btn-busy");
    }
  });

  $("mdlTree").addEventListener("change", updatePicked);
  $("mdlSelectAll").addEventListener("click", () => {
    document.querySelectorAll("#mdlTree input[data-del-path]").forEach((el) => { el.checked = true; });
    updatePicked();
  });
  $("mdlDelete").addEventListener("click", async () => {
    const picked = [...document.querySelectorAll("#mdlTree input[data-del-path]:checked")];
    if (!picked.length) return;
    const bytes = picked.reduce((a, el) => a + Number(el.dataset.size || 0), 0);
    if (!(await appConfirm(t("gcConfirm", { count: String(picked.length) }) + ` (${fmtGb(bytes)})`,
                           { confirmLabel: t("gcDelete") }))) return;
    const btn = $("mdlDelete");
    btn.disabled = true; btn.classList.add("btn-busy");
    try {
      const res = await api("/api/models/gc", {
        method: "POST",
        body: JSON.stringify({ files: picked.map((el) => el.dataset.delPath) }),
      });
      toast(t("gcFreed", { gb: String(res.freedGb) }));
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false; btn.classList.remove("btn-busy");
    }
  });

  refresh();
});
