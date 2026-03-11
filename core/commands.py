import os      
import subprocess      
import webbrowser      
import requests      
import logging      
import re      
import psutil    
import sys   
try:
    import speech_recognition as sr
except ImportError:
    sr = None
import csv
import io
import time
from config import WEATHER_API_KEY
from datetime import datetime, timedelta     
from core.memory import (    
    add_to_memory,    
    get_user_data,    
    save_user_data,    
    load_user_memory,    
    save_user_memory,    
    # recordatorios (nueva API por usuario)    
    add_reminder_item,    
    list_reminders,    
    update_reminder,    
    remove_reminder_item,    
    archive_expired_reminders,
    renew_reminder,
    count_archived_reminders,
    clear_reminder_history,
)     
    
# Configurar logging      
logging.basicConfig(level=logging.DEBUG)      
logger = logging.getLogger(__name__)      
    


def fix_python_volume(level: float = 1.0):
    """
    Fuerza el volumen de python.exe en Windows (0.0–1.0).
    Se apoya en get_nircmd_path para resolver la ruta correcta.
    """
    try:
        level = max(0.0, min(1.0, float(level)))
        nircmd_path = get_nircmd_path()
        subprocess.run(
            [nircmd_path, "setappvolume", "python.exe", str(level)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
        )
    except Exception as e:
        logger.error(f"Error ajustando volumen de Python: {e}")




def _call_ron_api_feedback(prompt: str, username: str = "local-task") -> str:
    """
    Llama al backend de Ron (/ron) para generar un feedback en lenguaje natural
    a partir de un prompt. Devuelve solo el texto útil.
    """
    try:
        base = (os.environ.get("RON_API_URL") or "").strip().rstrip("/")
        if not base:
            base = "https://ron-production.up.railway.app"

        url = f"{base}/ron"
        token = os.environ.get("RON_AUTH_TOKEN") or ""

        payload = {
            "text": prompt,
            "message": prompt,
            "username": username,
            "source": "desktop-task",
            "return_json": True,
        }

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()

        # Intentar parsear JSON primero
        try:
            data = resp.json()
        except Exception:
            return resp.text.strip()

        for key in ("user_response", "ron", "reply", "message", "text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

        return resp.text.strip()
    except Exception as e:
        logger.error(f"Error llamando al backend de Ron para feedback: {e}")
        return ""


  
# Diccionario de sitios comunes (expandido del código local)      
web_apps = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "gmail.com": "https://mail.google.com",
    "correo gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://www.twitter.com",
    "x": "https://twitter.com",
    "tiktok": "https://www.tiktok.com",
    "whatsapp": "https://web.whatsapp.com",
    "linkedin": "https://www.linkedin.com",
    "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com",
}



def _resolve_standard_path(raw_path: str) -> str:
    """
    Normaliza rutas tipo 'mis documentos', 'descargas', 'imagenes', etc.
    a rutas absolutas del usuario en Windows.

    También resuelve el placeholder {username} en rutas como:
    C:/Users/{username}/Desktop/archivo.txt
    """
    if not raw_path:
        return raw_path

    # Normalizamos separadores pero mantenemos el string original para no perder mayúsculas
    raw = str(raw_path).strip()
    raw = raw.replace("\\", "/")
    raw = raw.replace("<", "").replace(">", "").replace("~", "")

    home = os.path.expanduser("~")
    # Nombre de usuario real según la carpeta Home (ej: C:\Users\LMAR -> 'LMAR')
    real_username = os.path.basename(home)

    # Soporte para placeholder {username} (case-insensitive en la práctica en Windows)
    raw = raw.replace("{username}", real_username)

    lower = raw.lower()

    # Mapeo de alias -> carpetas reales
    aliases = {
        # Español
        "escritorio": os.path.join(home, "Desktop"),
        "mi escritorio": os.path.join(home, "Desktop"),
        "mis documentos": os.path.join(home, "Documents"),
        "documentos": os.path.join(home, "Documents"),
        "descargas": os.path.join(home, "Downloads"),
        "mis descargas": os.path.join(home, "Downloads"),
        "imagenes": os.path.join(home, "Pictures"),
        "mis imagenes": os.path.join(home, "Pictures"),
        "imágenes": os.path.join(home, "Pictures"),
        "mis imágenes": os.path.join(home, "Pictures"),
        "videos": os.path.join(home, "Videos"),
        "mis videos": os.path.join(home, "Videos"),
        "música": os.path.join(home, "Music"),
        "musica": os.path.join(home, "Music"),
        "mi musica": os.path.join(home, "Music"),
        "mi música": os.path.join(home, "Music"),
    }

    # Si empieza por un alias conocido (ej: "escritorio/notas.txt")
    for key, base_dir in aliases.items():
        if lower.startswith(key):
            rest = raw[len(key):].lstrip("/\\ ")
            return os.path.join(base_dir, rest) if rest else base_dir

    # Si ya parece una ruta absoluta (C:/..., D:/..., \\servidor\...)
    # devolvemos la ruta expandida (variables de entorno, ~, etc.)
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if os.path.isabs(expanded):
        return expanded

    # Fallback: interpretamos la ruta como relativa al home del usuario
    return os.path.join(home, expanded)


def open_url_in_browser(url: str, **kwargs):
    """Abre una URL en el navegador predeterminado."""
    if not url: return {"ok": False, "error": "No URL provided"}
    try:
        import webbrowser
        webbrowser.open(url)
        return {"ok": True, "message": f"Opening {url} in browser"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_standard_path(path=None, directory=None, base=None, progress_callback=None):
    """
    Devuelve una ruta absoluta a partir de:
    - un alias tipo "escritorio", "documentos", "descargas", etc.
    - una ruta parcial como "escritorio/archivo.txt"
    - o una ruta ya absoluta (solo se normaliza).

    Este comando existe para alinear con lo que el prompt STRICT_JSON_SYSTEM
    le dice al modelo: que puede usar "get_standard_path".
    Internamente usa _resolve_standard_path, así que hereda todos sus alias.
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        raw = path or directory or base
        if not raw:
            msg = "Falta 'path' o 'directory' para resolver la ruta estándar"
            send_progress(f"⚠️ {msg}")
            return msg

        resolved = _resolve_standard_path(str(raw))
        send_progress(f"✅ Ruta resuelta: {resolved}")
        return resolved
    except Exception as e:
        logger.error(f"Error en get_standard_path('{path or directory or base}'): {e}")
        return f"Error al resolver la ruta: {e}"



def get_nircmd_path():    
    """Obtiene la ruta a nircmd.exe según el entorno"""    
    # Si está empaquetado con Electron    
    if getattr(sys, 'frozen', False):    
        # Ruta en aplicación empaquetada    
        base_path = os.path.dirname(sys.executable)    
        nircmd_path = os.path.join(base_path, 'resources', 'bin', 'nircmd.exe')    
    else:    
        # Desarrollo: buscar en PATH o usar ruta relativa    
        nircmd_path = 'nircmd'  # Asume que está en PATH    
        
    return nircmd_path  
    
# FUNCIONES DE AUDIO CON SOPORTE DE PROGRESO  
    
def get_audio_processes():  
    """Enumera procesos que probablemente tengan audio activo (sin duplicados)"""  
    audio_apps = set()  
    common_audio_processes = [  
        'chrome.exe', 'firefox.exe', 'msedge.exe', 'brave.exe',  
        'spotify.exe', 'vlc.exe', 'wmplayer.exe', 'musicbee.exe',  
        'discord.exe', 'teams.exe', 'zoom.exe', 'slack.exe', 'youtube.exe',  
        'netflix.exe', 'whatsapp.exe',  
    ]  
      
    # CRÍTICO: Excluir procesos de Ron para evitar bloqueo de volumen    
    excluded_processes = {    
        'python.exe',           # Ron 24/7 local    
        'pythonw.exe',          # Python sin consola    
        'ron assistant.exe',    # Electron launcher    
        'ron-assistant.exe',    # Variante del nombre
        'python3.exe',            
    }  
  
    try:  
        for proc in psutil.process_iter(['name']):  
            pname = proc.info.get('name')  
            if not pname:  
                continue  
              
            # ✅ NUEVO: Verificar que NO esté en excluded_processes  
            pname_lower = pname.lower()  
            if pname_lower in excluded_processes:  
                continue  # Saltar procesos excluidos  
            
            if pname_lower in common_audio_processes:  
                audio_apps.add(pname)  
    except Exception as e:  
        logger.error(f"Error enumerando procesos de audio: {e}")  
  
    return list(audio_apps)
      
def duck_other_applications(progress_callback=None):      
    """Reduce volumen de apps conocidas al 20%"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔊 Reduciendo volumen de otras aplicaciones...")  
        processes = get_audio_processes()      
            
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica    
          
        reduced_count = 0  
        for proc_name in processes:      
            send_progress(f"🔉 Ajustando volumen de {proc_name}...")  
            result = subprocess.run(      
                [nircmd_path, 'setappvolume', proc_name, '0.2'],      
                capture_output=True,      
                text=True,    
                timeout=2  # Evitar bloqueos    
            )      
            if result.returncode == 0:      
                logger.debug(f"Volumen reducido para {proc_name}")  
                reduced_count += 1  
            else:      
                logger.warning(f"No se pudo reducir volumen de {proc_name}")      
          
        send_progress(f"✅ Volumen reducido en {reduced_count} aplicaciones")  
        return {"ok": True, "message": f"Volumen reducido en {reduced_count} aplicaciones"}      
    except Exception as e:      
        logger.error(f"Error en duck_other_applications: {e}")      
        return {"ok": False, "error": str(e)}      
      
def restore_application_volumes(progress_callback=None):      
    """Restaura volumen de apps al 100%"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔊 Restaurando volumen de aplicaciones...")  
        processes = get_audio_processes()      
            
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica    
          
        restored_count = 0  
        for proc_name in processes:      
            send_progress(f"🔊 Restaurando volumen de {proc_name}...")  
            result = subprocess.run(      
                [nircmd_path, 'setappvolume', proc_name, '1.0'],      
                capture_output=True,      
                text=True,    
                timeout=2  # Evitar bloqueos    
            )      
            if result.returncode == 0:      
                logger.debug(f"Volumen restaurado para {proc_name}")  
                restored_count += 1  
          
        send_progress(f"✅ Volumen restaurado en {restored_count} aplicaciones")  
        return {"ok": True, "message": f"Volumen restaurado en {restored_count} aplicaciones"}      
    except Exception as e:      
        logger.error(f"Error en restore_application_volumes: {e}")      
        return {"ok": False, "error": str(e)}


def search_file(
    name=None,
    filename=None,
    query=None,
    file_path=None,
    path=None,
    roots=None,
    max_depth=5,
    progress_callback=None,
):
    """
    Busca un archivo por nombre en subcarpetas de rutas base.

    Acepta:
    - name / filename: nombre directo (ej: 'notas.txt')
    - file_path / path: puede venir ruta o frase que lo contenga
    - query: incluso una frase larga tipo:
      "Buscar el archivo chat.txt en todas las carpetas principales..."

    Si recibe una frase, intenta extraer el primer patrón tipo 'algo.ext'
    con una regex y usa eso como nombre de archivo.
    """

    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        # 1) Unificamos todas las posibles entradas en un solo texto crudo
        raw = (
            filename
            or name
            or file_path
            or path
            or query
            or ""
        )
        raw = str(raw).strip()

        if not raw:
            msg = "Falta 'name', 'filename', 'file_path' o 'query' para buscar el archivo"
            send_progress(f"⚠️ {msg}")
            return msg

        # 2) Intentar extraer un nombre de archivo tipo algo.ext de una frase
        #    (por ejemplo "Buscar el archivo chat.txt en todas las carpetas...")
        candidate = os.path.basename(raw).strip(" '\"")

        # Si el "candidate" parece muy frase o no tiene punto, buscamos con regex en el texto completo
        if (" " in candidate and "." not in candidate) or len(candidate) > 60:
            m = re.search(r"([A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,6})", raw)
            if m:
                candidate = m.group(1)

        search_name = candidate.strip()
        if not search_name:
            msg = "No pude extraer un nombre de archivo válido para buscar"
            send_progress(f"⚠️ {msg}")
            return msg

        search_name_lower = search_name.lower()
        send_progress(f"🔍 Buscando '{search_name}' en el sistema...")

        home = os.path.expanduser("~")

        # 3) Determinar raíces de búsqueda
        base_roots = []
        if roots:
            if isinstance(roots, str):
                roots = [roots]
            for r in roots:
                base_roots.append(_resolve_standard_path(r))
        else:
            base_roots = [
                os.path.join(home, "Desktop"),
                os.path.join(home, "Documents"),
                os.path.join(home, "Downloads"),
                os.path.join(home, "Pictures"),
                os.path.join(home, "Music"),
                os.path.join(home, "Videos"),
            ]

        results = []

        for base in base_roots:
            if not os.path.isdir(base):
                continue

            send_progress(f"📂 Explorando: {base}")
            base_depth = base.count(os.sep)

            for root, dirs, files in os.walk(base):
                current_depth = root.count(os.sep)
                if current_depth - base_depth > max_depth:
                    # No seguir bajando más profundo
                    dirs[:] = []
                    continue

                for fname in files:
                    fname_lower = fname.lower()
                    # Coincidencia exacta o parcial
                    if (
                        search_name_lower == fname_lower
                        or search_name_lower in fname_lower
                    ):
                        full_path = os.path.join(root, fname)
                        results.append(full_path)
                        send_progress(f"✅ Encontrado: {full_path}")
                        if len(results) >= 100:
                            send_progress("⚠️ Demasiados resultados, se truncará la lista")
                            break
                if len(results) >= 100:
                    break
            if len(results) >= 100:
                break

        if not results:
            msg = f"No encontré '{search_name}' en las carpetas principales (Escritorio, Documentos, Descargas, etc.)."
            send_progress(f"⚠️ {msg}")
            return msg

        # 4) Construir respuesta
        lines = [f"Encontré {len(results)} coincidencia(s) para '{search_name}':"]
        for i, p in enumerate(results[:20], start=1):
            lines.append(f"{i}. {p}")

        msg_ok = "\n".join(lines)
        send_progress("✅ Búsqueda de archivo completada")
        return msg_ok

    except Exception as e:
        logger.error(f"Error buscando archivo '{name or filename or query}': {e}")
        return f"Error al buscar el archivo: {e}"


def append_to_file(
    file_path=None,
    path=None,
    text="",
    times=1,
    add_newline=True,
    progress_callback=None,
):
    """
    Agrega texto a un archivo de texto.

    Soporta:
    - file_path o path (usa _resolve_standard_path para alias y {username})
    - text: el texto a agregar (si viene vacío, por defecto usa 'hola')
    - times: cuántas veces repetir el texto (acepta string estilo '20 veces')
    - add_newline: si se agrega salto de línea después de cada repetición
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        target = file_path or path
        if not target:
            msg = "Falta 'file_path' o 'path' para appendear al archivo"
            send_progress(f"⚠️ {msg}")
            return msg

        resolved = _resolve_standard_path(target)

        # Texto por defecto si no se especifica nada
        if text is None or text == "":
            text = "hola"

        # Normalizar times (puede venir como string tipo '20', '20 veces', etc.)
        try:
            if isinstance(times, str):
                import re as _re
                m = _re.search(r"\d+", times)
                times_int = int(m.group(0)) if m else 1
            else:
                times_int = int(times)
        except Exception:
            times_int = 1

        if times_int < 1:
            times_int = 1

        send_progress(f"📝 Agregando texto al archivo: {resolved}")
        logger.info(f"Append a archivo {resolved} (text='{text}', times={times_int})")

        # Crear archivo si no existe
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "a", encoding="utf-8", errors="replace") as f:
            for _ in range(times_int):
                f.write(text)
                if add_newline:
                    f.write("\n")

        msg_ok = f"Texto agregado al archivo: {resolved}"
        send_progress(f"✅ {msg_ok}")
        return msg_ok

    except Exception as e:
        logger.error(f"Error appendiendo al archivo '{file_path or path}': {e}")
        return f"Error al modificar el archivo: {e}"

