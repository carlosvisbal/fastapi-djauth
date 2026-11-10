import { $, api, config, safeNext, setMsg, token } from "./common.js";

const params = new URLSearchParams(location.search);
const cfg = await config();
const next = safeNext(params.get("next"), cfg.home_url);

// Si ya hay sesión válida, no tiene sentido volver a pedir credenciales.
try { await api("me"); location.replace(next); } catch { /* sin sesión: mostrar el formulario */ }

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("#msg");
  const body = { username: $("#username").value.trim(), password: $("#password").value };
  if (!body.username || !body.password) { setMsg(msg, "Escriba su usuario y contraseña.", "error"); return; }
  $("#submit").disabled = true;
  setMsg(msg, "Comprobando…");
  try {
    if (cfg.sessions) {
      token.set(null);
      await api("login", { method: "POST", body });
    } else {
      const r = await api("token", { method: "POST", body });
      token.set(r.access_token);
    }
    location.replace(next);
  } catch (e) {
    setMsg(msg, e.message, "error");
    $("#password").value = "";
    $("#password").focus();
  } finally {
    $("#submit").disabled = false;
  }
});
