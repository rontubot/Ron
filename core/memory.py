import os    
import json    
import requests    
import base64    
import socket
import getpass    
import platform    
import re    
from datetime import datetime    
    
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

def load_memory(username: str):
    _require_username(username)
    return load_user_memory(username)

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
    _require_username(username)
    mem = load_user_memory(username)
    if "recordatorios" not in mem or not isinstance(mem.get("recordatorios"), dict):
        mem["recordatorios"] = {}

    parts = activity.split(":", 1)
    title = parts[0].strip().lower()
    description = parts[1].strip() if len(parts) > 1 else "(Sin descripción)"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mem["recordatorios"][title] = {
        "description": description,
        "created": timestamp
    }

    save_user_memory(username, mem)
    return f"Recordatorio agregado: {title} - {description}."

def get_reminders(username: str):
    _require_username(username)
    mem = load_user_memory(username)
    recordatorios = mem.get("recordatorios", {})
    if recordatorios:
        result = "Tus recordatorios son:\\n"
        for title, data in recordatorios.items():
            if isinstance(data, dict):
                result += f"- {title}: {data.get('description','(sin descripción)')} (creado: {data.get('created','fecha desconocida')})\\n"
            else:
                result += f"- {title}: {data}\\n"  # compat formato viejo
        return result
    return "No tienes recordatorios pendientes."

def remove_reminder(username: str, activity: str):
    _require_username(username)
    mem = load_user_memory(username)
    recordatorios = mem.get("recordatorios", {})
    title = activity.strip().lower()
    matches = [k for k in recordatorios if title in k]
    if len(matches) == 1:
        del recordatorios[matches[0]]
        mem["recordatorios"] = recordatorios
        save_user_memory(username, mem)
        return f"Recordatorio '{matches[0]}' eliminado."
    elif len(matches) > 1:
        return "Hay múltiples recordatorios similares. Dime el título exacto."
    return "No encontré un recordatorio con ese título."

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
