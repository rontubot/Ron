import os  
import openai  
import re  
import time  
import sys  
from core.memory import add_to_memory, load_memory, get_user_data, save_user_data  
from core.commands import (  
    open_application, close_application, get_weather,   
    search_google, search_youtube, shutdown, restart, suspend  
)  
from dotenv import load_dotenv  
  
load_dotenv()  
openai.api_key = os.getenv("OPENAI_API_KEY")  
  
def detect_command_intent(user_input):  
    """Detecta la intención del comando de forma flexible"""  
      
    # Patrones de despedida - MUY AMPLIOS para capturar cualquier despedida  
    farewell_patterns = [  
        r"(vale|bueno|ok|bien)?\\s*(hasta luego|adiós|chao|nos vemos|me voy|hasta la vista)",  
        r"(vale|bueno|ok|bien)?\\s*(desconéctate|apágate|ciérrate|termina)",  
        r"(hasta|nos)\\s+(luego|vemos|pronto)",  
        r"(me|ya)\\s+(voy|retiro|despido)",  
        r"(que tengas|ten)\\s+(buen|buena)\\s+(día|tarde|noche)",  
        r"(gracias|thanks)\\s+(y\\s+)?(hasta luego|adiós|chao)",  
        r"^(adiós|chao|bye|hasta luego)$"  
    ]  
      
    for pattern in farewell_patterns:  
        if re.search(pattern, user_input, re.IGNORECASE):  
            return {"type": "farewell", "action": "disconnect"}  
      
    # Patrones de reproducción de música  
    music_patterns = [  
        r"(puedes|podrías)?\\s*(reproducir|reproduce|pon|poner)\\s*(una canción de|música de)?\\s*(.+)",  
        r"(quiero escuchar|escuchar)\\s*(.+)",  
        r"(busca|pon)\\s*(música|canción)\\s*(de)?\\s*(.+)"  
    ]  
      
    for pattern in music_patterns:  
        match = re.search(pattern, user_input, re.IGNORECASE)  
        if match:  
            artist = match.group(-1).strip()  
            return {"type": "music", "action": "play", "query": artist}  
      
    # Patrones de apertura de aplicaciones  
    app_patterns = [  
        r"(puedes|podrías)?\\s*(abrir|abre|abrime)\\s*(.+)",  
        r"(quiero|necesito)\\s*(abrir|usar)\\s*(.+)",  
        r"(abre|abrir)\\s+(.+)"  
    ]  
      
    for pattern in app_patterns:  
        match = re.search(pattern, user_input, re.IGNORECASE)  
        if match:  
            app_name = match.group(-1).strip()  
            return {"type": "app", "action": "open", "target": app_name}  
      
    # Patrones de clima  
    weather_patterns = [  
        r"(clima|tiempo)\\s*(en|de)\\s*(.+)",  
        r"(cómo está el clima|qué tiempo hace)\\s*(en|de)?\\s*(.+)?"  
    ]  
      
    for pattern in weather_patterns:  
        match = re.search(pattern, user_input, re.IGNORECASE)  
        if match:  
            city = match.group(-1).strip() if match.group(-1) else "Madrid"  
            return {"type": "weather", "action": "get", "city": city}  
      
    # Patrones de búsqueda  
    search_patterns = [  
        r"(busca|buscar)\\s*(en google)?\\s*(.+)",  
        r"(google)\\s*(.+)"  
    ]  
      
    for pattern in search_patterns:  
        match = re.search(pattern, user_input, re.IGNORECASE)  
        if match:  
            query = match.group(-1).strip()  
            return {"type": "search", "action": "google", "query": query}  
      
    return None  
  
