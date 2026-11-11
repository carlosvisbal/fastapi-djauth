import { $, api, config, el, fmtDate, logout, requireLogin, setMsg, showErrors } from "./common.js";

const cfg = await config();
const me = await requireLogin();
const can = (perm) => me.is_superuser || me.permissions.includes(perm);
if (!(me.is_staff || me.is_superuser)) {
  document.querySelector("main").replaceChildren(el("div", { class: "card" },
    el("h1", { text: "Sin acceso" }), el("p", { text: "Su cuenta no tiene acceso a la administración." }),
    el("a", { class: "btn", href: cfg.home_url, text: "Volver al sitio" })));
  throw new Error("sin acceso");
}
$("#home").href = cfg.home_url;
$("#who").textContent = me.full_name || me.username;
$("#logout").addEventListener("click", logout);

const ACTIONS = { add: "Creó", change: "Modificó", delete: "Eliminó", password: "Cambió la contraseña", reset_link: "Generó enlace", login: "Inició sesión", logout_all: "Cerró sesiones" };
const pill = (on) => el("span", { class: `pill ${on ? "yes" : "no"}`, text: on ? "Sí" : "No" });
const state = { perms: [], groups: [], tab: "users" };

async function loadCatalog() {
  [state.perms, state.groups] = await Promise.all([
    api("permissions").then((r) => r.items),
    can("auth.view_group") ? api("groups").then((r) => r.items) : Promise.resolve([]),
  ]);
  $("#u-group").replaceChildren(el("option", { value: "", text: "Todos los grupos" }), ...state.groups.map((g) => el("option", { value: g.id, text: g.name })));
}

/** Casillas de permisos agrupadas por aplicación, con filtro. Devuelve un lector de los ids marcados. */
function permissionBox(box, filterInput, selected, { disabledIds = new Set() } = {}) {
  const chosen = new Set(selected);
  const render = () => {
    const q = (filterInput?.value || "").toLowerCase();
    const byApp = Map.groupBy(state.perms.filter((p) => !q || `${p.key} ${p.name}`.toLowerCase().includes(q)), (p) => p.app_label);
    box.replaceChildren(...[...byApp].flatMap(([app, perms]) => [
      el("h4", { text: app }),
      ...perms.map((p) => el("label", { class: "check" },
        el("input", { type: "checkbox", checked: chosen.has(p.id), disabled: disabledIds.has(p.id), onchange: (e) => (e.target.checked ? chosen.add(p.id) : chosen.delete(p.id)) }),
        p.name, el("code", { text: p.key }))),
    ]));
    if (!box.children.length) box.append(el("p", { class: "muted small", text: "Ningún permiso coincide." }));
  };
  filterInput?.addEventListener("input", render);
  render();
  return { ids: () => [...chosen], setAll: (on) => { state.perms.forEach((p) => (on ? chosen.add(p.id) : chosen.delete(p.id))); render(); } };
}

// ====================================================================== pestañas
function showTab(name) {
  state.tab = name;
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== `tab-${name}`;
  ({ users: Users.list, groups: Groups.list, perms: Perms.list, history: History.list, log: Log.list })[name]();
}
for (const b of document.querySelectorAll(".tabs button")) {
  const perm = { users: "auth.view_user", groups: "auth.view_group", history: "auth.view_userchange", log: "auth.view_logentry" }[b.dataset.tab];
  if (perm && !can(perm)) b.hidden = true;
  b.addEventListener("click", () => showTab(b.dataset.tab));
}

