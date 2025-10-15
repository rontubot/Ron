import os
from openai import OpenAI
import json
import logging
from datetime import datetime
import re as _re
from core.commands import run_command
import hashlib
import time

from core.profile import (
    get_or_init_profile,
    append_to_profile_window,
    build_persona,
    purge_expired_facts,
)
from core.memory import (
    add_to_memory,
    load_user_memory,
    save_user_memory,
    get_user_data,
    save_user_data,
    resolve_username,
    load_memory,
    get_display_name,
    set_display_name,
    maybe_extract_name_from_text,
)
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configurar logging para debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRICT_JSON_SYSTEM = r"""
Responde ÚNICAMENTE con un objeto JSON válido, sin backticks ni texto extra.
Esquema: {"user_response":"texto","commands":[{"action":"...","params":{}}]}.
Si el usuario pide una acción ejecutable, DEBES incluir al menos un comando en 'commands'.
Nunca digas que no puedes hacer algo si existe un comando que lo haga.
SOLO puedes usar estas acciones en 'commands':
["search_youtube","open_application","close_application","search_google","get_weather",
 "add_reminder","get_reminders","remove_reminder","diagnose_system_performance",
 "check_system_services","restart_critical_services","clean_temp_files","flush_dns",
 "shutdown","restart","suspend","set_volume","create_file","create_folder",
 "move_file","copy_file","create_shortcut","delete_file","list_files"].
IMPORTANTE: Para close_application SIEMPRE incluye 'app_name' en params.
Para set_volume usa 'level' (número 0-100).
Para create_file usa 'file_path' y opcionalmente 'content'.
Para create_folder usa 'folder_path'.
Para move_file/copy_file usa 'source' y 'destination'.
Para create_shortcut usa 'target_path', 'shortcut_path' y opcionalmente 'description'.
"""



STYLE_GUIDE = """
Dirección al usuario:
- No repitas su nombre salvo que sea útil.
- Usa el nombre solo en estos casos: (1) cuando necesites confirmar algo importante, (2) si hay ambigüedad o varias personas.
- En el resto de los casos, habla en segunda persona, sin usar el nombre.
- Evita fórmulas, sé natural y directo.
"""


CLASSIFIER_SYSTEM = (
"Actúas como un clasificador de memoria. "
"Dado el último mensaje del usuario y un snapshot de su perfil, decide si hay preferencias explícitas, "
"cambios, intereses, rasgos o hechos efímeros. "
"Responde SOLO JSON con una lista 'ops'. Cada op tiene: "
"{op:'add|update|remove', type:'preference|interest|trait|do|dont|fact', key:'...', value:..., "
"ttl:'PT24H|P7D|null', confidence:0-1, source:'explicit|inferred'}."
" No inventes campos ni copies el texto completo del usuario."
)

def run_turn_classifier(client, model, last_message: str, profile_snapshot: dict) -> dict:
    u = json.dumps({"last_message": last_message, "profile_snapshot": profile_snapshot}, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"system","content": CLASSIFIER_SYSTEM},
                  {"role":"user","content": u}],
        response_format={"type":"json_object"},
        temperature=0.2,
        max_tokens=250,
    )
    return json.loads(resp.choices[0].message.content)



BATCH_SYSTEM = (
"Eres un perfilador. Dado un lote de mensajes del usuario, produce SOLO JSON con: "
"{label: 'una_palabra_minúscula_sin_espacios', traits:[hasta 3 adjetivos], "
"interests:[hasta 5 temas snake_case], dos:[hasta 3], donts:[hasta 3]}."
)

def run_batch_profiler(client, model, recent_window: list) -> dict:
    import json
    u = json.dumps({"messages": recent_window}, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=model,  
        messages=[{"role":"system","content": BATCH_SYSTEM},
                  {"role":"user","content": u}],
        response_format={"type":"json_object"},
        temperature=0.2,
        max_tokens=250,
    )
    return json.loads(resp.choices[0].message.content)