def bulk_file_analysis(
    pattern=None,
    filename=None,
    name=None,
    file_path=None,
    path=None,
    roots=None,
    max_depth=10,
    progress_callback=None,
    **kwargs,
):
    """
    Comando genérico usado por tareas de fondo para localizar archivos.

    Ahora actúa como un wrapper de search_file:
    - Acepta pattern/filename/name para el nombre.
    - Acepta file_path/path para rutas tipo 'escritorio/hola.txt' o con {username}.
    """
    # Unificamos la lógica delegando en search_file
    search_name = (filename or pattern or name or "").strip() or None

    return search_file(
        name=search_name,
        filename=search_name,
        query=search_name,
        file_path=file_path,
        path=path,
        roots=roots,
        max_depth=max_depth,
        progress_callback=progress_callback,
    )



def analyze_file(file_path, analysis_type="general", progress_callback=None, max_preview_chars=4000):
    """
    Analiza un archivo local y devuelve un reporte en texto plano:
    - ruta, tamaño, tipo, Nº de líneas
    - para código (ej. .py) intenta contar funciones / clases
    - vista previa (truncada) del contenido
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not file_path:
            msg = "Falta 'file_path' para analizar"
            send_progress(f"⚠️ {msg}")
            return msg

        # Resolver alias (escritorio, documentos, {username}, etc.)
        expanded_path = _resolve_standard_path(file_path)

        if not os.path.exists(expanded_path):
            msg = f"El archivo no existe: {expanded_path}"
            send_progress(f"⚠️ {msg}")
            return msg

        if not os.path.isfile(expanded_path):
            msg = f"La ruta no es un archivo: {expanded_path}"
            send_progress(f"⚠️ {msg}")
            return msg

        send_progress(f"📂 Iniciando análisis de {os.path.basename(expanded_path)}...")

        size_bytes = os.path.getsize(expanded_path)
        size_kb = size_bytes / 1024.0
        ext = os.path.splitext(expanded_path)[1].lower() or "desconocido"

        # Heurística simple para decidir si lo tratamos como texto
        text_like_exts = {
            ".py", ".txt", ".md", ".json", ".js", ".ts",
            ".html", ".css", ".csv", ".ini", ".cfg",
            ".yml", ".yaml"
        }
        is_probably_text = ext in text_like_exts or size_bytes < 2 * 1024 * 1024

        content = ""
        if is_probably_text:
            send_progress("📖 Leyendo contenido para vista previa...")
            with open(expanded_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        else:
            send_progress("📦 Archivo binario; se omitirá la vista previa del contenido")

        lines = content.splitlines() if content else []
        num_lines = len(lines)

        metrics = [
            f"Ruta: {expanded_path}",
            f"Tipo: {ext}",
            f"Tamaño: {size_bytes} bytes (~{size_kb:.1f} KB)",
            f"Líneas: {num_lines}",
        ]

        # Métricas específicas para Python
        if ext == ".py" and content:
            num_funcs = len(re.findall(r'^def\s+\w+', content, flags=re.MULTILINE))
            num_classes = len(re.findall(r'^class\s+\w+', content, flags=re.MULTILINE))
            metrics.append(f"Funciones (def): {num_funcs}")
            metrics.append(f"Clases (class): {num_classes}")

        # Vista previa
        preview_block = ""
        if content:
            snippet = content[:max_preview_chars]
            if len(content) > max_preview_chars:
                preview_block = (
                    f"Vista previa del contenido (truncado a {max_preview_chars} caracteres):\n"
                    f"{snippet}"
                )
            else:
                preview_block = f"Contenido completo:\n{snippet}"

        report_parts = [
            "=== METADATOS DEL ARCHIVO ===",
            *metrics,
        ]
        if preview_block:
            report_parts.append("")
            report_parts.append("=== VISTA PREVIA ===")
            report_parts.append(preview_block)

        report = "\n".join(report_parts).strip()

        send_progress("📋 Reporte completo generado")
        return report

    except Exception as e:
        logger.error(f"Error analizando archivo: {e}")
        send_progress(f"⚠️ Error analizando archivo: {e}")
        return f"Error analizando archivo: {e}"



def cmd_analyze_local_file(params, ctx):
    """
    Comando de alto nivel para analizar un archivo local:
    - Usa analyze_file para obtener métricas y vista previa
    - Envía ese análisis al backend de Ron para generar feedback armado
    """
    username = _username(ctx, params)
    file_path = params.get("file_path") or params.get("path")

    if not file_path:
        return {"ok": False, "error": "Falta 'file_path' o 'path' para analizar"}

    analysis_type = params.get("analysis_type") or "code"

    # Podemos pasar progress_callback si lo hubiera
    progress_callback = ctx.get("progress_callback")

    # 1) Análisis automático básico
    base_report = analyze_file(
        file_path,
        analysis_type=analysis_type,
        progress_callback=progress_callback,
    )
    if not isinstance(base_report, str):
        base_report = str(base_report)

    # 2) Pedir a Ron un feedback más armado usando ese análisis
    prompt = (
        "Quiero que actúes como un experto en revisión de código. "
        "Te paso un análisis automático de un archivo y una vista previa de su contenido. "
        "Con esa información, genera un feedback técnico claro en español para el usuario. "
        "Incluye:\n"
        "- Un breve resumen de lo que hace el archivo.\n"
        "- Puntos fuertes del código.\n"
        "- Problemas, riesgos o malas prácticas que veas.\n"
        "- Recomendaciones concretas de mejora.\n\n"
        "Análisis automático y vista previa del archivo:\n"
        f"{base_report}\n\n"
        "Fin del análisis."
    )

    feedback = _call_ron_api_feedback(prompt, username=username)

    if feedback:
        final_message = feedback
    else:
        # Si falla la llamada al backend, al menos devolvemos el análisis básico
        final_message = base_report

    return {
        "ok": True,
        "message": final_message,
        "analysis": base_report,
    }



  
def _username(ctx: dict, params: dict | None = None) -> str:    
    """    
    Obtiene el username de:    
    - params["username"]    
    - ctx["username"] o ctx["user"]    
    - (fallback) algo como 'default'    
    """    
    if params and isinstance(params, dict) and params.get("username"):    
        return str(params["username"]).strip()    
    if ctx and isinstance(ctx, dict):    
        if ctx.get("username"):    
            return str(ctx["username"]).strip()    

def execute_autonomous_plan(plan, progress_callback=None):
    """
    Ejecuta un plan autónomo (lista de pasos) generado por el backend.
    """
    def send_progress(msg):
        if progress_callback: progress_callback(msg)
        logger.info(msg)

    try:
        if not plan or not isinstance(plan, dict):
            return {"ok": False, "error": "Plan inválido"}

        steps = plan.get("steps", [])
        if not steps:
            return {"ok": True, "message": "Plan vacío, nada que ejecutar."}

        send_progress(f"⚙️ Iniciando plan autónomo: {plan.get('task', 'Tarea compleja')}")
        
        results = []
        for step in steps:
            desc = step.get("description", "Paso sin descripción")
            cmd = step.get("command")
            ctype = step.get("type", "cmd")
            
            send_progress(f"▶️ {desc}")
            
            if not cmd:
                continue

            try:
                if ctype == "powershell":
                    # Ejecutar PowerShell codificado en Base64 para evitar problemas de escape es mejor, 
                    # pero aquí usaremos directo por simplicidad y compatibilidad con lo que manda el backend
                    full_cmd = f'powershell -NoProfile -Command "{cmd}"'
                    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=120)
                elif ctype == "python":
                    full_cmd = [sys.executable, "-c", cmd]
                    res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=120)
                else: # cmd
                    full_cmd = f'cmd /c "{cmd}"'
                    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=120)
                
                output = (res.stdout + res.stderr).strip()
                results.append(f"✅ {desc}: {output[:100]}")
                logger.info(f"Step '{desc}' output: {output}")
                
            except Exception as e:
                err = f"❌ Error en paso '{desc}': {e}"
                send_progress(err)
                results.append(err)
                # Si falla un paso crítico, ¿paramos? Por ahora seguimos best-effort
        
        final_msg = "Plan completado.\n" + "\n".join(results)
        send_progress("✅ Plan finalizado.")
        return final_msg

    except Exception as e:
        logger.error(f"Error ejecutando plan autónomo: {e}")
        return {"ok": False, "error": str(e)}  
  
  
def open_application(app_name, progress_callback=None):      
    """Función mejorada: abre apps sin bloquear y reporta errores visibles si fallan."""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        app_name_clean = app_name.lower().strip()      
        send_progress(f"🚀 Intentando abrir {app_name_clean}...")  
        logger.info(f"Intentando abrir aplicación: {app_name_clean}")      
              
        # 1. Buscar en aplicaciones web primero      
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador")  
            send_progress(f"✅ {app_name.capitalize()} abierto en el navegador")  
            return f"Abriendo {app_name.capitalize()} en el navegador."      
              
        # 2. Buscar coincidencias parciales en web apps      
        for key, url in web_apps.items():      
            if key in app_name_clean or app_name_clean in key:      
                webbrowser.open(url)      
                logger.info(f"Abriendo {key} en navegador (coincidencia parcial)")  
                send_progress(f"✅ {key.capitalize()} abierto en el navegador")  
                return f"Abriendo {key.capitalize()} en el navegador."      
              
        # 3. Intentar abrir aplicación local      
        # Intentamos verificar si es un comando conocido o path absoluto simple
        import shutil
        
        # Si es nombre directo (ej: notepad, calc, code)
        resolved = shutil.which(app_name) or shutil.which(app_name + ".exe")
        
        # Aliases comunes de Windows que NO están en PATH pero "start" los conoce (App Paths)
        # Es difícil validar "start word" sin ejecutarlo.
        # Estrategia: Ejecutar y si falla (catch), devolver error formateado.
        
        cmd = f'start "" "{app_name}"'      
        logger.info(f"Ejecutando comando (non-blocking): {cmd}")      
        
        # Usamos Popen pero intentamos detectar si 'start' falló inmediatamente (raro en shell=True)
        # En Windows con shell=True, si el binario no existe, a veces popup de sistema.
        # Para evitar el popup y capturar el error, podríamos usar powershell con try/catch?
        # O mejor: intentar ubicarlo primero.
        
        # Truco: Powershell Start-Process -ErrorAction Stop
        # Si falla, Popen capturará stderr si lo redireccionamos.
        
        ps_cmd = f'powershell -Command "try {{ Start-Process \\"{app_name}\\" -ErrorAction Stop }} catch {{ Write-Error $_.Exception.Message; exit 1 }}"'
        
        # Ejecutamos con espera CORTA para ver si arranca (los UI apps retornan rápido el control)
        # NOTA: Start-Process es asíncrono por defecto para GUI apps, así que retorna rápido.
        
        proc = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True)
        
        if proc.returncode != 0:
            # Falló el arranque
            err_msg = proc.stderr.strip() or "Aplicación no encontrada en el sistema."
            logger.error(f"Error abriendo {app_name}: {err_msg}")
            
            # 🔹 RETORNO DE ERROR PARA NOTIFICACIÓN UI
            # Si contiene "no se encuentra", lo traducimos para el usuario
            if "no se encuentra" in err_msg or "cannot find" in err_msg or "is not recognized" in err_msg:
                 return {
                    "ok": False, 
                    "error": f"No encuentro la aplicación '{app_name}'. Verifica que esté instalada.",
                    "show_notification": True
                }
            
            return {
                "ok": False, 
                "error": f"Error al abrir '{app_name}': {err_msg}",
                "show_notification": True
            }

        logger.info(f"Aplicación {app_name} lanzada correctamente (según Powershell)")  
        send_progress(f"✅ {app_name} se está abriendo...")  
        return f"Abriendo {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Excepción al abrir {app_name}: {str(e)}")      
        return {
            "ok": False, 
            "error": f"Error crítico abriendo '{app_name}': {str(e)}",
            "show_notification": True
        }  
  
  
def close_application(app_name, progress_callback=None):
    """Cierra una aplicación por nombre, usando aliases y detección dinámica de procesos."""
    def send_progress(msg: str):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        original_name = str(app_name or "").strip()
        if not original_name:
            msg = "No se especificó el nombre de la aplicación a cerrar."
            send_progress(f"⚠️ {msg}")
            return msg

        # Solo soportado en Windows
        if os.name != "nt":
            msg = "El cierre de aplicaciones solo está disponible en Windows."
            send_progress(f"⚠️ {msg}")
            return msg

        send_progress(f"🔴 Cerrando {original_name}...")
        logger.info(f"Intentando cerrar aplicación: {original_name}")

        lower_name = original_name.lower()

        # Aliases para apps comunes (puedes ir sumando más aquí)
        alias_map = {
            "photoshop": ["Photoshop.exe", "Adobe Photoshop.exe"],
            "premiere": ["Adobe Premiere Pro.exe", "Premiere.exe"],
            "after effects": ["AfterFX.exe", "Adobe After Effects.exe"],
            "chrome": ["chrome.exe", "GoogleChromePortable.exe"],
            "edge": ["msedge.exe"],
            "word": ["WINWORD.EXE"],
            "excel": ["EXCEL.EXE"],
            "powerpoint": ["POWERPNT.EXE"],
            "spotify": ["Spotify.exe"],
            "discord": ["Discord.exe"],
        }

        candidate_exes = []

        # 1) Coincidencias con aliases conocidos
        for key, exes in alias_map.items():
            if key in lower_name:
                candidate_exes.extend(exes)

        # 2) Fallback genérico: usar la última palabra como base
        if not candidate_exes:
            base = original_name.replace(".exe", "").split()[-1]
            candidate_exes.append(base + ".exe")

        # 3) Obtener lista de procesos activos con tasklist
        running_processes = []
        try:
            tl = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            if tl.returncode == 0 and tl.stdout:
                reader = csv.reader(io.StringIO(tl.stdout))
                for row in reader:
                    if not row:
                        continue
                    image_name = row[0].strip().strip('"')
                    if image_name:
                        running_processes.append(image_name)
        except Exception as e:
            logger.warning(f"No se pudo ejecutar tasklist para detectar procesos: {e}")

        # 4) Seleccionar procesos a matar
        to_kill = set()
        lower_running = {p.lower(): p for p in running_processes}

        # 4.1 Coincidencia exacta con los candidates
        for cand in candidate_exes:
            cl = cand.lower()
            if cl in lower_running:
                to_kill.add(lower_running[cl])

        # 4.2 Fallback: búsqueda "contiene" por tokens (para nombres tipo 'Adobe Photoshop 2024.exe')
        if not to_kill and running_processes:
            tokens = [t for t in lower_name.replace(".exe", "").split() if len(t) >= 3]
            for img_lower, img_real in lower_running.items():
                if any(t in img_lower for t in tokens):
                    to_kill.add(img_real)

        if not to_kill:
            msg = f"No encontré ningún proceso que coincida con '{original_name}'."
            logger.info(msg)
            send_progress(f"⚠️ {msg}")
            return f"No pude cerrar {original_name}."

        # 5) Ejecutar taskkill sobre todos los procesos detectados
        errors = []
        closed = []

        for exe_name in to_kill:
            cmd = f'taskkill /IM "{exe_name}" /F'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Aplicación {exe_name} cerrada exitosamente")
                closed.append(exe_name)
            else:
                err = result.stderr.strip() or "Error desconocido"
                logger.error(f"Error al cerrar {exe_name}: {err}")
                errors.append(f"{exe_name}: {err}")

        if closed:
            if len(closed) == 1:
                msg = f"{original_name} cerrado exitosamente ({closed[0]})."
            else:
                msg = f"Se cerraron procesos relacionados con {original_name}: {', '.join(closed)}."
            send_progress(f"✅ {msg}")
            return msg

        # Si no se cerró nada pero sí hubo matches → hubo errores con taskkill
        if errors:
            msg = f"No pude cerrar {original_name}. Detalle: {'; '.join(errors)}"
            send_progress(f"⚠️ {msg}")
            return f"No pude cerrar {original_name}."

        # Último fallback por seguridad
        msg = f"No pude cerrar {original_name}."
        send_progress(f"⚠️ {msg}")
        return msg

    except Exception as e:
        logger.error(f"Excepción al cerrar {app_name}: {str(e)}")
        return f"Error al cerrar {app_name}: {e}"


  
  
def try_web_fallback(app_name, progress_callback=None):      
    """Intenta abrir versión web de una aplicación"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        app_name_clean = app_name.lower().strip()      
        send_progress(f"🌐 Buscando versión web de {app_name_clean}...")  
        logger.info(f"Intentando fallback web para: {app_name_clean}")      
              
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador (fallback)")  
            send_progress(f"✅ {app_name.capitalize()} abierto en navegador")  
            return f"Abriendo {app_name.capitalize()} en el navegador."      
        else:      
            logger.warning(f"No hay fallback web para {app_name_clean}")  
            send_progress(f"⚠️ No hay versión web disponible para {app_name_clean}")  
            return f"No tengo una versión web para {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Error en fallback web: {str(e)}")      
        return f"Error al intentar abrir versión web: {e}"