def construir_historial_openai():  
    memory = load_memory()  
    historial = memory.get("conversaciones", [])  
  
    mensajes = [  
        {  
            "role": "system",  
            "content": """  
Eres Ron, un asistente de voz amigable, conversador y eficiente. Te comunicas como si hablaras con alguien cara a cara: natural, sin ser repetitivo ni muy técnico.  
  
⚠️ NO USES símbolos especiales como asteriscos, guiones o markdown, ya que el usuario usa un lector de voz.  
  
IMPORTANTE: Si detectas que el usuario quiere ejecutar un comando pero no lo dice exactamente, interpreta su intención y ejecuta el comando apropiado.  
  
Ejemplos de interpretación:  
- "vale hasta luego" = comando de despedida (DESACTIVAR BOT)  
- "puedes reproducir una canción de mgk" = reproduce música de MGK  
- "me gustaría abrir youtube" = abre YouTube  
  
Puedes ejecutar estos comandos:  
- Despedida: 'hasta luego', 'adiós', 'desconéctate' (SIEMPRE DESACTIVA EL BOT)  
- Abrir apps: 'abre YouTube', 'abrir Google'  
- Clima: 'clima en Madrid', 'tiempo en Barcelona'  
- Música: 'reproduce salsa', 'pon música de rock'  
- Búsquedas: 'busca en Google', 'youtube cómo cocinar'  
- Guardar recordatorios  
  
No digas que eres una inteligencia artificial. Tu creador se llama Luis.  
"""  
        }  
    ]  
  
    # Manejar tanto formato nuevo (con timestamp) como anterior (sin timestamp)  
    for mensaje in historial[-50:]:  
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:  
            mensajes.append({"role": "user", "content": mensaje["user"]})  
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})  
  
    return mensajes  
  
def shutdown_bot():  
    """Función para desactivar el bot completamente"""  
    print("🔴 Bot desactivándose...")  
    # Guardar estado de desactivación  
    try:  
        memory = load_memory()  
        memory["datos"]["bot_active"] = False  
        from core.memory import save_memory_direct  
        save_memory_direct(memory)  
    except:  
        pass  
      
    # Terminar el proceso  
    sys.exit(0)  
  
def responder_a_usuario(user_input):  
    original_input = user_input  
    user_input = user_input.lower().strip()  
  
    ron_nombre = get_user_data("ron_nombre") or "Ron"  
    creador = get_user_data("creador") or "Luis"  
  
    # Detectar intención de comando PRIMERO  
    command_intent = detect_command_intent(user_input)  
      
    if command_intent:  
        print(f"DEBUG: Comando detectado: {command_intent}")  
          
        if command_intent["type"] == "farewell":  
            # DESACTIVAR BOT INMEDIATAMENTE  
            response = "Hasta luego. Que tengas un buen día."  
            add_to_memory(original_input, response)  
            print("🔴 Despedida detectada - Desactivando bot...")  
            shutdown_bot()  
            return response  
          
        elif command_intent["type"] == "music":  
            query = command_intent["query"]  
            print(f"DEBUG: Ejecutando search_youtube para música: {query}")  
            result = search_youtube(f"música de {query}")  
            print(f"DEBUG: Resultado música: {result}")  
            return result  
          
        elif command_intent["type"] == "app":  
            app_name = command_intent["target"]  
            print(f"DEBUG: Ejecutando open_application: {app_name}")  
            result = open_application(app_name)  
            print(f"DEBUG: Resultado app: {result}")  
            return result  
          
        elif command_intent["type"] == "weather":  
            city = command_intent["city"]  
            print(f"DEBUG: Ejecutando get_weather: {city}")  
            result = get_weather(city)  
            print(f"DEBUG: Resultado clima: {result}")  
            return result  
          
        elif command_intent["type"] == "search":  
            query = command_intent["query"]  
            print(f"DEBUG: Ejecutando search_google: {query}")  
            result = search_google(query)  
            print(f"DEBUG: Resultado búsqueda: {result}")  
            return result  
  
    # Comandos directos exactos  
    if "abre " in user_input or "abrir " in user_input:  
        app_name = user_input.replace("abre ", "").replace("abrir ", "").strip()  
        return open_application(app_name)  
      
    if "clima en " in user_input or "tiempo en " in user_input:  
        city = user_input.replace("clima en ", "").replace("tiempo en ", "").strip()  
        return get_weather(city)  
      
    if "busca en google " in user_input:  
        query = user_input.replace("busca en google ", "").strip()  
        return search_google(query)  
      
    if user_input.startswith("youtube "):  
        query = user_input.replace("youtube ", "").strip()  
        return search_youtube(query)  
      
    if user_input.startswith("reproduce "):  
        query = user_input.replace("reproduce ", "").strip()  
        return search_youtube(f"música {query}")  
  
    # Respuestas directas sin usar OpenAI  
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
  
    # Usar la función unificada para construir el historial  
    mensajes = construir_historial_openai()  
      
    # Agregar el mensaje actual del usuario  
    mensajes.append({"role": "user", "content": original_input})  
  
    # Obtener respuesta de OpenAI  
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
  
    # Simulación de pensamiento DESPUÉS de generar la respuesta  
    time.sleep(0.5)  
  
    # Guardar la conversación en memoria  
    add_to_memory(original_input, ron_response)  
    return ron_response  
  
generate_response = responder_a_usuario