def apply_batch_result(prof: dict, data: dict):
    from core.profile import decay_and_add, ema_trait
    label = (data.get("label") or "").strip().lower()
    if label:
        decay_and_add(prof["tags"], label, 1.0)
        prof["last_labels"] = (prof["last_labels"] + [label])[-5:]

    for t in (data.get("traits") or [])[:3]:
        ema_trait(prof["traits"], t)

    for it in (data.get("interests") or [])[:5]:
        decay_and_add(prof["interests"], it, 1.0)

    if data.get("dos"):
        for d in data["dos"]:
            if d not in prof["dos"]:
                prof["dos"].append(d)
        prof["dos"] = prof["dos"][-3:]

    if data.get("donts"):
        for d in data["donts"]:
            if d not in prof["donts"]:
                prof["donts"].append(d)
        prof["donts"] = prof["donts"][-3:]






def apply_ops(prof: dict, ops: list, confidence_threshold: float = 0.65):
    from core.profile import decay_and_add, ema_trait, add_fact, add_history
    for op in ops or []:
        if op.get("confidence", 0) < confidence_threshold:
            continue
        t = op.get("type"); key = (op.get("key") or "").strip().lower()
        val = op.get("value"); src = op.get("source","inferred")

        if t == "preference":
            if op["op"] in ("add","update"):
                prefs = prof["preferences"]; prefs[key] = val
            elif op["op"] == "remove":
                prof["preferences"].pop(key, None)

        elif t == "interest":
            if op["op"] in ("add","update"):
                decay_and_add(prof["interests"], key, 1.0)

        elif t == "trait":
            if op["op"] in ("add","update"):
                ema_trait(prof["traits"], key)

        elif t == "do":
            if op["op"] in ("add","update"):
                if key not in prof["dos"]:
                    prof["dos"].append(key)
                prof["dos"] = prof["dos"][-3:]
            elif op["op"] == "remove":
                prof["dos"] = [x for x in prof["dos"] if x != key]

        elif t == "dont":
            if op["op"] in ("add","update"):
                if key not in prof["donts"]:
                    prof["donts"].append(key)
                prof["donts"] = prof["donts"][-3:]
            elif op["op"] == "remove":
                prof["donts"] = [x for x in prof["donts"] if x != key]

        elif t == "fact":
            # TTL en ISO 8601 (PT.. / P..), por simplicidad soportamos PT24H y P7D
            ttl = (op.get("ttl") or "").upper()
            seconds = 0
            if ttl == "PT24H": seconds = 24*3600
            elif ttl == "P7D": seconds = 7*24*3600
            if op["op"] in ("add","update") and seconds > 0:
                add_fact(prof, key, val, seconds)

        add_history(prof, {"op": op["op"], "type": t, "key": key, "source": src})




def _append_user_conv(username: str, user_text: str, ron_text: str, source: str = "voice"):
    """Guarda un turno en la memoria del usuario (con recorte a 100), evitando duplicados por pares y por ventana de tiempo."""
    try:
        mem = load_user_memory(username) or {}
        conv = mem.get("conversaciones", [])

        # 1) Dedupe por pares en los últimos 5 turnos
        pair = {"user": user_text, "ron": ron_text, "source": source}
        for item in reversed(conv[-5:]):
            if (
                isinstance(item, dict)
                and item.get("user") == pair["user"]
                and item.get("ron") == pair["ron"]
                and item.get("source") == pair["source"]
            ):
                # Ya existe este par recientemente
                return

        # 2) Dedupe por hash con TTL de 8s (para requests concurrentes)
        import hashlib, time
        phash = hashlib.sha256(f"{username}|{user_text}|{ron_text}|{source}".encode()).hexdigest()
        now = time.time()
        recent_pairs = mem.get("__recent_pairs__", [])
        # elimina viejos
        recent_pairs = [p for p in recent_pairs if (now - float(p.get("ts", 0))) < 8]
        if any(p.get("hash") == phash for p in recent_pairs):
            return
        recent_pairs.append({"hash": phash, "ts": now})
        mem["__recent_pairs__"] = recent_pairs

        # 3) Guarda la conversación
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


def parse_and_execute_commands_dynamic(gpt_response: str, ctx: dict | None = None, async_execute: bool = False) -> str:
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

        if async_execute:
            import threading
            threading.Thread(
                target=lambda: run_command(action, params, ctx or {}),
                daemon=True
            ).start()
        else:
            res = run_command(action, params, ctx or {})
            if not res.get("ok", True):
                logger.warning(f"Comando '{action}' falló: {res.get('error')}")
    return user_response if user_response else "Procesando tu solicitud..."



