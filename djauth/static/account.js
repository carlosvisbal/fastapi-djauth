import { $, api, config, el, logout, requireLogin, setMsg, showErrors } from "./common.js";

const cfg = await config();
const me = await requireLogin();
$("#home").href = cfg.home_url;
$("#who").textContent = me.full_name || me.username;
$("#admin-link").hidden = !(me.is_staff || me.is_superuser);
$("#logout").addEventListener("click", logout);
for (const k of ["username", "email", "first_name", "last_name"]) $(`#${k}`).value = me[k] || "";
$("#groups").textContent = me.groups.join(", ") || "Ninguno";
$("#perms").textContent = me.is_superuser ? "Superusuario: tiene todos los permisos." : me.permissions.join(", ") || "Ninguno";
$("#help").replaceChildren(...cfg.password_help.map((t) => el("li", { text: t })));

$("#profile").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("#profile-msg");
  try {
    await api("me", { method: "PATCH", body: { email: $("#email").value, first_name: $("#first_name").value, last_name: $("#last_name").value } });
    showErrors($("#profile"), {});
    setMsg(msg, "Datos guardados.", "ok");
  } catch (e) { showErrors($("#profile"), e); setMsg(msg, e.message, "error"); }
});

$("#password").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("#password-msg");
  if ($("#new1").value !== $("#new2").value) { setMsg(msg, "Las contraseñas nuevas no coinciden.", "error"); return; }
  try {
    await api("me/password", { method: "POST", body: { old_password: $("#old").value, new_password: $("#new1").value } });
    ev.target.reset();
    showErrors($("#password"), {});
    setMsg(msg, "Contraseña cambiada.", "ok");
  } catch (e) { showErrors($("#password"), e); setMsg(msg, e.message, "error"); }
});
