import os
from openai import OpenAI
import json
import logging
from datetime import datetime
import re as _re
from core.commands import run_command  # dispatcher único
from core.memory import (
    add_to_memory,
    load_user_memory,
    save_user_memory,
    get_user_data,
    save_user_data,
    load_memory,
)
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configurar logging para debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRICT_JSON_SYSTEM = (
    "Responde ÚNICAMENTE con un objeto JSON válido, sin backticks ni texto extra. "
    'Esquema: {"user_response":"texto","commands":[{"action":"...","params":{}}]}. '
    "El campo user_response admite Markdown básico y \\n. "
    "Si el usuario pide una acción ejecutable, DEBES incluir al menos un comando en 'commands'. "
    "Nunca digas que no puedes hacer algo si existe un comando que lo haga. "
    "SOLO puedes usar estas acciones en 'commands': "
    "[\"search_youtube\",\"open_application\",\"close_application\",\"search_google\",\"get_weather\","
    "\"add_reminder\",\"get_reminders\",\"remove_reminder\",\"diagnose_system_performance\","
    "\"check_system_services\",\"restart_critical_services\",\"clean_temp_files\",\"flush_dns\","
    "\"shutdown\",\"restart\",\"suspend\"]. "
    "Si crees que necesitas otra acción, usa la más cercana de la lista anterior."
)


def resolve_username(username: str | None) -> str:
    candidate = (
        (username or "").strip()
        or os.getenv("RON_USERNAME", "").strip()
        or os.getenv("USERNAME", "").strip()
        or os.getenv("USER", "").strip()
    )
    if not candidate:
        try:
            import os as _os
            candidate = (_os.getlogin() or "").strip()
        except Exception:
            candidate = "default"
    return candidate.lower()





def _append_user_conv(username: str, user_text: str, ron_text: str, source: str = "voice"):
    """Guarda un turno en la memoria del usuario (con recorte a 100)."""
    try:
        mem = load_user_memory(username) or {}
        conv = mem.get("conversaciones", [])
        conv.append(
            {
                "user": user_text,
                "ron": ron_text,
                "timestamp": datetime.utcnow().isoformat(),
                "source": source,
            }
        )
        if len(conv) > 100:
            conv = conv[-100:]
        mem["conversaciones"] = conv
        save_user_memory(username, mem)
    except Exception as e:
        logger.error(f"Error guardando conversación de usuario '{username}': {e}")


def fix_common_json_errors(response: str) -> str:
    """Intenta corregir errores comunes de JSON antes de json.loads."""
    if not isinstance(response, str):
        return response

    # Quitar fences accidentales
    response = response.strip()
    if response.startswith("```"):
        response = response.strip("`").strip()

    # Normalizaciones
    response = response.replace('"userresponse":', '"user_response":')
    response = response.replace('"applicationname":', '"app_name":')
    response = response.replace('"openapplication"', '"open_application"')

    # Quedarse con el primer bloque {...}
    first = response.find("{")
    last = response.rfind("}")
    if first != -1 and last != -1:
        response = response[first : last + 1]

    # Eliminar comas colgantes


    response = _re.sub(r",\s*([}\]])", r"\1", response)
    return response


