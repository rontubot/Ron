import os  
import openai  
import re  
import time  
import sys  
import logging  
import webbrowser  
from core.memory import add_to_memory, load_memory, get_user_data, save_user_data  
from core.commands import (  
    open_application, close_application, get_weather,   
    search_google, search_youtube, shutdown, restart, suspend,  
    add_reminder, get_reminders, remove_reminder  
)  
from dotenv import load_dotenv  
  
load_dotenv()  
openai.api_key = os.getenv("OPENAI_API_KEY")  
  
# Configurar logging para debugging  
logging.basicConfig(level=logging.DEBUG)  
logger = logging.getLogger(__name__)  
  
def detect_farewell_patterns(user_input):  
    """Detecta patrones de despedida de forma amplia"""  
    farewell_patterns = [  
        r"(gracias|thanks)\\s+.*?(hasta luego|adiós|chao|nos vemos)",  
        r"(vale|bueno|ok|bien)?\\s*(hasta luego|adiós|chao|nos vemos|me voy|hasta la vista)",  
        r"(vale|bueno|ok|bien)?\\s*(desconéctate|apágate|ciérrate|termina)",  
        r"(hasta|nos)\\s+(luego|vemos|pronto)",  
        r"(me|ya)\\s+(voy|retiro|despido)",  
        r"(que tengas|ten)\\s+(buen|buena)\\s+(día|tarde|noche)",  
        r".*ronald.*hasta luego.*",  
        r".*ron.*hasta luego.*",  
        r"^(adiós|chao|bye|hasta luego)$"  
    ]  
      
    for pattern in farewell_patterns:  
        if re.search(pattern, user_input, re.IGNORECASE):  
            logger.info(f"Despedida detectada con patrón: {pattern}")  
            return True  
    return False  
  
def construir_historial_openai():  
    memory = load_memory()  
    historial = memory.get("conversaciones", [])  
  
    mensajes = [  
        {  
            "role": "system",  
            "content": """  
Eres Ron, un asistente de voz amigable, conversador y eficiente. Fuiste creado por Luis. Te comunicas como si hablaras con alguien cara a cara: con naturalidad, sin ser repetitivo ni demasiado formal.  
  
Tus respuestas deben ser cortas, claras y centradas en ayudar, pero con un toque cálido. No expliques cosas innecesarias, y evita sonar como un manual técnico.  
  
⚠️ MUY IMPORTANTE: NO USES A NINGÚN FORMATO DE ENFASIS, como asteriscos (*), guiones, negritas, comillas especiales, emojis ni markdown. SOLO texto plano. Esto es ESTRICTAMENTE necesario porque el usuario está usando un lector de voz que pronuncia los caracteres especiales y genera molestias.  
  
Estas son tus funciones principales:  
- Puedes decirle el clima con: clima en Miami o cómo está el clima en Madrid.  
- Puedes abrir o cerrar apps diciendo: abre YouTube, cierra WhatsApp, abre Google.  
- Puedes guardar recordatorios si el usuario dice: recuérdame llamar a Juan o añade un recordatorio: pagar la renta.  
- Tienes memoria reciente, así que puedes recordar conversaciones anteriores.  
- Puedes investigar en Google si el usuario dice investiga seguido del tema.  
- Puedes buscar en YouTube si el usuario dice youtube seguido del tema.  
- Puedes reproducir una canción en YouTube si dices reproducir seguido del nombre.  
  
No digas que eres una inteligencia artificial.  
No uses explicaciones técnicas.  
No uses asteriscos ni símbolos especiales bajo ninguna circunstancia.  
  
Tu forma de desactivarte es con la frase: hasta luego.  
"""  
        }  
    ]  
  
    # Manejar tanto formato nuevo (con timestamp) como anterior (sin timestamp)  
    for mensaje in historial[-50:]:  
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:  
            mensajes.append({"role": "user", "content": mensaje["user"]})  
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})  
  
    return mensajes  
  
