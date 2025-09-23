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
    
# Configuración unificada para usar el mismo repositorio para lectura y escritura    
GITHUB_USERNAME = "rontubot"    
REPO_NAME = "ron-memory-store"    
BRANCH = "main"    
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"    
    
   
    
def get_github_token():    
    try:    
        r = requests.get("https://ron-production.up.railway.app/github-token", timeout=10)    
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

    uname = _sanitized_username(username)
    file_path = f"memory/users/{uname}.json"
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return json.loads(r.content)
        elif r.status_code == 404:
            return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}
        else:
            print(f"⚠️ Error al cargar memoria ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        print(f"Error cargando memoria de usuario: {e}")

    return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}


REMINDERS_DIR = "recordatorios"

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _reminders_path_for(username: str) -> str:
    uname = _sanitized_username(username)
    return f"{REMINDERS_DIR}/{uname}.json"

def load_user_reminders(username: str) -> dict:
    token = get_github_token()
    if not token:
        return {"user": username, "updated_at": _now(), "reminders": []}

    file_path = _reminders_path_for(username)
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = json.loads(r.content)
            # sanity
            data.setdefault("user", username)
            data.setdefault("updated_at", _now())
            data.setdefault("reminders", [])
            return data
        elif r.status_code == 404:
            return {"user": username, "updated_at": _now(), "reminders": []}
        else:
            print(f"⚠️ Error load_user_reminders({r.status_code}): {r.text[:120]}")
    except Exception as e:
        print(f"Error cargando recordatorios: {e}")
    return {"user": username, "updated_at": _now(), "reminders": []}

def save_user_reminders(username: str, reminders_doc: dict) -> bool:
    token = get_github_token()
    if not token:
        return False

    reminders_doc = reminders_doc or {}
    reminders_doc["user"] = username
    reminders_doc["updated_at"] = _now()
    reminders_doc.setdefault("reminders", [])

    file_path = _reminders_path_for(username)
    url = f"{GITHUB_API_BASE}/{file_path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    # obtener sha si existe
    sha = None
    try:
        existing = requests.get(url, headers=headers, timeout=10)
        if existing.status_code == 200:
            sha = existing.json().get("sha")
    except Exception as e:
        print(f"⚠️ No se pudo obtener SHA recordatorios: {e}")

    content = base64.b64encode(
        json.dumps(reminders_doc, indent=2, ensure_ascii=False).encode("utf-8")
    ).decode()

    payload = {"message": f"Actualizar recordatorios de {username}", "content": content, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, json=payload, headers=headers, timeout=20)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"Error guardando recordatorios: {e}")
        return False


def add_reminder_item(
    username: str,
    title: str,
    description: str = "",
    category: str = "inbox",
    status: str = "todo",
    priority: str = "normal",
    due_date: str | None = None,   # "YYYY-MM-DD"
    due_time: str | None = None,   # "HH:MM"
    tags: list[str] | None = None,
) -> dict:
    """
    Crea y guarda un recordatorio; devuelve el item creado.
    """
    doc = load_user_reminders(username)
    item = {
        "id": str(uuid.uuid4()),
        "title": (title or "").strip(),
        "description": (description or "").strip(),
        "category": (category or "inbox").strip().lower(),
        "status": (status or "todo").strip().lower(),
        "priority": (priority or "normal").strip().lower(),
        "due_date": (due_date or None),
        "due_time": (due_time or None),
        "tags": list(tags or []),
        "created_at": _now(),
        "updated_at": _now(),
    }
    doc["reminders"].append(item)
    ok = save_user_reminders(username, doc)
    if not ok:
        print("⚠️ No se pudo guardar el recordatorio")
    return item

def list_reminders(username: str, category: str | None = None, status: str | None = None) -> list[dict]:
    doc = load_user_reminders(username)
    items = doc.get("reminders", [])
    if category:
        items = [r for r in items if (r.get("category") or "").lower() == category.lower()]
    if status:
        items = [r for r in items if (r.get("status") or "").lower() == status.lower()]
    # opcional: orden por due_date/due_time y luego prioridad
    def _key(r):
        dd = r.get("due_date") or "9999-12-31"
        tt = r.get("due_time") or "23:59"
        prio = {"urgent": 0, "high": 1, "normal": 2, "low": 3}.get((r.get("priority") or "normal").lower(), 2)
        return (dd, tt, prio)
    return sorted(items, key=_key)

