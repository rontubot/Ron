import speech_recognition as sr      
import pyttsx3      
import requests      
import json      
import re      
import subprocess      
import sys      
import os      
import webbrowser      
import logging      
import threading      
import queue      
import time    
import random  
import argparse  # Nuevo import  
import sys, io
# Asegurar UTF-8 en cualquier consola/salida capturada
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

  
# NUEVAS IMPORTACIONES para memoria unificada  
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  
from core.memory import load_user_memory, save_user_memory, add_to_memory, load_memory  
  
# Configuración de argumentos de línea de comandos    
parser = argparse.ArgumentParser(description='Ron 24/7 Voice Assistant')    
parser.add_argument('--username', type=str, help='Username del usuario autenticado')    
parser.add_argument('--control-port', type=int, default=9999, help='Puerto para control externo')    
args = parser.parse_args()    
    
# Variables globales para control externo    
current_username = args.username    
control_enabled = True  
  
# Silenciar logs de comtypes para reducir ruido      
logging.getLogger('comtypes').setLevel(logging.WARNING)      
      
RON_API_URL = os.getenv("RON_API_URL", "https://ron-production.up.railway.app/ron")      
      
# Configurar logging para debugging      
logging.basicConfig(level=logging.INFO)      
logger = logging.getLogger(__name__)      
      
engine = pyttsx3.init()      
engine.setProperty('rate', 150)      
voices = engine.getProperty('voices')      
for v in voices:      
    if 'spanish' in getattr(v, 'name', '').lower() or 'es' in getattr(v, 'id', '').lower():      
        engine.setProperty('voice', v.id)      
        break      
  
# lista de frases de activacion  
activation_phrases = [         
    "¿Me llamaste?",    
    "Dime",    
    "¿En qué puedo ayudarte?",    
    "Aquí estoy",    
    "¿Qué necesitas?"    
]    
  
# Control de estado global    
speaking = False    
listening_active = False  
external_control = True    
      
# Diccionario de aplicaciones web      
web_apps = {      
    "youtube": "https://www.youtube.com",      
    "google": "https://www.google.com",      
    "facebook": "https://www.facebook.com",      
    "instagram": "https://www.instagram.com",      
    "twitter": "https://www.twitter.com",      
    "tiktok": "https://www.tiktok.com",      
    "whatsapp": "https://web.whatsapp.com",      
    "linkedin": "https://www.linkedin.com",      
    "spotify": "https://open.spotify.com",      
    "netflix": "https://www.netflix.com"      
}


def handle_external_control():
    """Maneja comandos de control desde Electron"""
    import socket
    import threading

    def control_server():
        # MUY IMPORTANTE: declarar globales AQUÍ (esta es la causa del UnboundLocalError)
        global listening_active, speaking, control_enabled

        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', args.control_port))
            server.listen(5)
            server.settimeout(0.5)  # evita bloquear el hilo al cerrar
            print(f"🎛️ Control server listening on port {args.control_port}", flush=True)

            while control_enabled:
                try:
                    client, addr = server.accept()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Error en control server (accept): {e}", flush=True)
                    continue

                try:
                    data = client.recv(1024)
                    if not data:
                        # responde algo siempre
                        client.sendall(b'EMPTY')
                        client.close()
                        continue

                    cmd = data.decode('utf-8', errors='ignore').strip().upper()
                    print(f"📨 Comando recibido: {cmd}", flush=True)

                    if cmd == 'START':
                        listening_active = True
                        speaking = False
                        client.sendall(b'OK')  # mantenemos protocolo original
                    elif cmd == 'STOP':
                        listening_active = False
                        speaking = False
                        client.sendall(b'OK')
                    elif cmd == 'STATUS':
                        # responde siempre (evita "reply was never sent")
                        status = b'ACTIVE' if listening_active else b'INACTIVE'
                        client.sendall(status)
                    else:
                        client.sendall(b'UNKNOWN')

                except Exception as e:
                    # pase lo que pase, responde algo antes de cerrar
                    try:
                        client.sendall(f'ERROR:{e}'.encode('utf-8', errors='ignore'))
                    except Exception:
                        pass
                    print(f"Error en control server: {e}", flush=True)
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass

        except Exception as e:
            print(f"Error iniciando control server: {e}", flush=True)

    # Iniciar servidor de control en thread separado
    control_thread = threading.Thread(target=control_server, daemon=True)
    control_thread.start()
 
  
