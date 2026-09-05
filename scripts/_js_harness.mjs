// Загрузчик для снимков JS: грузит НАСТОЯЩИЙ модуль из static/js, а модули из
// списка JS_STUBS подменяет заглушками с теми же именами экспортов.
//
// Почему именно так. Фронт — 37 ES-модулей, 645 экспортных функций и ноль
// классов; «чистых» по DOM модулей четыре, но каждый импортирует рендер-функции,
// а те тянут всё приложение. Заглушка обязана экспортировать ТЕ ЖЕ имена, что
// настоящий модуль: ESM линкует импорты статически, и «экспорт чего угодно»
// (Proxy) здесь не работает — линкер сверяет список имён до исполнения. Поэтому
// имена читаются из настоящего файла, а тела — пустые функции с меткой __stub.
// Заглушке можно задать поведение: globalThis.__stubReturns["dialogs.appConfirm"] = async () => true —
// так снимок проходит подтверждение, которое в браузере ждёт клика.
// Не-функциональному экспорту можно задать значение: globalThis.__stubValues["canvas.SCHEDULE_WEEKDAYS"] = [...]
// — задаётся ДО импорта модуля под снимком, заглушка читает его при оценке; потом
// значение живой привязки меняется через globalThis.__stubSetters["мод.имя"](v).
//
// Запуск (см. scripts/test_js_*.py):
//   JS_ROOT=static/js JS_STUBS=form,cloud node --import <register hook> <probe>
import { readFileSync } from "node:fs";
import path from "node:path";

const STUBS = new Set((process.env.JS_STUBS || "").split(",").map((s) => s.trim()).filter(Boolean));
const ROOT = process.env.JS_ROOT;

// Заглушка async-функции обязана вернуть Promise: настоящий код пишет
// `refreshTopology().catch(...)`, и undefined на месте промиса — это не
// поведение модуля, а артефакт харнесса (он однажды попал в тост как
// «TypeError: reading 'catch'»).
const ASYNC = new Set();
function exportNames(file) {
  const src = readFileSync(file, "utf8");
  const names = new Set();
  for (const m of src.matchAll(/^export\s+async\s+function\s*\*?\s*(\w+)/gm)) ASYNC.add(path.basename(file, ".js") + "." + m[1]);
  for (const m of src.matchAll(/^export\s+(?:async\s+)?function\s*\*?\s*(\w+)/gm)) names.add(m[1]);
  // One declaration can name several bindings — `export let a = 1, b = 0, c = false;`
  // — and a stub that exports only the first breaks the ESM link with
  // "does not provide an export named ...". Split the declarator list.
  for (const m of src.matchAll(/^export\s+(?:const|let|var)\s+([^;\n]+)/gm))
    for (const part of m[1].split(","))
      { const n = part.trim().match(/^(\w+)/); if (n) names.add(n[1]); }
  for (const m of src.matchAll(/^export\s+class\s+(\w+)/gm)) names.add(m[1]);
  for (const m of src.matchAll(/^export\s+\{([^}]+)\}/gm))
    for (const n of m[1].split(",")) { const t = n.trim(); if (t) names.add(t.split(/\s+as\s+/).pop()); }
  return [...names];
}

export async function resolve(specifier, context, next) {
  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    const base = path.basename(specifier, ".js");
    if (STUBS.has(base)) return { url: "caravan-stub:" + base, shortCircuit: true };
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  if (url.startsWith("caravan-stub:")) {
    const base = url.slice("caravan-stub:".length);
    const names = exportNames(path.join(ROOT, base + ".js"));
    const body = names.map((n) => {
      const key = base + "." + n;
      const kw = ASYNC.has(key) ? "async " : "";
      // Не-функциональный экспорт соседа (массив дней недели, Map-кэш) можно задать
      // значением: globalThis.__stubValues["canvas.SCHEDULE_WEEKDAYS"] = [...] ДО импорта
      // модуля под снимком — заглушка читает его при своей оценке. Иначе экспорт —
      // функция, и `.indexOf` на ней был бы артефактом харнесса, не поведением.
      // Значение — ЖИВАЯ привязка (`let`) с сеттером в globalThis.__stubSetters[key]:
      // модуль под снимком видит смену значения между пинами (activeView,
      // topologyPointerDrag), как видел бы смену переменной настоящего соседа.
      return `export let ${n} = (() => { const key = ${JSON.stringify(key)}; if (globalThis.__stubValues && Object.prototype.hasOwnProperty.call(globalThis.__stubValues, key)) return globalThis.__stubValues[key]; const f = ${kw}(...a) => (globalThis.__stubReturns && typeof globalThis.__stubReturns[key] === "function") ? globalThis.__stubReturns[key](...a) : undefined; f.__stub = key; return f; })();
(globalThis.__stubSetters ||= {})[${JSON.stringify(key)}] = (v) => { ${n} = v; };`;
    }).join("\n");
    return { format: "module", source: body + "\nexport default {};\n", shortCircuit: true };
  }
  return next(url, context);
}
