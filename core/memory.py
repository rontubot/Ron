import os    
import json    
import requests    
import base64    
import socket
import getpass    
import platform    
import re    
import uuid
from datetime import datetime, timedelta    
# === Helpers de nombre preferido para cada usuario ===
from datetime import datetime as _dt
import re as _re
from pathlib import Path as _Path
import os as _os
import logging, time, uuid, base64, requests, json
from core.location import get_now_localized
log = logging.getLogger(__name__)

# 🔹 Detect Electron tasks path automatically for desktop app stability
if not os.getenv("RON_TASKS_PATH"):
    _app_data = os.getenv("APPDATA")
    if _app_data:
        _path = os.path.join(_app_data, "ron-web-app", "tasks.json")
        if os.path.exists(_path):
            os.environ["RON_TASKS_PATH"] = _path
            log.info(f"🔗 RON_TASKS_PATH auto-detected: {_path}")


# Configuración unificada para usar el mismo repositorio para lectura y escritura    
GITHUB_USERNAME = "rontubot"    
REPO_NAME = "ron-memory-store"    
BRANCH = "main"    
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"    
ENABLE_GITHUB_LOGIN = os.getenv("ENABLE_GITHUB_LOGIN", "false").lower() == "true"
GITHUB_TOKEN_ENV = os.getenv("GITHUB_TOKEN", "").strip()
    
   
    
def _use_github() -> bool:
    """
    Solo usamos GitHub si el feature está habilitado y hay un token en env.
    Evita red e impide timeouts si no hay configuración correcta.
    """
    return ENABLE_GITHUB_LOGIN and bool(GITHUB_TOKEN_ENV)

def get_github_token():  
    """  
    Obtiene el token de GitHub:  
    1. Primero intenta desde variable de entorno (si corre en Railway)  
    2. Si no, intenta desde el endpoint de Railway (si corre localmente)  
    """  
    # Primero intentar desde variable de entorno (Railway)  
    token = os.getenv("GITHUB_TOKEN")  
    if token:  
        return token.strip()  
      
    # Si no hay variable local, intentar endpoint de Railway (Ron 24/7)  
    try:  
        r = requests.get("https://ron-production.up.railway.app/github-token", timeout=30)  
        if r.status_code == 200:  
            return r.text.strip()  
    except Exception as e:  
        print(f"⚠️ Error obteniendo token de GitHub: {e}")  
      
    return None
    
def get_memory_file_path():
    raise RuntimeError("get_memory_file_path() está deprecada: usar memory/users/{username}.json via load_user_memory/save_user_memory")   
  
# FUNCIONES DE MEMORIA POR USUARIO (movidas desde api.py)  
def load_user_memory(username: str):  
    """Carga la memoria específica del usuario"""  
    token = get_github_token()  
    if not token:  
        return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}  
      
    file_path = f"memory/users/{username}.json"  
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}?ref=main"  
    headers = {  
        "Authorization": f"token {token}",  
        "Accept": "application/vnd.github.v3.raw"  
    }  
      
    try:  
        r = requests.get(url, headers=headers, timeout=15)  
        if r.status_code == 200:  
            return json.loads(r.content)  
        elif r.status_code == 404:  
            return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}  
    except Exception as e:  
        print(f"Error cargando memoria de usuario: {e}")  
      
    return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}



# === RECORDATORIOS: STORAGE LOCAL POR USUARIO ================================

def _now(username: str | None = None) -> str:
    tz = "UTC"
    if username:
        # Intentamos obtener la zona horaria del perfil del usuario
        try:
            from core.profile import get_or_init_profile
            # load_user_memory ya está disponible en este módulo
            mem = load_user_memory(username)
            prof = get_or_init_profile(mem)
            tz = prof.get("timezone", "UTC")
        except:
            pass
    
    return get_now_localized(tz).strftime("%Y-%m-%d %H:%M:%S")


def _reminders_base_dir() -> str:
    """
    Carpeta base donde se guardan los recordatorios locales.
    En desktop termina algo así como:
    C:/Users/LMAR/.ron_desktop/reminders
    """
    home = os.path.expanduser("~")
    base = os.path.join(home, ".ron_desktop", "reminders")
    os.makedirs(base, exist_ok=True)
    return base