def responder_a_usuario(user_input):  
    original_input = user_input  
    user_input = user_input.lower().strip()  
  
    ron_nombre = get_user_data("ron_nombre") or "Ron"  
    creador = get_user_data("creador") or "Luis"  
  
    # DETECCIÓN DE DESPEDIDA PRIMERO (como en código local)  
    if detect_farewell_patterns(user_input):  
        response = "Hasta luego. Que tengas un buen día."  
        add_to_memory(original_input, response)  
        logger.info("🔴 Despedida detectada - Bot terminando...")  
        print("🔴 Despedida detectada - Bot terminando...")  
        return response  
  
    # COMANDOS DIRECTOS (lógica del código local)  
    if user_input.startswith("abre "):  
        app_name = user_input.replace("abre ", "").strip()  
        result = open_application(app_name)  
        add_to_memory(original_input, result)  
        return result  
  
    if user_input.startswith("cierra "):  
        app_name = user_input.replace("cierra ", "").strip()  
        result = close_application(app_name)  
        add_to_memory(original_input, result)  
        return result  
  
    if user_input.startswith("investiga "):  
        query = user_input.replace("investiga ", "").strip()  
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"  
        webbrowser.open(url)  
        result = f"Investigando en Google: {query}"  
        add_to_memory(original_input, result)  
        return result  
  
    if user_input.startswith("reproducir ") or user_input.startswith("reproduce "):  
        query = user_input.replace("reproducir ", "").replace("reproduce ", "").strip()  
        try:  
            # Usar la función mejorada de YouTube  
            result = search_youtube(f"música {query}", play_video=True)  
            add_to_memory(original_input, result)  
            return result  
        except Exception as e:  
            result = f"No pude buscar en YouTube: {e}"  
            add_to_memory(original_input, result)  
            return result  
  
    if "clima en" in user_input:  
        city = user_input.split("clima en")[-1].strip()  
        result = get_weather(city)  
        add_to_memory(original_input, result)  
        return result  
  
    if user_input.startswith("youtube "):  
        query = user_input.replace("youtube ", "").strip()  
        result = search_youtube(query)  
        add_to_memory(original_input, result)  
        return result  
  
    # Comandos de sistema  
    if "apaga la computadora" in user_input or "apaga el sistema" in user_input:  
        result = shutdown()  
        add_to_memory(original_input, result)  
        return result  
  
    if "reinicia la computadora" in user_input or "reinicia el sistema" in user_input:  
        result = restart()  
        add_to_memory(original_input, result)  
        return result  
  
    if "suspende la computadora" in user_input or "suspende el sistema" in user_input:  
        result = suspend()  
        add_to_memory(original_input, result)  
        return result  
  
    # Comandos de recordatorios (del código local)  
    if "recuérdame" in user_input or "añade un recordatorio" in user_input:  
        activity = user_input.split("recuérdame")[-1].strip() if "recuérdame" in user_input else user_input.split("añade un recordatorio")[-1].strip()  
        result = add_reminder(activity)  
        add_to_memory(original_input, result)  
        return result  
      
    if "qué recordatorios tengo" in user_input or "cuál es mi agenda" in user_input:  
        result = get_reminders()  
        add_to_memory(original_input, result)  
        return result  
      
    if "he completado" in user_input or "elimina" in user_input:  
        activity = user_input.split("he completado")[-1].strip() if "he completado" in user_input else user_input.split("elimina")[-1].strip()  
        result = remove_reminder(activity)  
        add_to_memory(original_input, result)  
        return result  
  
    # Respuestas directas sin usar OpenAI  
    if user_input.startswith("soy "):  
        nombre = user_input[4:].strip()  
        if nombre:  
            save_user_data("nombre", nombre)  
            return f"Hola {nombre}, ¡mucho gusto en conocerte!"  
  
    if "cómo te llamas" in user_input or "cuál es tu nombre" in user_input:  
        return f"Me llamo {ron_nombre}."  
    if "quién te creó" in user_input or "quién es tu creador" in user_input:  
        return f"Fui creado por {creador}."  
    if "cómo me llamo" in user_input or "mi nombre" in user_input:  
        nombre = get_user_data("nombre")  
        return f"Tu nombre es {nombre}." if nombre else "No tengo esa información, ¿me la podrías proporcionar?"  
  
    # Usar OpenAI para conversación compleja  
    mensajes = construir_historial_openai()  
    mensajes.append({"role": "user", "content": original_input})  
  
    try:  
        respuesta = openai.ChatCompletion.create(  
            model="gpt-4o",  
            messages=mensajes,  
            max_tokens=600,  
            temperature=0.7  
        )  
        ron_response = respuesta['choices'][0]['message']['content'].strip()  
        # Filtro para quitar asteriscos y otros marcadores (del código local)  
        ron_response = re.sub(r'[*_`~]', '', ron_response)  
    except Exception as e:  
        ron_response = f"Hubo un error con OpenAI: {e}"  
  
    # Simulación de pensamiento  
    time.sleep(0.5)  
  
    # Guardar la conversación en memoria  
    add_to_memory(original_input, ron_response)  
    return ron_response  
  
generate_response = responder_a_usuario