"use strict";

("use strict");
// Locale affects presentation only. API identifiers and stored user data remain unchanged.
let currentLanguage =
  typeof navigator !== "undefined" &&
  navigator.language?.toLowerCase().startsWith("en")
    ? "en"
    : "es";
try {
  const saved = globalThis.localStorage?.getItem("commerce-demo-language");
  if (saved === "en" || saved === "es") currentLanguage = saved;
} catch {}
function getLanguage() {
  return currentLanguage;
}
function uiLocale() {
  return currentLanguage === "en" ? "en-US" : "es-AR";
}
const reverseMessages = new Map();
for (const [es, en] of Object.entries(MESSAGES))
  if (!reverseMessages.has(en)) reverseMessages.set(en, es);
const messagePatterns = [];
for (const [es, en] of Object.entries(MESSAGES))
  if (/\{\d+\}/.test(es)) {
    const build = (key) => {
      const slots = [];
      let pattern = "",
        cursor = 0;
      for (const m of key.matchAll(/\{(\d+)\}/g)) {
        pattern +=
          key.slice(cursor, m.index).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
          "([\\s\\S]*?)";
        slots.push(Number(m[1]));
        cursor = m.index + m[0].length;
      }
      pattern += key.slice(cursor).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return { re: new RegExp("^" + pattern + "$"), slots };
    };
    messagePatterns.push({ es, en, source: build(es), target: build(en) });
  }
