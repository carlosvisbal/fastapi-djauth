import { $, api, config, el, setMsg, showErrors } from "./common.js";

// El enlace trae uid y token en el fragmento (#): no viajan al servidor al cargar la página.
const params = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, "", location.pathname); // que el token no quede en el historial
const uid = Number(params.get("uid"));
const tok = params.get("token");
const cfg = await config();
$("#help").replaceChildren(...cfg.password_help.map((t) => el("li", { text: t })));
if (!uid || !tok) {
  $("#form").hidden = true;
  setMsg($("#msg"), "El enlace está incompleto. Pida uno nuevo al administrador.", "error");
}

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("#msg");
  if ($("#p1").value !== $("#p2").value) { setMsg(msg, "Las contraseñas no coinciden.", "error"); return; }
  $("#submit").disabled = true;
  try {
    await api("reset/confirm", { method: "POST", body: { uid, token: tok, new_password: $("#p1").value } });
    $("#form").hidden = true;
    setMsg(msg, "Contraseña guardada. Ya puede iniciar sesión.", "ok");
  } catch (e) {
    showErrors($("#form"), e);
    setMsg(msg, e.message, "error");
  } finally {
    $("#submit").disabled = false;
  }
});