def parse_and_execute_commands_dynamic(gpt_response: str, ctx: dict | None = None) -> str:
    try:
        corrected = fix_common_json_errors(gpt_response)
        response_data = json.loads(corrected)
    except json.JSONDecodeError:
        import re as _re
        ur = ""
        m = _re.search(r'"user_response"\s*:\s*"(.+?)"', gpt_response, flags=_re.DOTALL)
        if m:
            raw = m.group(1)
            try:
                ur = json.loads(f'"{raw}"')
            except Exception:
                ur = raw.replace("\\n", "\n").replace('\\"', '"')
        return ur or "Procesando tu solicitud..."
    except Exception as e:
        logger.error(f"Error inesperado parseando JSON: {e}")
        return "Procesando tu solicitud..."

    user_response = response_data.get("user_response", "")
    commands_to_execute = response_data.get("commands", []) or []

    # Log para ver si el modelo trajo comandos
    if commands_to_execute:
        logger.info(f"[LLM commands] {', '.join([ (c.get('action') or '?') for c in commands_to_execute ])}")
    else:
        logger.info("[LLM commands] (vacío)")

    # Ejecutar comandos devueltos por la LLM
    for command in commands_to_execute:
        action = (command.get("action") or "").strip()
        params = command.get("params", {}) or {}
        if not action:
            continue
        if action == "search_youtube":
            params.setdefault("play_video", True)

        res = run_command(action, params, ctx or {})
        if not res.get("ok", True):
            logger.warning(f"Comando '{action}' falló: {res.get('error')}")

    # ---------- Fallback local (si NO hubo comandos) ----------
    if not commands_to_execute and ctx and isinstance(ctx.get("last_user_text", ""), str):
        ut = ctx["last_user_text"].lower()

        play_triggers = ("reproduce", "reproducir", "pon ", "poné ", "poner ", "pón ", "play ")
        if any(tok in ut for tok in play_triggers):
            import re
            m = re.search(r"(reproduce|reproducir|pon(?:er|é| )|play)\s+(.*)", ut)
            query = (m.group(2) if m else ut).strip()
            if query and query not in ("el segundo", "el primero", "esa", "ese", "eso"):
                rc = run_command("search_youtube", {"query": query, "play_video": True}, ctx or {})
                if rc.get("ok", True):
                    return user_response or f"Reproduciendo **{query}** en YouTube."
    # -----------------------------------------------------------

    return user_response if user_response else "Procesando tu solicitud..."


def detect_farewell_patterns(user_input: str) -> bool:
    """Detección simplificada de despedidas - SOLO 'hasta luego'"""
    return "hasta luego" in (user_input or "").lower()


def construir_historial_openai():
    memory = load_memory(username) or {}
    historial = memory.get("conversaciones", []) or []

    mensajes = [
        {"role": "system", "content": STRICT_JSON_SYSTEM},
        {
         "role": "system",
         "content": """
        Eres Ron, un asistente creado por Luis que EJECUTA acciones. Formato de salida SIEMPRE:
        {"user_response":"...","commands":[{"action":"...","params":{...}}]}

        REGLAS OBLIGATORIAS:
        - Si el usuario pide reproducir música, abrir algo, buscar en YouTube/Google, crear o listar recordatorios, diagnosticar el sistema, etc., SIEMPRE incluye un comando correspondiente en 'commands'.
        - No digas “no puedo”, usa el comando. Ej.: para música usa search_youtube con {"query": "...", "play_video": true}.
        - Si el usuario se refiere a “el segundo artista”, “el primero”, etc., interpreta según el contexto previo y construye la query. Ej.: si antes recomendaste “Amyl and the Sniffers” como #2, y el usuario dice “reproduce el segundo”, usa {"query": "Amyl and the Sniffers canción popular", "play_video": true}.
        - Siempre que ejecutes un comando, el 'user_response' debe confirmar lo que harás de forma breve.

        EJEMPLOS (FEW-SHOT):

        Usuario: "sorpréndeme con algo de música punk nuevo"
        Asistente:
        {"user_response":"Te propongo **Amyl and the Sniffers** y **The Linda Lindas**. ¿Quieres que ponga alguno?",
         "commands":[]}

        Usuario: "reproduce el segundo artista que dijiste"
        Asistente:
        {"user_response":"Poniendo **The Linda Lindas** en YouTube.",
         "commands":[{"action":"search_youtube","params":{"query":"The Linda Lindas canción popular","play_video":true}}]}

        Usuario: "pon algo de Bad Bunny"
        Asistente:
        {"user_response":"Reproduciendo **Bad Bunny** en YouTube.",
         "commands":[{"action":"search_youtube","params":{"query":"Bad Bunny video oficial","play_video":true}}]}

        Usuario: "recuérdame llamar a mamá a las 8pm"
        Asistente:
        {"user_response":"Listo, te recordaré llamar a mamá a las 8pm.",
         "commands":[{"action":"add_reminder","params":{"activity":"llamar a mamá","due_time":"20:00"}}]}
        """
        }
    ]

    # Reducir historial a últimos 20 mensajes para mejor rendimiento
    for mensaje in historial[-20:]:
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:
            mensajes.append({"role": "user", "content": mensaje["user"]})
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})

    return mensajes


