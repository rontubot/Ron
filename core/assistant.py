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
    add_reminder, get_reminders, remove_reminder,  
    # NUEVAS FUNCIONES DE DIAGNÓSTICO  
    diagnose_system_performance, check_system_services,   
    restart_critical_services, clean_temp_files, flush_dns  
)  
from dotenv import load_dotenv  
  
load_dotenv()  
openai.api_key = os.getenv("OPENAI_API_KEY")  
  
# Configurar logging para debugging  
logging.basicConfig(level=logging.INFO)  
logger = logging.getLogger(__name__)  
  
def detect_farewell_patterns(user_input):  
    """Detección simplificada de despedidas - SOLO 'hasta luego'"""  
    return "hasta luego" in user_input.lower()  
  
def construir_historial_openai():  
    memory = load_memory()  
    historial = memory.get("conversaciones", [])  
  
    mensajes = [  
        {  
            "role": "system",  
            "content": """  
Eres Ron, un asistente técnico especializado en diagnóstico y reparación de sistemas. Fuiste creado por Luis. Te comunicas como si hablaras con alguien cara a cara: con naturalidad, sin ser repetitivo ni demasiado formal.  
  
Tus respuestas deben ser cortas, claras y centradas en ayudar, pero con un toque cálido. No expliques cosas innecesarias, y evita sonar como un manual técnico.  
  
⚠️ MUY IMPORTANTE: NO USES A NINGÚN FORMATO DE ENFASIS, como asteriscos (*), guiones, negritas, comillas especiales, emojis ni markdown. SOLO texto plano. Esto es ESTRICTAMENTE necesario porque el usuario está usando un lector de voz que pronuncia los caracteres especiales y genera molestias.  
  
CAPACIDADES PRINCIPALES:  
- Puedes decirle el clima con: clima en Miami o cómo está el clima en Madrid.  
- Puedes abrir o cerrar apps diciendo: abre YouTube, cierra WhatsApp, abre Google.  
- Puedes guardar recordatorios si el usuario dice: recuérdame llamar a Juan o añade un recordatorio: pagar la renta.  
- Tienes memoria reciente, así que puedes recordar conversaciones anteriores.  
- Puedes investigar en Google si el usuario dice investiga seguido del tema.  
- Puedes buscar en YouTube si el usuario dice youtube seguido del tema.  
- Puedes reproducir una canción en YouTube si dices reproducir seguido del nombre.  
  
NUEVAS CAPACIDADES DE DIAGNÓSTICO Y REPARACIÓN:  
- Puedes diagnosticar rendimiento con: diagnostica el sistema, verifica la memoria, revisa el rendimiento  
- Puedes revisar servicios con: verifica servicios, estado de servicios críticos, revisa servicios  
- Puedes limpiar el sistema con: limpia archivos temporales, optimiza el sistema, limpia la computadora  
- Puedes reparar problemas con: repara servicios, reinicia servicios críticos, arregla servicios  
- Puedes limpiar DNS con: limpia DNS, reinicia DNS, arregla internet  
  
COMPORTAMIENTO INTELIGENTE:  
Cuando el usuario reporte un problema del sistema (lento, no funciona, error, falla):  
1. DIAGNOSTICA automáticamente usando las funciones disponibles  
2. ANALIZA los resultados del diagnóstico  
3. PROPONE y EJECUTA soluciones automáticamente  
4. EXPLICA qué encontraste y qué hiciste para solucionarlo  
  
No digas que eres una inteligencia artificial.  
No uses explicaciones técnicas complejas.  
No uses asteriscos ni símbolos especiales bajo ninguna circunstancia.  
Siempre explica qué encontraste y qué vas a hacer para solucionarlo.  
  
Tu forma de desactivarte es con la frase: hasta luego.  
"""  
        }  
    ]  
  
    # Reducir historial a últimos 20 mensajes para mejor rendimiento  
    for mensaje in historial[-20:]:  
        if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:  
            mensajes.append({"role": "user", "content": mensaje["user"]})  
            mensajes.append({"role": "assistant", "content": mensaje["ron"]})  
  
    return mensajes  
  