def update_reminder(username: str, reminder_id: str, **fields) -> dict | None:
    doc = load_user_reminders(username)
    items = doc.get("reminders", [])
    for r in items:
        if r.get("id") == reminder_id:
            # solo campos permitidos
            allowed = {"title","description","category","status","priority","due_date","due_time","tags"}
            for k, v in fields.items():
                if k in allowed:
                    r[k] = v
            r["updated_at"] = _now()
            save_user_reminders(username, doc)
            return r
    return None


def find_reminder_by_title(username: str, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    items = load_user_reminders(username).get("reminders", [])
    return [r for r in items if q in (r.get("title","").lower() + " " + r.get("description","").lower())]




def save_user_memory(username: str, memory_data: dict):
    """Guarda la memoria específica del usuario"""
    token = get_github_token()
    if not token:
        return False

    uname = _sanitized_username(username)
    file_path = f"memory/users/{uname}.json"
    url = f"{GITHUB_API_BASE}/{file_path}"

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    # Obtener SHA del archivo existente (si está)
    sha = None
    try:
        existing_file = requests.get(url, headers=headers, timeout=10)
        if existing_file.status_code == 200:
            data = existing_file.json()
            sha = data.get("sha")
    except Exception as e:
        print(f"⚠️ No se pudo obtener SHA existente: {e}")

    # Preparar contenido con UTF-8 y sin escapar ASCII
    content = base64.b64encode(
        json.dumps(memory_data, indent=2, ensure_ascii=False).encode("utf-8")
    ).decode()

    payload = {
        "message": f"Actualizar memoria de {username}",
        "content": content,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        response = requests.put(url, json=payload, headers=headers, timeout=20)
        return response.status_code in (200, 201)
    except Exception as e:
        print(f"Error guardando memoria de usuario: {e}")
        return False
        
  
def load_users_from_github():  
    """Carga la base de datos de usuarios desde GitHub"""  
    token = get_github_token()  
    if not token:  
        return {}  
      
    file_path = "users/users.json"  
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH}"  
    headers = {  
        "Authorization": f"token {token}",  
        "Accept": "application/vnd.github.v3.raw"  
    }  
      
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
    token = get_github_token()  
    if not token:  
        return False  
      
    file_path = "users/users.json"  
    url = f"{GITHUB_API_BASE}/{file_path}"  
      
    # Obtener SHA del archivo existente  
    headers = {"Authorization": f"token {token}"}  
    existing_file = requests.get(url, headers=headers)  
    sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None  
      
    # Preparar datos para GitHub  
    content = base64.b64encode(json.dumps(users_data, indent=2).encode()).decode()  
    data = {  
        "message": "Actualizar base de datos de usuarios",  
        "content": content,  
        "branch": BRANCH  
    }  
    if sha:  
        data["sha"] = sha  
      
    try:  
        response = requests.put(url, json=data, headers=headers)  
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
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        meta = " • ".join([r.get("category","inbox"), r.get("status","todo"), r.get("priority","normal")])
        out.append(f"- [{r['id'][:8]}] {r['title']} {f'({dd})' if dd.strip() else ''} — {meta}")
    return "\n".join(out)

def remove_reminder_item(username: str, reminder_id: str) -> bool:
    doc = load_user_reminders(username)
    items = doc.get("reminders", [])
    new_items = [r for r in items if r.get("id") != reminder_id]
    if len(new_items) == len(items):
        return False
    doc["reminders"] = new_items
    return save_user_reminders(username, doc)

# Wrapper legacy para mantener compat en otros módulos
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
    Centraliza cómo resolvemos el username para filename seguro.
    Si ya tienes otra versión en este módulo, puedes omitir esta
    o dejar esta (son equivalentes).
    """
    candidate = (
        (username or "").strip()
        or _os.getenv("RON_USERNAME", "").strip()
        or _os.getenv("USERNAME", "").strip()
        or _os.getenv("USER", "").strip()
    )
    if not candidate:
        try:
            candidate = (_os.getlogin() or "").strip()
        except Exception:
            candidate = "default"
    # normaliza: minúsculas y solo caracteres seguros para filename
    candidate = candidate.lower()
    candidate = _re.sub(r"[^a-z0-9._-]+", "_", candidate)
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
