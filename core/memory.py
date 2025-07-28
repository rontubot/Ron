# core/memory.py
import os
import json

MEMORY_FILE = "data/ron_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            try:
                memory = json.load(file)
                if "datos" not in memory:
                    memory["datos"] = {}
                if "conversaciones" not in memory:
                    memory["conversaciones"] = []
                if "ron_nombre" not in memory["datos"]:
                    memory["datos"]["ron_nombre"] = "Ron"
                if "creador" not in memory["datos"]:
                    memory["datos"]["creador"] = "Luis"
                return memory
            except json.JSONDecodeError:
                pass
    return {"datos": {"ron_nombre": "Ron", "creador": "Luis"}, "conversaciones": []}

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=4, ensure_ascii=False)

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
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):
        memory["recordatorios"] = {}
    parts = activity.split(":", 1)
    title = parts[0].strip().lower()
    description = parts[1].strip() if len(parts) > 1 else "(Sin descripción)"
    memory["recordatorios"][title] = description
    save_memory(memory)
    return f"Recordatorio agregado: {title} - {description}."

def get_reminders():
    memory = load_memory()
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):
        memory["recordatorios"] = {}
    if memory["recordatorios"]:
        return "Tus recordatorios son:\n" + "\n".join(f"- {title}: {desc}" for title, desc in memory["recordatorios"].items())
    return "No tienes recordatorios pendientes."

def remove_reminder(activity):
    memory = load_memory()
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):
        memory["recordatorios"] = {}
    title = activity.strip().lower()
    matches = [key for key in memory["recordatorios"] if title in key]
    if len(matches) == 1:
        removed_title = matches[0]
        memory["recordatorios"].pop(removed_title)
        save_memory(memory)
        return f"Recordatorio '{removed_title}' eliminado."
    elif len(matches) > 1:
        return "Hay múltiples recordatorios similares. Dime el título exacto."
    return "No encontré un recordatorio con ese título."