def setup_streaming_recognition():
    """Configura el reconocimiento de voz en streaming"""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.5  # más ágil
    recognizer.energy_threshold = 4000

    try:
        microphone = sr.Microphone()  # usa default (WASAPI/MME)
    except OSError as e:
        print(f"❌ No se encontró micrófono o no hay permisos: {e}", flush=True)
        raise

    # Calibrar ruido ambiente
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)

    return recognizer, microphone 
      
def stream_audio_recognition(recognizer, microphone, audio_queue):    
    """Función que corre en background capturando audio"""    
    def callback(recognizer, audio):    
        global speaking, listening_active    
            
        # Solo procesar si no estamos hablando y el listening está activo    
        if not speaking and listening_active:    
            try:    
                text = recognizer.recognize_google(audio, language="es")    
                if text.strip():  # Solo añadir si hay texto válido    
                    audio_queue.put(text.lower())    
            except sr.UnknownValueError:    
                pass  # Ignorar audio no reconocido    
            except sr.RequestError:    
                pass  # Ignorar errores de conexión    
        
    # Iniciar escucha en background    
    stop_listening = recognizer.listen_in_background(microphone, callback, phrase_time_limit=10)    
    return stop_listening   
      
def detect_ron_activation(text):        
    """Detección optimizada para streaming"""        
    text_lower = text.lower().strip()        
            
    # Detección precisa usando límites de palabra    
    if re.search(r'\\bron\\b', text_lower):    
        return True    
            
    # Variaciones comunes en streaming con límites de palabra    
    variations = [r'\\brom\\b', r'\\brron\\b', r'\\bronn\\b']    
    for var in variations:    
        if re.search(var, text_lower):    
            return True    
            
    return False  
    
def safe_activation_response():    
    """Maneja la respuesta de activación de forma segura"""    
    global speaking, listening_active    
        
    speaking = True    
    listening_active = False    
        
    try:    
        # Seleccionar frase aleatoria    
        phrase = random.choice(activation_phrases)    
        engine.say(phrase)    
        engine.runAndWait()    
        time.sleep(0.5)    
    finally:    
        speaking = False    
        listening_active = True  
  