def search_google(query, progress_callback=None): 
    def send_progress(msg):
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
    try:      
        send_progress(f"🔍 Buscando en Google: {query}")  
        logger.info(f"Buscando en Google: {query}")      
        search_url = f"https://www.google.com/search?q={query}"      
        webbrowser.open(search_url)      
        send_progress(f"✅ Búsqueda abierta en navegador")  
        return f"Buscando '{query}' en Google."      
    except Exception as e:      
        logger.error(f"Error buscando en Google: {str(e)}")      
        return f"Error al buscar en Google: {e}"  
  
  
def search_youtube(query, play_video=True, progress_callback=None):      
    """Busca y opcionalmente reproduce un video de YouTube"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🎥 Buscando en YouTube: {query}")  
        logger.info(f"Buscando en YouTube: {query}")      
              
        if play_video:      
            send_progress("🔍 Buscando video (modo rápido)...")
            # OPTIMIZACIÓN: Abrir búsqueda directa para eliminar delay de scraping
            # youtube-search tarda 5-10s. Abrir la URL es instantáneo (0s).
            search_url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAQ%3D%3D" # sp=... filtra solo videos
            webbrowser.open(search_url)
            send_progress(f"✅ Video encontrado en YouTube")  
            return f"Abriendo resultados para '{query}'."

        # Búsqueda simple      
        search_url = f"https://www.youtube.com/results?search_query={query}"      
        webbrowser.open(search_url)      
        send_progress(f"✅ Búsqueda abierta en YouTube")  
        return f"Buscando '{query}' en YouTube."      
              
    except Exception as e:      
        logger.error(f"Error buscando en YouTube: {str(e)}")      
        return f"Error al buscar en YouTube: {e}"  
  
  
def get_weather(city, progress_callback=None):      
    """Obtiene el clima de una ciudad"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🌤️ Consultando clima de {city}...")  
        logger.info(f"Obteniendo clima para: {city}")      
        api_key = WEATHER_API_KEY      
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=es"      
              
        send_progress("📡 Conectando con servicio meteorológico...")  
        response = requests.get(url, timeout=5)      
        data = response.json()      
              
        if response.status_code == 200:      
            temp = data['main']['temp']      
            description = data['weather'][0]['description']      
            humidity = data['main']['humidity']      
            result = f"En {city}: {temp}°C, {description}. Humedad: {humidity}%"      
            logger.info(f"Clima obtenido: {result}")      
            send_progress(f"✅ {result}")  
            return result      
        else:      
            error_msg = f"No pude obtener el clima de {city}"      
            logger.error(f"Error API clima: {data.get('message', 'Unknown')}")      
            send_progress(f"⚠️ {error_msg}")  
            return error_msg      
                  
    except Exception as e:      
        logger.error(f"Error obteniendo clima: {str(e)}")      
        return f"Error al obtener el clima: {e}"  
  
  