// ====================================================================== usuarios
const Users = (() => {
  const PAGE = 50;
  let offset = 0, total = 0, order = "username", editing = null, permsBox = null;
  const list = async () => {
    $("#users-list").hidden = false;
    $("#user-edit").hidden = true;
    const q = new URLSearchParams({ limit: PAGE, offset, order });
    if ($("#u-q").value.trim()) q.set("q", $("#u-q").value.trim());
    if ($("#u-active").value) q.set("is_active", $("#u-active").value);
    if ($("#u-staff").value) q.set("is_staff", $("#u-staff").value);
    if ($("#u-group").value) q.set("group", $("#u-group").value);
    try {
      const r = await api(`users?${q}`);
      total = r.total;
      $("#u-total").textContent = `${total} usuarios`;
      $("#u-rows").replaceChildren(...(r.items.length ? r.items.map((u) => el("tr", { class: "clickable", tabindex: "0", onclick: () => edit(u.id), onkeydown: (e) => e.key === "Enter" && edit(u.id) },
        el("td", {}, el("strong", { text: u.username })), el("td", { text: u.full_name }), el("td", { text: u.email }),
        el("td", { text: u.groups.join(", ") || "—" }), el("td", {}, pill(u.is_active)), el("td", {}, pill(u.is_staff)),
        el("td", {}, pill(u.is_superuser)), el("td", { text: fmtDate(u.last_login) }))) : [el("tr", {}, el("td", { colspan: 8, class: "muted", text: "Ningún usuario coincide." }))]));
      $("#u-page").textContent = total ? `${offset + 1}–${Math.min(offset + PAGE, total)} de ${total}` : "";
      $("#u-prev").disabled = offset === 0;
      $("#u-next").disabled = offset + PAGE >= total;
    } catch (e) { setMsg($("#msg"), e.message, "error"); }
  };
  let timer;
  $("#u-q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { offset = 0; list(); }, 250); });
  for (const id of ["#u-active", "#u-staff", "#u-group"]) $(id).addEventListener("change", () => { offset = 0; list(); });
  for (const b of document.querySelectorAll("[data-order]")) b.addEventListener("click", () => { order = order === b.dataset.order ? (order.startsWith("-") ? order.slice(1) : `-${order}`) : b.dataset.order; list(); });
  $("#u-prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); list(); });
  $("#u-next").addEventListener("click", () => { offset += PAGE; list(); });
  $("#u-new").hidden = !can("auth.add_user");
  $("#u-new").addEventListener("click", () => edit(null));
  $("#ue-back").addEventListener("click", list);

  // Campos propios: columnas reales (cfg.user_fields, en el primer nivel del usuario) y campos JSON
  // (cfg.extra_fields, dentro de `extra`). Los dos se editan igual en el formulario.
  function fieldInput(f, value, key, scope) {
    const attrs = { "data-field": key, "data-scope": scope, "data-name": f.name, disabled: f.editable === false };
    if (f.type === "bool") return el("input", { type: "checkbox", checked: !!value, ...attrs });
    if (f.type === "choice") {
      return el("select", attrs, el("option", { value: "", text: "—" }), ...f.choices.map((c) => el("option", { value: c, text: c, selected: c === value })));
    }
    const type = { integer: "number", number: "number", date: "date", datetime: "datetime-local" }[f.type] || "text";
    const v = value == null ? "" : f.type === "datetime" ? String(value).slice(0, 16) : value;
    return el("input", { type, value: v, step: f.type === "integer" ? "1" : "any", maxlength: f.max_length || null, ...attrs });
  }
  function fieldControl(f, value, key, scope) {
    const input = fieldInput(f, value, key, scope);
    const help = f.help_text ? el("span", { class: "help", text: f.help_text }) : null;
    return f.type === "bool"
      ? el("div", { class: "field-wrap" }, el("label", { class: "check" }, input, f.label), help)
      : el("label", { class: "field" }, `${f.label}${f.required ? " *" : ""}`, input, help);
  }
  function extraInputs(user) {
    $("#ue-extra").replaceChildren(
      ...(cfg.user_fields || []).map((f) => fieldControl(f, user[f.name], f.name, "column")),
      ...cfg.extra_fields.map((f) => fieldControl(f, user.extra?.[f.name], `extra.${f.name}`, "extra")));
  }
  const readField = (i) => (i.type === "checkbox" ? i.checked : i.value === "" ? null : i.value);
  const scopedValues = (scope) => Object.fromEntries([...document.querySelectorAll(`#ue-extra [data-scope="${scope}"]:not([disabled])`)].map((i) => [i.dataset.name, readField(i)]));

  async function edit(id) {
    setMsg($("#ue-msg"), "");
    $("#ue-notice").hidden = true;
    showErrors($("#ue-form"), {});
    const u = id ? await api(`users/${id}`) : { username: "", email: "", first_name: "", last_name: "", is_active: true, is_staff: false, is_superuser: false, group_ids: [], permission_ids: [], extra: {} };
    editing = id ? u : null;
    $("#users-list").hidden = true;
    $("#user-edit").hidden = false;
    $("#ue-title").textContent = id ? u.username : "Nuevo usuario";
    $("#ue-username").value = u.username;
    // Con inicio de sesión por correo, el usuario es el correo: se oculta el campo y el correo es obligatorio.
    const emailLogin = cfg.username_field === "email";
    $("#ue-username").closest("label").hidden = emailLogin;
    $("#ue-email").required = emailLogin;
    $("#ue-email").closest("label").firstChild.textContent = emailLogin ? "Correo (para iniciar sesión) * " : "Correo ";
    $("#ue-email").value = u.email;
    $("#ue-first").value = u.first_name;
    $("#ue-last").value = u.last_name;
    $("#ue-active").checked = u.is_active;
    $("#ue-staff").checked = u.is_staff;
    $("#ue-super").checked = u.is_superuser;
    $("#ue-super").disabled = !me.is_superuser; // solo un superusuario concede o quita este nivel
    $("#ue-password-wrap").hidden = !!id;
    $("#ue-password").value = $("#ue-password2").value = "";
    extraInputs(u);
    const myGroups = new Set(u.group_ids);
    $("#ue-groups").replaceChildren(...(state.groups.length ? state.groups.map((g) => el("label", { class: "check" },
      el("input", { type: "checkbox", value: g.id, checked: myGroups.has(g.id) }), g.name, el("code", { text: `${g.permissions.length} permisos` }))) : [el("p", { class: "muted small", text: "No hay grupos." })]));
    permsBox = permissionBox($("#ue-perms"), $("#ue-perm-q"), u.permission_ids);
    const inherited = state.groups.filter((g) => myGroups.has(g.id)).flatMap((g) => g.permissions);
    $("#ue-inherited").textContent = inherited.length ? `Por sus grupos ya tiene: ${[...new Set(inherited)].join(", ")}` : "";
    $("#ue-dates").textContent = id ? `Alta: ${fmtDate(u.date_joined)} · Último acceso: ${fmtDate(u.last_login)} · Sesiones activas: ${u.active_sessions}${u.has_usable_password ? "" : " · Sin contraseña"}` : "";
    const readOnly = id ? !can("auth.change_user") : !can("auth.add_user");
    for (const n of $("#ue-form").querySelectorAll("input, select, #ue-save")) if (n.id !== "ue-perm-q") n.disabled = n.disabled || readOnly;
    for (const b of ["#ue-reset-link", "#ue-setpass", "#ue-logout"]) $(b).hidden = !id || !can("auth.change_user");
    $("#ue-history").hidden = !id || !can("auth.view_logentry");
    $("#ue-changes").hidden = !id || !can("auth.view_userchange");
    $("#ue-reason").value = "";
    $("#ue-reason").closest("label").hidden = readOnly;
    $("#ue-delete").hidden = !id || !can("auth.delete_user") || id === me.id;
  }

  $("#ue-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("#ue-msg");
    const body = {
      ...(cfg.username_field === "email" ? {} : { username: $("#ue-username").value.trim() }), email: $("#ue-email").value.trim(),
      first_name: $("#ue-first").value.trim(), last_name: $("#ue-last").value.trim(),
      is_active: $("#ue-active").checked, is_staff: $("#ue-staff").checked,
      groups: [...$("#ue-groups").querySelectorAll("input:checked")].map((i) => Number(i.value)),
      permissions: permsBox.ids(), extra: scopedValues("extra"), ...scopedValues("column"),
    };
    if (me.is_superuser) body.is_superuser = $("#ue-super").checked;
    try {
      if (editing) {
        await api(`users/${editing.id}${reasonQuery()}`, { method: "PATCH", body });
        setMsg(msg, "Cambios guardados.", "ok");
        await edit(editing.id);
        setMsg(msg, "Cambios guardados.", "ok");
      } else {
        if ($("#ue-password").value !== $("#ue-password2").value) { setMsg(msg, "Las contraseñas no coinciden.", "error"); return; }
        const created = await api(`users${reasonQuery()}`, { method: "POST", body: { ...body, password: $("#ue-password").value || null } });
        await edit(created.id);
        setMsg(msg, "Usuario creado.", "ok");
      }
    } catch (e) { showErrors($("#ue-form"), e); setMsg(msg, e.message, "error"); }
  });

  /** `?reason=…` con el motivo escrito en el formulario (vacío = sin motivo). */
  function reasonQuery() {
    const reason = $("#ue-reason").value.trim();
    return reason ? `?${new URLSearchParams({ reason })}` : "";
  }
  async function action(fn, okText) {
    try { await fn(); setMsg($("#ue-msg"), okText, "ok"); } catch (e) { setMsg($("#ue-msg"), e.message, "error"); }
  }
  $("#ue-reset-link").addEventListener("click", () => action(async () => {
    const r = await api(`users/${editing.id}/reset-link`, { method: "POST" });
    const url = new URL(r.url, location.href).href;
    $("#ue-notice").replaceChildren(el("strong", { text: "Enlace para elegir contraseña: " }), el("code", { text: url }),
      el("p", { class: "small", text: `Válido ${Math.round(r.expires_in / 3600)} h y de un solo uso. Envíelo por un canal privado.` }),
      el("button", { class: "btn", type: "button", text: "Copiar", onclick: () => navigator.clipboard?.writeText(url) }));
    $("#ue-notice").hidden = false;
  }, "Enlace generado."));
  $("#ue-setpass").addEventListener("click", () => {
    const password = prompt(`Contraseña nueva para ${editing.username}:`);
    if (password) action(() => api(`users/${editing.id}/password${reasonQuery()}`, { method: "POST", body: { password } }), "Contraseña asignada; sus sesiones abiertas se cerraron.");
  });
  $("#ue-logout").addEventListener("click", () => action(() => api(`users/${editing.id}/logout`, { method: "POST" }), "Sesiones cerradas."));
  $("#ue-history").addEventListener("click", () => Log.forObject("user", editing.id, editing.username));
  $("#ue-changes").addEventListener("click", () => History.forUser(editing.id, editing.username));
  $("#ue-delete").addEventListener("click", async () => {
    if (!confirm(`¿Eliminar a ${editing.username}? No se puede deshacer. Si solo quiere quitarle el acceso, desmarque "Activo".`)) return;
    try { await api(`users/${editing.id}${reasonQuery()}`, { method: "DELETE" }); list(); } catch (e) { setMsg($("#ue-msg"), e.message, "error"); }
  });
  return { list };
})();

// ====================================================================== grupos
const Groups = (() => {
  let editing = null, box = null;
  async function list() {
    await loadCatalog();
    $("#g-new").hidden = !can("auth.add_group");
    $("#g-rows").replaceChildren(...(state.groups.length ? state.groups.map((g) => el("tr", { class: "clickable", tabindex: "0", onclick: () => edit(g), onkeydown: (e) => e.key === "Enter" && edit(g) },
      el("td", {}, el("strong", { text: g.name })), el("td", { text: String(g.permissions.length) }), el("td", { text: String(g.members) }))) : [el("tr", {}, el("td", { colspan: 3, class: "muted", text: "Aún no hay grupos. Cree uno por cada rol (p. ej. Operador, Supervisor)." }))]));
  }
  function edit(g) {
    editing = g;
    $("#group-edit").hidden = false;
    $("#g-title").textContent = g ? g.name : "Nuevo grupo";
    $("#g-name").value = g?.name || "";
    box = permissionBox($("#g-perms"), $("#g-perm-q"), g?.permission_ids || []);
    const readOnly = g ? !can("auth.change_group") : !can("auth.add_group");
    for (const n of $("#g-form").querySelectorAll("input:not([type=search]), button[type=submit], #g-all, #g-none")) n.disabled = readOnly;
    $("#g-delete").hidden = !g || !can("auth.delete_group");
    setMsg($("#g-msg"), "");
    showErrors($("#g-form"), {});
  }
  $("#g-new").addEventListener("click", () => edit(null));
  $("#g-all").addEventListener("click", () => box.setAll(true));
  $("#g-none").addEventListener("click", () => box.setAll(false));
  $("#g-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = { name: $("#g-name").value.trim(), permissions: box.ids() };
    try {
      const saved = editing ? await api(`groups/${editing.id}`, { method: "PATCH", body }) : await api("groups", { method: "POST", body });
      await list();
      edit(state.groups.find((g) => g.id === saved.id));
      setMsg($("#g-msg"), "Grupo guardado.", "ok");
    } catch (e) { showErrors($("#g-form"), e); setMsg($("#g-msg"), e.message, "error"); }
  });
  $("#g-delete").addEventListener("click", async () => {
    if (!confirm(`¿Eliminar el grupo ${editing.name}? Sus miembros pierden los permisos del grupo.`)) return;
    try { await api(`groups/${editing.id}`, { method: "DELETE" }); $("#group-edit").hidden = true; list(); } catch (e) { setMsg($("#g-msg"), e.message, "error"); }
  });
  return { list };
})();