def _reminders_file(username: str) -> str:
    """
    JSON por usuario para recordatorios.
    Usa resolve_username para que el nombre sea seguro como filename.
    """
    uname = resolve_username(username)
    return os.path.join(_reminders_base_dir(), f"{uname}.json")


def _load_electron_tasks():
    """
    Lee y mapea las tareas de Electron (tasks.json) al formato de recordatorios de Python.
    Esto permite que la voz y la UI compartan la misma fuente de verdad.
    """
    path = os.getenv("RON_TASKS_PATH")
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        
        mapped = []
        for t in data:
            # Solo nos interesan recordatorios
            if t.get("kind") != "reminder":
                continue
            
            # Mapeo de campos
            due_at = t.get("due_at") # ISO
            d_date, d_time = None, None
            if due_at:
                try:
                    # '2025-12-25T15:00:00.000Z' o similar
                    # datetime.fromisoformat maneja el formato Z en Python 3.11+
                    # Para compatibilidad, reemplazamos Z por +00:00
                    clean_iso = due_at.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(clean_iso)
                    d_date = dt.strftime("%Y-%m-%d")
                    d_time = dt.strftime("%H:%M")
                except:
                    pass
            
            mapped.append({
                "id": t.get("id"),
                "title": t.get("description", "Recordatorio"),
                "description": t.get("notes") or "", 
                "category": t.get("category", "General"),
                "status": t.get("status", "todo"),
                "due_date": d_date,
                "due_time": d_time,
                "recurrence": t.get("recurrence"),
                "days_of_week": t.get("daysOfWeek") or [],
                "color": t.get("color") or "#00f3ff",
                "priority": t.get("priority") or 1,
                "remind_every_value": t.get("remindEveryValue") or 0,
                "remind_every_unit": t.get("remindEveryUnit") or "hours",
                "created_at": t.get("created_at")
            })
        return mapped
    except Exception as e:
        log.error(f"Error cargando tareas de Electron: {e}")
        return []


def _save_electron_tasks(items: list[dict]):
    """
    Guarda los recordatorios de vuelta en tasks.json de Electron.
    Mantiene los otros tipos de tareas (no-recordatorios) intactos.
    """
    path = os.getenv("RON_TASKS_PATH")
    if not path or not os.path.exists(path):
        return False
    try:
        # 1. Cargar datos actuales
        with open(path, "r", encoding="utf-8") as f:
            all_data = json.load(f)
        if not isinstance(all_data, list):
            all_data = []
            
        # 2. Filtrar lo que NO es recordatorio
        non_reminders = [t for t in all_data if t.get("kind") != "reminder"]
        
        # 3. Mapear items de Python -> Electron
        new_electron_items = []
        for r in items:
            # Reconstruir due_at (ISO)
            due_at = None
            if r.get("due_date"):
                d = r["due_date"]
                t = r.get("due_time") or "00:00"
                due_at = f"{d}T{t}:00" # Formato simple compatible con Electron
                
            e_item = {
                "id": r.get("id"),
                "user": "default",
                "kind": "reminder",
                "description": r.get("title", "Recordatorio"),
                "source": "local",
                "status": r.get("status", "queued"),
                "progress": 100,
                "params": {},
                "result_summary": None,
                "error": None,
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at") or r.get("created_at"),
                "due_at": due_at,
                "category": r.get("category", "General"),
                "color": r.get("color", "#00f3ff"),
                "daysOfWeek": r.get("days_of_week") or [],
                "notes": r.get("description") or "",
                "priority": r.get("priority") or 1,
                "remindEveryValue": r.get("remind_every_value") or 0,
                "remindEveryUnit": r.get("remind_every_unit") or "hours",
                "recurrence": r.get("recurrence"),
                "original_task_id": None
            }
            # Preservar position si existía en Electron previamente? 
            # Es difícil sin mapear IDs primero, pero podemos intentar buscarlo en original
            old_match = next((x for x in all_data if x.get("id") == r.get("id")), None)
            if old_match and "position" in old_match:
                e_item["position"] = old_match["position"]
                
            new_electron_items.append(e_item)
            
        final_list = non_reminders + new_electron_items
        
        # 4. Guardar
        with open(path, "w", encoding="utf-8") as f:
            json.dump(final_list, f, ensure_ascii=False, indent=2)
        log.info(f"✅ Electron tasks.json sincronizado ({len(new_electron_items)} recordatorios)")
        return True
    except Exception as e:
        log.error(f"Error sincronizando con Electron: {e}")
        return False