def parse_commands_only(gpt_response: str) -> dict:
    import json
    try:
        from core.assistant import fix_common_json_errors  # si está arriba en el archivo
    except Exception:
        pass  # si ya está en el mismo módulo no hace falta

    try:
        corrected = fix_common_json_errors(gpt_response)
        data = json.loads(corrected)
    except Exception:
        # Devolver algo razonable aunque venga mal
        return {"user_response": gpt_response, "commands": []}

    allowed = {
        "search_youtube","open_application","close_application","search_google","get_weather",
        "add_reminder","get_reminders","remove_reminder","diagnose_system_performance",
        "check_system_services","restart_critical_services","clean_temp_files","flush_dns",
        "shutdown","restart","suspend"
    }

    cmds = data.get("commands") or []
    if not isinstance(cmds, list):
        cmds = []

    cleaned = []
    for c in cmds:
        action = (c.get("action") or "").strip()
        if action in allowed:
            params = c.get("params") or {}
            cleaned.append({"action": action, "params": params})

    return {
        "user_response": data.get("user_response") or data.get("reply") or "",
        "commands": cleaned,
    }





def detect_farewell_patterns(user_input: str) -> bool:  
    """Detección robusta de despedidas"""  
    if not user_input:  
        return False  
      
    farewell_patterns = [  
        # Despedidas directas  
        "hasta luego", "adiós", "nos vemos", "chao", "bye", "goodbye", "see you",  
        "hasta pronto", "hasta mañana", "me voy", "ya me voy",  
          
        # Comandos de desactivación  
        "desactívate", "desactivate", "apágate", "ciérrate", "termina",  
        "sal", "salir", "exit", "quit",  
          
        # Finalizaciones de tarea  
        "eso es todo", "ya terminé", "ya está", "perfecto", "listo",  
        "gracias, eso es todo", "no necesito nada más", "ya no necesito nada",  
          
        # Confirmaciones de finalización  
        "está bien así", "así está bien", "perfecto así", "ya está listo"  
    ]  
      
    user_lower = user_input.lower().strip()  
      
    # Detectar patrones exactos  
    for pattern in farewell_patterns:  
        if pattern in user_lower:  
            return True  
      
    # Detectar frases cortas que indican finalización  
    short_endings = ["ok", "vale", "bien", "perfecto", "listo", "gracias"]  
    words = user_lower.split()  
    if len(words) <= 2 and any(word in short_endings for word in words):  
        return True  
      
    return False