// ====================================================================== permisos
const Perms = { list: () => $("#p-rows").replaceChildren(...state.perms.map((p) => el("tr", {}, el("td", { text: p.app_label }), el("td", {}, el("code", { text: p.codename })), el("td", { text: p.name })))) };

// ====================================================================== historial de cambios de usuarios
const History = (() => {
  const PAGE = 50;
  const ACTION_TEXT = { create: "Alta", update: "Modificación", password: "Contraseña", delete: "Eliminación" };
  const LABELS = {
    username: "Usuario", email: "Correo", first_name: "Nombre", last_name: "Apellidos", is_active: "Activo",
    is_staff: "Acceso a la administración", is_superuser: "Superusuario", groups: "Grupos", permissions: "Permisos", password: "Contraseña",
    ...Object.fromEntries((cfg.user_fields || []).map((f) => [f.name, f.label])),
    ...Object.fromEntries((cfg.extra_fields || []).map((f) => [`extra.${f.name}`, f.label])),
  };
  let offset = 0, total = 0, user = null;
  $("#h-field").append(...Object.entries(LABELS).map(([value, text]) => el("option", { value, text })));

  const show = (v) => (v === null || v === undefined || v === "" ? "—" : v === true ? "Sí" : v === false ? "No" : Array.isArray(v) ? (v.length ? v.join(", ") : "—") : String(v));
  function changeList(action, changes) {
    const items = Object.entries(changes).map(([name, c]) => {
      const label = el("strong", { text: `${LABELS[name] ?? name}: ` });
      if (c.hidden) {
        const verb = { create: "definida", delete: "eliminada" }[action] ?? "cambiada";
        return el("li", {}, label, name === "password" ? verb : `${action === "update" ? "cambió" : verb} (dato protegido)`);
      }
      if (action === "create") return el("li", {}, label, show(c.new));
      if (action === "delete") return el("li", {}, label, show(c.old));
      return el("li", {}, label, el("del", { text: show(c.old) }), " → ", el("ins", { text: show(c.new) }));
    });
    return el("ul", { class: "changes" }, ...items);
  }
  async function list() {
    const q = new URLSearchParams({ limit: PAGE, offset });
    if (user) q.set("user_id", user.id);
    if ($("#h-action").value) q.set("action", $("#h-action").value);
    if ($("#h-field").value) q.set("field", $("#h-field").value);
    $("#h-filter").textContent = user ? `Solo: ${user.label}` : "";
    $("#h-clear").hidden = !user;
    try {
      const r = await api(`user-history?${q}`);
      total = r.total;
      $("#h-rows").replaceChildren(...(r.items.length ? r.items.map((h) => el("tr", {},
        el("td", { text: fmtDate(h.changed_at) }), el("td", { text: h.user }), el("td", {}, el("span", { class: `pill ${h.action === "delete" ? "no" : h.action === "create" ? "yes" : ""}`, text: ACTION_TEXT[h.action] ?? h.action })),
        el("td", {}, changeList(h.action, h.changes)), el("td", { text: h.actor }),
        el("td", { class: "small", text: [h.reason, h.ip].filter(Boolean).join(" · ") || "—" }))) : [el("tr", {}, el("td", { colspan: 6, class: "muted", text: "Sin cambios registrados." }))]));
      $("#h-page").textContent = total ? `${offset + 1}–${Math.min(offset + PAGE, total)} de ${total}` : "";
      $("#h-prev").disabled = offset === 0;
      $("#h-next").disabled = offset + PAGE >= total;
    } catch (e) { setMsg($("#msg"), e.message, "error"); }
  }
  for (const id of ["#h-action", "#h-field"]) $(id).addEventListener("change", () => { offset = 0; list(); });
  $("#h-prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); list(); });
  $("#h-next").addEventListener("click", () => { offset += PAGE; list(); });
  $("#h-clear").addEventListener("click", () => { user = null; offset = 0; list(); });
  function forUser(id, label) { user = { id, label }; offset = 0; showTab("history"); }
  return { list, forUser };
})();

// ====================================================================== registro
const Log = (() => {
  const PAGE = 100;
  let offset = 0, total = 0, filter = null;
  async function list() {
    const q = new URLSearchParams({ limit: PAGE, offset });
    if (filter) { q.set("object_type", filter.type); q.set("object_id", filter.id); }
    $("#l-filter").textContent = filter ? `Solo: ${filter.label}` : "";
    $("#l-clear").hidden = !filter;
    try {
      const r = await api(`log?${q}`);
      total = r.total;
      $("#l-rows").replaceChildren(...(r.items.length ? r.items.map((e) => el("tr", {},
        el("td", { text: fmtDate(e.action_time) }), el("td", { text: e.username || "sistema" }), el("td", { text: ACTIONS[e.action] ?? e.action }),
        el("td", { text: e.object_repr ? `${e.object_type === "group" ? "Grupo" : "Usuario"} ${e.object_repr}` : "—" }), el("td", { text: e.message }))) : [el("tr", {}, el("td", { colspan: 5, class: "muted", text: "Sin registros." }))]));
      $("#l-page").textContent = total ? `${offset + 1}–${Math.min(offset + PAGE, total)} de ${total}` : "";
      $("#l-prev").disabled = offset === 0;
      $("#l-next").disabled = offset + PAGE >= total;
    } catch (e) { setMsg($("#msg"), e.message, "error"); }
  }
  $("#l-prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); list(); });
  $("#l-next").addEventListener("click", () => { offset += PAGE; list(); });
  $("#l-clear").addEventListener("click", () => { filter = null; offset = 0; list(); });
  function forObject(type, id, label) { filter = { type, id, label }; offset = 0; showTab("log"); }
  return { list, forObject };
})();

await loadCatalog();
showTab(can("auth.view_user") ? "users" : can("auth.view_group") ? "groups" : "perms");
