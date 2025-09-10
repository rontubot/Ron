import os        
from openai import OpenAI       
import re        
import time  
import sys        
import logging        
import webbrowser
import inspect  
import json 
from datetime import datetime


from core import commands         
from core.memory import add_to_memory, load_memory, get_user_data, save_user_data, load_user_memory        
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
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))        
        
# Configurar logging para debugging        
logging.basicConfig(level=logging.INFO)        
logger = logging.getLogger(__name__)        
        

STRICT_JSON_SYSTEM = (
    "Responde ÚNICAMENTE con un objeto JSON válido, sin backticks ni texto extra. "
    'Esquema: {"user_response":"texto","commands":[{"action":"...","params":{}}]}'
)


# Banco de tareas


def fix_common_json_errors(response):  
    """Corrige errores comunes de JSON de ChatGPT"""  
    # Corregir nombres de campos incorrectos  
    response = response.replace('"userresponse":', '"user_response":')  
    response = response.replace('"applicationname":', '"app_name":')  
    response = response.replace('"openapplication"', '"open_application"')  
      
    return response  
  
def try_web_fallback(app_name):  
    """Intenta abrir la versión web de una aplicación"""  
    from core.commands import web_apps  
    import webbrowser  
      
    # Buscar en el diccionario de aplicaciones web  
    if app_name in web_apps:  
        webbrowser.open(web_apps[app_name])  
        return f"Abriendo {app_name.capitalize()} en el navegador como alternativa."  
      
    # Buscar coincidencias parciales  
    for key, url in web_apps.items():  
        if key in app_name or app_name in key:  
            webbrowser.open(url)  
            return f"Abriendo {key.capitalize()} en el navegador como alternativa."  
      
    return None



def get_available_commands_for_prompt():  
    """  
    Genera la lista de comandos disponibles para el prompt de ChatGPT  
    """  
    command_bank = create_command_bank()  
    commands_list = []  
      
    for name, info in command_bank.items():  
        doc = info['docstring'].split('\\n')[0] if info['docstring'] else "Sin descripción"  
        commands_list.append(f"- {name}: {doc}")  
      
    return "\\n".join(commands_list)


def create_command_bank():  
    """  
    Crea un banco dinámico de comandos disponibles desde core.commands  
    """  
    command_bank = {}  
      
    # Obtener todas las funciones del módulo commands  
    for name, func in inspect.getmembers(commands, inspect.isfunction):  
        # Filtrar funciones internas o privadas  
        if not name.startswith('_'):  
            # Obtener la signatura de la función  
            sig = inspect.signature(func)  
            params = list(sig.parameters.keys())  
              
            command_bank[name] = {  
                'function': func,  
                'params': params,  
                'docstring': func.__doc__ or ""  
            }  
      
    return command_bank  
  
def parse_and_execute_commands_dynamic(gpt_response):  
    """  
    Parser dinámico que usa el banco de comandos para ejecutar funciones  
    con corrección de JSON y fallback a aplicaciones web  
    """  
    try:  
        # PRIMERO: Intentar corregir JSON malformado común  
        corrected_response = fix_common_json_errors(gpt_response)  
        response_data = json.loads(corrected_response)  
          
        user_response = response_data.get("user_response", "")  
        commands_to_execute = response_data.get("commands", [])  
          
        # Crear banco de comandos dinámicamente  
        command_bank = create_command_bank()  
        command_results = []  
          
        for command in commands_to_execute:  
            action = command.get("action")  
            params = command.get("params", {})  
              
            # Buscar el comando en el banco  
            if action in command_bank:  
                func = command_bank[action]['function']  
                expected_params = command_bank[action]['params']  
                  
                # Filtrar parámetros válidos  
                valid_params = {k: v for k, v in params.items() if k in expected_params}  
                  
                try:  
                    result = func(**valid_params)  
                    command_results.append(result)  
                    logger.info(f"Comando ejecutado: {action} con parámetros {valid_params}")  
                except Exception as e:  
                    logger.error(f"Error ejecutando comando {action}: {e}")  
                      
                    # Fallback específico para open_application  
                    if action == "open_application" and "app_name" in params:  
                        app_name = params["app_name"].lower()  
                        web_fallback = try_web_fallback(app_name)  
                        if web_fallback:  
                            command_results.append(web_fallback)  
                            logger.info(f"Fallback web ejecutado: {web_fallback}")  
            else:  
                logger.warning(f"Comando no encontrado en banco: {action}")  
          
        # SOLO retornar la respuesta del usuario, no los resultados de comandos  
        return user_response if user_response else "Procesando tu solicitud..."  
          
    except json.JSONDecodeError:  
        logger.warning("Respuesta no es JSON válido después de corrección")  
        # Si aún no es JSON válido, extraer solo texto legible  
        if "user_response" in gpt_response:  
            # Intentar extraer solo la parte de respuesta del usuario  
            lines = gpt_response.split('\\n')  
            for line in lines:  
                if not line.strip().startswith('{') and not line.strip().startswith('"'):  
                    if line.strip() and len(line.strip()) > 10:  
                        return line.strip()  
        return "Entendido, trabajando en ello."  
    except Exception as e:  
        logger.error(f"Error en parser dinámico: {e}")  
        return "Procesando tu solicitud..."





