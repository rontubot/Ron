import os
import json
import requests
import base64
import socket

GITHUB_USERNAME = "rontubot"
REPO_NAME = "Ron"
BRANCH = "main"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents/memory"

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
    ip = get_public_ip()
    return f"{ip}.json"

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
    token = get_github_token()
    if not token:
        return

    file_path = get_memory_file_path()
    url = f"{GITHUB_API_BASE}/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Get current SHA if file exists
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    content_bytes = json.dumps(memory, indent=4, ensure_ascii=False).encode("utf-8")
    b64_content = base64.b64encode(content_bytes).decode("utf-8")

    data = {
        "message": f"update memory for {file_path}",
        "content": b64_content,
        "branch": BRANCH
    }

    if sha:
        data["sha"] = sha

    requests.put(url, headers=headers, json=data)

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
    memory["conversaciones"].append({"user": user_text, "ron": ron_response})
    memory["conversaciones"] = memory["conversaciones"][-20:]
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
