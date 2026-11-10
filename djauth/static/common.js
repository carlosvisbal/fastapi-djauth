// Utilidades compartidas por las páginas de djauth. Funciona con sesión (cookie) o con token
// Bearer: si el servidor solo admite tokens, el token se guarda en sessionStorage de esta pestaña.

export const $ = (sel, root = document) => root.querySelector(sel);
const TOKEN_KEY = "djauth.token";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "value") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c instanceof Node ? c : String(c));
  return node;
}

export const token = {
  get() { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set(v) { try { v ? sessionStorage.setItem(TOKEN_KEY, v) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* sin almacenamiento */ } },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `Error ${status}`);
    this.status = status;
    this.errors = body?.errors || {};
  }
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`api/${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

let configPromise = null;
export function config() {
  configPromise ??= api("config").then((c) => {
    document.documentElement.style.setProperty("--brand", c.brand_color);
    document.title = `${document.title} · ${c.site_name}`;
    for (const n of document.querySelectorAll("[data-site-name]")) n.textContent = c.site_name;
    return c;
  });
  return configPromise;
}

/** Usuario actual o redirección al inicio de sesión. */
export async function requireLogin() {
  try {
    return await api("me");
  } catch (e) {
    if (e.status === 401) {
      location.replace(`login?next=${encodeURIComponent(location.pathname + location.search)}`);
      return new Promise(() => {});
    }
    throw e;
  }
}

export async function logout() {
  try { await api("logout", { method: "POST" }); } catch { /* ya estaba cerrada */ }
  token.set(null);
  location.href = "login";
}

export function setMsg(node, text, kind = "") {
  node.textContent = text || "";
  node.className = `msg ${kind}`;
}

/** Muestra los errores por campo (`errors` del servidor) bajo cada control con data-field. */
export function showErrors(form, err) {
  for (const n of form.querySelectorAll(".err")) n.remove();
  for (const [field, messages] of Object.entries(err.errors || {})) {
    const input = form.querySelector(`[data-field="${CSS.escape(field)}"]`);
    if (input) input.closest("label, .field-wrap")?.append(el("p", { class: "err", text: messages.join(" ") }));
  }
}

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "—");

/** Solo rutas locales: evita que `?next=` redirija a otro sitio. */
export function safeNext(value, fallback) {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : fallback;
}
