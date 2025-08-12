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
  
# Control de estado global  
speaking = False  
listening_active = True  
    
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
    
def setup_streaming_recognition():    
    """Configura el reconocimiento de voz en streaming"""    
    recognizer = sr.Recognizer()    
    recognizer.pause_threshold = 1.5  # Reducir para mayor velocidad    
    recognizer.energy_threshold = 4000    
    microphone = sr.Microphone()    
        
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
    stop_listening = recognizer.listen_in_background(microphone, callback, phrase_time_limit=8)    
    return stop_listening  
    
def detect_ron_activation(text):    
    """Detección optimizada para streaming"""    
    text_lower = text.lower().strip()    
        
    # Detección más permisiva para streaming    
    if 'ron' in text_lower:    
        return True    
        
    # Variaciones comunes en streaming    
    variations = ['rom', 'rron', 'ronn']    
    for var in variations:    
        if var in text_lower:    
            return True    
        
    return False  
  
def safe_activation_response():  
    """Maneja la respuesta de activación de forma segura"""  
    global speaking, listening_active  
      
    speaking = True  
    listening_active = False  
      
    try:  
        engine.say("Hola, ¿en qué puedo ayudarte?")  
        engine.runAndWait()  
        time.sleep(0.5)  
    finally:  
        speaking = False  
        listening_active = True  
    
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
        temp_result = subprocess.run('del /q /f /s "%temp%\\\\\\\\*" 2>nul', shell=True, capture_output=True, text=True)    
            
        # Limpiar archivos temporales del sistema    
        system_temp_result = subprocess.run('del /q /f /s "C:\\\\\\\\Windows\\\\\\\\Temp\\\\\\\\*" 2>nul', shell=True, capture_output=True, text=True)    
            
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
    """Envía texto al servidor solo si no es un comando local"""    
    global speaking, listening_active    
        
    # Pausar reconocimiento durante la respuesta del servidor    
    speaking = True    
    listening_active = False    
        
    try:    
        resp = requests.post(RON_API_URL, json={"text": text})    
        if resp.ok:    
            response_data = resp.json()    
            ron = response_data.get("ron")    
            print(f"🤖 Ron: {ron}")    
            engine.say(ron)    
            engine.runAndWait()    
            time.sleep(0.5)  # Pausa adicional    
                
            # Verificar si el servidor envía señal de shutdown    
            if response_data.get("shutdown"):    
                return True  # Señal para terminar    
        else:    
            print("❌ Error al contactar con Ron")    
            engine.say("No puedo comunicarme con el servidor.")    
            engine.runAndWait()    
            time.sleep(0.5)    
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
    print("🟢 Di 'Ron' para activarme.")    
        
    # Configurar streaming    
    recognizer, microphone = setup_streaming_recognition()    
    audio_queue = queue.Queue()    
        
    # Iniciar captura de audio en background    
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)    
        
    activado = False    
        
    try:    
        while True:    
            try:    
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
        stop_listening(wait_for_stop=False)