def construir_historial_usuario_openai(username: str):
    """Historial OpenAI específico del usuario autenticado"""
    memory = load_user_memory(username) or {}
    historial = memory.get("conversaciones", []) or []

    mensajes = [
        {"role": "system", "content": STRICT_JSON_SYSTEM},
        {
            "role": "system",
            "content": """
Eres Ron, un asistente técnico especializado en ejecución y optimizador de tareas. Fuiste creado por Luis.
PRIORIDAD: ejecutar comandos. Formato de salida: JSON estricto con {"user_response": "...", "commands":[...]}.
""",
        },
    ]

    for mensaje in historial[-20:]:
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:
            mensajes.append({"role": "user", "content": mensaje["user"]})
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})

    return mensajes


def handle_tool_call(llm_payload: dict, ctx: dict):
    """
    llm_payload: salida del modelo ya parseada
    ctx: debe incluir p.ej. {"username": "..."}
    """
    cmd = (
        llm_payload.get("cmd")
        or llm_payload.get("command")
        or llm_payload.get("tool")
        or ""
    ).strip()

    params = llm_payload.get("params") or llm_payload.get("arguments") or {}
    res = run_command(cmd, params, ctx)

    try:
        username = (ctx or {}).get("username") or params.get("username")
        if username:
            user_text = llm_payload.get("user_text", "")
            ron_text = (
                res.get("message")
                or res.get("result")
                or json.dumps(res, ensure_ascii=False)
            )
            add_to_memory(username, user_text, ron_text)
    except Exception:
        logger.debug("No se pudo registrar la memoria de la herramienta", exc_info=True)

    return res