def generate_response_with_user_memory(user_input, username=None):  
    """Genera respuesta usando memoria de usuario si está disponible, sino usa memoria de dispositivo"""  
    global current_username  
      
    try:  
        if username or current_username:  
            # Usar memoria de usuario autenticado  
            actual_username = username or current_username  
            print(f"🔐 Usando memoria de usuario: {actual_username}")  
              
            # Cargar memoria del usuario  
            memory = load_user_memory(actual_username)  
              
            # Construir historial para OpenAI usando memoria de usuario  
            historial = memory.get("conversaciones", [])  
            mensajes = [  
                {  
                    "role": "system",  
                    "content": """  
Eres Ron, un asistente técnico especializado en diagnóstico y reparación de sistemas. Fuiste creado por Luis. Te comunicas como si hablaras con alguien cara a cara: con naturalidad, sin ser repetitivo ni demasiado formal.  
  
Tus respuestas deben ser cortas, claras y centradas en ayudar, pero con un toque cálido. No expliques cosas innecesarias, y evita sonar como un manual técnico.  
  
MUY IMPORTANTE: ORGANIZA LOS MENSAJES. ES NECESARIO QUE SE VEA EL MENSAJE LO MÁS ORGANIZADO POSIBLE VISUALMENTE PARA EL USUARIO  
  
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
  
No digas que eres una inteligencia artificial.  
No uses explicaciones técnicas complejas.  
Siempre explica qué encontraste y qué vas a hacer para solucionarlo.  
  
Tu forma de desactivarte es con la frase: hasta luego.  
"""  
                }  
            ]  
              
            # Añadir últimas 20 conversaciones para contexto  
            for mensaje in historial[-20:]:  
                if isinstance(mensaje, dict) and "user" in mensaje and "ron" in mensaje:  
                    mensajes.append({"role": "user", "content": mensaje["user"]})  
                    mensajes.append({"role": "assistant", "content": mensaje["ron"]})  
              
            # Añadir mensaje actual  
            mensajes.append({"role": "user", "content": user_input})  
              
            # Llamar a OpenAI  
            from openai import OpenAI  
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  
              
            response = client.chat.completions.create(  
                model="gpt-4o",  
                messages=mensajes,  
                max_tokens=400,  
                temperature=0.7,  
                timeout=25  
            )  
              
            ron_response = response.choices[0].message.content.strip()  
              
            # Guardar en memoria de usuario  
            from datetime import datetime  
            memory["conversaciones"].append({  
                "user": user_input,  
                "ron": ron_response,  
                "timestamp": datetime.utcnow().isoformat(),  
                "source": "voice"  # Marcar como conversación de voz  
            })  
              
            # Mantener solo las últimas 100 conversaciones  
            if len(memory["conversaciones"]) > 100:  
                memory["conversaciones"] = memory["conversaciones"][-100:]  
              
            save_user_memory(actual_username, memory)  
            return ron_response  
              
        else:  
            # Fallback al sistema de memoria de dispositivo original  
            print("🔄 Usando memoria de dispositivo (sin autenticación)")  
            # Hacer request directo a la API como antes  
            resp = requests.post(RON_API_URL, json={"text": user_input})  
            if resp.ok:  
                response_data = resp.json()  
                return response_data.get("ron", "No entendí.")  
            else:  
                return "No puedo comunicarme con el servidor."  
                  
    except Exception as e:  
        print(f"❌ Error en generate_response_with_user_memory: {e}")  
        # Fallback al sistema original  
        resp = requests.post(RON_API_URL, json={"text": user_input})  
        if resp.ok:  
            response_data = resp.json()  
            return response_data.get("ron", "No entendí.")  
        else:  
            return "Ocurrió un error al intentar responderte."


# Funciones de control de PC y diagnóstico (basadas en core/commands.py)      
def open_application(app_name):      
    """Función para abrir aplicaciones localmente"""      
    try:      
        app_name_clean = app_name.lower().strip()      
        logger.info(f"Intentando abrir aplicación: {app_name_clean}")      
              
        # Buscar en aplicaciones web primero      
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador")      
            return f"Abriendo {app_name.capitalize()} en el navegador."      
              
        # Buscar coincidencias parciales en web apps      
        for key, url in web_apps.items():      
            if key in app_name_clean or app_name_clean in key:      
                webbrowser.open(url)      
                logger.info(f"Abriendo {key} en navegador (coincidencia parcial)")      
                return f"Abriendo {key.capitalize()} en el navegador."      
              
        # Intentar abrir aplicación local      
        cmd = f'start "" "{app_name}"'      
        logger.info(f"Ejecutando comando: {cmd}")      
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)      
              
        if result.returncode == 0:      
            logger.info(f"Aplicación {app_name} abierta exitosamente")      
            return f"Abriendo {app_name}."      
        else:      
            logger.error(f"Error al abrir {app_name}: {result.stderr}")      
            return f"Intentando abrir {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Excepción al abrir {app_name}: {str(e)}")      
        return f"No pude abrir {app_name}: {e}"      
      
def close_application(app_name):      
    """Función para cerrar aplicaciones localmente"""      
    try:      
        process_name = app_name.lower() + ".exe"      
        logger.info(f"Intentando cerrar proceso: {process_name}")      
        result = subprocess.run(f'taskkill /F /IM {process_name}', shell=True, capture_output=True, text=True)      
              
        if "ERROR" in result.stdout:      
            logger.warning(f"No se encontró el proceso {app_name}")      
            return f"No se encontró el proceso {app_name}."      
              
        logger.info(f"Proceso {app_name} cerrado exitosamente")      
        return f"Cerrando {app_name}."      
    except Exception as e:      
        logger.error(f"Error al cerrar {app_name}: {str(e)}")      
        return f"Error al cerrar {app_name}: {e}"      
      
