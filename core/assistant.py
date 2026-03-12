import os
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
from core.location import get_now_localized
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

from core.autonomous import requires_autonomous_execution, autonomous_command_execution

from dotenv import load_dotenv

load_dotenv()

#🔹 Lazy-load del cliente OpenAI para evitar crash sin API key
_openai_client = None

def _get_openai_client():
    """Obtiene el cliente OpenAI, creándolo solo cuando se necesita"""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY no configurada")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

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
  "add_reminder","add_multiple_reminders","get_reminders","remove_reminder",
  "get_reminder_history","renew_reminder","clear_reminder_history",
  "update_reminder","diagnose_system_performance",      
 "check_system_services","restart_critical_services","clean_temp_files","flush_dns",      
 "shutdown","restart","suspend","set_volume","create_file","create_folder",      
 "move_file","copy_file","create_shortcut","delete_file","list_files",      
 "read_file","analyze_file","list_directory_detailed","get_standard_path",
 "queue_local_task", "stop_listening"].
    
REGLAS DE FORMATO DE TEXTO (user_response):
- NUNCA uses punto y coma (;), usa coma (,) o punto (.) seguido de MAYÚSCULA.
- Habla natural.

    
IMPORTANTE:     
- Para create_file usa SIEMPRE:
  - "file_path": ruta COMPLETA (ej: "C:\\Users\\{username}\\Desktop\\archivo.txt")
  - "content": texto completo que debe ir dentro del archivo (HTML, CSS, JS, código, etc.)
- Cuando el usuario pida que un archivo tenga “contenido”, “plantilla”, “estructura”, etc., DEBES rellenar el campo "content" con el contenido final.
- NO uses get_standard_path + create_file en secuencia. Genera la ruta completa directamente.    
- Para search_youtube: si el usuario dice "reproduce", "reproducir", "pon", "poner", "escucha", "escuchar", SIEMPRE incluye "play_video": true  
- Para search_youtube: si el usuario solo dice "busca" o "buscar", usa "play_video": false  
- Para close_application SIEMPRE incluye 'app_name' en params.    
- Para set_volume usa 'level' (número 0-100).    
- Para create_folder usa 'folder_path' con ruta completa.    
- Para move_file/copy_file usa 'source' y 'destination' con rutas completas.    
- Para create_shortcut usa 'target_path', 'shortcut_path' y opcionalmente 'description'.    
- Para read_file usa 'file_path'.      
- Para analyze_file usa 'file_path' y opcionalmente 'analysis_type' (general|code_review|improve).      
- Para list_directory_detailed usa 'directory_path'.     
- Si el usuario dice "esa carpeta", "esa misma carpeta", "en la carpeta que creaste", etc.,
  debes reutilizar la ÚLTIMA ruta de carpeta que tú mismo mencionaste en la conversación
  (por ejemplo, si antes dijiste "Carpeta creada: C:\\Users\\LMAR\\Desktop\\NuevaCarpeta",
  usa esa ruta como base).

- Para queue_local_task:
- ÚSALO cuando el usuario pida algo que pueda ejecutarse en segundo plano (por ejemplo: analizar un archivo de código, hacer un diagnóstico largo, revisar varios archivos, o programar un recordatorio futuro).
- En params SIEMPRE incluye:
- "task_type": tipo de tarea (ejemplos: "analyze_local_file", "diagnose_system", "bulk_file_analysis", "reminder_timer")
- "description": una frase corta pensada para el usuario, describiendo qué hará la tarea (ejemplo: "Recordatorio en 5 minutos: mandar el informe").
- Si la tarea involucra archivos locales, incluye también:
  - "file_path": ruta del archivo.