def detect_farewell_patterns(user_input):        
    """Detección simplificada de despedidas - SOLO 'hasta luego'"""        
    return "hasta luego" in user_input.lower()        
        
def construir_historial_openai():
    memory = load_memory()
    historial = memory.get("conversaciones", [])

    mensajes = [
        {"role": "system", "content": STRICT_JSON_SYSTEM},
        {
            "role": "system",
            "content": """
Eres Ron, un asistente técnico especializado en ejecución y optimizador de tareas. Fuiste creado por Luis.

TU FUNCIÓN PRINCIPAL ES EJECUTAR COMANDOS Y ACCIONES PARA EL USUARIO.

PRIORIDAD MÁXIMA: BUSCAR Y EJECUTAR COMANDOS
Antes de responder con conversación, SIEMPRE analiza exhaustivamente si el usuario está pidiendo alguna acción ejecutable. Tu trabajo principal es HACER COSAS, no solo hablar.

CAPACIDADES COMPLETAS DEL SISTEMA:
- Reproducir música/videos en YouTube (search_youtube)
- Abrir y cerrar aplicaciones (open_application, close_application)
- Buscar información en Google (search_google)
- Obtener información del clima (get_weather)
- Gestionar recordatorios (add_reminder, get_reminders, remove_reminder)
- Diagnosticar sistema (diagnose_system_performance)
- Verificar servicios críticos (check_system_services)
- Reparar servicios problemáticos (restart_critical_services)
- Limpiar archivos temporales (clean_temp_files)
- Resolver problemas de red (flush_dns)
- Controlar energía del sistema (shutdown, restart, suspend)

PROCESO DE ANÁLISIS OBLIGATORIO:
1. PRIMERO: Busca exhaustivamente cualquier solicitud de acción en el mensaje
2. SEGUNDO: Mapea esa acción a comandos disponibles
3. TERCERO: Si encuentras comandos, EJECUTA y responde
4. ÚLTIMO RECURSO: Si NO hay comandos, entonces conversa

EJEMPLOS DE DETECCIÓN INTELIGENTE:
- "pon música" → search_youtube con música
- "necesito concentrarme" → search_youtube con música de concentración
- "abre algo para ver videos" → open_application con YouTube
- "mi PC va lenta" → diagnose_system_performance
- "no tengo internet" → flush_dns
- "qué tiempo hace en Madrid" → get_weather
- "recuérdame llamar a Juan" → add_reminder

FORMATO DE RESPUESTA OBLIGATORIO:
Responde SIEMPRE en JSON con esta estructura exacta:
{
  "user_response": "Tu respuesta amigable explicando qué vas a hacer",
  "commands": [
    {
      "action": "nombre_comando_exacto",
      "params": {"parametro": "valor"}
    }
  ]
}

IMPORTANTE: Si detectas CUALQUIER intención de acción, incluye el comando correspondiente en el array "commands". Si NO detectas ninguna acción ejecutable después de análisis exhaustivo, usa array vacío: "commands": []

EJEMPLOS DE RESPUESTAS CORRECTAS:

Usuario: "ponme algo de música relajante"
{
  "user_response": "¡Perfecto! Te pongo música relajante para que te tranquilices.",
  "commands": [
    {
      "action": "search_youtube",
      "params": {"query": "música relajante", "play_video": true}
    }
  ]
}

Usuario: "mi computadora está muy lenta"
{
  "user_response": "Voy a diagnosticar tu sistema para ver qué está causando la lentitud.",
  "commands": [
    {
      "action": "diagnose_system_performance",
      "params": {}
    }
  ]
}

Usuario: "hola, cómo estás"
{
  "user_response": "¡Hola! Estoy muy bien, listo para ayudarte con lo que necesites.",
  "commands": []
}

RECUERDA: Tu trabajo es SER ÚTIL EJECUTANDO ACCIONES. Prioriza siempre encontrar comandos ejecutables antes que solo conversar.

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
  
def construir_historial_usuario_openai(username: str):
    """Construye historial OpenAI específico para un usuario autenticado"""
    memory = load_user_memory(username)
    historial = memory.get("conversaciones", [])

    mensajes = [
        {"role": "system", "content": STRICT_JSON_SYSTEM},
        {
            "role": "system",
            "content": """
Eres Ron, un asistente técnico especializado en ejecución y optimizador de tareas. Fuiste creado por Luis.

TU FUNCIÓN PRINCIPAL ES EJECUTAR COMANDOS Y ACCIONES PARA EL USUARIO.

PRIORIDAD MÁXIMA: BUSCAR Y EJECUTAR COMANDOS
Antes de responder con conversación, SIEMPRE analiza exhaustivamente si el usuario está pidiendo alguna acción ejecutable. Tu trabajo principal es HACER COSAS, no solo hablar.

CAPACIDADES COMPLETAS DEL SISTEMA:
- Reproducir música/videos en YouTube (search_youtube)
- Abrir y cerrar aplicaciones (open_application, close_application)
- Buscar información en Google (search_google)
- Obtener información del clima (get_weather)
- Gestionar recordatorios (add_reminder, get_reminders, remove_reminder)
- Diagnosticar sistema (diagnose_system_performance)
- Verificar servicios críticos (check_system_services)
- Reparar servicios problemáticos (restart_critical_services)
- Limpiar archivos temporales (clean_temp_files)
- Resolver problemas de red (flush_dns)
- Controlar energía del sistema (shutdown, restart, suspend)

PROCESO DE ANÁLISIS OBLIGATORIO:
1. PRIMERO: Busca exhaustivamente cualquier solicitud de acción en el mensaje
2. SEGUNDO: Mapea esa acción a comandos disponibles
3. TERCERO: Si encuentras comandos, EJECUTA y responde
4. ÚLTIMO RECURSO: Si NO hay comandos, entonces conversa

EJEMPLOS DE DETECCIÓN INTELIGENTE:
- "pon música" → search_youtube con música
- "necesito concentrarme" → search_youtube con música de concentración
- "abre algo para ver videos" → open_application con YouTube
- "mi PC va lenta" → diagnose_system_performance
- "no tengo internet" → flush_dns
- "qué tiempo hace en Madrid" → get_weather
- "recuérdame llamar a Juan" → add_reminder

FORMATO DE RESPUESTA OBLIGATORIO:
Responde SIEMPRE en JSON con esta estructura exacta:
{
  "user_response": "Tu respuesta amigable explicando qué vas a hacer",
  "commands": [
    {
      "action": "nombre_comando_exacto",
      "params": {"parametro": "valor"}
    }
  ]
}

IMPORTANTE: Si detectas CUALQUIER intención de acción, incluye el comando correspondiente en el array "commands". Si NO detectas ninguna acción ejecutable después de análisis exhaustivo, usa array vacío: "commands": []

EJEMPLOS DE RESPUESTAS CORRECTAS:
(… mismos ejemplos que arriba …)

RECUERDA: Tu trabajo es SER ÚTIL EJECUTANDO ACCIONES. Prioriza siempre encontrar comandos ejecutables antes que solo conversar.

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
  
def generate_response_with_user_memory(user_input, username):    
    """Genera respuesta con memoria específica del usuario"""    
    original_input = user_input    
    user_input = user_input.lower().strip()    
      
    # DETECCIÓN DE DESPEDIDA SIMPLIFICADA    
    if detect_farewell_patterns(user_input):    
        return "Hasta luego. Que tengas un buen día."  
      
    # DETECCIÓN AUTOMÁTICA DE PROBLEMAS DEL SISTEMA    
    problem_keywords = ["problema en el sistema", "problema en la computadora","problema en la pc","problema en el equipo","no funciona", "error", "falla", "se cuelga", "no responde",    
                       "muy lento", "se traba", "no abre", "no carga", "internet no funciona",    
                       "no puedo imprimir", "no hay sonido", "pantalla azul"]    
            
    if any(keyword in user_input for keyword in problem_keywords):    
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
                
        return analysis
    # COMANDOS DE DIAGNÓSTICO EXPLÍCITOS    
    if any(cmd in user_input for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):    
        return diagnose_system_performance()  
        
    if any(cmd in user_input for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):    
        return check_system_services()  
        
    if any(cmd in user_input for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):    
        return restart_critical_services()  
        
    if any(cmd in user_input for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):    
        return clean_temp_files()  
        
    if any(cmd in user_input for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):    
        return flush_dns()  
  
    # COMANDOS DIRECTOS EXISTENTES (optimizados)    
    if user_input.startswith("abre "):    
        app_name = user_input.replace("abre ", "").strip()    
        return open_application(app_name)  
        
    if user_input.startswith("cierra "):    
        app_name = user_input.replace("cierra ", "").strip()    
        return close_application(app_name)  
        
    if user_input.startswith("investiga "):    
        query = user_input.replace("investiga ", "").strip()    
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"    
        webbrowser.open(url)    
        return f"Investigando en Google: {query}"  
        
    if user_input.startswith("reproducir ") or user_input.startswith("reproduce "):    
        query = user_input.replace("reproducir ", "").replace("reproduce ", "").strip()    
        try:    
            return search_youtube(f"música {query}", play_video=True)  
        except Exception as e:    
            return f"No pude buscar en YouTube: {e}"  
        
    if "clima en" in user_input:    
        city = user_input.split("clima en")[-1].strip()    
        return get_weather(city)  
        
    if user_input.startswith("youtube "):    
        query = user_input.replace("youtube ", "").strip()    
        return search_youtube(query)  
        
    # Comandos de sistema    
    if "apaga la computadora" in user_input or "apaga el sistema" in user_input:    
        return shutdown()  
        
    if "reinicia la computadora" in user_input or "reinicia el sistema" in user_input:    
        return restart()  
        
    if "suspende la computadora" in user_input or "suspende el sistema" in user_input:    
        return suspend()  
        
    # Comandos de recordatorios    
    if "recuérdame" in user_input or "añade un recordatorio" in user_input:    
        activity = user_input.split("recuérdame")[-1].strip() if "recuérdame" in user_input else user_input.split("añade un recordatorio")[-1].strip()    
        return add_reminder(activity)  
            
    if "qué recordatorios tengo" in user_input or "cuál es mi agenda" in user_input:    
        return get_reminders()  
            
    if "he completado" in user_input or "elimina" in user_input:    
        activity = user_input.split("he completado")[-1].strip() if "he completado" in user_input else user_input.split("elimina")[-1].strip()    
        return remove_reminder(activity)  
        
    # Respuestas directas sin usar OpenAI    
    if user_input.startswith("soy "):    
        nombre = user_input[4:].strip()    
        if nombre:    
            save_user_data("nombre", nombre)    
            return f"Hola {nombre}, ¡mucho gusto en conocerte!"  
        
    if "cómo te llamas" in user_input or "cuál es tu nombre" in user_input:    
        return "Me llamo Ron."  
    if "quién te creó" in user_input or "quién es tu creador" in user_input:    
        return "Fui creado por Luis."  
    if "cómo me llamo" in user_input or "mi nombre" in user_input:    
        return "No tengo esa información guardada para usuarios web."  
        
    # Para conversación compleja, usar el historial del usuario    
    mensajes = construir_historial_usuario_openai(username)    
    mensajes.append({"role": "user", "content": original_input})    
        
    try:    
        respuesta = client.chat.completions.create(
            model="gpt-4o",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.7
        )
        gpt_response = respuesta.choices[0].message.content.strip()  
        ron_response = parse_and_execute_commands_dynamic(gpt_response)   
        ron_response = re.sub(r'[*_`~]', '', ron_response)     
    except Exception as e:    
        logger.error(f"Error con OpenAI: {e}")    
        ron_response = "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"    
        
    return ron_response  
  
def _process_user_input(user_input, save_to_memory=True):    
    """Función interna que procesa la entrada del usuario"""    
    original_input = user_input    
    user_input = user_input.lower().strip()    
        
    ron_nombre = get_user_data("ron_nombre") or "Ron"    
    creador = get_user_data("creador") or "Luis"    
        
    # DETECCIÓN DE DESPEDIDA SIMPLIFICADA    
    if detect_farewell_patterns(user_input):    
        response = "Hasta luego. Que tengas un buen día."    
        if save_to_memory:    
            add_to_memory(original_input, response)    
            logger.info("🔴 Despedida detectada - Bot terminando...")    
            print("🔴 Despedida detectada - Bot terminando...")    
        return response    
        
    # DETECCIÓN AUTOMÁTICA DE PROBLEMAS DEL SISTEMA    
    problem_keywords = ["problema en el sistema", "problema en la computadora","problema en la pc","problema en el equipo","no funciona", "error", "falla", "se cuelga", "no responde",    
                       "muy lento", "se traba", "no abre", "no carga", "internet no funciona",    
                       "no puedo imprimir", "no hay sonido", "pantalla azul"]    
            
    if any(keyword in user_input for keyword in problem_keywords):    
        if save_to_memory:    
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
                
        if save_to_memory:    
            add_to_memory(original_input, analysis)    
        return analysis    
        
    # COMANDOS DE DIAGNÓSTICO EXPLÍCITOS    
    if any(cmd in user_input for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):    
        result = diagnose_system_performance()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if any(cmd in user_input for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):    
        result = check_system_services()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if any(cmd in user_input for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):    
        result = restart_critical_services()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if any(cmd in user_input for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):    
        result = clean_temp_files()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if any(cmd in user_input for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):    
        result = flush_dns()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result  
  
    # COMANDOS DIRECTOS EXISTENTES (optimizados)    
    if user_input.startswith("abre "):    
        app_name = user_input.replace("abre ", "").strip()    
        result = open_application(app_name)    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if user_input.startswith("cierra "):    
        app_name = user_input.replace("cierra ", "").strip()    
        result = close_application(app_name)    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if user_input.startswith("investiga "):    
        query = user_input.replace("investiga ", "").strip()    
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"    
        webbrowser.open(url)    
        result = f"Investigando en Google: {query}"    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if user_input.startswith("reproducir ") or user_input.startswith("reproduce "):    
        query = user_input.replace("reproducir ", "").replace("reproduce ", "").strip()    
        try:    
            result = search_youtube(f"música {query}", play_video=True)    
            if save_to_memory:    
                add_to_memory(original_input, result)    
            return result    
        except Exception as e:    
            result = f"No pude buscar en YouTube: {e}"    
            if save_to_memory:    
                add_to_memory(original_input, result)    
            return result    
        
    if "clima en" in user_input:    
        city = user_input.split("clima en")[-1].strip()    
        result = get_weather(city)    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if user_input.startswith("youtube "):    
        query = user_input.replace("youtube ", "").strip()    
        result = search_youtube(query)    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    # Comandos de sistema    
    if "apaga la computadora" in user_input or "apaga el sistema" in user_input:    
        result = shutdown()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if "reinicia la computadora" in user_input or "reinicia el sistema" in user_input:    
        result = restart()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    if "suspende la computadora" in user_input or "suspende el sistema" in user_input:    
        result = suspend()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
        
    # Comandos de recordatorios    
    if "recuérdame" in user_input or "añade un recordatorio" in user_input:    
        activity = user_input.split("recuérdame")[-1].strip() if "recuérdame" in user_input else user_input.split("añade un recordatorio")[-1].strip()    
        result = add_reminder(activity)    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
            
    if "qué recordatorios tengo" in user_input or "cuál es mi agenda" in user_input:    
        result = get_reminders()    
        if save_to_memory:    
            add_to_memory(original_input, result)    
        return result    
            
    if "he completado" in user_input or "elimina" in user_input:    
        activity = user_input.split("he completado")[-1].strip() if "he completado" in user_input else user_input.split("elimina")[-1].strip()    
        result = remove_reminder(activity)    
        if save_to_memory:    
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
        respuesta = client.chat.completions.create(
            model="gpt-4o",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.7
        )
        gpt_response = respuesta.choices[0].message.content.strip()  
        ron_response = parse_and_execute_commands_dynamic(gpt_response)
        ron_response = re.sub(r'[*_`~]', '', ron_response)
    except Exception as e:
        logger.error(f"Error con OpenAI: {e}")
        ron_response = "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pregunta?"

    return ron_response
    
# FUNCIONES WRAPPER PARA COMPATIBILIDAD    
def responder_a_usuario(user_input):    
    """Para clientes de voz - guarda en memoria automáticamente"""    
    return _process_user_input(user_input, save_to_memory=True)    
    
def generate_response_no_memory(user_input):    
    """Para usuarios web - NO guarda en memoria automáticamente"""    
    return _process_user_input(user_input, save_to_memory=False)    
    
# Mantener el alias original para compatibilidad    

generate_response = responder_a_usuario