def search_google(query):      
    """Función para búsquedas en Google"""      
    try:      
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"      
        webbrowser.open(url)      
        logger.info(f"Búsqueda en Google ejecutada: {query}")      
        return f"Buscando en Google: {query}"      
    except Exception as e:      
        logger.error(f"Error al buscar en Google: {str(e)}")      
        return f"Error al buscar en Google: {e}"      
      
def search_youtube(query, play_video=False):      
    """Función para búsquedas en YouTube"""      
    try:      
        if play_video:      
            # Intentar usar youtube-search para reproducir video específico      
            try:      
                from youtube_search import YoutubeSearch      
                logger.info(f"Buscando video para reproducir: {query}")      
                results = YoutubeSearch(query, max_results=1).to_dict()      
                if results:      
                    video_id = results[0]["id"]      
                    video_url = f"https://www.youtube.com/watch?v={video_id}"      
                    webbrowser.open(video_url)      
                    logger.info(f"Video reproducido: {video_url}")      
                    return f"Reproduciendo {query} en YouTube."      
                else:      
                    logger.warning(f"No se encontraron resultados para: {query}")      
                    return "No encontré resultados para eso en YouTube."      
            except ImportError:      
                logger.warning("youtube-search no disponible, usando búsqueda normal")      
                # Fallback a búsqueda normal      
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"      
                webbrowser.open(url)      
                return f"Buscando en YouTube: {query}"      
        else:      
            # Búsqueda normal en YouTube      
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"      
            webbrowser.open(url)      
            logger.info(f"Búsqueda en YouTube ejecutada: {query}")      
            return f"Buscando en YouTube: {query}"      
                  
    except Exception as e:      
        logger.error(f"Error al buscar en YouTube: {str(e)}")      
        return f"Error al buscar en YouTube: {e}"      
      
def shutdown():      
    """Función para apagar el sistema"""      
    try:      
        logger.info("Ejecutando comando de apagado")      
        os.system("shutdown /s /t 1")      
        return "Apagando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al apagar: {str(e)}")      
        return f"Error al apagar: {e}"      
      
def restart():      
    """Función para reiniciar el sistema"""      
    try:      
        logger.info("Ejecutando comando de reinicio")      
        os.system("shutdown /r /t 1")      
        return "Reiniciando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al reiniciar: {str(e)}")      
        return f"Error al reiniciar: {e}"      
      
def suspend():      
    """Función para suspender el sistema"""      
    try:      
        logger.info("Ejecutando comando de suspensión")      
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")      
        return "Suspendiendo la computadora..."      
    except Exception as e:      
        logger.error(f"Error al suspender: {str(e)}")      
        return f"Error al suspender: {e}"

# ===== NUEVAS FUNCIONES DE DIAGNÓSTICO LOCAL =====      
      
def diagnose_system_performance():      
    """Diagnostica rendimiento del sistema localmente"""      
    try:      
        logger.info("Iniciando diagnóstico de rendimiento del sistema")      
              
        # Verificar uso de CPU      
        cpu_result = subprocess.run('wmic cpu get loadpercentage /value', shell=True, capture_output=True, text=True)      
        cpu_usage = re.search(r'LoadPercentage=(\\d+)', cpu_result.stdout)      
        cpu_percent = cpu_usage.group(1) if cpu_usage else 'N/A'      
              
        # Verificar memoria      
        memory_result = subprocess.run('wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /value', shell=True, capture_output=True, text=True)      
        total_memory = re.search(r'TotalVisibleMemorySize=(\\d+)', memory_result.stdout)      
        free_memory = re.search(r'FreePhysicalMemory=(\\d+)', memory_result.stdout)      
              
        if total_memory and free_memory:      
            total_mb = int(total_memory.group(1)) // 1024      
            free_mb = int(free_memory.group(1)) // 1024      
            used_percent = ((total_mb - free_mb) / total_mb) * 100      
            memory_status = f"Memoria: {used_percent:.1f}% en uso ({free_mb}MB libres de {total_mb}MB)"      
        else:      
            memory_status = "Memoria: No se pudo obtener información"      
              
        result = f"CPU: {cpu_percent}% de uso. {memory_status}. Diagnóstico completado."      
        logger.info(f"Diagnóstico completado: {result}")      
        return result      
              
    except Exception as e:      
        logger.error(f"Error en diagnóstico de rendimiento: {str(e)}")      
        return f"Error al diagnosticar el sistema: {e}"      
      