REGLAS DE RECORDATORIOS:
- Al listar recordatorios pendientes (get_reminders), NO menciones actividades en el "Historial" (vencidas/archivadas).
- Si el usuario pregunta por tareas pasadas, vencidas o el historial, usa "get_reminder_history".
- Para renovar una tarea del historial, usa "renew_reminder" con 'reminder_id', 'due_date' y 'due_time'.
- Para limpiar TODO el historial de vencidos, usa "clear_reminder_history".
- NO menciones el historial a menos que el usuario lo pida explícitamente o haya más de 10 acumulados.
- "path": ruta COMPLETA del archivo (ejemplo: "C:\\Users\\{username}\\Desktop\\bot_voz.py").
- Cuando el usuario pida analizar un archivo local (rutas como "C:\\Users\\..." o "/home/..."), PREFIERE usar "queue_local_task" con "task_type": "analyze_local_file" en lugar de llamar directamente a "analyze_file".
- Cuando el usuario pida que lo recuerdes en N minutos/horas (por ejemplo: "recuérdame en 20 minutos mandar el informe"), PREFIERE usar "add_reminder" con "delay_seconds".
- Para add_reminder:
  - add_reminder(title: str, description: str = "", due_date: str = None, due_time: str = None, recurrence: str = None, daysOfWeek: list = None, notes: str = "", priority: int = 1, remindEveryValue: int = 0, remindEveryUnit: str = 'hours', category: str = 'inbox')
  - **AUTONOMÍA: Clasifica como category: "daily" (Día a día)** si la actividad es una rutina de vida repetitiva, hábitos personales, hogar o ejercicio (ej: bañarse, hacer la comida, trotar cada 3 días, regar plantas), INCLUSO si no ocurre todos los días. **EXCEPCIÓN CRÍTICA:** Si el usuario te pide un recordatorio de ÚNICA VEZ con un tiempo exacto, retraso o cuenta regresiva (ej: "recuérdame en 20 min" o "a las 5 hacer comida"), pon `category: "inbox"`, NUNCA "daily".
  - Usa 'recurrence: "daily"' para alarmas de todos los días y 'due_time' para la hora ("HH:MM").
  - Usa 'recurrence: "days"' y 'daysOfWeek: ["Lun", "Mie"]' para alarmas en días específicos.
  - Usa 'remindEveryValue' y 'remindEveryUnit' para que Ron te recuerde periódicamente.
  - USA TU RAZONAMIENTO: Si el usuario pide algo "más seguido" o "cada cierto tiempo", deduce el intervalo apropiado.
  Ej: "Recuérdame tomar agua cada hora" -> { "remindEveryValue": 1, "remindEveryUnit": "hours", "priority": 3 }
  Ej: "Recuérdame hacer el almuerzo todos los días a mediodía" -> { "recurrence": "daily", "due_time": "12:00" }
- Para add_multiple_reminders:
  - **OBLIGATORIO:** Si el usuario te menciona 2 o más tareas en un mismo mensaje (ej: "haz esto Y pon una alarma Y recuérdame lo otro"), SIEMPRE usa este comando en lugar de un solo add_reminder.
  - Params: "reminders" (lista de objetos con los params de add_reminder).
- Para update_reminder:
  - Params: "reminder_id" (obligatorio), y los campos a cambiar ("title", "status": "done"|"todo", etc).
- Para remove_reminder:
  - Params: "reminder_id" (si lo conoces) O "title" (para buscar y borrar).
- Para get_reminders:
  - Params: "status" (opcional: "todo"|"done"|"all"), "category" (opcional).


Rutas estándar de Windows:    
- Escritorio: C:\\Users\\{username}\\Desktop    
- Documentos: C:\\Users\\{username}\\Documents    
- Descargas: C:\\Users\\{username}\\Downloads
- Imagenes: C:\\Users\\{username}\\Pictures    
- Music: C:\\Users\\{username}\\Music    
- Videos: C:\\Users\\{username}\\Videos
  
EJEMPLOS - YouTube:  
Usuario: "reproduce Paulo Londra"  
Asistente: {"user_response":"Reproduciendo Paulo Londra.","commands":[{"action":"search_youtube","params":{"query":"Paulo Londra","play_video":true}}]}  
  
