import os
import openai
import re
from core.memory import add_to_memory, load_memory, get_user_data, save_user_data
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def construir_historial_openai():
    memory = load_memory()
    historial = memory.get("conversaciones", [])

    mensajes = [
        {
            "role": "system",
            "content": """
Eres Ron, un asistente de voz amigable, conversador y eficiente. Te comunicas como si hablaras con alguien cara a cara: natural, sin ser repetitivo ni muy técnico.

⚠️ NO USES símbolos especiales como asteriscos, guiones o markdown, ya que el usuario usa un lector de voz.

Puedes:
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

    for mensaje in historial[-20:]:
        mensajes.append({"role": "user", "content": mensaje["user"]})
        mensajes.append({"role": "assistant", "content": mensaje["ron"]})

    return mensajes

def responder_a_usuario(user_input):  
    user_input = user_input.lower().strip()  
  
    ron_nombre = get_user_data("ron_nombre") or "Ron"  
    creador = get_user_data("creador") or "Luis"  
  
    if user_input.startswith("soy "):  
        nombre = user_input[4:].strip()  
        if nombre:  
            save_user_data("nombre", nombre)  
            return f"Hola {nombre}, mucho gusto."  
  
    if "cómo te llamas" in user_input or "cuál es tu nombre" in user_input:  
        return f"Me llamo {ron_nombre}."  
    if "quién te creó" in user_input or "quién es tu creador" in user_input:  
        return f"Fui creado por {creador}."  
    if "cómo me llamo" in user_input or "mi nombre" in user_input:  
        nombre = get_user_data("nombre")  
        return f"Tu nombre es {nombre}." if nombre else "No tengo esa información. ¿Me la podrías decir?"  
  
    # 🔧 CORRECCIÓN: Usar la función dedicada para construir el historial  
    mensajes = construir_historial_openai()  
      
    # Añadir el mensaje actual del usuario  
    mensajes.append({"role": "user", "content": user_input})  
  
    # 🧠 Obtener respuesta  
    try:  
        respuesta = openai.ChatCompletion.create(  
            model="gpt-4o",  
            messages=mensajes,  
            max_tokens=600,  
            temperature=0.7  
        )  
        ron_response = respuesta['choices'][0]['message']['content'].strip()  
        ron_response = re.sub(r'[*_`~]', '', ron_response)  
    except Exception as e:  
        ron_response = f"Hubo un error al contactar a OpenAI: {e}"  
  
    # ✅ Guardar memoria con la respuesta real  
    add_to_memory(user_input, ron_response)  
    return ron_response

generate_response = responder_a_usuario
