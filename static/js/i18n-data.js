// UI translation data. 20 languages; strings missing from a language fall
// back to English (see t() in i18n helpers).
export const LANGS = [
  { code: "en", emoji: "☕", label: "English" },
  { code: "zh", emoji: "🐼", label: "中文" },
  { code: "hi", emoji: "🪷", label: "हिन्दी" },
  { code: "es", emoji: "🥘", label: "Español" },
  { code: "fr", emoji: "🥐", label: "Français" },
  { code: "ar", emoji: "🕌", label: "العربية" },
  { code: "bn", emoji: "🐅", label: "বাংলা" },
  { code: "pt", emoji: "⚽", label: "Português" },
  { code: "ru", emoji: "🪆", label: "Русский" },
  { code: "ja", emoji: "🗻", label: "日本語" },
  { code: "de", emoji: "🥨", label: "Deutsch" },
  { code: "id", emoji: "🦎", label: "Bahasa Indonesia" },
  { code: "ur", emoji: "🌙", label: "اردو" },
  { code: "tr", emoji: "🧿", label: "Türkçe" },
  { code: "ko", emoji: "🥋", label: "한국어" },
  { code: "vi", emoji: "🛵", label: "Tiếng Việt" },
  { code: "it", emoji: "🍕", label: "Italiano" },
  { code: "te", emoji: "🪔", label: "తెలుగు" },
  { code: "mr", emoji: "🥭", label: "मराठी" },
  { code: "ta", emoji: "🐘", label: "தமிழ்" },
];

// ── the tables themselves ────────────────────────────────────────────────────
// One file per language under ./i18n/, loaded when that language is selected.
// They used to live here, all twenty of them, in a single 1.95 MB module that
// every page downloaded in full to render ONE of them — 62% of the JS on the
// board, and the largest thing on a cold load by a wide margin.
//
// `en` is the exception and is imported statically: t() falls back to English
// for any key a translation is missing, and that fallback is synchronous, so
// English has to be there before the first render regardless of the language.
// An English UI therefore still loads exactly one table.
import en from "./i18n/en.js";

export const messages = { en };

const KNOWN = new Set(LANGS.map((l) => l.code));

// Modules that add their own strings to a language table — the onboarding tours
// keep theirs in onboarding-strings.js and merge them in. That merge used to run
// once at import, when every language was already present. Now a table arrives
// later than the module does, so the merge has to run again for each one, or a
// tour in Japanese would silently be a tour in English.
const _augmenters = [];

export function onLanguageLoaded(fn) {
  _augmenters.push(fn);
  Object.keys(messages).forEach((code) => fn(code, messages[code]));
}

/** Load one language's table into `messages`. Idempotent; resolves to the code
 *  actually available, which is "en" when the requested file cannot be had —
 *  a missing translation must not leave the page with no strings at all. */
export async function loadLanguage(code) {
  const want = String(code || "").trim();
  if (!want || !KNOWN.has(want) || messages[want]) return messages[want] ? want : "en";
  try {
    messages[want] = (await import(`./i18n/${want}.js`)).default;
    _augmenters.forEach((fn) => fn(want, messages[want]));
    return want;
  } catch (err) {
    console.warn(`i18n: ${want} unavailable, staying on English`, err);
    return "en";
  }
}

/** Every language at once. For the CI guards that compare all twenty against
 *  English — never call this from the page; it is the 1.9 MB this split exists
 *  to avoid. */
export async function allMessages() {
  await Promise.all(LANGS.map((l) => loadLanguage(l.code)));
  return messages;
}