def _load_reminders(username: str) -> list[dict]:
    """
    Carga recordatorios desde GitHub (primaria) con fallback a local.
    """
    username = resolve_username(username)
    
    # 🔹 SI ESTAMOS EN ELECTRON (Escritorio), la fuente de verdad es tasks.json
    electron_tasks = _load_electron_tasks()
    if electron_tasks:
        log.info(f"✅ Usando {len(electron_tasks)} recordatorios de Electron (tasks.json)")
        return electron_tasks

    # 🔹 Intentar cargar desde GitHub primero (Flujo móvil/web puro)
    token = get_github_token()
    if token:
        try:
            file_path = f"reminders/{username}.json"
            url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}?ref=main"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.raw"
            }
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = json.loads(r.content)
                if isinstance(data, list):
                    log.info(f"✅ Recordatorios cargados desde GitHub para {username}")
                    return data
            elif r.status_code == 404:
                # Archivo no existe en GitHub, retornar vacío
                log.info(f"📝 No hay recordatorios en GitHub para {username}")
                return []
        except Exception as e:
            log.warning(f"⚠️ Error cargando recordatorios desde GitHub para {username}: {e}")
            # Si hay un error de red pero queremos modo estricto, mejor no usar local
            if os.getenv("RON_DISABLE_LOCAL_MEMORY") == "1":
                return []
    
    # 🔹 Fallback: cargar desde archivo local (SOLO SI NO ESTA DESHABILITADO)
    if os.getenv("RON_DISABLE_LOCAL_MEMORY") == "1":
        return []

    path = _reminders_file(username)
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            log.info(f"✅ Recordatorios cargados desde archivo local para {username}")
            return data
        return []
    except Exception as e:
        log.warning(f"⚠️ No se pudieron cargar recordatorios desde {path}: {e}")
        return []


def _save_reminders(username: str, items: list[dict]) -> bool:
    """
    Guarda recordatorios en GitHub (primaria) y local (backup).
    Esto mantiene los recordatorios sincronizados entre dispositivos.
    """
    username = resolve_username(username)
    success_github = False
    success_local = False
    
    # 🔹 Guardar en GitHub primero
    token = get_github_token()
    if token:
        try:
            file_path = f"reminders/{username}.json"
            url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}"
            
            headers = {"Authorization": f"token {token}"}
            
            # Obtener SHA del archivo existente
            existing_file = requests.get(url, headers=headers, timeout=10)
            sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None
            
            # Preparar datos
            content = base64.b64encode(json.dumps(items, ensure_ascii=False, indent=2).encode()).decode()
            data = {
                "message": f"Actualizar recordatorios de {username}",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha
            
            # Subir a GitHub
            response = requests.put(url, json=data, headers=headers, timeout=15)
            if response.status_code in [200, 201]:
                log.info(f"✅ Recordatorios guardados en GitHub para {username}")
                success_github = True
            else:
                log.warning(f"⚠️ Error guardando en GitHub: {response.status_code}")
        except Exception as e:
            log.warning(f"⚠️ Error guardando recordatorios en GitHub para {username}: {e}")
    
    # 🔹 Guardar copia local como backup (SOLO SI NO ESTA DESHABILITADO)
    if os.getenv("RON_DISABLE_LOCAL_MEMORY") == "1":
        return success_github

    path = _reminders_file(username)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        log.info(f"✅ Recordatorios guardados localmente para {username}")
        success_local = True
    except Exception as e:
        log.warning(f"⚠️ No se pudieron guardar recordatorios en {path}: {e}")
    
    # 🔹 SI ESTAMOS EN ELECTRON, sincronizar también tasks.json
    if os.getenv("RON_TASKS_PATH"):
        _save_electron_tasks(items)

    # Retornar True si al menos uno tuvo éxito
    return success_github or success_local


# Compat: API antigua que devolvía un doc con 'reminders'
def load_user_reminders(username: str) -> dict:
    items = _load_reminders(username)
    return {
        "user": username,
        "updated_at": _now(),
        "reminders": items,
    }


def save_user_reminders(username: str, reminders_doc: dict) -> bool:
    """
    Compat: acepta un dict con clave 'reminders' y lo guarda en disco local.
    Ignora GitHub.
    """
    items = reminders_doc.get("reminders", []) if isinstance(reminders_doc, dict) else []
    return _save_reminders(username, items)


def add_reminder_item(
    username: str,
    title: str,
    description: str = "",
    category: str = "inbox",
    status: str = "todo",
    priority: int | str = 1,
    due_date: str | None = None,   # "YYYY-MM-DD"
    due_time: str | None = None,   # "HH:MM"
    tags: list[str] | None = None,
    color: str | None = "#00f3ff",
    days_of_week: list[str] | None = None,
    remind_every_value: int | None = 0,
    remind_every_unit: str | None = "hours",
    recurrence: str | None = None
) -> dict:
    """
    Crea y guarda un recordatorio en storage local por usuario.
    NO depende de GitHub.
    """
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)

    item = {
        "id": str(uuid.uuid4()),
        "title": (title or "").strip(),
        "description": (description or "").strip(),
        "category": (category or "inbox").strip().lower(),
        "status": (status or "todo").strip().lower(),
        "priority": priority,
        "due_date": (due_date or None),
        "due_time": (due_time or None),
        "tags": list(tags or []),
        "color": color or "#00f3ff",
        "days_of_week": days_of_week or [],
        "remind_every_value": remind_every_value or 0,
        "remind_every_unit": remind_every_unit or "hours",
        "recurrence": recurrence,
        "created_at": _now(username),
        "updated_at": _now(username),
    }

    items.append(item)
    if not _save_reminders(username, items):
        log.warning("⚠️ No se pudo guardar el recordatorio en disco")

    return item