Usuario: "pon música de rock"  
Asistente: {"user_response":"Poniendo música de rock.","commands":[{"action":"search_youtube","params":{"query":"música rock","play_video":true}}]}  
  
Usuario: "busca videos de gatos"  
Asistente: {"user_response":"Buscando videos de gatos.","commands":[{"action":"search_youtube","params":{"query":"videos de gatos","play_video":false}}]}  

Usuario: "recuérdame comprar leche mañana a las 9 am"
Asistente: {"user_response":"Listo, agendado.","commands":[{"action":"add_reminder","params":{"title":"Comprar leche","due_time":"09:00","priority":"normal"}}]} (Nota: el asistente debe calcular la fecha si es posible, o dejarla pendiente).

Usuario: "qué tengo pendiente?"
Asistente: {"user_response":"Revisando tus recordatorios...","commands":[{"action":"get_reminders","params":{"status":"todo"}}]}

Usuario: "borra el recordatorio de la leche"
Asistente: {"user_response":"Borrando recordatorio.","commands":[{"action":"remove_reminder","params":{"title":"Comprar leche"}}]}

Usuario: "hasta luego Ron"
Asistente: {"user_response":"Hasta luego, que descanses.","commands":[{"action":"stop_listening","params":{}}]}
"""


STYLE_GUIDE = """
Dirección al usuario:
- No repitas su nombre salvo que sea útil.
- Usa el nombre solo en estos casos: (1) cuando necesites confirmar algo importante, (2) si hay ambigüedad o varias personas.
- En el resto de los casos, habla en segunda persona, sin usar el nombre.
- Evita fórmulas, sé natural y directo.
- REGLA DE PUNTUACIÓN (NORMA APA/ESTÁNDAR):
  - Usa mayúscula inicial siempre y DESPUÉS DE CADA PUNTO.
  - Usa comas (,) para pausas breves en lugar de puntos seguidos si la frase continúa.
  - Usa punto seguido (.) solo para separar ideas completas.
  - NUNCA uses punto y coma (;), usa coma en su lugar.
  - Al final de tu respuesta, usa un punto final si corresponde.
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
        max_completion_tokens=10000,
    )
    return json.loads(resp.choices[0].message.content)