def construir_historial_openai():
    memory = load_memory() or {}
    historial = memory.get("conversaciones", []) or []

    mensajes.append({      
        "role": "system",      
        "content": """      
    Eres Ron, un asistente que puede ejecutar CUALQUIER comando de Windows.      
      
    REGLA CRÍTICA:  
    Si el usuario pregunta "¿qué puedes hacer?", "ayuda", "qué sabes hacer", o similar:  
    - NO listes funciones técnicas  
    - NO menciones comandos específicos  
    - Responde de forma breve y genérica  
    - Invita al usuario a hacer una solicitud específica  
    - Intenta que todas tus solicitudes sean rapidas, asi que si te mandan a ejecutar algo ejecutalo y no preguntes por ejecutarlo, solo hazlo. 
      
    Formato de salida SIEMPRE:      
    {"user_response":"...","commands":[{"type":"cmd|powershell|python","command":"comando_exacto","safe":true}]}      
              
    REGLAS OBLIGATORIAS:      
    - NO uses markdown (**negrita**, *cursiva*, `código`), emojis (😀🔥✅), ni símbolos especiales en 'user_response'. Solo texto plano sin formato.      
    - NUNCA uses estas cosas (\n, *, #, \n1, \n2, \n3) en 'user_response'. Usa puntos y comas para separar ideas. Solo puedes hacerlo si el usuario lo pide             
    - Para comandos básicos (abrir apps, YouTube, recordatorios), usa las acciones predefinidas: open_application, search_youtube, add_reminder, etc.      
    - Para comandos avanzados del sistema, genera comandos cmd/PowerShell/Python directamente.      
    - Marca safe:true solo si el comando es seguro (no destructivo).      
    - Nunca digas que no puedes hacer algo, busca el comando y ejecutalo. Evita preguntas innecesarias.      
      
    EJEMPLOS - PREGUNTAS SOBRE CAPACIDADES (IMPORTANTE):  
      
    Usuario: "¿qué puedes hacer?"  
    Asistente:  
    {"user_response":"Puedo ayudarte con tareas del sistema, búsquedas, recordatorios y más. ¿En qué necesitas ayuda?","commands":[]}  
      
    Usuario: "ayuda"  
    Asistente:  
    {"user_response":"Estoy aquí para ayudarte. ¿Qué necesitas que haga?","commands":[]}  
      
    Usuario: "qué sabes hacer"  
    Asistente:  
    {"user_response":"Puedo asistirte con diversas tareas. ¿Hay algo específico que quieras que haga?","commands":[]}  
              
    EJEMPLOS - COMANDOS BÁSICOS:      
              
    Usuario: "abre chrome"      
    Asistente:      
    {"user_response":"Abriendo Google Chrome.","commands":[{"action":"open_application","params":{"app_name":"chrome"}}]}      
              
    Usuario: "busca en youtube cualquier cosa"      
    Asistente:      
    {"user_response":"Buscando en YouTube.","commands":[{"action":"search_youtube","params":{"query":"video popular","play_video":true}}]}      
              
    Usuario: "recuérdame llamar a mamá a las 8pm"      
    Asistente:      
    {"user_response":"Listo, te recordaré llamar a mamá a las 8pm.","commands":[{"action":"add_reminder","params":{"activity":"llamar a mamá","due_time":"20:00"}}]}      
              
    EJEMPLOS - COMANDOS AVANZADOS:      
              
    Usuario: "sube el volumen al 80%"      
    Asistente:      
    {"user_response":"Subiendo volumen al 80%.","commands":[{"type":"powershell","command":"Set-Volume -Level 80","safe":true}]}      
              
    Usuario: "limpia archivos temporales"      
    Asistente:      
    {"user_response":"Limpiando archivos temporales.","commands":[{"type":"cmd","command":"del /q /f /s %TEMP%\\*","safe":true}]}      
              
    Usuario: "reinicia el servicio de audio"      
    Asistente:      
    {"user_response":"Reiniciando servicio de audio.","commands":[{"type":"cmd","command":"net stop audiosrv && net start audiosrv","safe":true}]}      
    """      
    })

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

    # NUEVO: cargar/crear perfil y purgar facts expirados
    prof = get_or_init_profile(memory)
    purge_expired_facts(prof)
    persona = build_persona(prof) if prof.get("enabled", True) else None

    mensajes = []
    if persona:
        mensajes.append({"role": "system", "content": persona})

    # Tu system base y el STRICT_JSON_SYSTEM
    mensajes.append({"role": "system", "content": STRICT_JSON_SYSTEM})
    mensajes.append({
        "role": "system",
        "content": (
            "Eres Ron, un asistente técnico especializado en ejecución y optimizador de tareas. "
            "PRIORIDAD: ejecutar comandos cuando corresponda. "
            'Formato de salida: JSON estricto con {"user_response": "...", "commands":[...]}.'
        ),
    })

    for mensaje in historial[-20:]:
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:
            mensajes.append({"role": "user", "content": mensaje["user"]})
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})

    # IMPORTANTE: guardamos el memory actualizado (perfil pudo purgar facts)
    save_user_memory(username, memory)
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

    # ---- Idempotencia por turno (evita doble proceso del mismo input en pocos segundos)
    mem_for_idem = load_user_memory(username) or {}
    recent_turns = mem_for_idem.get("__recent_turns__", [])
    now = time.time()
    turn_hash = hashlib.sha256(f"{username}|{original_input.strip().lower()}".encode()).hexdigest()

    # si el mismo hash fue procesado en los últimos 8s, devolvemos la misma respuesta sin repetir nada
    for item in reversed(recent_turns[-10:]):  # mira los últimos 10
        if item.get("hash") == turn_hash and (now - float(item.get("ts", 0))) < 8:
            cached_resp = item.get("response")
            if cached_resp:
                return cached_resp
            break

    # Helper: registra la respuesta en __recent_turns__ y retorna
    def _finalize_and_return(text: str):
        try:
            mem_tmp = load_user_memory(username) or {}
            rt = (mem_tmp.get("__recent_turns__", []) or [])[-19:]  # conserva hasta 20
            rt.append({"hash": turn_hash, "ts": now, "response": text})
            mem_tmp["__recent_turns__"] = rt
            save_user_memory(username, mem_tmp)
        except Exception:
            pass
        return text

    # === Nombre preferido del usuario (display_name) ===
        try:  
            mem_name = load_user_memory(username) or {}  
            display_name = get_display_name(username)  
          
            if not display_name:  
                # 1) Intentar extraer del texto actual  
                possible = maybe_extract_name_from_text(original_input)  
                if possible:  
                    set_display_name(username, possible)  
                    display_name = possible  
                else:  
                    # 2) Preguntar UNA sola vez  
                    asked = (mem_name.get("profile", {}) or {}).get("asked_display_name_once")  
                    if not asked:  
                        mem_name.setdefault("profile", {})["asked_display_name_once"] = True  
                        save_user_memory(username, mem_name)  
                        prompt_name = (  
                            "¿Cómo quieres que te llame? (por ejemplo: Me llamo Ana)\n"  
                            "Puedo guardar esto para dirigirme a ti correctamente."  
                        )  
                        return _finalize_and_return(prompt_name)  
        except Exception:  
            # Si algo falla, seguimos sin bloquear el turno  
            pass

    # ==== PERFIL: ventana + clasificador + contador + batch ====
    try:
        mem = load_user_memory(username) or {}
        prof = get_or_init_profile(mem)

        if prof.get("enabled", True) and os.getenv("RON_PROFILE_TURN_CLASSIFIER", "1") == "1": 
            # 1) ventana deslizante
            append_to_profile_window(prof, original_input)

            # 2) clasificador por turno
            snapshot = {
                "preferences": prof.get("preferences", {}),
                "dos": prof.get("dos", []),
                "donts": prof.get("donts", []),
            }
            try:
                cls = run_turn_classifier(client, "gpt-5-chat-latest", original_input, snapshot)
                ops = cls.get("ops") if isinstance(cls, dict) else None
                if ops:
                    apply_ops(prof, ops, confidence_threshold=0.65)
            except Exception as _e:
                logger.debug(f"Clasificador por turno falló (no crítico): {_e}")

            # 3) batch cada 20 mensajes si hay ventana suficiente
            prof["message_count"] = int(prof.get("message_count", 0)) + 1
            do_batch = (prof["message_count"] % 20 == 0) and (len(prof.get("recent_window", [])) >= 8)
            if do_batch:
                try:
                    batch = run_batch_profiler(client, "gpt-5-chat-latest", prof["recent_window"])
                    apply_batch_result(prof, batch)
                except Exception as _e:
                    logger.debug(f"Batch profiler falló (no crítico): {_e}")

        # 4) limpieza de facts expirados y persistencia
        purge_expired_facts(prof)
        save_user_memory(username, mem)
    except Exception as _e:
        logger.debug(f"Hook de perfil falló (no crítico): {_e}")
    # ==== FIN PERFIL ====

    # --- Despedida ---
    if detect_farewell_patterns(user_input):
        response = "Hasta luego. Que tengas un buen día."
        if save_to_memory:
            _append_user_conv(username, original_input, response, source="voice")
        return _finalize_and_return(response)

    # --- Detección automática de problemas del sistema ---
    problem_keywords = [
        # si querés reactivar esta rama, descomenta y ajusta la lista:
        # "problema en el sistema", "problema en la computadora", "problema en la pc",
        # "problema en el equipo", "no funciona", "error", "falla", "se cuelga",
        # "no responde", "muy lento", "se traba", "no abre", "no carga",
        # "internet no funciona", "no puedo imprimir", "no hay sonido", "pantalla azul",
        # "conexión", "red", "wifi"
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

        if "cpu:" in str(diag_msg).lower() and any(w in user_input for w in ["lento", "se traba"]):
            r = run_command("clean_temp_files", {}, {"username": username})
            repairs.append(r.get("message") or r.get("result") or json.dumps(r, ensure_ascii=False))
            analysis += f" También limpié archivos temporales para mejorar el rendimiento: {repairs[-1]}"

        if any(w in user_input for w in ["internet", "conexión", "red", "wifi"]):
            r = run_command("flush_dns", {}, {"username": username})
            repairs.append(r.get("message") or r.get("result") or json.dumps(r, ensure_ascii=False))
            analysis += f" Limpié la caché DNS para resolver problemas de conexión: {repairs[-1]}"

        if repairs:
            analysis += " Intenta usar tu computadora ahora para ver si el problema se resolvió."

        if save_to_memory:
            _append_user_conv(username, original_input, analysis, source="voice")
        return _finalize_and_return(analysis)

    # --- Comandos explícitos de diagnóstico / sistema ---
    if any(cmd in user_input for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):
        res = run_command("diagnose_system_performance", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if any(cmd in user_input for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):
        res = run_command("check_system_services", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if any(cmd in user_input for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):
        res = run_command("restart_critical_services", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if any(cmd in user_input for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):
        res = run_command("clean_temp_files", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if any(cmd in user_input for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):
        res = run_command("flush_dns", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- Sistema (energía) ---
    if "apaga la computadora" in user_input or "apaga el sistema" in user_input:
        res = run_command("shutdown", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if "reinicia la computadora" in user_input or "reinicia el sistema" in user_input:
        res = run_command("restart", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if "suspende la computadora" in user_input or "suspende el sistema" in user_input:
        res = run_command("suspend", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- Directos ---
    if user_input.startswith("abre "):
        app = user_input.replace("abre ", "").strip()
        res = run_command("open_application", {"app_name": app}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if user_input.startswith("cierra "):
        app = user_input.replace("cierra ", "").strip()
        res = run_command("close_application", {"app_name": app}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if user_input.startswith("investiga "):
        query = user_input.replace("investiga ", "").strip()
        res = run_command("search_google", {"query": query}, {"username": username})
        msg = res.get("message") or res.get("result") or f"Investigando en Google: {query}"
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if user_input.startswith("reproducir ") or user_input.startswith("reproduce "):
        query = user_input.replace("reproducir ", "").replace("reproduce ", "").strip()
        res = run_command("search_youtube", {"query": f"música {query}", "play_video": True}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if "clima en" in user_input:
        city = user_input.split("clima en")[-1].strip()
        res = run_command("get_weather", {"city": city}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- YouTube (buscar y reproducir) ---
    if user_input.startswith("youtube ") or user_input.startswith("yt "):
        query = user_input.replace("youtube ", "", 1).replace("yt ", "", 1).strip()
        res = run_command("search_youtube", {"query": query, "play_video": True}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- YouTube (solo buscar) ---
    if user_input.startswith("buscar en youtube "):
        query = user_input.replace("buscar en youtube ", "", 1).strip()
        res = run_command("search_youtube", {"query": query, "play_video": False}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- Recordatorios ---
    if "recuérdame" in user_input or "añade un recordatorio" in user_input:
        activity = (
            user_input.split("recuérdame")[-1].strip()
            if "recuérdame" in user_input
            else user_input.split("añade un recordatorio")[-1].strip()
        )
        res = run_command("add_reminder", {"activity": activity}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if "qué recordatorios tengo" in user_input or "cuál es mi agenda" in user_input:
        res = run_command("get_reminders", {}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    if "he completado" in user_input or "elimina" in user_input:
        # como fallback intentamos por título
        activity = (
            user_input.split("he completado")[-1].strip()
            if "he completado" in user_input
            else user_input.split("elimina")[-1].strip()
        )
        res = run_command("remove_reminder", {"title": activity}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)
        if save_to_memory:
            _append_user_conv(username, original_input, msg, source="voice")
        return _finalize_and_return(msg)

    # --- Conversación con OpenAI (rama final) ---
    mensajes = construir_historial_usuario_openai(username)
    mensajes.append({"role": "user", "content": original_input})

    try:
        respuesta = client.chat.completions.create(
            model="gpt-5-chat-latest",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=900,
            temperature=0.7,
        )
        gpt_response = respuesta.choices[0].message.content.strip()
        ron_response = parse_and_execute_commands_dynamic(
            gpt_response,
            ctx={"username": username, "last_user_text": original_input},
            async_execute=os.getenv("RON_ASYNC_COMMANDS", "0") == "1",
        )
    except Exception as e:
        logger.error(f"Error con OpenAI: {e}")
        ron_response = "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"

    # --- Respuesta final sin prefijo de saludo/nombre ---
    final_text = ron_response if isinstance(ron_response, str) else str(ron_response)

    # Guardar en memoria (si corresponde) y devolver
    if save_to_memory:
        _append_user_conv(username, original_input, final_text, source="voice")
    return _finalize_and_return(final_text)



def _process_user_input_streaming(user_input, save_to_memory=True, username=None):    
    """    
    Versión streaming de _process_user_input que genera chunks progresivamente.    
    Yields chunks de texto a medida que se generan.    
    """    
    username = resolve_username(username)    
    original_input = user_input    
    user_input = (user_input or "").lower().strip()    
        
    # Idempotencia    
    mem_for_idem = load_user_memory(username) or {}    
    recent_turns = mem_for_idem.get("__recent_turns__", [])    
    now = time.time()    
    turn_hash = hashlib.sha256(f"{username}|{original_input.strip().lower()}".encode()).hexdigest()    
        
    for item in reversed(recent_turns[-10:]):    
        if item.get("hash") == turn_hash and (now - float(item.get("ts", 0))) < 8:    
            cached_resp = item.get("response")    
            if cached_resp:    
                yield cached_resp    
                return    
            break    
        
    # === TODOS los casos que NO deben hacer streaming ===  
      
    # 1. Nombre de usuario  
    try:  
        mem_name = load_user_memory(username) or {}  
        display_name = get_display_name(username)  
        if not display_name:  
            possible = maybe_extract_name_from_text(original_input)  
            if possible:  
                set_display_name(username, possible)  
            else:  
                asked = (mem_name.get("profile", {}) or {}).get("asked_display_name_once")  
                if not asked:  
                    mem_name.setdefault("profile", {})["asked_display_name_once"] = True  
                    save_user_memory(username, mem_name)  
                    prompt_name = (  
                        "¿Cómo quieres que te llame? (por ejemplo: Me llamo Ana)\n"  
                        "Puedo guardar esto para dirigirme a ti correctamente."  
                    )  
                    yield prompt_name  
                    return  
    except Exception:  
        pass  
      
    # 2. Despedida  
    if detect_farewell_patterns(user_input):  
        response = "Hasta luego. Que tengas un buen día."  
        if save_to_memory:  
            _append_user_conv(username, original_input, response, source="voice")  
        yield response  
        return  
      
    # 3. Comandos directos (TODOS los casos de _process_user_input)  
    direct_command_patterns = [  
        ("apaga la computadora", "apaga el sistema"),  
        ("reinicia la computadora", "reinicia el sistema"),  
        ("suspende la computadora", "suspende el sistema"),  
        ("diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"),  
        ("verifica servicios", "estado de servicios", "revisa servicios"),  
        ("repara servicios", "reinicia servicios", "arregla servicios"),  
        ("limpia archivos temporales", "optimiza el sistema", "limpia la computadora"),  
        ("limpia dns", "reinicia dns", "arregla internet"),  
        ("qué recordatorios tengo", "cuál es mi agenda"),  
    ]  
      
    direct_command_prefixes = [  
        "abre ", "cierra ", "investiga ", "reproducir ", "reproduce ",  
        "youtube ", "yt ", "buscar en youtube ", "recuérdame", "añade un recordatorio",  
        "he completado", "elimina"  
    ]  
      
    # Verificar si es comando directo  
    is_direct_command = False  
    if "clima en" in user_input:  
        is_direct_command = True  
    else:  
        for pattern_group in direct_command_patterns:  
            if any(cmd in user_input for cmd in pattern_group):  
                is_direct_command = True  
                break  
        if not is_direct_command:  
            for prefix in direct_command_prefixes:  
                if user_input.startswith(prefix):  
                    is_direct_command = True  
                    break  
      
    if is_direct_command:  
        result = _process_user_input(user_input, save_to_memory, username)  
        yield result  
        return  
        
    # === Conversación con OpenAI (CON STREAMING REAL) ===  
      
    # Perfil (mismo código que _process_user_input)  
    try:  
        mem = load_user_memory(username) or {}  
        prof = get_or_init_profile(mem)  
        if prof.get("enabled", True) and os.getenv("RON_PROFILE_TURN_CLASSIFIER", "1") == "1":   
            append_to_profile_window(prof, original_input)  
            snapshot = {  
                "preferences": prof.get("preferences", {}),  
                "dos": prof.get("dos", []),  
                "donts": prof.get("donts", []),  
            }  
            try:  
                cls = run_turn_classifier(client, "gpt-5-chat-latest", original_input, snapshot)  
                ops = cls.get("ops") if isinstance(cls, dict) else None  
                if ops:  
                    apply_ops(prof, ops, confidence_threshold=0.65)  
            except Exception:  
                pass  
            prof["message_count"] = int(prof.get("message_count", 0)) + 1  
            do_batch = (prof["message_count"] % 20 == 0) and (len(prof.get("recent_window", [])) >= 8)  
            if do_batch:  
                try:  
                    batch = run_batch_profiler(client, "gpt-5-chat-latest", prof["recent_window"])  
                    apply_batch_result(prof, batch)  
                except Exception:  
                    pass  
        purge_expired_facts(prof)  
        save_user_memory(username, mem)  
    except Exception:  
        pass  
      
    mensajes = construir_historial_usuario_openai(username)    
    mensajes.append({"role": "user", "content": original_input})    
        
    try:    
        # STREAMING SIN response_format (para recibir texto progresivo)  
        respuesta = client.chat.completions.create(    
            model="gpt-5-chat-latest",    
            messages=mensajes,    
            max_tokens=900,    
            temperature=0.7,    
            stream=True  # SIN response_format para streaming real  
        )    
            
        full_response = ""    
        accumulated_text = ""  
            
        for chunk in respuesta:    
            if chunk.choices[0].delta.content:    
                content = chunk.choices[0].delta.content    
                accumulated_text += content  
                full_response += content  
                  
                # Enviar cada chunk inmediatamente  
                yield content  
          
        # Al final, intentar parsear comandos del texto completo  
        try:  
            # Intentar extraer JSON si el modelo lo generó  
            corrected = fix_common_json_errors(full_response)  
            response_data = json.loads(corrected)  
              
            # Ejecutar comandos si los hay  
            commands_to_execute = response_data.get("commands", []) or []  
            if commands_to_execute:  
                for command in commands_to_execute:  
                    action = (command.get("action") or "").strip()  
                    params = command.get("params", {}) or {}  
                    if action:  
                        if action == "search_youtube":  
                            params.setdefault("play_video", True)  
                        run_command(action, params, {"username": username, "last_user_text": original_input})  
        except:  
            # Si no es JSON válido, usar el texto completo como respuesta  
            pass  
            
        # Guardar en memoria    
        if save_to_memory:    
            _append_user_conv(username, original_input, full_response, source="voice")    
            
        # Actualizar __recent_turns__    
        try:    
            mem_tmp = load_user_memory(username) or {}    
            rt = (mem_tmp.get("__recent_turns__", []) or [])[-19:]    
            rt.append({"hash": turn_hash, "ts": now, "response": full_response})    
            mem_tmp["__recent_turns__"] = rt    
            save_user_memory(username, mem_tmp)    
        except:    
            pass    
                
    except Exception as e:    
        logger.error(f"Error con OpenAI streaming: {e}")    
        yield "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"
  
  
# Wrapper público para streaming  
def responder_a_usuario_streaming(user_input: str, username: str = "default"):  
    """Para clientes que soporten streaming - genera chunks progresivamente"""  
    return _process_user_input_streaming(user_input, save_to_memory=True, username=username)



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