def add_reminders_batch(username: str, items_params: list[dict]) -> list[dict]:
    """
    Agrega múltiples recordatorios de una vez y guarda una única vez.
    Más eficiente para listas largas (como rutinas diarias).
    """
    username = (username or "default").strip() or "default"
    current_items = _load_reminders(username)
    
    new_items = []
    now_ts = _now(username)
    
    for params in items_params:
        title = (params.get("title") or "").strip()
        description = (params.get("description") or "").strip()
        category = (params.get("category") or "inbox").strip().lower()
        status = (params.get("status") or "todo").strip().lower()
        priority = params.get("priority") or 1
        due_date = params.get("due_date")
        due_time = params.get("due_time")
        tags = list(params.get("tags") or [])
        color = params.get("color") or "#00f3ff"
        days_of_week = params.get("days_of_week") or []
        remind_every_value = params.get("remind_every_value") or 0
        remind_every_unit = params.get("remind_every_unit") or "hours"
        recurrence = params.get("recurrence")

        item = {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "category": category,
            "status": status,
            "priority": priority,
            "due_date": due_date,
            "due_time": due_time,
            "tags": tags,
            "color": color,
            "days_of_week": days_of_week,
            "remind_every_value": remind_every_value,
            "remind_every_unit": remind_every_unit,
            "recurrence": recurrence,
            "created_at": now_ts,
            "updated_at": now_ts,
        }
        new_items.append(item)
    
    current_items.extend(new_items)
    if not _save_reminders(username, current_items):
        log.warning(f"⚠️ No se pudieron guardar {len(new_items)} recordatorios en disk/cloud")
    
    return new_items


def list_reminders(
    username: str,
    category: str | None = None,
    status: str | None = None
) -> list[dict]:
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)

    if category:
        items = [r for r in items if (r.get("category") or "").lower() == category.lower()]
    if status:
        items = [r for r in items if (r.get("status") or "").lower() == status.lower()]

    # Orden por fecha y prioridad (opcional)
    def _key(r: dict):
        # 0. Posición manual (si existe)
        pos = r.get("position", 999999999)
        # 1. Fecha de vencimiento
        dd = r.get("due_date") or "9999-12-31"
        # 2. Hora
        tt = r.get("due_time") or "23:59"
        # 3. Prioridad
        prio = {"urgent": 0, "high": 1, "normal": 2, "low": 3}.get(
            (r.get("priority") or "normal").lower(), 2
        )
        return (pos, dd, tt, prio)

    return sorted(items, key=_key)


