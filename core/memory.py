import os  
import json  
import requests  
import base64  
import socket  
from datetime import datetime  
  
# Configuración unificada para usar el mismo repositorio para lectura y escritura  
GITHUB_USERNAME = "rontubot"  
REPO_NAME = "ron-memory-store"  
BRANCH = "main"  
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"  
  
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
    # Usar device_id en lugar de IP para mantener chats por dispositivo  
    device_id = get_device_id()  
    return f"memory/{device_id}.json"  
  
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
  
    try:  
        r = requests.get(url, headers=headers)  
        if r.status_code == 200:  
            return json.loads(r.content)  
        elif r.status_code == 404:  
            print(f"📁 Archivo de memoria no encontrado, creando uno nuevo")  
            return {"datos": {"ron_nombre": "Ron", "creador": "Luis"}, "conversaciones": []}  
        else:  
            print(f"⚠️ Error al cargar memoria: {r.status_code}")  
    except Exception as e:  
        print(f"⚠️ Error al procesar memoria: {e}")  
  
    return {"datos": {"ron_nombre": "Ron", "creador": "Luis"}, "conversaciones": []}  
  
def save_memory(new_memory):  
    token = get_github_token()  
    if not token:  
        print("⚠️ Token de GitHub no disponible")  
        return  
  
    file_path = get_memory_file_path()  
    device_id = file_path.split("/")[-1].replace(".json", "")  
    api_url = f"{GITHUB_API_BASE}/{file_path}"  
  
    headers = {  
        "Authorization": f"token {token}",  
        "Accept": "application/vnd.github.v3+json"  
    }  
  
    # Paso 1: Intenta obtener la versión actual del archivo  
    existing_memory = {  
        "datos": {"ron_nombre": "Ron", "creador": "Luis"},  
        "conversaciones": []  
    }  
    sha = None  
    try:  
        r = requests.get(api_url, headers=headers)  
        if r.status_code == 200:  
            sha = r.json()["sha"]  
            content_raw = base64.b64decode(r.json()["content"])  
            existing_memory = json.loads(content_raw)  
    except Exception as e:  
        print(f"⚠️ No se pudo cargar memoria existente: {e}")  
  
    # Paso 2: Fusionar la memoria nueva con la existente  
    existing_memory["datos"].update(new_memory.get("datos", {}))  
  
    if "conversaciones" not in existing_memory:  
        existing_memory["conversaciones"] = []  
  
    existing_memory["conversaciones"] += new_memory.get("conversaciones", [])  
    existing_memory["conversaciones"] = existing_memory["conversaciones"][-100:]  # limitar tamaño  
  
    # Paso 3: Codificar y subir el archivo  
    content_encoded = base64.b64encode(json.dumps(existing_memory, indent=4, ensure_ascii=False).encode()).decode()  
    payload = {  
        "message": f"update memory for {device_id}",  
        "content": content_encoded,  
        "branch": BRANCH  
    }  
    if sha:  
        payload["sha"] = sha  
  
    response = requests.put(api_url, headers=headers, json=payload)  
  
    if response.status_code in [200, 201]:  
        print(f"✅ Memoria de {device_id} guardada correctamente.")  
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
  
    # Agregar timestamp a cada conversación  
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  
    conversation_entry = {  
        "user": user_text,  
        "ron": ron_response,  
        "timestamp": timestamp  
    }  
  
    memory["conversaciones"].append(conversation_entry)  
    memory["conversaciones"] = memory["conversaciones"][-100:]  
  
    save_memory(memory)  
  
def add_reminder(activity):  
    memory = load_memory()  
    if "recordatorios" not in memory or not isinstance(memory.get("recordatorios"), dict):  
        memory["recordatorios"] = {}  
    parts = activity.split(":", 1)  
    title = parts[0].strip().lower()  
    description = parts[1].strip() if len(parts) > 1 else "(Sin descripción)"  
      
    # Agregar timestamp al recordatorio  
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  
    memory["recordatorios"][title] = {  
        "description": description,  
        "created": timestamp  
    }  
      
    save_memory(memory)  
    return f"Recordatorio agregado: {title} - {description}."  
  
def get_reminders():  
    memory = load_memory()  
    recordatorios = memory.get("recordatorios", {})  
    if recordatorios:  
        result = "Tus recordatorios son:\\n"  
        for title, data in recordatorios.items():  
            if isinstance(data, dict):  
                result += f"- {title}: {data['description']} (creado: {data.get('created', 'fecha desconocida')})\\n"  
            else:  
                # Compatibilidad con formato anterior  
                result += f"- {title}: {data}\\n"  
        return result  
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