def shutdown(progress_callback=None):      
    """Función mejorada para apagar el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("⚠️ Apagando el sistema en 1 segundo...")  
        logger.info("Ejecutando comando de apagado")      
        os.system("shutdown /s /t 1")      
        send_progress("🔴 Sistema apagándose...")  
        return "Apagando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al apagar: {str(e)}")      
        return f"Error al apagar: {e}"      
      
def restart(progress_callback=None):      
    """Función mejorada para reiniciar el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("⚠️ Reiniciando el sistema en 1 segundo...")  
        logger.info("Ejecutando comando de reinicio")      
        os.system("shutdown /r /t 1")      
        send_progress("🔄 Sistema reiniciándose...")  
        return "Reiniciando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al reiniciar: {str(e)}")      
        return f"Error al reiniciar: {e}"      
      
def suspend(progress_callback=None):      
    """Función mejorada para suspender el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("💤 Suspendiendo el sistema...")  
        logger.info("Ejecutando comando de suspensión")      
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")      
        send_progress("✅ Sistema suspendido")  
        return "Suspendiendo la computadora..."      
    except Exception as e:      
        logger.error(f"Error al suspender: {str(e)}")      
        return f"Error al suspender: {e}"  
  
  
def set_volume(level, progress_callback=None):
    """Ajusta el volumen del sistema. Usa PyCAW si está disponible; si no, intenta fallback con nircmd."""
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        send_progress(f"🔊 Ajustando volumen al {level}%...")
        if isinstance(level, str):
            level = int(level.replace('%', ''))
        level = max(0, min(100, int(level)))

        try:
            # Intento con PyCAW
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            send_progress(f"✅ Volumen ajustado al {level}%")
            return f"Volumen ajustado al {level}%"
        except Exception as e:
            logger.warning(f"PyCAW no disponible, intento fallback con nircmd: {e}")

            # Fallback con nircmd (acepta de 0 a 65535)
            nircmd_path = get_nircmd_path()
            scalar = int(65535 * (level / 100.0))
            subprocess.run([nircmd_path, 'setsysvolume', str(scalar)], timeout=2)
            send_progress(f"✅ Volumen ajustado al {level}% (fallback)")
            return f"Volumen ajustado al {level}%"
    except Exception as e:
        logger.error(f"Error ajustando volumen: {str(e)}")
        return f"Error ajustando volumen: {e}"



def create_file(file_path, content="", progress_callback=None):
    """Crea un archivo con contenido opcional, soportando alias tipo 'escritorio', 'documentos', etc."""
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not file_path:
            msg = "Falta 'file_path' para crear el archivo"
            send_progress(f"⚠️ {msg}")
            return msg

        # Normalizar y resolver ubicaciones estándar
        resolved_path = _resolve_standard_path(file_path)

        send_progress(f"📝 Creando archivo: {resolved_path}")
        logger.info(f"Creando archivo: {resolved_path}")

        parent = os.path.dirname(resolved_path)
        if parent:
            send_progress("📁 Creando directorio padre si es necesario...")
            os.makedirs(parent, exist_ok=True)

        send_progress("✍️ Escribiendo contenido del archivo...")
        with open(resolved_path, "w", encoding="utf-8") as f:
            f.write(content or "")

        msg_ok = f"Archivo creado: {resolved_path}"
        send_progress(f"✅ {msg_ok}")
        return msg_ok

    except Exception as e:
        logger.error(f"Error creando archivo '{file_path}': {e}")
        return f"Error creando archivo: {e}"
  
  
def create_folder(folder_path, progress_callback=None):
    """Crea una carpeta, soportando alias tipo 'escritorio', 'documentos', etc."""
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not folder_path:
            msg = "Falta 'folder_path' para crear la carpeta"
            send_progress(f"⚠️ {msg}")
            return msg

        resolved_path = _resolve_standard_path(folder_path)

        send_progress(f"📁 Creando carpeta: {resolved_path}")
        logger.info(f"Creando carpeta: {resolved_path}")

        os.makedirs(resolved_path, exist_ok=True)

        msg_ok = f"Carpeta creada: {resolved_path}"
        send_progress(f"✅ {msg_ok}")
        return msg_ok

    except Exception as e:
        logger.error(f"Error creando carpeta '{folder_path}': {e}")
        return f"Error creando carpeta: {e}"

      
def move_file(source, destination, progress_callback=None):
    """
    Mueve un archivo de origen a destino.

    Soporta:
    - Rutas normales: "escritorio/chat.txt"
    - Comodines: "escritorio/*.py"  → mueve TODOS los .py
    - Ambos extremos pasan por _resolve_standard_path
    """
    import shutil
    import glob

    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not source or not destination:
            msg = "Faltan 'source' o 'destination' para mover el archivo"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        # Resolver alias (escritorio, documentos, {username}, etc.)
        raw_src = _resolve_standard_path(source)
        dst = _resolve_standard_path(destination)

        has_wildcard = "*" in raw_src or "?" in raw_src

        # Caso 1: comodín → mover varios archivos
        if has_wildcard:
            send_progress(f"📦 Moviendo archivos que coincidan con '{raw_src}' a '{dst}'")
            logger.info(f"Moviendo archivos por patrón: {raw_src} -> {dst}")

            matches = glob.glob(raw_src)
            matches = [m for m in matches if os.path.isfile(m)]

            if not matches:
                msg = f"El archivo de origen no existe o no hay coincidencias: {raw_src}"
                send_progress(f"⚠️ {msg}")
                return {"ok": False, "error": msg}

            # Asegurar que el destino sea un directorio
            os.makedirs(dst, exist_ok=True)

            moved = 0
            for src_file in matches:
                base = os.path.basename(src_file)
                final_dest = os.path.join(dst, base)
                send_progress(f"🚚 Moviendo {src_file} → {final_dest}")
                shutil.move(src_file, final_dest)
                moved += 1

            msg_ok = f"Se movieron {moved} archivo(s) a {dst}"
            send_progress(f"✅ {msg_ok}")
            return msg_ok

        # Caso 2: un solo archivo
        src = raw_src
        send_progress(f"📦 Moviendo archivo de {src} a {dst}")
        logger.info(f"Moviendo archivo de {src} a {dst}")

        if not os.path.exists(src):
            msg = f"El archivo de origen no existe: {src}"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        # Si destino es un directorio, asegurarlo; si no, aseguramos su parent
        if os.path.isdir(dst) or dst.endswith(os.sep):
            os.makedirs(dst, exist_ok=True)
            final_dest = os.path.join(dst, os.path.basename(src))
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            final_dest = dst

        send_progress(f"🚚 Moviendo archivo...")
        shutil.move(src, final_dest)

        send_progress("✅ Archivo movido exitosamente")
        return f"Archivo movido de {src} a {final_dest}"

    except Exception as e:
        logger.error(f"Error moviendo archivo de '{source}' a '{destination}': {e}")
        return {"ok": False, "error": f"Error moviendo archivo: {e}"}


      
def copy_file(source, destination, progress_callback=None):
    """
    Copia archivo(s) de origen a destino.

    Soporta:
    - Rutas normales: "escritorio/chat.txt"
    - Comodines: "escritorio/*.py"  → copia TODOS los .py al destino (que debe ser carpeta)
    - Ambos extremos pasan por _resolve_standard_path
    """
    import shutil
    import glob

    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not source or not destination:
            msg = "Faltan 'source' o 'destination' para copiar"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        raw_src = _resolve_standard_path(source)
        dst = _resolve_standard_path(destination)

        has_wildcard = "*" in raw_src or "?" in raw_src

        # Caso 1: comodín → copiar varios archivos
        if has_wildcard:
            send_progress(f"📋 Copiando archivos que coincidan con '{raw_src}' a '{dst}'")
            logger.info(f"Copiando por patrón: {raw_src} -> {dst}")

            matches = glob.glob(raw_src)
            matches = [m for m in matches if os.path.isfile(m)]
            if not matches:
                msg = f"No hay coincidencias para: {raw_src}"
                send_progress(f"⚠️ {msg}")
                return {"ok": False, "error": msg}

            os.makedirs(dst, exist_ok=True)

            copied = 0
            for src_file in matches:
                base = os.path.basename(src_file)
                final_dest = os.path.join(dst, base)
                send_progress(f"📄 Copiando {src_file} → {final_dest}")
                shutil.copy2(src_file, final_dest)
                copied += 1

            msg_ok = f"Se copiaron {copied} archivo(s) a {dst}"
            send_progress(f"✅ {msg_ok}")
            return msg_ok

        # Caso 2: un solo archivo
        src = raw_src
        send_progress(f"📋 Copiando archivo de {src} a {dst}")
        logger.info(f"Copiando archivo de {src} a {dst}")

        if not os.path.exists(src):
            msg = f"El archivo de origen no existe: {src}"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        # Si destino es carpeta, crearla y poner mismo nombre
        if os.path.isdir(dst) or dst.endswith(os.sep):
            os.makedirs(dst, exist_ok=True)
            final_dest = os.path.join(dst, os.path.basename(src))
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            final_dest = dst

        send_progress("📄 Copiando archivo...")
        shutil.copy2(src, final_dest)

        send_progress("✅ Archivo copiado exitosamente")
        return f"Archivo copiado de {src} a {final_dest}"

    except Exception as e:
        logger.error(f"Error copiando archivo de '{source}' a '{destination}': {e}")
        return {"ok": False, "error": f"Error copiando archivo: {e}"}

  
  
def create_shortcut(target_path=None, shortcut_path=None, description=None, icon_path=None, progress_callback=None):
    """Crea un acceso directo (alineado con STRICT_JSON: usa target_path y shortcut_path)."""
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        if not target_path or not shortcut_path:
            msg = "Faltan 'target_path' y/o 'shortcut_path' para crear el acceso directo"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        target_resolved = _resolve_standard_path(target_path)
        shortcut_resolved = _resolve_standard_path(shortcut_path)

        send_progress(f"🔗 Creando acceso directo a {target_resolved}")
        logger.info(f"Creando acceso directo: {shortcut_resolved} -> {target_resolved}")

        import os
        os.makedirs(os.path.dirname(shortcut_resolved), exist_ok=True)

        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        scut = shell.CreateShortcut(shortcut_resolved)
        scut.TargetPath = target_resolved                  # Nota: propiedad correcta con P mayúscula
        scut.WorkingDirectory = os.path.dirname(target_resolved) or os.path.expanduser("~")
        if description:
            scut.Description = str(description)
        if icon_path:
            scut.IconLocation = _resolve_standard_path(icon_path)
        scut.save()

        send_progress("✅ Acceso directo creado exitosamente")
        return f"Acceso directo creado: {shortcut_resolved}"
    except Exception as e:
        logger.error(f"Error creando acceso directo: {str(e)}")
        return {"ok": False, "error": f"Error creando acceso directo: {e}"}

  
  
def delete_file(file_path, progress_callback=None):
    """
    Elimina un archivo o carpeta.
    Mantiene compatibilidad con el uso actual, pero ahora también soporta directorios.
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        import shutil

        if not file_path:
            msg = "Falta 'file_path' para eliminar"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        resolved = _resolve_standard_path(file_path)

        if not os.path.exists(resolved):
            msg = f"No existe la ruta: {resolved}"
            send_progress(f"⚠️ {msg}")
            return {"ok": False, "error": msg}

        if os.path.isfile(resolved):
            send_progress(f"🗑️ Eliminando archivo: {resolved}")
            os.remove(resolved)
            msg_ok = f"Archivo eliminado: {resolved}"
        else:
            send_progress(f"🗑️ Eliminando carpeta: {resolved}")
            shutil.rmtree(resolved, ignore_errors=True)
            msg_ok = f"Carpeta eliminada: {resolved}"

        send_progress(f"✅ {msg_ok}")
        return msg_ok

    except Exception as e:
        logger.error(f"Error eliminando '{file_path}': {e}")
        return {"ok": False, "error": f"Error eliminando archivo/carpeta: {e}"}
  
  
