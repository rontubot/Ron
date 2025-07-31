import os
import openai
import re
from core.memory import load_memory, add_to_memory, get_user_data, save_user_data
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def generate_response(user_text):
    user_text = user_text.lower().strip()

    ron_nombre = get_user_data("ron_nombre") or "Ron"
    creador = get_user_data("creador") or "Luis"

    if user_text.startswith("soy "):
        nombre = user_text[4:].strip()
        if nombre:
            save_user_data("nombre", nombre)
            return f"Hola {nombre}, mucho gusto."

    if "cómo te llamas" in user_text or "cuál es tu nombre" in user_text:
        return f"Me llamo {ron_nombre}."
    if "quién te creó" in user_text or "quién es tu creador" in user_text:
        return f"Fui creado por {creador}."
    if "cómo me llamo" in user_text or "mi nombre" in user_text:
        nombre = get_user_data("nombre")
        return f"Tu nombre es {nombre}." if nombre else "No tengo esa información. ¿Me la podrías decir?"

    memory = load_memory()
    history = [
        {
            "role": "system",
            "content": """
Eres Ron, un asistente de voz amigable, conversador y eficiente. Te comunicas como si hablaras con alguien cara a cara: natural, sin ser repetitivo ni muy técnico.

⚠️ NO USES símbolos especiales como asteriscos, guiones o markdown, ya que el usuario usa un lector de voz.

Puedes:
- Controlar la TV con frases como 'sube volumen de la tele'
- Dar el clima: 'clima en Madrid'
- Abrir apps: 'abre YouTube'
- Guardar recordatorios
- Investigar: 'investiga mejores cámaras'
- Buscar en YouTube: 'youtube cómo preparar ramen'
- Reproducir canciones: 'reproduce salsa vieja'
- Desactivarte con: 'hasta luego'

No digas que eres una inteligencia artificial. Tu creador se llama Luis.
"""
        }
    ]

    for entry in memory.get("conversaciones", [])[-20:]:
        history.append({"role": "user", "content": entry["user"]})
        history.append({"role": "assistant", "content": entry["ron"]})

    history.append({"role": "user", "content": user_text})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=history,
            max_tokens=600,
            temperature=0.7
        )
        ron_response = response["choices"][0]["message"]["content"].strip()
        ron_response = re.sub(r'[*_`~]', '', ron_response)
    except Exception as e:
        ron_response = f"Hubo un error al contactar a OpenAI: {e}"

    add_to_memory(user_text, ron_response)
    return ron_response
