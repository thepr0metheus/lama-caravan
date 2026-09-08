// Минимум браузерных глобалов, чтобы модули static/js ИМПОРТИРОВАЛИСЬ в node.
// Ровно столько, сколько нужно на этапе импорта; всё, что трогает DOM при
// вызове, в снимках не вызывается — либо покрывается заглушкой модуля.
const noop = () => undefined;
// Форма читается через $(id) → document.getElementById и .value/.checked.
// Снимок задаёт поля словарём globalThis.__fields = { id: { value, checked } };
// всё, чего в словаре нет, — null, как в браузере для отсутствующего элемента.
// Этого достаточно, чтобы гонять readConfigForm без DOM-движка.
const el = (id) => (globalThis.__fields && Object.prototype.hasOwnProperty.call(globalThis.__fields, id))
  ? globalThis.__fields[id] : null;
globalThis.document = { getElementById: el, addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, querySelector: () => null, querySelectorAll: () => [],
                        body: {}, documentElement: { dataset: {}, style: {} },
                        addEventListener: noop, removeEventListener: noop, createElement: () => ({ style: {}, dataset: {}, setAttribute: noop, appendChild: noop }) };
globalThis.window = globalThis;
// Сеть под снимком не нужна и не должна быть: fetch записывает вызовы в
// globalThis.__fetchCalls (path, method, body) и отвечает тем, что лежит в
// globalThis.__fetchReply[path] (или {ok:true}). Так пинится то, что уходит
// на провод, — а не ответ сервера.
globalThis.__fetchCalls = [];
globalThis.__fetchReply = {};
globalThis.fetch = async (path, opts = {}) => {
  globalThis.__fetchCalls.push({ path: String(path), method: opts.method || "GET", body: opts.body === undefined ? null : opts.body });
  const reply = Object.prototype.hasOwnProperty.call(globalThis.__fetchReply, String(path)) ? globalThis.__fetchReply[String(path)] : { ok: true };
  const status = (reply && typeof reply === "object" && typeof reply.__status === "number") ? reply.__status : 200;
  return new Response(JSON.stringify(reply), { status, headers: { "content-type": "application/json" } });
};
// Модули вешают слушатели на window/document на верхнем уровне (resize, keydown,
// visibilitychange); в node это no-op — снимки не про события.
globalThis.addEventListener = noop; globalThis.removeEventListener = noop; globalThis.dispatchEvent = noop;
globalThis.location = { pathname: "/", search: "", hash: "", href: "http://localhost/" };
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k), clear: () => store.clear() };
globalThis.sessionStorage = globalThis.localStorage;
if (!globalThis.navigator?.language) {
  try { Object.defineProperty(globalThis, "navigator", { value: { language: "en", languages: ["en"] }, configurable: true }); } catch (e) {}
}
// Таймер страницы не должен продлевать жизнь СНИМКУ. Опрос, который в браузере
// правильно тикает, пока идёт загрузка, в node держал бы процесс вечно: снимок
// висел бы вместо того, чтобы упасть или пройти. unref() оставляет таймерам всю
// их работу, но лишает права одним своим существованием не давать выйти.
const _realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => {
  const handle = _realSetTimeout(fn, ms, ...rest);
  if (handle && typeof handle.unref === "function") handle.unref();
  return handle;
};
globalThis.setInterval = ((real) => (fn, ms, ...rest) => {
  const handle = real(fn, ms, ...rest);
  if (handle && typeof handle.unref === "function") handle.unref();
  return handle;
})(globalThis.setInterval);
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop, removeEventListener: noop });