def list_files(directory_path=None, progress_callback=None):
    """Lista archivos en un directorio. Si no se pasa, usa el Escritorio como default."""
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        # Default: Escritorio del usuario
        # Resolver alias (escritorio, documentos, {username}, etc.)
        resolved = _resolve_standard_path(directory_path or "escritorio")

        send_progress(f"📂 Listando archivos en: {resolved}")
        logger.info(f"Listando archivos en: {resolved}")

        if not os.path.isdir(resolved):
            msg = f"La ruta no es un directorio válido: {resolved}"
            send_progress(f"⚠️ {msg}")
            return msg

        files = os.listdir(resolved)
        send_progress(f"📊 Encontrados {len(files)} elementos")

        if files:
            # Limitamos a 50 para no explotar la respuesta
            file_list = "\n".join(files[:50])
            send_progress("✅ Lista generada")
            return f"Archivos en {resolved}:\n{file_list}"
        else:
            send_progress("⚠️ Directorio vacío")
            return f"No hay archivos en {resolved}"

    except Exception as e:
        logger.error(f"Error listando archivos: {e}")
        return f"Error listando archivos: {e}"


def list_directory_detailed(directory=None, path=None, directory_path=None, progress_callback=None):
    """
    Lista un directorio con detalles (tamaño y fecha) para cada entrada.
    Acepta 'directory', 'path' o 'directory_path'. Si ninguno se pasa, usa Escritorio.
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        target = directory or path or directory_path
        if not target:
            target = os.path.join(os.path.expanduser("~"), "Desktop")

        resolved = _resolve_standard_path(target)
        send_progress(f"📂 Listando (detallado) en: {resolved}")

        if not os.path.isdir(resolved):
            msg = f"La ruta no es un directorio válido: {resolved}"
            send_progress(f"⚠️ {msg}")
            return msg

        entries = os.listdir(resolved)
        if not entries:
            send_progress("⚠️ Directorio vacío")
            return f"No hay archivos en {resolved}"

        lines = []
        for name in entries[:50]:  # límite de seguridad
            full = os.path.join(resolved, name)
            try:
                stat = os.stat(full)
                size_kb = stat.st_size / 1024.0
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                kind = "📁" if os.path.isdir(full) else "📄"
                lines.append(f"{kind} {name} — {size_kb:.1f} KB — modificado {mtime}")
            except Exception:
                lines.append(f"❓ {name}")

        send_progress("✅ Lista detallada generada")
        return f"Contenido de {resolved}:\n" + "\n".join(lines)

    except Exception as e:
        logger.error(f"Error listando directorio detallado: {e}")
        return f"Error listando directorio: {e}"




def read_file(file_path=None, path=None, max_chars=4000, progress_callback=None):
    """
    Lee el contenido de un archivo de texto y devuelve una vista previa.
    Soporta parámetros 'file_path' o 'path'.
    """
    def send_progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        target = file_path or path
        if not target:
            msg = "Falta 'file_path' o 'path' para leer el archivo"
            send_progress(f"⚠️ {msg}")
            return msg

        resolved = _resolve_standard_path(target)

        if not os.path.exists(resolved):
            msg = f"El archivo no existe: {resolved}"
            send_progress(f"⚠️ {msg}")
            return msg

        if not os.path.isfile(resolved):
            msg = f"La ruta no es un archivo: {resolved}"
            send_progress(f"⚠️ {msg}")
            return msg

        send_progress(f"📖 Leyendo archivo: {os.path.basename(resolved)}")

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if len(content) > max_chars:
            preview = content[:max_chars]
            send_progress("📏 Contenido truncado para vista previa")
            return f"Vista previa de {resolved} (truncado a {max_chars} caracteres):\n{preview}"
        else:
            send_progress("✅ Archivo leído completamente")
            return f"Contenido de {resolved}:\n{content}"

    except Exception as e:
        logger.error(f"Error leyendo archivo: {e}")
        return f"Error leyendo archivo: {e}"


  
def diagnose_system_performance(progress_callback=None):      
    """Diagnostica rendimiento del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Iniciando diagnóstico de rendimiento del sistema...")  
        logger.info("Iniciando diagnóstico de rendimiento del sistema")      
          
        # Verificar uso de CPU  
        send_progress("📊 Verificando uso de CPU...")  
        cpu_result = subprocess.run('wmic cpu get loadpercentage /value', shell=True, capture_output=True, text=True)      
        cpu_usage = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)      
        cpu_percent = cpu_usage.group(1) if cpu_usage else 'N/A'      
          
        # Verificar memoria  
        send_progress("💾 Verificando memoria RAM...")  
        memory_result = subprocess.run('wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /value', shell=True, capture_output=True, text=True)      
        total_memory = re.search(r'TotalVisibleMemorySize=(\d+)', memory_result.stdout)      
        free_memory = re.search(r'FreePhysicalMemory=(\d+)', memory_result.stdout)      
              
        if total_memory and free_memory:      
            total_mb = int(total_memory.group(1)) // 1024      
            free_mb = int(free_memory.group(1)) // 1024      
            used_percent = ((total_mb - free_mb) / total_mb) * 100      
            memory_status = f"Memoria: {used_percent:.1f}% en uso ({free_mb}MB libres de {total_mb}MB)"      
        else:      
            memory_status = "Memoria: No se pudo obtener información"      
          
        # Verificar espacio en disco  
        send_progress("💿 Verificando espacio en disco...")  
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)      
              
        result = f"CPU: {cpu_percent}% de uso. {memory_status}. Diagnóstico completado."      
        logger.info(f"Diagnóstico completado: {result}")      
        send_progress(f"✅ {result}")  
        return result      
              
    except Exception as e:      
        logger.error(f"Error en diagnóstico de rendimiento: {str(e)}")      
        return f"Error al diagnosticar el sistema: {e}"


def check_system_services(progress_callback=None):      
    """Verifica servicios críticos del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Verificando servicios críticos del sistema...")  
        logger.info("Verificando servicios críticos del sistema")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS', 'Dhcp', 'Dnscache']      
        results = []      
        problems = []      
          
        for service in critical_services:      
            send_progress(f"⚙️ Verificando servicio: {service}")  
            try:      
                result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" in result.stdout:      
                    results.append(f"{service}: OK")      
                else:      
                    results.append(f"{service}: PROBLEMA")      
                    problems.append(service)      
            except:      
                results.append(f"{service}: ERROR")      
                problems.append(service)      
          
        status = "Servicios verificados: " + ", ".join(results)      
        if problems:      
            status += f". Servicios con problemas detectados: {', '.join(problems)}"      
          
        send_progress(f"✅ Verificación completada: {len(problems)} problemas encontrados")  
        logger.info(f"Verificación de servicios completada: {len(problems)} problemas encontrados")      
        return status      
              
    except Exception as e:      
        logger.error(f"Error verificando servicios: {str(e)}")      
        return f"Error al verificar servicios: {e}"      
      
def restart_critical_services(progress_callback=None):      
    """Reinicia servicios críticos que están parados"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔄 Reiniciando servicios críticos...")  
        logger.info("Reiniciando servicios críticos")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS']      
        restarted = []      
          
        for service in critical_services:      
            send_progress(f"⚙️ Procesando servicio: {service}")  
            try:      
                # Verificar estado actual      
                check_result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" not in check_result.stdout:      
                    send_progress(f"🔧 Reiniciando {service}...")  
                    # Intentar reiniciar      
                    stop_result = subprocess.run(f'net stop "{service}"', shell=True, capture_output=True, text=True)      
                    start_result = subprocess.run(f'net start "{service}"', shell=True, capture_output=True, text=True)      
                    if start_result.returncode == 0:      
                        restarted.append(service)      
                        logger.info(f"Servicio {service} reiniciado exitosamente")  
                        send_progress(f"✅ {service} reiniciado exitosamente")  
            except Exception as e:      
                logger.warning(f"No se pudo reiniciar {service}: {e}")      
          
        if restarted:      
            result = f"Servicios reiniciados: {', '.join(restarted)}"  
        else:      
            result = "No fue necesario reiniciar servicios o no se pudieron reiniciar"  
          
        send_progress(f"✅ Proceso completado")  
        return result      
              
    except Exception as e:      
        logger.error(f"Error reiniciando servicios: {str(e)}")      
        return f"Error al reiniciar servicios: {e}"      
      