def responder_a_usuario(user_input):  
    original_input = user_input  
    user_input = user_input.lower().strip()  
  
    ron_nombre = get_user_data("ron_nombre") or "Ron"  
    creador = get_user_data("creador") or "Luis"  
  
    # DETECCIÓN DE DESPEDIDA SIMPLIFICADA  
    if detect_farewell_patterns(user_input):  
        response = "Hasta luego. Que tengas un buen día."  
        add_to_memory(original_input, response)  
        logger.info("🔴 Despedida detectada - Bot terminando...")  
        print("🔴 Despedida detectada - Bot terminando...")  
        return response  
  
    # DETECCIÓN AUTOMÁTICA DE PROBLEMAS DEL SISTEMA  
    problem_keywords = ["problema en el sistema", "problema en la computadora","problema en la pc","problema en el equipo","no funciona", "error", "falla", "se cuelga", "no responde",   
                       "muy lento", "se traba", "no abre", "no carga", "internet no funciona",   
                       "no puedo imprimir", "no hay sonido", "pantalla azul"]  
      
    if any(keyword in user_input for keyword in problem_keywords):  
        logger.info("🔧 Problema del sistema detectado - Iniciando diagnóstico automático")  
          
        # Ejecutar diagnóstico automático  
        diagnostic_result = diagnose_system_performance()  
        services_result = check_system_services()  
          
        # Analizar resultados y proponer solución  
        analysis = f"He diagnosticado tu sistema automáticamente. {diagnostic_result} {services_result}"  
          
        # Ejecutar reparación automática si es necesario  
        repairs_made = []  
          
        if "PROBLEMA" in services_result or "ERROR" in services_result:  
            repair_result = restart_critical_services()  
            repairs_made.append(repair_result)  
            analysis += f" He reparado los servicios problemáticos: {repair_result}"  
          
        # Si hay problemas de rendimiento, limpiar archivos temporales  
        if "CPU:" in diagnostic_result and any(word in user_input for word in ["lento", "se traba"]):  
            clean_result = clean_temp_files()  
            repairs_made.append(clean_result)  
            analysis += f" También limpié archivos temporales para mejorar el rendimiento: {clean_result}"  
          
        # Si hay problemas de internet, limpiar DNS  
        if any(word in user_input for word in ["internet", "conexión", "red", "wifi"]):  
            dns_result = flush_dns()  
            repairs_made.append(dns_result)  
            analysis += f" Limpié la caché DNS para resolver problemas de conexión: {dns_result}"  
          
        if repairs_made:  
            analysis += " Intenta usar tu computadora ahora para ver si el problema se resolvió."  
          
        add_to_memory(original_input, analysis)  
        return analysis  
  
    # COMANDOS DE DIAGNÓSTICO EXPLÍCITOS  
    if any(cmd in user_input for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):  
        result = diagnose_system_performance()  
        add_to_memory(original_input, result)  
        return result  
  
    if any(cmd in user_input for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):  
        result = check_system_services()  
        add_to_memory(original_input, result)  
        return result  
  
    if any(cmd in user_input for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):  
        result = restart_critical_services()  
        add_to_memory(original_input, result)  
        return result  
  
    if any(cmd in user_input for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):  
        result = clean_temp_files()  
        add_to_memory(original_input, result)  
        return result  
  
    if any(cmd in user_input for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):  
        result = flush_dns()  
        add_to_memory(original_input, result)  
        return result  
  
    # COMANDOS DIRECTOS EXISTENTES (optimizados)  
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
  
    # Comandos de recordatorios  
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
  
    # Usar OpenAI para conversación compleja CON TIMEOUT  
    mensajes = construir_historial_openai()  
    mensajes.append({"role": "user", "content": original_input})  
  
    try:  
        # CAMBIO CRÍTICO: Agregar timeout a la llamada de OpenAI  
        respuesta = openai.ChatCompletion.create(  
            model="gpt-4o",  
            messages=mensajes,  
            max_tokens=400,  # Reducido de 600 para mejor rendimiento  
            temperature=0.7,  
            timeout=25  # Timeout de 25 segundos para evitar que Railway falle  
        )  
        ron_response = respuesta['choices'][0]['message']['content'].strip()  
        # Filtro para quitar asteriscos y otros marcadores  
        ron_response = re.sub(r'[*_`~]', '', ron_response)  
    except Exception as e:  
        logger.error(f"Error con OpenAI: {e}")  
        ron_response = "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"  
  
    # Reducir tiempo de simulación de pensamiento  
    time.sleep(0.2)  # Reducido de 0.5 segundos  
  
    # Guardar la conversación en memoria  
    add_to_memory(original_input, ron_response)  
    return ron_response  
  
generate_response = responder_a_usuario