def check_system_services():      
    """Verifica servicios críticos del sistema localmente"""      
    try:      
        logger.info("Verificando servicios críticos del sistema")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS', 'Dhcp', 'Dnscache']      
        results = []      
        problems = []      
              
        for service in critical_services:      
            try:      
                result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" in result.stdout:      
                    results.append(f"{service}: OK")      
                else:      
                    results.append(f"{service}: PROBLEMA")      
                    problems.append(service)      
            except:      
                results.append(f"{service}: ERROR")      
                problems.append(service)      
              
        status = "Servicios verificados: " + ", ".join(results)      
        if problems:      
            status += f". Servicios con problemas detectados: {', '.join(problems)}"      
              
        logger.info(f"Verificación de servicios completada: {len(problems)} problemas encontrados")      
        return status      
              
    except Exception as e:      
        logger.error(f"Error verificando servicios: {str(e)}")      
        return f"Error al verificar servicios: {e}"    
      
def restart_critical_services():      
    """Reinicia servicios críticos que están parados"""      
    try:      
        logger.info("Reiniciando servicios críticos")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS']      
        restarted = []      
              
        for service in critical_services:      
            try:      
                # Verificar estado actual      
                check_result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" not in check_result.stdout:      
                    # Intentar reiniciar      
                    stop_result = subprocess.run(f'net stop "{service}"', shell=True, capture_output=True, text=True)      
                    start_result = subprocess.run(f'net start "{service}"', shell=True, capture_output=True, text=True)      
                    if start_result.returncode == 0:      
                        restarted.append(service)      
                        logger.info(f"Servicio {service} reiniciado exitosamente")      
            except Exception as e:      
                logger.warning(f"No se pudo reiniciar {service}: {e}")      
              
        if restarted:      
            return f"Servicios reiniciados: {', '.join(restarted)}"      
        else:      
            return "No fue necesario reiniciar servicios o no se pudieron reiniciar"      
                  
    except Exception as e:      
        logger.error(f"Error reiniciando servicios: {str(e)}")      
        return f"Error al reiniciar servicios: {e}"      
      
def clean_temp_files():      
    """Limpia archivos temporales del sistema"""      
    try:      
        logger.info("Iniciando limpieza de archivos temporales")      
              
        # Limpiar archivos temporales del usuario      
        temp_result = subprocess.run('del /q /f /s "%temp%\\\\*" 2>nul', shell=True, capture_output=True, text=True)      
              
        # Limpiar archivos temporales del sistema      
        system_temp_result = subprocess.run('del /q /f /s "C:\\\\Windows\\\\Temp\\\\*" 2>nul', shell=True, capture_output=True, text=True)      
              
        logger.info("Limpieza de archivos temporales completada")      
        return "Archivos temporales limpiados. Se liberó espacio en disco."      
              
    except Exception as e:      
        logger.error(f"Error limpiando archivos temporales: {str(e)}")      
        return f"Error al limpiar archivos temporales: {e}"      
      