# =========================
# FUNCIÓN PRINCIPAL (única)
# =========================
def _process_user_input(user_input, save_to_memory=True, username=None):

    """Procesa la entrada del usuario y ejecuta comandos vía run_command."""
    username = resolve_username(username)

    original_input = user_input
    user_input = (user_input or "").lower().strip()

    ron_nombre = get_user_data(username, "ron_nombre") if username else "Ron"
    creador = get_user_data(username, "creador") if username else "Luis"

    # --- Despedida ---
    if detect_farewell_patterns(user_input):
        response = "Hasta luego. Que tengas un buen día."

        _append_user_conv(username, original_input, response, source="voice")
        return response

    # --- Detección automática de problemas del sistema ---
    problem_keywords = [
        "problema en el sistema",
        "problema en la computadora",
        "problema en la pc",
        "problema en el equipo",
        "no funciona",
        "error",
        "falla",
        "se cuelga",
        "no responde",
        "muy lento",
        "se traba",
        "no abre",
        "no carga",
        "internet no funciona",
        "no puedo imprimir",
        "no hay sonido",
        "pantalla azul",
    ]
    if any(keyword in user_input for keyword in problem_keywords):
        # Diagnóstico
        diag = run_command("diagnose_system_performance", {}, {"username": username})
        services = run_command("check_system_services", {}, {"username": username})

        diag_msg = (diag.get("message") or diag.get("result") or json.dumps(diag, ensure_ascii=False))
        services_msg = (services.get("message") or services.get("result") or json.dumps(services, ensure_ascii=False))
        analysis = f"He diagnosticado tu sistema automáticamente. {diag_msg} {services_msg}"

        # Reparaciones
        repairs = []

        if "PROBLEMA" in services_msg or "ERROR" in services_msg:
            r = run_command("restart_critical_services", {}, {"username": username})
            repairs.append(r.get("message") or r.get("result") or json.dumps(r, ensure_ascii=False))
            analysis += f" He reparado los servicios problemáticos: {repairs[-1]}"

        if "cpu:" in diag_msg.lower() and any(w in user_input for w in ["lento", "se traba"]):
            r = run_command("clean_temp_files", {}, {"username": username})
            repairs.append(r.get("message") or r.get("result") or json.dumps(r, ensure_ascii=False))
            analysis += f" También limpié archivos temporales para mejorar el rendimiento: {repairs[-1]}"

        if any(w in user_input for w in ["internet", "conexión", "red", "wifi"]):
            r = run_command("flush_dns", {}, {"username": username})
            repairs.append(r.get("message") or r.get("result") or json.dumps(r, ensure_ascii=False))
            analysis += f" Limpié la caché DNS para resolver problemas de conexión: {repairs[-1]}"

        if repairs:
            analysis += " Intenta usar tu computadora ahora para ver si el problema se resolvió."


        _append_user_conv(username, original_input, analysis, source="voice")
        return analysis

    # --- Comandos explícitos de diagnóstico / sistema ---
    if any(cmd in user_input for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):
        res = run_command("diagnose_system_performance", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if any(cmd in user_input for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):
        res = run_command("check_system_services", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if any(cmd in user_input for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):
        res = run_command("restart_critical_services", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if any(cmd in user_input for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):
        res = run_command("clean_temp_files", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if any(cmd in user_input for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):
        res = run_command("flush_dns", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- Sistema (energía) ---
    if "apaga la computadora" in user_input or "apaga el sistema" in user_input:
        res = run_command("shutdown", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if "reinicia la computadora" in user_input or "reinicia el sistema" in user_input:
        res = run_command("restart", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if "suspende la computadora" in user_input or "suspende el sistema" in user_input:
        res = run_command("suspend", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- Directos ---
    if user_input.startswith("abre "):
        app = user_input.replace("abre ", "").strip()
        res = run_command("open_application", {"app_name": app}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if user_input.startswith("cierra "):
        app = user_input.replace("cierra ", "").strip()
        res = run_command("close_application", {"app_name": app}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if user_input.startswith("investiga "):
        query = user_input.replace("investiga ", "").strip()
        res = run_command("search_google", {"query": query}, {"username": username})
        msg = res.get("message") or res.get("result") or f"Investigando en Google: {query}"
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if user_input.startswith("reproducir ") or user_input.startswith("reproduce "):
        query = user_input.replace("reproducir ", "").replace("reproduce ", "").strip()
        res = run_command("search_youtube", {"query": f"música {query}", "play_video": True}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if "clima en" in user_input:
        city = user_input.split("clima en")[-1].strip()
        res = run_command("get_weather", {"city": city}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- YouTube (buscar y reproducir) ---
    if user_input.startswith("youtube ") or user_input.startswith("yt "):
        query = user_input.replace("youtube ", "", 1).replace("yt ", "", 1).strip()
        res = run_command("search_youtube", {"query": query, "play_video": True}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- YouTube (solo buscar) ---
    if user_input.startswith("buscar en youtube "):
        query = user_input.replace("buscar en youtube ", "", 1).strip()
        res = run_command("search_youtube", {"query": query, "play_video": False}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- Recordatorios ---
    if "recuérdame" in user_input or "añade un recordatorio" in user_input:
        activity = (
            user_input.split("recuérdame")[-1].strip()
            if "recuérdame" in user_input
            else user_input.split("añade un recordatorio")[-1].strip()
        )
        res = run_command("add_reminder", {"activity": activity}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if "qué recordatorios tengo" in user_input or "cuál es mi agenda" in user_input:
        res = run_command("get_reminders", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    if "he completado" in user_input or "elimina" in user_input:
        # aquí idealmente usarías ID; como fallback, intentamos por título
        activity = (
            user_input.split("he completado")[-1].strip()
            if "he completado" in user_input
            else user_input.split("elimina")[-1].strip()
        )
        res = run_command("remove_reminder", {"title": activity}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        _append_user_conv(username, original_input, msg, source="voice")
        return msg

    # --- Conversación con OpenAI (rama final) ---
    mensajes = construir_historial_usuario_openai(username)
    mensajes.append({"role": "user", "content": original_input})

    try:
        respuesta = client.chat.completions.create(
            model="gpt-4o",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=900,
            temperature=0.7,
        )
        gpt_response = respuesta.choices[0].message.content.strip()
        ron_response = parse_and_execute_commands_dynamic(gpt_response, ctx={"username": username, "last_user_text": original_input})
    except Exception as e:
        logger.error(f"Error con OpenAI: {e}")
        ron_response = "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"


    _append_user_conv(username, original_input, ron_response, source="voice")
    return ron_response


# ================
# WRAPPERS PÚBLICOS
# ================
def responder_a_usuario(user_input: str, username: str = "default"):
    """Para clientes de voz - guarda en memoria automáticamente"""
    return _process_user_input(user_input, save_to_memory=True, username=username)


def generate_response_no_memory(user_input: str, username: str = "default"):
    """Para clientes web - NO guarda en memoria automáticamente"""
    return _process_user_input(user_input, save_to_memory=False, username=username)


def generate_response_with_user_memory(user_input, username=None):
    # Guarda en memoria del usuario si hay username
    return _process_user_input(user_input, save_to_memory=True, username=username)


# Alias legacy
generate_response = responder_a_usuario