def clean_temp_files(progress_callback=None):      
    """Limpia archivos temporales del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🧹 Iniciando limpieza de archivos temporales...")  
        logger.info("Limpiando archivos temporales")      
          
        send_progress("📁 Limpiando carpeta Temp de Windows...")  
        temp_result = subprocess.run('del /q /f /s %TEMP%\\*', shell=True, capture_output=True, text=True)      
          
        send_progress("📁 Limpiando carpeta Prefetch...")  
        prefetch_result = subprocess.run('del /q /f /s C:\\Windows\\Prefetch\\*', shell=True, capture_output=True, text=True)      
          
        send_progress("✅ Limpieza de archivos temporales completada")  
        return "Archivos temporales limpiados exitosamente."      
              
    except Exception as e:      
        logger.error(f"Error limpiando archivos temporales: {str(e)}")      
        return f"Error al limpiar archivos temporales: {e}"      
      
def flush_dns(progress_callback=None):      
    """Limpia la caché DNS"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🌐 Limpiando caché DNS...")  
        logger.info("Limpiando caché DNS")      
        result = subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, text=True)      
          
        if result.returncode == 0:      
            send_progress("✅ Caché DNS limpiada exitosamente")  
            return "Caché DNS limpiada exitosamente."      
        else:      
            send_progress("⚠️ Error al limpiar caché DNS")  
            return "Error al limpiar caché DNS."      
                  
    except Exception as e:      
        logger.error(f"Error limpiando DNS: {str(e)}")      
        return f"Error al limpiar DNS: {e}"      
      
def network_reset(progress_callback=None):      
    """Reinicia la configuración de red"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🌐 Reiniciando configuración de red...")  
        logger.info("Reiniciando configuración de red")      
          
        send_progress("🔄 Ejecutando netsh winsock reset...")  
        winsock_result = subprocess.run('netsh winsock reset', shell=True, capture_output=True, text=True)      
          
        send_progress("🔄 Ejecutando netsh int ip reset...")  
        ip_result = subprocess.run('netsh int ip reset', shell=True, capture_output=True, text=True)      
          
        send_progress("✅ Configuración de red reiniciada. Se recomienda reiniciar el sistema.")  
        return "Configuración de red reiniciada. Se recomienda reiniciar el sistema."      
              
    except Exception as e:      
        logger.error(f"Error reiniciando red: {str(e)}")      
        return f"Error al reiniciar red: {e}"      
      
def check_disk_space(progress_callback=None):      
    """Verifica el espacio disponible en disco"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("💿 Verificando espacio en disco...")  
        logger.info("Verificando espacio en disco")      
          
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)      
          
        # Parsear resultados  
        disks = []  
        lines = disk_result.stdout.split('\n')  
        current_disk = {}  
          
        for line in lines:  
            if 'Caption=' in line:  
                current_disk['caption'] = line.split('=')[1].strip()  
            elif 'FreeSpace=' in line:  
                try:  
                    free_bytes = int(line.split('=')[1].strip())  
                    current_disk['free_gb'] = free_bytes / (1024**3)  
                except:  
                    pass
            elif 'Size=' in line:  
                try:  
                    size_bytes = int(line.split('=')[1].strip())  
                    current_disk['size_gb'] = size_bytes / (1024**3)  
                    if 'free_gb' in current_disk and 'caption' in current_disk:  
                        disks.append(current_disk)  
                        current_disk = {}  
                except:  
                    pass  
          
        result = "Espacio en disco:\n"  
        for disk in disks:  
            used_percent = ((disk['size_gb'] - disk['free_gb']) / disk['size_gb']) * 100  
            result += f"{disk['caption']}: {disk['free_gb']:.1f}GB libres de {disk['size_gb']:.1f}GB ({used_percent:.1f}% usado)\n"  
            send_progress(f"💿 {disk['caption']}: {disk['free_gb']:.1f}GB libres ({used_percent:.1f}% usado)")  
          
        send_progress("✅ Verificación de espacio completada")  
        return result.strip()      
              
    except Exception as e:      
        logger.error(f"Error verificando espacio en disco: {str(e)}")      
        return f"Error al verificar espacio en disco: {e}"      