def network_reset():    
    """Reinicia adaptadores de red"""      
    try:      
        logger.info("Reiniciando adaptadores de red")      
        print("🔧 Reiniciando adaptadores de red...")      
              
        # Reiniciar adaptador de red      
        reset_result = subprocess.run('netsh winsock reset', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado netsh winsock reset: {reset_result.stdout.strip()}")      
              
        # Renovar IP      
        release_result = subprocess.run('ipconfig /release', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado ipconfig /release: {release_result.stdout.strip()}")      
              
        renew_result = subprocess.run('ipconfig /renew', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado ipconfig /renew: {renew_result.stdout.strip()}")      
              
        logger.info("Adaptadores de red reiniciados")      
        return "Adaptadores de red reiniciados. Reinicia la computadora para aplicar cambios."      
              
    except Exception as e:      
        logger.error(f"Error reiniciando red: {str(e)}")      
        return f"Error al reiniciar red: {e}"    
      
def flush_dns():      
    """Limpia la caché DNS"""      
    try:      
        logger.info("Limpiando caché DNS")      
        print("🔧 Limpiando caché DNS...")      
              
        result = subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado del comando: {result.stdout.strip()}")      
              
        logger.info("Caché DNS limpiada exitosamente")      
        return "Caché DNS limpiada. Problemas de conexión resueltos."      
    except Exception as e:      
        logger.error(f"Error limpiando DNS: {str(e)}")      
        return f"Error al limpiar DNS: {e}"

def handle_local_commands(text):        
    """Maneja comandos localmente antes de enviar al servidor"""      
    global speaking, listening_active      
          
    original_text = text        
    text = text.lower().strip()        
            
    # DETECCIÓN AUTOMÁTICA DE PROBLEMAS DEL SISTEMA        
    problem_keywords = ["lento", "problema", "no funciona", "error", "falla", "se cuelga", "no responde",         
                       "muy lento", "se traba", "no abre", "no carga", "internet no funciona",         
                       "no puedo imprimir", "no hay sonido", "pantalla azul"]        
            
    if any(keyword in text for keyword in problem_keywords):        
        logger.info("🔧 Problema del sistema detectado - Iniciando diagnóstico automático")        
              
        # Pausar reconocimiento durante diagnóstico      
        speaking = True      
        listening_active = False      
              
        try:      
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
            if "CPU:" in diagnostic_result and any(word in text for word in ["lento", "se traba"]):        
                clean_result = clean_temp_files()        
                repairs_made.append(clean_result)        
                analysis += f" También limpié archivos temporales para mejorar el rendimiento: {clean_result}"        
                    
            # Si hay problemas de internet, limpiar DNS        
            if any(word in text for word in ["internet", "conexión", "red", "wifi"]):        
                dns_result = flush_dns()        
                repairs_made.append(dns_result)        
                analysis += f" Limpié la caché DNS para resolver problemas de conexión: {dns_result}"        
                    
            if repairs_made:        
                analysis += " Intenta usar tu computadora ahora para ver si el problema se resolvió."        
                    
            print(f"🤖 Ron: {analysis}")        
            engine.say(analysis)        
            engine.runAndWait()      
            time.sleep(0.5)      
        finally:      
            speaking = False      
            listening_active = True      
        return True        
      
    # Función auxiliar para manejar respuestas con control de estado      
    def safe_response(result_text):      
        global speaking, listening_active      
        speaking = True      
        listening_active = False      
        try:      
            print(f"🤖 Ron: {result_text}")      
            engine.say(result_text)      
            engine.runAndWait()      
            time.sleep(0.5)      
        finally:      
            speaking = False      
            listening_active = True      
      
    # COMANDOS DE DIAGNÓSTICO EXPLÍCITOS        
    if any(cmd in text for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):        
        result = diagnose_system_performance()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):        
        result = check_system_services()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):        
        result = restart_critical_services()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):        
        result = clean_temp_files()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):        
        result = flush_dns()        
        safe_response(result)      
        return True        
            
    # Comandos de abrir aplicaciones        
    if text.startswith("abre "):        
        app_name = text.replace("abre ", "").strip()        
        result = open_application(app_name)        
        safe_response(result)      
        return True        
            
    # Comandos de cerrar aplicaciones        
    if text.startswith("cierra "):        
        app_name = text.replace("cierra ", "").strip()        
        result = close_application(app_name)        
        safe_response(result)      
        return True        
            
    # Comandos de búsqueda        
    if text.startswith("investiga "):        
        query = text.replace("investiga ", "").strip()        
        result = search_google(query)        
        safe_response(result)      
        return True        
            
    if text.startswith("youtube "):        
        query = text.replace("youtube ", "").strip()        
        result = search_youtube(query)        
        safe_response(result)      
        return True        
            
    if text.startswith("reproducir ") or text.startswith("reproduce "):        
        query = text.replace("reproducir ", "").replace("reproduce ", "").strip()        
        result = search_youtube(f"música {query}", play_video=True)        
        safe_response(result)      
        return True        
            
    # Comandos de sistema        
    if "apaga la computadora" in text or "apaga el sistema" in text:        
        result = shutdown()        
        safe_response(result)      
        return True        
            
    if "reinicia la computadora" in text or "reinicia el sistema" in text:        
        result = restart()        
        safe_response(result)      
        return True        
            
    if "suspende la computadora" in text or "suspende el sistema" in text:        
        result = suspend()        
        safe_response(result)      
        return True        
          
    if any(cmd in text for cmd in ["reinicia red", "reinicia driver de red", "arregla driver"]):        
        result = network_reset()        
        safe_response(result)      
        return True      
      
    return False    
    