function interpolate(text, args) {
  return text.replace(/\{(\d+)\}/g, (match, i) =>
    i < args.length ? String(args[i]) : match,
  );
}
function tr(key, args = []) {
  if (typeof key !== "string")
    return key === null || key === undefined ? "" : String(key);
  const canonical = Object.hasOwn(MESSAGES, key)
    ? key
    : reverseMessages.get(key);
  if (canonical !== undefined)
    return interpolate(
      currentLanguage === "en" ? MESSAGES[canonical] : canonical,
      args,
    );
  for (const p of messagePatterns) {
    const source = p.source.re.exec(key),
      target = source ? null : p.target.re.exec(key),
      match = source || target;
    if (match) {
      const values = [];
      const slots = (source ? p.source : p.target).slots;
      slots.forEach((slot, i) => (values[slot] = match[i + 1]));
      return interpolate(currentLanguage === "en" ? p.en : p.es, values);
    }
  }
  for (const [es, en] of Object.entries(MESSAGES)) {
    if (
      es.length > 4 &&
      /\s$/.test(es) &&
      !/^\s/.test(es) &&
      !es.includes("{")
    ) {
      if (key.startsWith(es))
        return (currentLanguage === "en" ? en : es) + key.slice(es.length);
      if (key.startsWith(en))
        return (currentLanguage === "en" ? en : es) + key.slice(en.length);
    }
  }
  return key;
}
class UiValue {
  constructor(read, raw) {
    this.read = read;
    this.raw = raw;
  }
  value() {
    const v = this.read();
    if (v instanceof UiValue) return v.value();
    return this.raw ? String(v ?? "") : tr(String(v ?? ""));
  }
  toString() {
    return this.value();
  }
}
function ui(read, raw = false) {
  return new UiValue(read, raw);
}
function resolveUi(v) {
  while (v instanceof UiValue) v = v.read();
  return v;
}
function uiEmpty(v) {
  while (v instanceof UiValue) v = v.read();
  return v === null || v === undefined;
}
const localizedBindings = new Map();
function setText(node, value) {
  if (!node) return;
  const read = () =>
    value instanceof UiValue ? value.value() : String(value ?? "");
  localizedBindings.set(node, { kind: "text", read });
  node.textContent = read();
}
function localizeAttribute(node, name, key) {
  const read = () => (key instanceof UiValue ? key.value() : tr(key));
  const attribute = { node, name, read };
  attributeBindings.add(attribute);
  node.setAttribute(name, read());
}
const attributeBindings = new Set();
function serverMessage(message, status) {
  const original = String(message);
  if (original.startsWith("Value error, "))
    return (
      (currentLanguage === "en" ? "Invalid input: " : "Entrada inválida: ") +
      serverMessage(original.slice(13), status)
    );
  const field = /^([^:\n]{1,60}): (.+)$/.exec(original);
  if (
    field &&
    (Object.hasOwn(MESSAGES, field[1]) ||
      reverseMessages.has(field[1]) ||
      /^[a-z_]+$/.test(field[1]))
  )
    return tr(field[1]) + ": " + serverMessage(field[2], status);
  const translated = tr(original);
  if (
    currentLanguage === "es" ||
    translated !== original ||
    reverseMessages.has(original) ||
    Object.hasOwn(MESSAGES, original)
  )
    return translated;
  if (
    /^[\x00-\x7F]+$/.test(original) &&
    /required|greater|less|valid|input|field/i.test(original)
  )
    return original;
  return (
    "Request failed" +
    (status ? " (HTTP " + status + ")" : "") +
    ". Please refresh and try again."
  );
}
function pruneLocaleBindings() {
  for (const [node] of localizedBindings)
    if (node.isConnected === false) localizedBindings.delete(node);
  for (const binding of attributeBindings)
    if (binding.node.isConnected === false) attributeBindings.delete(binding);
}
function setLanguage(language) {
  if (!["es", "en"].includes(language)) throw new Error("Unsupported language");
  const selector =
    typeof document !== "undefined"
      ? document.getElementById("ui-language")
      : null;
  if (
    (typeof state !== "undefined" && state.busy) ||
    (typeof ops !== "undefined" && ops.incierta) ||
    (typeof document !== "undefined" &&
      document.getElementById("confirmacion")?.open)
  ) {
    if (selector) selector.value = currentLanguage;
    return false;
  }
  currentLanguage = language;
  try {
    globalThis.localStorage?.setItem("commerce-demo-language", language);
  } catch {}
  if (typeof document !== "undefined") {
    document.documentElement?.setAttribute?.("lang", language);
    if (selector) selector.value = language;
  }
  for (const [node, binding] of localizedBindings) {
    if (node.isConnected === false) {
      localizedBindings.delete(node);
      continue;
    }
    try {
      node.textContent = binding.read();
    } catch {
      localizedBindings.delete(node);
    }
  }
  for (const binding of attributeBindings) {
    if (binding.node.isConnected === false) {
      attributeBindings.delete(binding);
      continue;
    }
    binding.node.setAttribute(binding.name, binding.read());
  }
  return true;
}
function initializeLanguage() {
  if (typeof document.createTreeWalker !== "function") return;
  document.documentElement.lang = currentLanguage;
  const walk = document.createTreeWalker(document.body, 4),
    nodes = [];
  while (walk.nextNode()) nodes.push(walk.currentNode);
  for (const node of nodes) {
    const key = node.textContent.trim();
    if (key && Object.hasOwn(MESSAGES, key))
      setText(
        node,
        ui(() => tr(key)),
      );
  }
  for (const node of document.querySelectorAll(
    '[placeholder],[aria-label],meta[name="description"]',
  ))
    for (const attr of ["placeholder", "aria-label", "content"]) {
      const value = node.getAttribute(attr);
      if (value && Object.hasOwn(MESSAGES, value))
        localizeAttribute(node, attr, value);
    }
  const titleKey = "Gestión del negocio · Sistema de prueba";
  const title = document.querySelector("title");
  if (title)
    setText(
      title,
      ui(() => tr(titleKey)),
    );
  const select = document.getElementById("ui-language");
  if (select) {
    select.value = currentLanguage;
    select.addEventListener("change", () => setLanguage(select.value));
  }
  // Browser-generated form validation text is localized explicitly; values stay untouched.
  document.addEventListener(
    "invalid",
    (event) => {
      const input = event.target;
      input.setCustomValidity?.("");
      if (input.validity?.valueMissing)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "Please complete this field."
            : "Completá este campo.",
        );
      else if (input.validity?.patternMismatch)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "Please use the requested format."
            : "Usá el formato solicitado.",
        );
      else if (input.validity?.typeMismatch || input.validity?.badInput)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "Enter a valid value for this field."
            : "Ingresá un valor válido para este campo.",
        );
      else if (input.validity?.rangeUnderflow)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "The value must be at least " + input.min + "."
            : "El valor debe ser al menos " + input.min + ".",
        );
      else if (input.validity?.rangeOverflow)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "The value must be at most " + input.max + "."
            : "El valor debe ser como máximo " + input.max + ".",
        );
      else if (input.validity?.stepMismatch)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "Use the allowed numeric step."
            : "Usá el incremento numérico permitido.",
        );
      else if (input.validity?.tooShort)
        input.setCustomValidity(
          currentLanguage === "en"
            ? "Use at least " + input.minLength + " characters."
            : "Usá al menos " + input.minLength + " caracteres.",
        );
    },
    true,
  );
  document.addEventListener(
    "input",
    (event) => event.target.setCustomValidity?.(""),
    true,
  );
}
initializeLanguage();