def system_file_check(progress_callback=None):      
    """Ejecuta verificación de archivos del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Ejecutando verificación de archivos del sistema (esto puede tardar varios minutos)...")  
        logger.info("Ejecutando verificación de archivos del sistema")      
          
        send_progress("⏳ Ejecutando sfc /scannow...")  
        # Ejecutar sfc /scannow      
        sfc_result = subprocess.run('sfc /scannow', shell=True, capture_output=True, text=True)      
          
        if "no encontró ninguna infracción de integridad" in sfc_result.stdout.lower():      
            result = "Verificación de archivos del sistema completada. No se encontraron problemas."      
        elif "reparó correctamente" in sfc_result.stdout.lower():      
            result = "Verificación completada. Se repararon algunos archivos del sistema."      
        else:      
            result = "Verificación de archivos del sistema ejecutada. Revisa los logs para más detalles."      
          
        send_progress(f"✅ {result}")  
        logger.info("Verificación de archivos del sistema completada")      
        return result      
              
    except Exception as e:      
        logger.error(f"Error en verificación del sistema: {str(e)}")      
        return f"Error al verificar archivos del sistema: {e}"  
  
  
# Funciones de recordatorios del código local      
def cmd_add_reminder(params, ctx):    
    username = _username(ctx, params)    
    
    raw_title = (params.get("title") or "").strip()    
    raw_activity = (params.get("activity") or "").strip()    
    raw_text = (params.get("text") or "").strip()    
    description = (params.get("description") or "").strip()    
    
    # Priorizamos: title > activity > text    
    candidate = raw_title or raw_activity or raw_text    
    
    title = candidate    
    if ":" in candidate:    
        left, right = candidate.split(":", 1)    
        title = left.strip()    
        # si no pasaron description explícita, usamos la de activity/text    
        if not description:    
            description = right.strip()    
    
    if not title:    
        return {"ok": False, "error": "Falta 'title' (puedes pasar 'activity' en formato 'Título: descripción')"}    
    
    category = (params.get("category") or "inbox").strip().lower()    
    status   = (params.get("status") or "todo").strip().lower()    
    priority_val = params.get("priority")
    priority = str(priority_val).strip().lower() if priority_val is not None else "normal"
    due_date = params.get("due_date")  # "YYYY-MM-DD"    
    due_time = params.get("due_time")  # "HH:MM"    
    recurrence = params.get("recurrence") # Added this line to define recurrence
    
    if due_time and not due_date:
        from datetime import datetime, timedelta
        try:
            now = datetime.now()
            t_obj = datetime.strptime(due_time[:5], "%H:%M").time()
            target_dt = datetime.combine(now.date(), t_obj)
            if target_dt <= now:
                target_dt += timedelta(days=1)
            due_date = target_dt.strftime("%Y-%m-%d")
        except:
            pass

    # Asegura lista    
    raw_tags = params.get("tags")    
    tags = raw_tags if isinstance(raw_tags, list) else []    
    
    item = add_reminder_item(    
        username=username,    
        title=title,    
        description=description,    
        category=category,    
        status=status,    
        priority=priority,    
        due_date=due_date,    
        due_time=due_time,    
        tags=tags,
        recurrence=recurrence,
    )

    days_of_week = params.get("daysOfWeek")
    notes = params.get("notes", "")
    priority = params.get("priority", 1)
    remindEveryValue = params.get("remindEveryValue", 0)
    remindEveryUnit = params.get("remindEveryUnit", "hours")
    color = params.get("color")
    if (due_date and due_time) or (recurrence == 'days' and days_of_week) or (recurrence == 'daily' and due_time):
        try:
            from datetime import datetime
            due_at = None
            if due_date and due_time:
                due_dt = datetime.fromisoformat(f"{due_date}T{due_time}")
                due_at = due_dt.isoformat()
            
            return {
                "ok": True,
                "reminder": item,
                "commands": [
                    {
                        "action": "queue_local_task",
                        "params": {
                            "task_type": "reminder_timer",
                            "description": f"Recordatorio: {title}",
                            "params": {
                                "title": title,
                                "delay_seconds": 0,
                                "reminder_id": item.get("id"),
                                "daysOfWeek": days_of_week,
                                "notes": notes,
                                "priority": priority,
                                "remindEveryValue": remindEveryValue,
                                "remindEveryUnit": remindEveryUnit,
                                "color": color
                            },
                            "due_at": due_at,
                            "category": category,
                            "recurrence": recurrence,
                        }
                    }
                ]
            }
        except Exception as e:
            logger.warning(f"No se pudo crear tarea programada: {e}")

    return {"ok": True, "reminder": item}


def cmd_add_multiple_reminders(params, ctx):
    username = _username(ctx, params)
    reminders = params.get("reminders", [])
    if not isinstance(reminders, list):
        return {"ok": False, "error": "'reminders' debe ser una lista"}
    
    added = []
    for rem in reminders:
        rem_copy = dict(rem)
        if "username" not in rem_copy:
            rem_copy["username"] = username
            
        res = cmd_add_reminder(rem_copy, ctx)
        if res.get("ok") and "reminder" in res:
            added.append(res["reminder"])

    return {
        "ok": True,
        "message": f"Se agregaron {len(added)} recordatorios.",
        "added_count": len(added),
        "reminders": added
    }


def cmd_get_reminders(params, ctx):    
    username = _username(ctx, params)
    from core.memory import list_reminders
    from datetime import datetime, timedelta
    
    # 0. Archivar automáticamente lo vencido antes de listar
    archive_expired_reminders(username)
    
    # 1. Obtener recordatorios centralizados
    items = list_reminders(username)
    
    show_history = params.get("show_history", False)
    category_filter = params.get("category")
    
    # Filtrar por categoría si se especifica (ej: "daily")
    if category_filter:
        items = [t for t in items if t.get('category') == category_filter]
        
    # Filtrar por estado (no mostrar history a menos que se pida)
    exclude_statuses = ['archived', 'deleted', 'cancelled']
    if not show_history:
        exclude_statuses.append('history')
        
    items = [t for t in items if t.get('status') not in exclude_statuses]
            
    # 2. Filtrar por fecha si se solicita
    date_query = params.get("date")
    if date_query:
        target_date = ""
        if date_query.lower() in ["today", "hoy"]:
            target_date = datetime.now().strftime("%Y-%m-%d")
        elif date_query.lower() in ["tomorrow", "mañana"]:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif re.match(r"\d{4}-\d{2}-\d{2}", date_query):
            target_date = date_query
            
        if target_date:
            items = [r for r in items if r.get("due_date") == target_date]
            date_label = "para hoy" if date_query.lower() in ["today", "hoy"] else (f"para el {target_date}")
        else:
            date_label = f"en la fecha {date_query}"
    else:
        date_label = ""

    if not items:
        msg = f"No tienes recordatorios activos {date_label}."
        return {
            "ok": True,
            "reminders": [],
            "message": msg,
            "user_response": msg
        }

    # 3. Armar lista legible
    total = len(items)
    today_iso = datetime.now().strftime("%Y-%m-%d")
    header = f"Se encontraron {total} recordatorios {date_label}:"
    lines = [header]
    for i, item in enumerate(items[:10], start=1): 
        title = item.get("title", "(sin título)")
        due_d = item.get("due_date")
        due_t = item.get("due_time")
        prio = item.get("priority")
        
        extra = ""
        if due_d: 
             extra += f" el {due_d}"
             if due_d < today_iso: extra += " [VENCIDO]"
             elif due_d == today_iso: extra += " [HOY]"
        if due_t: extra += f" a las {due_t}"
        
        # Prioridad visual
        prio_high = False
        if isinstance(prio, (int, float)): prio_high = prio >= 3
        elif isinstance(prio, str): prio_high = prio.lower() in ["urgent", "high", "alta"]
        if prio_high: extra += " (Alta Importancia)"
        
        lines.append(f"{i}. {title}{extra}")
        
    if total > 10:
        lines.append(f"...y {total - 10} más.")

    final_text = "\n".join(lines)
    return {
        "ok": True,
        "reminders": items,
        "message": final_text,
        "user_response": final_text 
    }


def cmd_get_reminder_history(params, ctx):
    """Obtiene los recordatorios que están en el historial (status='history')"""
    username = _username(ctx, params)
    items = list_reminders(username, status="history")
    return {"ok": True, "reminders": items}


def cmd_renew_reminder(params, ctx):
    """Renueva un recordatorio del historial dándole una nueva fecha/hora"""
    username = _username(ctx, params)
    rid = params.get("id") or params.get("reminder_id")
    new_date = params.get("due_date")
    new_time = params.get("due_time") or "09:00"
    
    if not rid or not new_date:
        return {"ok": False, "error": "Faltan parámetros 'id' y 'due_date'"}
    
    item = renew_reminder(username, rid, new_date, new_time)
    if item:
        return {"ok": True, "reminder": item, "message": f"Recordatorio '{item['title']}' renovado para el {new_date}"}
    return {"ok": False, "error": "No se pudo renovar el recordatorio"}


def cmd_clear_reminder_history(params, ctx):
    """Limpia todo el historial de recordatorios (status='history')"""
    username = _username(ctx, params)
    count = clear_reminder_history(username)
    return {"ok": True, "count": count, "message": f"Se han eliminado {count} recordatorios del historial"}

    
    
def cmd_update_reminder(params, ctx):    
    username = _username(ctx, params)

    reminder_id = params.get("id") or params.get("reminder_id")
    title_query = (
        params.get("title_query")
        or params.get("title")
        or params.get("name")
        or params.get("activity")
        or params.get("text")
        or ""
    ).strip().lower()

    # Campos actualizables
    allowed_fields = {
        "title", "description", "category", "status",
        "priority", "due_date", "due_time", "tags", "position",
    }
    fields = {k: v for k, v in params.items() if k in allowed_fields}

    # Si viene id, usarlo directo
    if reminder_id:
        # SI ESTAMOS EN ELECTRON: Avisar a Electron
        if os.getenv("RON_TASKS_PATH"):
            print(json.dumps({
                "type": "commands",
                "commands": [{"action": "tasks:update", "params": {"id": reminder_id, "patch": fields}}]
            }, ensure_ascii=False), flush=True)
            return {
                "ok": True,
                "message": f"Recordatorio actualizado (id: {reminder_id}).",
            }
        
        updated = update_reminder(username, reminder_id, **fields)
        if updated:
            return {
                "ok": True,
                "message": f"Recordatorio actualizado (id: {reminder_id}).",
                "reminder": updated,
            }
        return {
            "ok": False,
            "error": "No se encontró un recordatorio con ese id.",
        }

    # Sin id → buscar por título aproximado
    if not title_query:
        return {
            "ok": False,
            "error": "Falta 'id' o 'title' para actualizar el recordatorio.",
        }

    items = list_reminders(username)
    if not items:
        return {
            "ok": False,
            "error": "No tienes recordatorios guardados.",
        }

    exact = None
    partials = []

    for item in items:
        rid = item.get("id") or item.get("_id")
        title = (item.get("title") or "").lower()
        if not rid:
            continue

        if title == title_query:
            exact = (rid, item)
            break

        if title_query in title:
            partials.append((rid, item))

    if exact:
        rid, item = exact
    elif len(partials) == 1:
        rid, item = partials[0]
    elif len(partials) > 1:
        return {
            "ok": False,
            "error": "Hay varios recordatorios con un título similar; sé más específico.",
        }
    else:
        return {
            "ok": False,
            "error": f"No encontré ningún recordatorio que coincida con '{title_query}'.",
        }

    # SI ESTAMOS EN ELECTRON: Avisar a Electron
    if os.getenv("RON_TASKS_PATH"):
        print(json.dumps({
            "type": "commands",
            "commands": [{"action": "tasks:update", "params": {"id": rid, "patch": fields}}]
        }, ensure_ascii=False), flush=True)
        return {
            "ok": True,
            "message": f"Recordatorio '{item.get('title')}' actualizado con éxito.",
        }

    updated = update_reminder(username, rid, **fields)
    if not updated:
        return {
            "ok": False,
            "error": "No se pudo actualizar el recordatorio.",
        }

    return {
        "ok": True,
        "message": f"Recordatorio '{updated.get('title')}' actualizado.",
        "reminder": updated,
    }

    
      
def cmd_remove_reminder(params, ctx):
    """
    Elimina un recordatorio por:
    - id / reminder_id
    - o por título aproximado: title, name, activity, text, title_query, etc.
    """
    username = _username(ctx, params)

    reminder_id = params.get("id") or params.get("reminder_id")

    # Intentar sacar un texto de búsqueda lo más genérico posible
    title_query = (
        params.get("title_query")
        or params.get("title")
        or params.get("name")
        or params.get("activity")
        or params.get("text")
        or ""
    ).strip().lower()

    items = list_reminders(username)
    if not items:
        return {"ok": False, "error": "No tienes recordatorios guardados."}

    rid = None
    item = None

    # 1. Búsqueda por ID directo
    if reminder_id:
        match = next((x for x in items if str(x.get("id")) == str(reminder_id)), None)
        if match:
            rid = reminder_id
            item = match

    # 2. Búsqueda por Título
    if not rid and title_query:
        # Búsqueda exacta primero
        match = next((x for x in items if x.get("title", "").lower() == title_query), None)
        if match:
            rid = match.get("id")
            item = match
        else:
            # Búsqueda parcial
            match = next((x for x in items if title_query in x.get("title", "").lower()), None)
            if match:
                rid = match.get("id")
                item = match

    if not rid:
        return {"ok": False, "error": f"No encontré ningún recordatorio que coincida con '{title_query or reminder_id}'."}

    # 🔹 SI ESTAMOS EN ELECTRON: Avisar a Electron para que borre de memoria y de su tasks.json
    if os.getenv("RON_TASKS_PATH"):
        # Imprimimos el comando para que Electron lo intercepte
        print(json.dumps({
            "type": "commands", 
            "commands": [{"action": "tasks:delete", "params": {"id": rid}}]
        }, ensure_ascii=False), flush=True)
        return {
            "ok": True, 
            "message": f"Recordatorio '{item.get('title')}' eliminado con éxito.",
        }

    # FLUJO NORMAL (Sin Electron)
    removed = remove_reminder_item(username, rid)
    if not removed:
        return {"ok": False, "error": "No se pudo eliminar el recordatorio."}

    return {
        "ok": True,
        "message": f"Recordatorio '{item.get('title')}' eliminado."
    }


def _parse_delay_from_text(default_seconds: int = 60, *texts) -> int:
    """
    Intenta extraer un tiempo (en segundos) a partir de texto tipo:
      - '5 minutos'
      - '30 segundos'
      - '2 horas'
    Devuelve default_seconds si no encuentra nada usable.
    """
    joined_parts = []
    for t in texts:
        if isinstance(t, str) and t.strip():
            joined_parts.append(t.strip().lower())
    joined = " ".join(joined_parts)

    if not joined:
        return default_seconds

    # Ej: "en 5 minutos", "dentro de 30 segundos", "2 horas"
    m = re.search(r"(\d+)\s*(segundo|segundos|seg|s|minuto|minutos|min|hora|horas|h)\b", joined)
    if m:
        n = int(m.group(1))
        unit = m.group(2)

        if unit.startswith(("seg", "s")):
            return max(1, n)
        if unit.startswith(("min", "m")):
            return max(1, n * 60)
        if unit.startswith(("hora", "h")):
            return max(1, n * 3600)

    # Último fallback: si hay algún número suelto, interpretarlo como minutos
    m2 = re.search(r"(\d+)", joined)
    if m2:
        return max(1, int(m2.group(1)) * 60)

    return default_seconds


def cmd_reminder_timer(params, ctx):
    """
    Tarea de cronómetro para recordatorios, pensada para usarse vía queue_local_task.

    params puede traer:
      - delay_seconds: segundos exactos a esperar (int o string)
      - delay / seconds / minutes / mins: sinónimos opcionales
      - title / activity / text / description: texto del recordatorio
      - reminder_id / id: id del recordatorio (para marcarlo como done)
      - username: opcional (si no, se toma de ctx)

    Devuelve un dict {ok, summary, message, error}.
    """
    def send_progress(msg: str):
        progress_callback = ctx.get("progress_callback")
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    try:
        params = params or {}
        ctx = ctx or {}

        # Username unificado
        username = _username(ctx, params)

        # ---------------- TEXTO DEL RECORDATORIO ----------------
        raw_title = (params.get("title") or "").strip()
        raw_activity = (params.get("activity") or "").strip()
        raw_text = (params.get("text") or "").strip()
        description = (params.get("description") or "").strip()

        # Priorizamos: title > activity > text > description
        text_base = raw_title or raw_activity or raw_text or description or ""

        # Si aun así está vacío, intentamos sacar título desde el recordatorio
        reminder_id = params.get("reminder_id") or params.get("id")
        if not text_base and reminder_id and username:
            try:
                items = list_reminders(username)
                for item in items:
                    rid = item.get("id") or item.get("_id")
                    if rid != reminder_id:
                        continue
                    text_base = (item.get("title") or item.get("description") or "").strip()
                    if text_base:
                        break
            except Exception as e:
                logger.warning(f"No se pudo obtener título desde el reminder_id {reminder_id}: {e}")

        if not text_base:
            text_base = "tu recordatorio"

        # Limpieza típica: si viene algo tipo "Recordatorio en 5 minutos: mandar el informe"
        low = text_base.lower()
        if low.startswith("recordatorio") and ":" in text_base:
            after = text_base.split(":", 1)[1].strip()
            if after:
                text_base = after

        # ---------------- RESOLVER DELAY EN SEGUNDOS ----------------
        delay = None

        # 1) Campos explícitos tipo delay_seconds / seconds / delay
        raw_delay = params.get("delay_seconds")
        if raw_delay is None and "seconds" in params:
            raw_delay = params["seconds"]
        if raw_delay is None and "delay" in params:
            raw_delay = params["delay"]

        if raw_delay is not None:
            if isinstance(raw_delay, (int, float)):
                delay = int(raw_delay)
            elif isinstance(raw_delay, str):
                s = raw_delay.strip().lower()
                if s.isdigit():
                    delay = int(s)
                else:
                    # Intentar parsear "5 minutos", "30 segundos", etc.
                    delay = _parse_delay_from_text(None, s)
                    # Intentar formato ISO tipo PT5M, PT30S si sigue sin valor
                    if delay is None:
                        m = re.match(r"^pt(\d+)([smh])", s)
                        if m:
                            n = int(m.group(1))
                            unit = m.group(2)
                            if unit == "s":
                                delay = n
                            elif unit == "m":
                                delay = n * 60
                            elif unit == "h":
                                delay = n * 3600

        # 2) minutes / mins numéricos
        if delay is None:
            mins_val = params.get("minutes") or params.get("mins")
            if mins_val is not None:
                try:
                    if isinstance(mins_val, str):
                        # Puede venir "5", "5 minutos"
                        m = re.search(r"\d+", mins_val)
                        mins_int = int(m.group(0)) if m else 0
                    else:
                        mins_int = int(mins_val)
                    if mins_int > 0:
                        delay = mins_int * 60
                except Exception:
                    pass

        # 3) Calcular desde due_date/due_time del recordatorio (si existe)
        if delay is None and reminder_id and username:
            try:
                items = list_reminders(username)
                now = datetime.now()
                for item in items:
                    rid = item.get("id") or item.get("_id")
                    if rid != reminder_id:
                        continue
                    due_d = item.get("due_date")
                    due_t = item.get("due_time")
                    if due_d and due_t:
                        try:
                            due_dt = datetime.fromisoformat(f"{due_d}T{due_t}")
                        except Exception:
                            try:
                                due_dt = datetime.strptime(
                                    f"{due_d} {due_t}", "%Y-%m-%d %H:%M"
                                )
                            except Exception:
                                continue
                        delta = (due_dt - now).total_seconds()
                        if delta > 1:
                            delay = int(delta)
                        break
            except Exception as e:
                logger.warning(f"No se pudo calcular delay desde el reminder_id {reminder_id}: {e}")

        # 4) Último intento: deducirlo del texto libre (prompt original, etc.)
        if delay is None:
            delay = _parse_delay_from_text(
                60,
                text_base,
                params.get("raw_text") or "",
                params.get("original_prompt") or "",
            )

        # Normalización final
        # Si el delay es muy grande (> 60s), delegamos a Electron TaskManager
        if delay > 60:
            due_at = (datetime.now() + timedelta(seconds=delay)).isoformat()
            send_progress(f"📅 Programando recordatorio para dentro de {delay // 60} minutos...")
            return {
                "ok": True,
                "summary": f"Recordatorio programado para dentro de {delay // 60} minutos.",
                "commands": [
                    {
                        "action": "queue_local_task",
                        "params": {
                            "task_type": "reminder_timer",
                            "description": f"Recordatorio: {text_base}",
                            "params": {
                                "title": text_base,
                                "delay_seconds": 0, # Ya no esperamos aquí
                                "reminder_id": reminder_id
                            },
                            "due_at": due_at,
                            "category": params.get("category", "General")
                        }
                    }
                ]
            }

        send_progress(f"⏱ Iniciando temporizador de {delay}s para el recordatorio '{text_base}'...")

        # Espera bloqueante (esto corre en proceso separado de TaskManager)
        time.sleep(delay)

        # Marcar recordatorio como done (opcional)
        if reminder_id and username:
            try:
                update_reminder(username, reminder_id, status="done")
            except Exception as e:
                logger.warning(f"No se pudo actualizar el estado del recordatorio {reminder_id}: {e}")

        final_msg = f"⏰ Te recuerdo: {text_base}"

        send_progress("✅ Temporizador completado, enviando recordatorio al usuario")

        return {
            "ok": True,
            "summary": final_msg,
            "message": final_msg,
            "error": "",
        }

    except Exception as e:
        logger.error(f"Error en cmd_reminder_timer: {e}")
        return {
            "ok": False,
            "error": f"Error en el temporizador de recordatorio: {e}",
        }




def cmd_queue_local_task(params, ctx):
    """
    Encola una tarea en el TaskManager (si existe en el contexto).
    """
    task_manager = ctx.get('task_manager')
    if not task_manager:
        return {"ok": False, "error": "No task manager available in this context"}

    task_type = params.get('task_type')
    description = params.get('description') or f"Tarea: {task_type}"
    
    def task_wrapper(progress_callback):
        # Inyectamos el progress_callback en el contexto
        new_ctx = ctx.copy()
        new_ctx['progress_callback'] = progress_callback
        
        # Mapeo de task_type a comando real
        cmd_map = {
            "analyze_local_file": "analyze_local_file",
            "diagnose_system": "diagnose_system_performance",
            "bulk_file_analysis": "bulk_file_analysis",
            "reminder_timer": "reminder_timer"
        }
        
        real_cmd = cmd_map.get(task_type, task_type)
        res = run_command(real_cmd, params, new_ctx)
        
        if not res.get("ok"):
            raise Exception(res.get("error", "Unknown error"))
            
        return res.get("message") or res.get("result") or "Tarea completada"

    task_id = task_manager.add_task(description, task_wrapper)
    return {"ok": True, "message": f"Tarea programada: {description}", "task_id": task_id}


def reminder_timer(params, ctx):
    """
    Wrapper de compatibilidad para código antiguo.
    Delegamos en cmd_reminder_timer.
    """
    return cmd_reminder_timer(params, ctx)


def cmd_get_audio_devices(params, ctx):
    """Retorna la lista de dispositivos de audio (micrófonos)."""
    if sr is None:
        return {"ok": False, "error": "SpeechRecognition no instalado"}
    
    try:
        mics = sr.Microphone.list_microphone_names()
        devices = [{"index": i, "name": name} for i, name in enumerate(mics)]
        return {"ok": True, "devices": devices}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def cmd_set_audio_device(params, ctx):
    """
    Selecciona un micrófono y solicita reinicio del servicio de voz.
    Params: { "index": int }
    """
    try:
        idx = int(params.get("index", -1))
        return {
            "ok": True,
            "message": f"Seleccionando micrófono {idx}...",
            "commands": [
                {
                    "action": "notify", 
                    "params": {"title": "Audio", "message": f"Cambiando micrófono a ID {idx}..."}
                },
                {
                    "action": "update-mic-config",
                    "params": {"index": idx}
                }
            ]
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}




COMMANDS = {      
    # ——— Recordatorios      
    "add_reminder": cmd_add_reminder,      
    "add_multiple_reminders": cmd_add_multiple_reminders,
    "get_reminders": cmd_get_reminders,      
    "update_reminder": cmd_update_reminder,      
    "remove_reminder": cmd_remove_reminder,    
    # temporizador de recordatorios
    "reminder_timer": cmd_reminder_timer,
    "reminder_timer": cmd_reminder_timer,
    "cmd_reminder_timer": cmd_reminder_timer,
    "queue_local_task": cmd_queue_local_task,
      
    # Sinónimos (opcional)      
    "agregar_recordatorio": cmd_add_reminder,      
    "listar_recordatorios": cmd_get_reminders,      
    "actualizar_recordatorio": cmd_update_reminder,      
    "eliminar_recordatorio": cmd_remove_reminder,      
      
    # ——— Apps / web      
    "open_application": open_application,      
    "close_application": close_application,      
    "try_web_fallback": try_web_fallback,      
    "search_google": search_google,      
    "search_youtube": search_youtube,      
    "search": search_google,
    "browse": open_url_in_browser,
    "execute_autonomous_plan": execute_autonomous_plan,
      
    # ——— Sistema      
    "shutdown": shutdown,      
    "restart": restart,      
    "suspend": suspend,      
    "diagnose_system_performance": diagnose_system_performance,      
    "check_system_services": check_system_services,      
    "restart_critical_services": restart_critical_services,      
    "clean_temp_files": clean_temp_files,      
    "flush_dns": flush_dns,      
    "network_reset": network_reset,      
    "check_disk_space": check_disk_space,      
    "system_file_check": system_file_check,  
  
    # ——— Análisis de archivos  
    # análisis rápido local (solo métricas + preview)
    "analyze_file": analyze_file,
    # análisis completo: usa analyze_file + _call_ron_api_feedback para generar feedback técnico
    "analyze_local_file": cmd_analyze_local_file,  
      
    # ——— Comandos Básicos Nuevos      
    "set_volume": set_volume,      
    "create_file": create_file,      
    "create_folder": create_folder,      
    "move_file": move_file,      
    "copy_file": copy_file,      
    "create_shortcut": create_shortcut,      
    "delete_file": delete_file,      
    "list_files": list_files,  
    "list_directory_detailed": list_directory_detailed,
    "read_file": read_file,
    "append_to_file": append_to_file,
    "search_file": search_file,  
    "bulk_file_analysis": bulk_file_analysis,
    "get_standard_path": get_standard_path,
      
    # ——— Utilidad      
    "get_weather": get_weather,    
    "duck_other_applications": duck_other_applications,    
    "restore_application_volumes": restore_application_volumes,
    
    # ——— Audio Configuration
    "get_audio_devices": cmd_get_audio_devices,
    "set_audio_device": cmd_set_audio_device,
}    
  
def run_command(cmd_name: str, params: dict | None = None, ctx: dict | None = None) -> dict:    
    """    
    Ejecuta un comando del registry y normaliza el resultado.    
    - Siempre devuelve un dict con {ok: bool, ...}    
    - Detecta handlers estilo (params, ctx) por nombre de parámetros, no por cantidad.    
    - Filtra kwargs para funciones normales según su firma.  
    - Inyecta progress_callback desde ctx si el comando lo soporta.  
    """    
    import inspect  
      
    params = params or {}    
    ctx = ctx or {}    
    fn = COMMANDS.get(cmd_name)    
    if not fn:    
        return {"ok": False, "error": f"Comando desconocido: {cmd_name}"}    
    
    try:    
        sig = inspect.signature(fn)    
        arg_names = [p.name for p in sig.parameters.values()]    
          
        # Extraer progress_callback del contexto si existe  
        progress_callback = ctx.get('progress_callback')  
    
        # Handler estilo comandos: def cmd_x(params, ctx)    
        if len(arg_names) >= 2 and arg_names[0] == "params" and arg_names[1] == "ctx":    
            result = fn(params, ctx)    
        else:    
            # Función "normal": ajustamos kwargs a su firma    
            allowed = set(arg_names)    
            filtered = {k: v for k, v in (params or {}).items() if k in allowed}    
              
            # Si el comando soporta progress_callback, inyectarlo  
            if 'progress_callback' in allowed and progress_callback:  
                filtered['progress_callback'] = progress_callback  
    
            if len(arg_names) == 0:    
                result = fn()    
            else:    
                result = fn(**filtered)    
    
        # Normalización de salida    
        if isinstance(result, str):    
            return {"ok": True, "message": result}    
        if isinstance(result, dict):    
            return {"ok": result.get("ok", True), **result}    
        return {"ok": True, "result": result}    
    
    except Exception as e:    
        logger.exception(f"Error ejecutando comando '{cmd_name}'")    
        return {"ok": False, "error": str(e)}