def update_reminder(username: str, reminder_id: str, **fields) -> dict | None:
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)

    allowed = {"title","description","category","status","priority","due_date","due_time","tags","position", "color", "days_of_week", "remind_every_value", "remind_every_unit", "recurrence"}
    updated_item = None

    for idx, r in enumerate(items):
        if r.get("id") == reminder_id:
            for k, v in fields.items():
                if k in allowed and v is not None:
                    r[k] = v
            r["updated_at"] = _now(username)
            items[idx] = r
            updated_item = r
            break

    if not updated_item:
        return None

    if not _save_reminders(username, items):
        log.warning("⚠️ No se pudieron guardar cambios del recordatorio")

    return updated_item


def remove_reminder_item(username: str, reminder_id: str) -> bool:
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)
    new_items = [r for r in items if r.get("id") != reminder_id]

    if len(new_items) == len(items):
        return False

    if not _save_reminders(username, new_items):
        log.warning("⚠️ No se pudo persistir la eliminación del recordatorio")

    return True

def permanent_delete_reminder(username: str, reminder_id: str) -> bool:
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)
    new_items = [r for r in items if r.get("id") != reminder_id]
    if len(new_items) == len(items):
        return False
    return _save_reminders(username, new_items)

def empty_trash_reminders(username: str) -> int:
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)
    new_items = [r for r in items if r.get("status") not in ["archived", "history", "deleted"]]
    count = len(items) - len(new_items)
    if count > 0:
        _save_reminders(username, new_items)
    return count


def find_reminder_by_title(username: str, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    items = _load_reminders(username)
    return [
        r
        for r in items
        if q in (r.get("title", "").lower() + " " + r.get("description", "").lower())
    ]

def _parse_date_robust(date_str: str) -> datetime | None:
    if not date_str: return None
    # Formatos comunes: YYYY-MM-DD, DD/MM/YYYY, D/M/YYYY
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"]
    # Limpiar posibles restos de tiempo si vienen en el mismo string
    clean_date = date_str.split(',')[0].split(' ')[0].strip()
    for fmt in formats:
        try:
            return datetime.strptime(clean_date, fmt)
        except:
            continue
    return None

def archive_expired_reminders(username: str) -> int:
    """Busca recordatorios vencidos y los marca como 'history'."""
    username = resolve_username(username)
    items = _load_reminders(username)
    
    now_dt = get_now_localized("UTC")
    try:
        from core.profile import get_or_init_profile
        mem = load_user_memory(username)
        prof = get_or_init_profile(mem)
        tz = prof.get("timezone", "UTC")
        now_dt = get_now_localized(tz)
    except:
        pass

    now_thresh = now_dt.strftime("%Y-%m-%d %H:%M")
    count = 0
    
    for r in items:
        status = r.get("status")
        if status in ["history", "archived", "deleted", "cancelled"]:
            continue
        
        # Ignorar recurrentes
        rec = r.get("recurrence")
        rev = r.get("remind_every_value")
        dow = r.get("days_of_week")
        if (rec and rec != "none") or (rev and rev > 0) or (dow and len(dow) > 0):
            continue
            
        due_date_str = r.get("due_date")
        due_time_str = r.get("due_time") or "23:59"
        
        if due_date_str:
            dt = _parse_date_robust(due_date_str)
            if dt:
                # Reconstruir due_val en formato ISO para comparación de strings
                # d_parts extraído de dt garantiza YYYY-MM-DD
                due_val = f"{dt.strftime('%Y-%m-%d')} {due_time_str[:5]}"
                
                # NO archivar si es de la categoría "daily" (Día a día)
                if r.get("category") == "daily":
                    continue
                    
                if due_val < now_thresh:
                    r["status"] = "history"
                    r["updated_at"] = now_dt.isoformat()
                    count += 1
                
    if count > 0:
        _save_reminders(username, items)
    return count
                
    if count > 0:
        _save_reminders(username, items)
        log.info(f"📦 Se archivaron {count} recordatorios vencidos para {username}")
    return count

def renew_reminder(username: str, reminder_id: str, new_due_date: str, new_due_time: str = "09:00") -> dict | None:
    """Toma un recordatorio del historial y lo devuelve a 'todo' con nueva fecha."""
    return update_reminder(username, reminder_id, status="todo", category="inbox", due_date=new_due_date, due_time=new_due_time)

def count_archived_reminders(username: str) -> int:
    """Cuenta cuántos recordatorios hay con status 'history'"""
    items = _load_reminders(username)
    return len([r for r in items if r.get("status") == "history"])

def clear_reminder_history(username: str) -> int:
    """Elimina permanentemente todos los recordatorios con status 'history'"""
    username = (username or "default").strip() or "default"
    items = _load_reminders(username)
    new_items = [r for r in items if r.get("status") != "history"]
    count = len(items) - len(new_items)
    if count > 0:
        _save_reminders(username, new_items)
    return count




def save_user_memory(username: str, memory_data: dict):  
    """Guarda la memoria específica del usuario"""  
    token = get_github_token()  
    if not token:  
        return False  
      
    file_path = f"memory/users/{username}.json"  
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}"  
      
    # Obtener SHA del archivo existente  
    headers = {"Authorization": f"token {token}"}  
    existing_file = requests.get(url, headers=headers)  
    sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None  
      
    # Preparar datos para GitHub  
    content = base64.b64encode(json.dumps(memory_data, indent=2).encode()).decode()  
    data = {  
        "message": f"Actualizar memoria de {username}",  
        "content": content,  
        "branch": "main"  
    }  
    if sha:  
        data["sha"] = sha  
      
    try:  
        response = requests.put(url, json=data, headers=headers)  
        return response.status_code in [200, 201]  
    except Exception as e:  
        print(f"Error guardando memoria de usuario: {e}")  
        return False
  
