import os
import json
import requests
import base64
import socket

GITHUB_USERNAME = "rontubot"
REPO_NAME = "Ron"
BRANCH = "main"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents/memory"

def get_device_id():
    device_id_file = "device_id.txt"
    if os.path.exists(device_id_file):
        with open(device_id_file, "r") as f:
            return f.read().strip()
    else:
        import uuid
        device_id = str(uuid.uuid4())
        with open(device_id_file, "w") as f:
            f.write(device_id)
        return device_id


def get_public_ip():
    try:
        return requests.get("https://api.ipify.org").text.strip()
    except:
        return "unknown"

def get_github_token():
    try:
        r = requests.get("https://ron-production.up.railway.app/github-token")
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return None

def get_memory_file_path():
    return f"{get_public_ip()}.json"



def load_memory():
    token = get_github_token()
    if not token:
        return {"datos": {"ron_nombre": "Ron", "creador": "Luis"}, "conversaciones": []}

    file_path = get_memory_file_path()
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw"
    }

    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        try:
            return json.loads(r.content)
        except:
            pass

    return {"datos": {"ron_nombre": "Ron", "creador": "Luis"}, "conversaciones": []}



def save_memory(memory):
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN no configurado")
        return

    device_id = get_device_id()
    file_path = f"memory/{get_memory_file_path()}"
    device_id = file_path.split("/")[-1].replace(".json", "")
    repo = "rontubot/ron-memory-store"
    branch = "main"

    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    
    # Paso 1: Ver si ya existe el archivo (para obtener el SHA si hace falta)
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    sha = None
    try:
        r = requests.get(api_url, headers=headers)
        if r.status_code == 200:
            sha = r.json()["sha"]
    except:
        pass

    # Paso 2: Codifica el nuevo contenido
    content_encoded = base64.b64encode(json.dumps(memory, indent=4, ensure_ascii=False).encode()).decode()

    # Paso 3: Crea o actualiza el archivo
    payload = {
        "message": f"update memory for {device_id}",
        "content": content_encoded,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(api_url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        print(f"✅ Memoria de {device_id} guardada en GitHub")

    else:
        print(f"❌ Error al guardar memoria: {response.status_code} - {response.text}")


def save_user_data(key, value):
    memory = load_memory()
    if key != "creador":
        memory["datos"][key] = value
        save_memory(memory)

def get_user_data(key):
    memory = load_memory()
    return memory["datos"].get(key, None)

def add_to_memory(user_text, ron_response):
    memory = load_memory()

    if "conversaciones" not in memory:
        memory["conversaciones"] = []

    # Asegurar que no se borre lo anterior
    memory["conversaciones"].append({"user": user_text, "ron": ron_response})

    # Puedes cambiar el límite si quieres más memoria persistente
    memory["conversaciones"] = memory["conversaciones"][-100:]

    save_memory(memory)

def add_reminder(activity):
    memory = load_memory()
    if "recordatorios" not in memory or not isinstance(memory.get("recordatorios"), dict):
        memory["recordatorios"] = {}
    parts = activity.split(":", 1)
    title = parts[0].strip().lower()
    description = parts[1].strip() if len(parts) > 1 else "(Sin descripción)"
    memory["recordatorios"][title] = description
    save_memory(memory)
    return f"Recordatorio agregado: {title} - {description}."

def get_reminders():
    memory = load_memory()
    recordatorios = memory.get("recordatorios", {})
    if recordatorios:
        return "Tus recordatorios son:\n" + "\n".join(f"- {k}: {v}" for k, v in recordatorios.items())
    return "No tienes recordatorios pendientes."

def remove_reminder(activity):
    memory = load_memory()
    recordatorios = memory.get("recordatorios", {})
    title = activity.strip().lower()
    matches = [k for k in recordatorios if title in k]
    if len(matches) == 1:
        del memory["recordatorios"][matches[0]]
        save_memory(memory)
        return f"Recordatorio '{matches[0]}' eliminado."
    elif len(matches) > 1:
        return "Hay múltiples recordatorios similares. Dime el título exacto."
    return "No encontré un recordatorio con ese título."
