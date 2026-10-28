// Teksty interfejsu: domyślnie angielski, polski do wyboru w ustawieniach (sekcja Ogólne).
// Słowniki są w JSON-ie, żeby tests/test_i18n.py mógł sprawdzić, że oba języki mają te same klucze.
import en from './i18n/en.json' with { type: 'json' }
import pl from './i18n/pl.json' with { type: 'json' }

const dictionaries = { en, pl }
export const UI_LANGUAGES = [['en', 'English'], ['pl', 'Polski']]  // każdy w swoim języku
let current = 'en'

export function setLanguage(code) {
  current = code in dictionaries ? code : 'en'
  document.documentElement.lang = current
}

export function language() {
  return current
}

export function locale() {
  return current === 'pl' ? 'pl-PL' : 'en-GB'
}

// Tekst z miejscami {nazwa}; wpis z formami liczby mnogiej wybiera formę według params.n.
export function t(key, params = {}) {
  let text = dictionaries[current][key] ?? en[key] ?? key
  if (typeof text === 'object') {
    const form = new Intl.PluralRules(locale()).select(params.n ?? 0)
    text = text[form] ?? text.other
  }
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match))
}

export function has(key) {
  return key in en
}

// Liczba z separatorem dziesiętnym języka interfejsu; bez `digits` najwyżej trzy miejsca po przecinku.
export function num(value, digits) {
  const options = digits === undefined ? {} : { minimumFractionDigits: digits, maximumFractionDigits: digits }
  return value.toLocaleString(locale(), options)
}

// Serwer zgłasza błędy kodami ({code, ...szczegóły}), które tłumaczy dopiero interfejs.
// Dane zapisane przez wersję 0.3.0 i starsze mogą mieć zamiast kodu gotowy polski tekst.
export function problemText(problem) {
  if (typeof problem === 'string') return problem
  if (typeof problem?.code !== 'string') return ''
  return has(`error.${problem.code}`) ? t(`error.${problem.code}`, problem) : problem.detail || problem.code
}

// Elementy oznaczone w index.html: data-i18n (treść), data-i18n-title i data-i18n-placeholder.
export function applyStatic(root = document) {
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n)
  for (const el of root.querySelectorAll('[data-i18n-title]')) el.title = t(el.dataset.i18nTitle)
  for (const el of root.querySelectorAll('[data-i18n-placeholder]')) el.placeholder = t(el.dataset.i18nPlaceholder)
}