def load_users_from_github():
    """Carga la base de datos de usuarios desde GitHub"""
    if not _use_github():
        return {}

    token = get_github_token()
    if not token:
        return {}

    file_path = "users/users.json"
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3.raw"}

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return json.loads(r.content)
        elif r.status_code == 404:
            return {}
    except Exception as e:
        print(f"Error cargando usuarios: {e}")

    return {}


def save_users_to_github(users_data: dict):
    """Guarda la base de datos de usuarios en GitHub"""
    if not _use_github():
        return False

    token = get_github_token()
    if not token:
        return False

    file_path = "users/users.json"
    url = f"{GITHUB_API_BASE}/{file_path}"

    headers = {"Authorization": f"token {token}"}
    try:
        existing_file = requests.get(url, headers=headers, timeout=10)
        sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None
    except Exception as e:
        print(f"⚠️ No se pudo obtener SHA usuarios: {e}")
        sha = None

    content = base64.b64encode(json.dumps(users_data, indent=2, ensure_ascii=False).encode("utf-8")).decode()
    data = {"message": "Actualizar base de datos de usuarios", "content": content, "branch": BRANCH}
    if sha:
        data["sha"] = sha

    try:
        response = requests.put(url, json=data, headers=headers, timeout=20)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"Error guardando usuarios: {e}")
        return False


        
# ===== LEGACY SHIMS AHORA USER-AWARE =====
# Todas estas funciones piden 'username' y guardan en memory/users/{username}.json
# Si no les pasás username, fallan explícito (para no recrear rutas por dispositivo).


def _sanitized_username(u: str) -> str:
    # Permite letras/números/_/-
    return re.sub(r'[^A-Za-z0-9_\-]', '_', u)