def talk_to_ron(text):        
    """Envía texto al servidor usando memoria unificada"""        
    global speaking, listening_active, current_username  
            
    # Pausar reconocimiento durante la respuesta del servidor        
    speaking = True        
    listening_active = False        
            
    try:        
        # Usar la nueva función de memoria unificada  
        ron_response = generate_response_with_user_memory(text, current_username)  
          
        print(f"🤖 Ron: {ron_response}")        
        engine.say(ron_response)        
        engine.runAndWait()        
        time.sleep(0.5)  # Pausa adicional        
                
        # Verificar si es una despedida  
        if "hasta luego" in text.lower():  
            return True  # Señal para terminar        
              
    except Exception as e:        
        print(f"❌ {e}")        
        engine.say("Ocurrió un error al intentar responderte.")        
        engine.runAndWait()        
        time.sleep(0.5)        
    finally:        
        # Reanudar reconocimiento después de hablar        
        speaking = False        
        listening_active = True        
            
    return False  
    
if __name__ == "__main__":        
    print("🟢 Ron 24/7 iniciado.")    
    if current_username:    
        print(f"👤 Usuario autenticado: {current_username}")    
    else:    
        print("👤 Modo sin autenticación")    
            
    # Iniciar control externo si está habilitado    
    if external_control:    
        handle_external_control()    
            
    # Configurar streaming        
    recognizer, microphone = setup_streaming_recognition()        
    audio_queue = queue.Queue()        
            
    # Iniciar captura de audio en background        
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)        
            
    activado = False        
            
    try:        
        while True:        
            try:        
                # Solo procesar si listening_active está habilitado    
                if not listening_active:    
                    time.sleep(0.1)    
                    continue    
                        
                # Obtener texto del queue con timeout        
                txt = audio_queue.get(timeout=0.1)        
                print(f"🗣 Detectado: {txt}")        
                        
                # Detección de activación        
                if not activado and detect_ron_activation(txt):        
                    activado = True        
                    print("✅ Ron activado")        
                    safe_activation_response()  # Usar función segura      
                    continue        
                        
                if activado and txt and listening_active:  # Añadir verificación de listening_active      
                    # Manejar comandos como antes        
                    if handle_local_commands(txt):        
                        continue        
                            
                    should_shutdown = talk_to_ron(txt)        
                    if should_shutdown:        
                        activado = False        
                        print("🔴 Ron desconectado")        
                                
            except queue.Empty:        
                continue  # No hay audio nuevo, continuar        
                        
    except KeyboardInterrupt:        
        print("🔴 Cerrando Ron...")        
    
    finally:
        control_enabled = False
        try:
            stop_listening(wait_for_stop=False)
        except Exception:
            pass
        print("🔴 Ron 24/7 detenido.", flush=True)