BATCH_SYSTEM = (
"Eres un perfilador psicológico y de comportamiento. "
"Dado un lote de mensajes, produce SOLO JSON con: "
"{label: 'etiqueta_estado', traits:[hasta 3], interests:[snake_case], "
"psycho_analysis: 'reporte_breve_psicologico_en_tercera_persona', "
"last_mood: 'mood_actual', analysis_traits: {paciencia:0..1, energia:0..1, ansiedad:0..1, empatia_requerida:0..1}}."
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
        max_completion_tokens=10000,
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

    # 🧠 Nuevos campos de psicoanálisis
    if data.get("psycho_analysis"):
        prof["psychological_analysis"] = data["psycho_analysis"]
    if data.get("last_mood"):
        prof["last_mood"] = data["last_mood"]
    if data.get("analysis_traits"):
        # EMA para los rasgos psicológicos (anclaje suave)
        existing = prof.get("analysis_traits", {})
        for k, v in data["analysis_traits"].items():
            existing[k] = (0.7 * existing.get(k, 0.5)) + (0.3 * v)
        prof["analysis_traits"] = existing






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

    # Normalizaciones de claves
    response = response.replace('"userresponse":', '"user_response":')
    response = response.replace('"applicationname":', '"app_name":')
    response = response.replace('"openapplication"', '"open_application"')

    # Arreglos específicos que hemos visto que el modelo rompe:
    # extensiones con ';' en lugar de '.'
    response = response.replace("; html", ".html")
    response = response.replace(";html", ".html")
    response = response.replace("; css", ".css")
    response = response.replace(";css", ".css")
    response = response.replace("; js", ".js")
    response = response.replace(";js", ".js")

    # DOCTYPE raro
    response = response.replace("<; DOCTYPE html>", "<!DOCTYPE html>")

    # rutas de recursos típicas que el modelo separa con ';'
    response = response.replace("style; css", "style.css")
    response = response.replace("script; js", "script.js")
    response = response.replace("via; placeholder; com", "via.placeholder.com")

    # Quedarse con el primer bloque {...}
    first = response.find("{")
    last = response.rfind("}")
    if first != -1 and last != -1:
        response = response[first : last + 1]

    # Eliminar comas colgantes
    response = _re.sub(r",\s*([}\]])", r"\1", response)
    return response



def parse_and_execute_commands_dynamic(gpt_response: str, ctx: dict | None = None, async_execute: bool = False, task_manager = None) -> str:  
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
        # 🔹 NUEVO: Imprimir JSON para que Electron intercepte (Recordatorios, etc.)
        print(json.dumps({"type": "commands", "commands": commands_to_execute}, ensure_ascii=False), flush=True)
    else:  
        logger.info("[LLM commands] (vacío)")  
  
    # Comandos que queremos mandar a background cuando hay task_manager
    background_actions = ["analyze_file", "diagnose_system_performance", "check_system_services", "search_file"]
  
    # Si hay task_manager disponible, usarlo para comandos largos  
    if task_manager and commands_to_execute:  
        for command in commands_to_execute:  
            action = (command.get("action") or "").strip()  
            params = command.get("params", {}) or {}  
              
            if not action:  
                continue  
              
            if action in background_actions:  
                def execute_with_progress(cmd_action=action, cmd_params=params):  
                    cmd_params['progress_callback'] = task_manager.send_message  
                    res = run_command(cmd_action, cmd_params, ctx or {})  
                    result_msg = res.get("message") or res.get("result") or "Completado"  
                    final_msg = f"✅ {result_msg}"
                    task_manager.send_message(final_msg)
                    
                    # Persist background task result to memory
                    try:
                        u_name = (ctx or {}).get("username") or "default"
                        _append_user_conv(u_name, f"Ejecutar {cmd_action} en segundo plano", final_msg, source="task")
                    except Exception as e:
                        logger.error(f"Error guardando memoria de tarea background: {e}")

                task_manager.run_background_task(f"{action}_{time.time()}", execute_with_progress)  
                continue
  
    # Ejecutar comandos devueltos por la LLM (flujo normal)  
    execution_outputs = []
    for command in commands_to_execute:  
        action = (command.get("action") or "").strip()  
        params = command.get("params", {}) or {}  
        if not action:  
            continue  
  
        # Si ya se procesó en background, saltar  
        if task_manager and action in background_actions:  
            continue  

        # 🔒 Protección: NO dejar que la LLM toque el volumen del sistema
        # si el usuario no dijo nada sobre volumen/sonido.
        if action == "set_volume":
            last_text = ((ctx or {}).get("last_user_text") or "").lower()
            volume_keywords = [
                "volumen", "volume", "sonido", "sube el volumen", "baja el volumen",
                "más fuerte", "más bajo", "silencio", "siléncialo", "mutea",
                "desmutea", "apaga el sonido", "prende el sonido"
            ]
            if not any(k in last_text for k in volume_keywords):
                logger.info("[LLM commands] Ignorando set_volume porque el usuario no lo pidió explícitamente.")
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
            
            # Capturar resultado para historial
            msg = res.get("message") or res.get("result")
            if msg:
                execution_outputs.append(str(msg))
  
    final_response = user_response if user_response else "Procesando tu solicitud..."
    if execution_outputs:
        final_response += "\n" + "\n".join(execution_outputs)

    return final_response



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
        "shutdown","restart","suspend","set_volume","create_file","create_folder",  
        "move_file","copy_file","create_shortcut","delete_file","list_files",  
        "read_file","analyze_file","list_directory_detailed","get_standard_path",  
        "queue_local_task"  
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
    """
    Historial "global" (no por usuario) que se usaba en versiones antiguas.
    La dejamos funcional por compatibilidad, pero hoy en día la rama principal
    es construir_historial_usuario_openai(username).
    """
    memory = load_memory() or {}
    historial = memory.get("conversaciones", []) or []

    mensajes = []  # 🔴 ANTES faltaba esta línea

    mensajes.append({      
        "role": "system",      
        "content": """      
    Eres Ron (también conocido como Ro), un asistente de voz y texto que puede ejecutar CUALQUIER de forma amigable, conversador y eficiente. Fuiste creado por Luis. Te comunicas como si hablaras con alguien cara a cara: con naturalidad, sin ser repetitivo ni demasiado formal.

Tus respuestas deben ser cortas, claras y centradas en ayudar, pero con un toque cálido. No expliques cosas innecesarias, y evita sonar como un manual técnico.      
      
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
    - La clave "action" NUNCA puede estar vacía. Si quieres crear carpetas usa "create_folder". Si quieres crear archivos usa "create_file".
    - Cuando crees una estructura web, usa SIEMPRE extensiones con punto: "index.html", "style.css", "script.js". Nunca uses ";" en lugar de ".".

    EJEMPLO - Crear estructura web básica en el Escritorio:

    Usuario: "crea una página web básica en una carpeta ron en el escritorio"
    Asistente:
    {"user_response":"Creando una carpeta 'ron' en el Escritorio con una página web básica.","commands":[
      {"action":"create_folder","params":{"folder_path":"C:\\Users\\{username}\\Desktop\\ron"}},
      {"action":"create_file","params":{"file_path":"C:\\Users\\{username}\\Desktop\\ron\\index.html","content":"<!DOCTYPE html><html lang=\\"es\\">...</html>"}},
      {"action":"create_file","params":{"file_path":"C:\\Users\\{username}\\Desktop\\ron\\style.css","content":"body { ... }"}},
      {"action":"create_file","params":{"file_path":"C:\\Users\\{username}\\Desktop\\ron\\script.js","content":"function mostrarSeccion(id) { ... }"}}
    ]}
          
    ...
    """      
    })

    # Reducir historial a últimos 20 mensajes
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

    # NUEVO: Inyectar tiempo localizado
    user_tz = prof.get("timezone", "UTC")
    now_localized = get_now_localized(user_tz)
    today_str = now_localized.strftime("%Y-%m-%d")
    now_time_str = now_localized.strftime("%H:%M:%S")

    mensajes = []
    if persona:
        mensajes.append({"role": "system", "content": persona})

    # Inyectar contexto temporal
    time_context = (
        "🚨 CONTEXTO TEMPORAL LOCALIZADO:\n"
        f"- Fecha de hoy: {today_str}\n"
        f"- Hora actual: {now_time_str}\n"
        f"- Zona horaria: {user_tz}\n"
        "Usa estos datos para calcular fechas relativas (mañana, el lunes, hace una hora, etc.)."
    )
    mensajes.append({"role": "system", "content": time_context})

    # Tu system base y el STRICT_JSON_SYSTEM
    mensajes.append({"role": "system", "content": STRICT_JSON_SYSTEM})
    # Estilo y personalidad (incluye prohibición de ";")
    mensajes.append({"role": "system", "content": STYLE_GUIDE})
    # CORRECCIÓN FONÉTICA ACTIVA (Para corregir errores de STT como "bacuman" -> "Bakuman")
    mensajes.append({
        "role": "system",
        "content": (
            "MODO DE INTERPRETACIÓN DE VOZ: ACTIVADO. "
            "El input del usuario proviene de transcripción de audio (STT) y puede contener errores fonéticos. "
            "TU TAREA OBVIA: Antes de procesar la intención, analiza fonéticamente el texto. "
            "Si detectas una palabra que suena como un título, nombre propio o término técnico conocido (ej: 'bacuman' -> 'Bakuman', 'yutub' -> 'YouTube', 'wasap' -> 'WhatsApp'), "
            "asume que el usuario quiso decir el término correcto y ACTÚA sobre ese término corregido. "
            "NO preguntes '¿quisiste decir...?', asúmelo con confianza y ejecuta la acción correcta. "
            "Si la corrección cambia significativamente el comando, menciona la corrección implícitamente en 'user_response' (ej: 'Abriendo Bakuman...' si el usuario dijo 'bacuman')."
        )
    })
    
    mensajes.append({
        "role": "system",
        "content": (
            "Eres Ron, un asistente técnico especializado en ejecución y optimizador de tareas. "
            "PRIORIDAD: ejecutar comandos cuando corresponda. "
            "IMPORTANTE: Si el usuario se despide, dice 'ya está', 'nada más', 'silencio', o indica que ha terminado la interacción, DEBES incluir la acción 'stop_listening' en 'commands'. "
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


def _extract_delay_from_activity(activity: str):
    """
    Intenta detectar patrones tipo:
    - "en 5 minutos mandar el informe"
    - "en 2 horas llamar a mamá"
    Devuelve: (actividad_limpia, delay_seconds, descripcion_humana) o (actividad, None, None)
    """
    if not activity:
        return activity, None, None

    original = activity.strip()
    lower = original.lower().strip()

    # Patrón: "en 5 minutos ..." al inicio del texto
    m = _re.match(
        r"en\s+(\d+)\s+(segundo|segundos|minuto|minutos|hora|horas|día|dias|días)\b",
        lower
    )
    if not m:
        return original, None, None

    try:
        amount = int(m.group(1))
    except ValueError:
        return original, None, None

    unit = m.group(2)
    unit_norm = {
        "segundo": "segundos",
        "segundos": "segundos",
        "minuto": "minutos",
        "minutos": "minutos",
        "hora": "horas",
        "horas": "horas",
        "día": "días",
        "dias": "días",
        "días": "días",
    }.get(unit, None)

    if not unit_norm or amount <= 0:
        return original, None, None

    seconds_per_unit = {
        "segundos": 1,
        "minutos": 60,
        "horas": 3600,
        "días": 86400,
    }
    delay_seconds = amount * seconds_per_unit[unit_norm]

    # Recortar el prefijo "en 5 minutos" del texto original
    prefix_len = len(m.group(0))
    remainder = original[prefix_len:].lstrip(" ,.:;-")

    # Limpiar conectores iniciales
    for pref in ["que ", "para ", "para que "]:
        if remainder.lower().startswith(pref):
            remainder = remainder[len(pref):]

    # Si quedó vacío, usamos el original como fallback (para no romper nada)
    if not remainder:
        remainder = original

    human = f"{amount} {unit_norm}"
    return remainder, delay_seconds, human




## =========================  
# FUNCIÓN PRINCIPAL (única)  
# =========================  
def _process_user_input(user_input, save_to_memory=True, username=None, task_manager=None):  
    """Procesa la entrada del usuario y ejecuta comandos vía run_command."""  
    username = resolve_username(username)  
  
    original_input = user_input  
    user_input = (user_input or "").lower().strip()  
    # Limpiar prefijos de activación si están presentes
    for prefix in ["ron", "ro", "rum", "run", "ru", "rom"]:
        if user_input.startswith(prefix + " "):
            user_input = user_input[len(prefix)+1:].strip()
            break
        elif user_input == prefix:
            user_input = ""
            break
  
    # ---- Idempotencia por turno (evita doble proceso del mismo input en pocos segundos)  
    mem_for_idem = load_user_memory(username) or {}  
    recent_turns = mem_for_idem.get("__recent_turns__", [])  
    now = time.time()  
    turn_hash = hashlib.sha256(f"{username}|{original_input.strip().lower()}".encode()).hexdigest()  
  
    # si el mismo hash fue procesado en los últimos 8s, devolvemos la misma respuesta sin repetir nada  
    for item in reversed(recent_turns[-10:]):  # mira los últimos 10  
        if item.get("hash") == turn_hash and (now - float(item.get("ts", 0))) < 60:  
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
                model_name = "gpt-5.1"
                cls = run_turn_classifier(_get_openai_client(), "gpt-5-mini", original_input, snapshot)
                ops = cls.get("ops") if isinstance(cls, dict) else None
                if ops:
                    apply_ops(prof, ops, confidence_threshold=0.65)
            except Exception as _e:
                logger.debug(f"Clasificador por turno falló (no crítico): {_e}")

            # 3) batch cada vez si hay ventana mínima suficiente (aprox 5 mensajes)
            # El usuario pidió que fuera cada vez para que sea más rápido.
            do_batch = (len(prof.get("recent_window", [])) >= 5)
            if do_batch:
                try:
                    model_name = "gpt-5.4"
                    batch = run_batch_profiler(_get_openai_client(), "gpt-5-mini", prof["recent_window"])
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

        # 1) Intentar extraer un delay tipo "en 5 minutos..."
        clean_activity = activity
        delay_seconds = None
        delay_human = None

        if task_manager:
            try:
                clean_activity, delay_seconds, delay_human = _extract_delay_from_activity(activity)
            except Exception as e:
                logger.debug(f"Error extrayendo delay del recordatorio: {e}")

        # 2) Crear el recordatorio en la memoria normal
        res = run_command("add_reminder", {"activity": clean_activity}, {"username": username})
        msg = res.get("message") or res.get("result") or json.dumps(res, ensure_ascii=False)

        # 🔹 SI HAY COMANDOS (como queue_local_task), imprimirlos para que Electron los capture
        if isinstance(res, dict) and "commands" in res:
             print(json.dumps({
                "type": "commands", 
                "commands": res["commands"]
            }, ensure_ascii=False), flush=True)

        # 3) Si tenemos TaskManager y un delay válido, programar el mensaje
        if task_manager and delay_seconds and delay_seconds > 0:
            try:
                reminder_message = f"Te recuerdo: {clean_activity}"
                task_manager.schedule_message(reminder_message, delay_seconds)
                if delay_human:
                    msg = f"{msg} También te avisaré en {delay_human}."
            except Exception as e:
                logger.error(f"Error programando recordatorio en TaskManager: {e}")

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

    # --- Modo autónomo: tareas complejas de sistema ---
    try:
        allow_auto = os.getenv("RON_ALLOW_AUTONOMOUS", "0") == "1"
    except Exception:
        allow_auto = False

    if allow_auto and requires_autonomous_execution(original_input):
        auto_result = autonomous_command_execution(original_input, username)

        # Si el plan se ejecutó bien, devolvemos su resumen y NO pasamos por el LLM normal
        if auto_result.get("success"):
            summary = auto_result.get("summary") or "He ejecutado un plan de comandos para esa tarea."
            if save_to_memory:
                _append_user_conv(username, original_input, summary, source="voice")
            return _finalize_and_return(summary)
        # Si NO tiene éxito, dejamos que siga el flujo normal abajo (LLM)

    # --- Conversación con OpenAI (rama final) ---
    mensajes = construir_historial_usuario_openai(username)
    mensajes.append({"role": "user", "content": original_input})


    try:
        respuesta = client.chat.completions.create(
            model="gpt-5.4",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_completion_tokens=4096,
            temperature=0.2,
        )
        gpt_response = respuesta.choices[0].message.content.strip()
        ron_response = parse_and_execute_commands_dynamic(  
            gpt_response,  
            ctx={  
                "username": username,   
                "last_user_text": original_input,  
                "progress_callback": task_manager.send_message if task_manager else None  
            },  
            async_execute=os.getenv("RON_ASYNC_COMMANDS", "0") == "1",  
            task_manager=task_manager  
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



def _process_user_input_streaming(user_input, save_to_memory=True, username=None, task_manager=None):      
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
    # 2. Despedida  
    if detect_farewell_patterns(user_input):  
        response = "Hasta luego. Que tengas un buen día."  
        if save_to_memory:  
            _append_user_conv(username, original_input, response, source="voice")  
        yield response
        # Enviar comando de cierre
        yield f"\n__COMMANDS__:{json.dumps([{'action':'stop_listening','params':{}}], ensure_ascii=False)}\n"
        return  
      
    # 3. Comandos directos (mismos patrones que _process_user_input)  
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

    # 🔹 Detectar específicamente recordatorios tipo "recuérdame..." o "añade un recordatorio..."
    is_reminder_cmd = ("recuérdame" in user_input) or ("añade un recordatorio" in user_input)

    # 🔹 Para recordatorios SIEMPRE usamos la ruta completa (_process_user_input),
    #     así se aplica _extract_delay_from_activity + TaskManager del servidor.
    if is_reminder_cmd:
        result = _process_user_input(
            original_input,
            save_to_memory=save_to_memory,
            username=username,
            task_manager=task_manager,
        )
        yield result if isinstance(result, str) else str(result)
        return

    # ⚠️ IMPORTANTE:
    # Por defecto NO ejecutamos comandos locales en el servidor.
    # Solo si RON_ALLOW_SERVER_COMMANDS=1 se usará la ruta directa
    # que llama a _process_user_input (y por tanto a run_command en server).
    allow_server_cmds = os.getenv("RON_ALLOW_SERVER_COMMANDS", "0") == "1"
    if is_direct_command and allow_server_cmds:
        # Usamos el input original (no lowercased) y pasamos task_manager
        result = _process_user_input(original_input, save_to_memory, username, task_manager=task_manager)
        yield result if isinstance(result, str) else str(result)
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
                cls = run_turn_classifier(_get_openai_client(), "gpt-5-mini", original_input, snapshot)  
                ops = cls.get("ops") if isinstance(cls, dict) else None  
                if ops:  
                    apply_ops(prof, ops, confidence_threshold=0.65)  
            except Exception:  
                pass  
            # Batch cada vez si hay ventana mínima (5 mensajes)
            do_batch = (len(prof.get("recent_window", [])) >= 5)  
            if do_batch:  
                try:  
                    batch = run_batch_profiler(_get_openai_client(), "gpt-5-mini", prof["recent_window"])  
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
        respuesta = client.chat.completions.create(    
            model="gpt-5.4",    
            messages=mensajes,    
            max_completion_tokens=1024, # Reducido para mayor velocidad en streaming
            temperature=0.2,    
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
        commands_to_send = []  
        try:      
            # Intentar extraer JSON si el modelo lo generó      
            corrected = fix_common_json_errors(full_response)      
            response_data = json.loads(corrected)      
                  
            # Parsear comandos para enviarlos al cliente  
            commands_to_send = response_data.get("commands", []) or []      
            if commands_to_send:    
                logger.info(f"📤 Enviando {len(commands_to_send)} comando(s) al cliente")  
                # Enviar comandos en formato especial que api.py pueda detectar  
                yield f"\n__COMMANDS__:{json.dumps(commands_to_send, ensure_ascii=False)}\n"  
        except Exception as e:      
            logger.warning(f"No se pudieron parsear comandos del streaming: {e}")  
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

        
  




# ================
# WRAPPERS PÚBLICOS
# ================

def responder_a_usuario(user_input: str, username: str = "default", task_manager=None):  
    return _process_user_input(user_input, save_to_memory=True, username=username, task_manager=task_manager)  
  
def generate_response_no_memory(user_input: str, username: str = "default", task_manager=None):  
    return _process_user_input(user_input, save_to_memory=False, username=username, task_manager=task_manager)  
  
def generate_response_with_user_memory(user_input, username=None, task_manager=None):  
    return _process_user_input(user_input, save_to_memory=True, username=username, task_manager=task_manager)  
  
def responder_a_usuario_streaming(user_input: str, username: str = "default", task_manager=None):  
    return _process_user_input_streaming(user_input, save_to_memory=False, username=username, task_manager=task_manager)

# Alias legacy
generate_response = responder_a_usuario