def add_to_memory(username: str, user_text: str, ron_response: str = ""):
    _require_username(username)
    mem = load_user_memory(username) or {}
    conv = mem.get("conversaciones", [])
    conv.append({
        "user": user_text,
        "ron": ron_response if isinstance(ron_response, str) else str(ron_response),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    # Mantén histórico razonable
    mem["conversaciones"] = conv[-100:]
    save_user_memory(username, mem)



def _require_username(username: str):
    if not username or not isinstance(username, str) or not username.strip():
        raise ValueError("username es requerido para operaciones de memoria")

def load_memory(username: str | None = None):
    """
    Compat: si se llama sin username, devolvemos {} (ya no hay memoria global).
    Si se pasa username, devolvemos la memoria del usuario.
    """
    if username:
        _require_username(username)
        return load_user_memory(username)
    return {}

def save_memory_direct(username: str, complete_memory: dict):
    _require_username(username)
    # Guarda el objeto completo, tal cual
    return save_user_memory(username, complete_memory)

def save_memory(username: str, new_memory: dict):
    """
    Mantiene compat de 'save_memory' pero ahora mergea SOLO 'datos' y 'recordatorios'
    dentro de la memoria del usuario.
    """
    _require_username(username)
    existing = load_user_memory(username)

    # Merge 'datos'
    if "datos" in new_memory:
        existing.setdefault("datos", {})
        existing["datos"].update(new_memory["datos"])

    # Merge 'recordatorios' (diccionario)
    if "recordatorios" in new_memory:
        existing.setdefault("recordatorios", {})
        existing["recordatorios"].update(new_memory["recordatorios"])

    return save_user_memory(username, existing)



def should_use_name(profile) -> bool:
    if not profile:
        return False
    # reglas: primera vez en la sesión o si pasó mucho tiempo
    last_used = profile.get("name_last_used_at")
    now = datetime.utcnow()
    if not last_used:
        return True  # primera vez
    # usa el nombre si pasó más de 30 min
    return (now - datetime.fromisoformat(last_used)) > timedelta(minutes=30)

def mark_name_used(profile):
    profile["name_last_used_at"] = datetime.utcnow().isoformat()
    return profile

def _load_profile(username: str):
    data = load_user_memory(username) or {}
    prof = data.get("profile") or {}
    return data, prof

def _save_profile(username: str, data: dict, prof: dict):
    data["profile"] = prof
    save_user_memory(username, data)

def mark_name_used_for(username: str, profile: dict):
    profile["name_last_used_at"] = _dt.utcnow().isoformat()
    data = load_user_memory(username) or {}
    data["profile"] = profile
    save_user_memory(username, data)
    return profile

def maybe_address(text: str, name: str | None, profile: dict | None, *, username: str | None = None) -> str:
    if not name or not profile:
        return text
    if should_use_name(profile):
        lowered = text.strip().lower()
        starts_with_saludo = lowered.startswith(("hola", "buenas", "hey"))
        if not starts_with_saludo:
            text = f"{name}, {text}"
        # ⬇️ Persistimos la marca de uso si tenemos username
        if username:
            mark_name_used_for(username, profile)
        else:
            profile["name_last_used_at"] = _dt.utcnow().isoformat()
    return text



def save_user_data(username: str, key, value):
    _require_username(username)
    mem = load_user_memory(username)
    mem.setdefault("datos", {})
    if key != "creador":
        mem["datos"][key] = value
        save_user_memory(username, mem)


def get_user_data(username: str, key):
    _require_username(username)
    mem = load_user_memory(username)
    return mem.get("datos", {}).get(key, None)

def add_reminder(username: str, activity: str):
    """
    Compat legado: activity puede venir 'Titulo: desc'.
    """
    _require_username(username)
    parts = (activity or "").split(":", 1)
    title = parts[0].strip()
    description = parts[1].strip() if len(parts) > 1 else ""
    item = add_reminder_item(username, title=title, description=description)
    return f"Recordatorio agregado: {item['title']} (id: {item['id']})."


def get_reminders(username: str, category: str | None = None):
    _require_username(username)
    items = list_reminders(username, category=category)
    if not items:
        return "No tienes recordatorios pendientes."
    out = ["Tus recordatorios:\n"]
    for r in items:
        dd = f"{r.get('due_date','')}" + (f" {r.get('due_time','')}" if r.get('due_time') else "")
        meta = " • ".join([
            r.get("category","inbox"),
            r.get("status","todo"),
            r.get("priority","normal"),
        ])
        out.append(f"- [{r['id'][:8]}] {r['title']} {f'({dd})' if dd.strip() else ''} — {meta}")
    return "\n".join(out)


def remove_reminder(username: str, reminder_id: str):
    _require_username(username)
    ok = remove_reminder_item(username, reminder_id)
    return "Recordatorio eliminado." if ok else "No encontré un recordatorio con ese ID."



def clean_duplicates(username: str):
    """
    Limpia duplicados en conversaciones del USUARIO.
    Duplicado = mismo (user, ron, timestamp). Mantiene orden e historia reciente.
    """
    _require_username(username)
    mem = load_user_memory(username)
    conversaciones = mem.get("conversaciones", [])
    seen = set()
    cleaned = []
    for conv in conversaciones:
        key = (conv.get("user", ""), conv.get("ron", ""), conv.get("timestamp", ""))
        if key not in seen:
            seen.add(key)
            cleaned.append(conv)
    mem["conversaciones"] = cleaned
    save_user_memory(username, mem)
    print(f"Limpieza completada: {len(conversaciones)} -> {len(cleaned)} conversaciones")
    return len(cleaned)

# Compat perfecto con código antiguo que llamaba save_to_memory(...)
def save_to_memory(username: str, *args, **kwargs):
    return add_to_memory(username, *args, **kwargs)





# Asegura la carpeta de memorias por usuario (si aún no la tienes arriba)
try:
    BASE_DIR = _Path(__file__).resolve().parent.parent
    MEMORY_DIR = BASE_DIR / "memory" / "users"
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def resolve_username(username: str | None) -> str:
    """
    Normaliza el username para evitar duplicados y mapear alias como imar -> lmar.
    """
    candidate = (
        (username or "").strip()
        or _os.getenv("RON_USERNAME", "").strip()
        or _os.getenv("USERNAME", "").strip()
    )
    if not candidate:
        return "default"
    
    u = candidate.lower()
    # Mapeo de alias conocidos
    if u in ["imar", "luis", "luismishit", "lmar"]:
        return "lmar"
    
    # Fallback to original logic for sanitization if not an alias
    # This part was missing in the instruction's provided code,
    # but is crucial for safe filenames and general username resolution.
    # We reconstruct it based on the original function's intent.
    if not u: # If after lowercasing and stripping, it's empty
        try:
            u = (_os.getlogin() or "").strip().lower()
        except Exception:
            u = "default"
    
    # normaliza: minúsculas y solo caracteres seguros para filename
    candidate = _re.sub(r"[^a-z0-9._-]+", "_", u)
    return candidate or "default"

def _user_path(username: str) -> _Path:
    """Path del archivo de memoria por usuario."""
    uname = resolve_username(username)
    return (MEMORY_DIR / f"{uname}.json")

def get_display_name(username: str) -> str | None:
    """
    Lee el 'display_name' desde el perfil del usuario en su archivo de memoria.
    Busca en profile.display_name y variantes por compatibilidad.
    """
    try:
        data = load_user_memory(username) or {}
        prof = data.get("profile", {}) or {}
        return (
            prof.get("display_name")
            or (prof.get("traits", {}) or {}).get("display_name")
            or (prof.get("preferences", {}) or {}).get("display_name")
        )
    except Exception:
        return None

def set_display_name(username: str, display_name: str):
    """
    Guarda/actualiza el 'display_name' del usuario en su archivo de memoria.
    """
    name = (display_name or "").strip()
    if not name:
        return
    data = load_user_memory(username) or {}
    prof = data.get("profile") or {}
    prof["display_name"] = name
    prof["updated_at"] = _dt.utcnow().isoformat()
    data["profile"] = prof
    save_user_memory(username, data)

def maybe_extract_name_from_text(text: str) -> str | None:
    """
    Heurística simple para detectar: 'me llamo X', 'mi nombre es X', 'soy X'.
    Devuelve un nombre capitalizado o None.
    """
    if not text:
        return None
    t = text.strip()
    patt = _re.compile(
        r"(?:me\s+llamo|mi\s+nombre\s+es|soy)\s+([A-Za-zÁÉÍÓÚÑÜáéíóúñü][^\d,.;:!?\n]{1,50})",
        _re.IGNORECASE,
    )
    m = patt.search(t)
    if not m:
        return None
    name = m.group(1).strip()
    # limpia signos finales y espacios múltiples
    name = _re.sub(r"[\.\!\?,;:]+$", "", name).strip()
    # capitaliza suavemente
    name = " ".join(p.capitalize() for p in name.split())
    return name if name else None
