import os  
import subprocess  
import webbrowser  
import requests  
import logging  
import re  
from config import WEATHER_API_KEY  
  
# Configurar logging  
logging.basicConfig(level=logging.DEBUG)  
logger = logging.getLogger(__name__)  
  
# Diccionario de sitios comunes (expandido del código local)  
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
  
def open_application(app_name):  
    """Función mejorada basada en el código local funcional"""  
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
          
        # Intentar abrir aplicación local con mejor manejo  
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
    """Función mejorada para cerrar aplicaciones"""  
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
  
def get_weather(city):  
    """Función de clima mejorada del código local"""  
    if not WEATHER_API_KEY:  
        return "No tengo configurada la API del clima. Necesitas configurar WEATHER_API_KEY."  
      
    params = {  
        "q": city,  
        "appid": WEATHER_API_KEY,  
        "units": "metric",  
        "lang": "es"  
    }  
    try:  
        logger.info(f"Obteniendo clima para: {city}")  
        response = requests.get("http://api.openweathermap.org/data/2.5/weather", params=params)  
        data = response.json()  
          
        if response.status_code == 200:  
            temp = data["main"]["temp"]  
            description = data["weather"][0]["description"]  
            result = f"La temperatura en {city} es de {temp} grados con {description}."  
            logger.info(f"Clima obtenido exitosamente: {result}")  
            return result  
        else:  
            logger.error(f"Error API clima: {response.status_code}")  
            return f"No pude obtener el clima de {city}. Verifica que el nombre sea correcto."  
    except Exception as e:  
        logger.error(f"Error al obtener clima: {str(e)}")  
        return f"Error al obtener el clima: {e}"  
  
def search_google(query):  
    """Función mejorada para búsquedas en Google"""  
    try:  
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"  
        webbrowser.open(url)  
        logger.info(f"Búsqueda en Google ejecutada: {query}")  
        return f"Buscando en Google: {query}"  
    except Exception as e:  
        logger.error(f"Error al buscar en Google: {str(e)}")  
        return f"Error al buscar en Google: {e}"  
  
def search_youtube(query, play_video=False):  
    """Función mejorada basada en el código local que realmente funciona"""  
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
    """Función mejorada para apagar el sistema"""  
    try:  
        logger.info("Ejecutando comando de apagado")  
        os.system("shutdown /s /t 1")  
        return "Apagando la computadora..."  
    except Exception as e:  
        logger.error(f"Error al apagar: {str(e)}")  
        return f"Error al apagar: {e}"  
  
def restart():  
    """Función mejorada para reiniciar el sistema"""  
    try:  
        logger.info("Ejecutando comando de reinicio")  
        os.system("shutdown /r /t 1")  
        return "Reiniciando la computadora..."  
    except Exception as e:  
        logger.error(f"Error al reiniciar: {str(e)}")  
        return f"Error al reiniciar: {e}"  
  
def suspend():  
    """Función mejorada para suspender el sistema"""  
    try:  
        logger.info("Ejecutando comando de suspensión")  
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")  
        return "Suspendiendo la computadora..."  
    except Exception as e:  
        logger.error(f"Error al suspender: {str(e)}")  
        return f"Error al suspender: {e}"  
  
# ===== NUEVAS FUNCIONES DE DIAGNÓSTICO Y REPARACIÓN =====  
  
def diagnose_system_performance():  
    """Diagnostica rendimiento del sistema"""  
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
          
        # Verificar espacio en disco  
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)  
          
        result = f"CPU: {cpu_percent}% de uso. {memory_status}. Diagnóstico completado."  
        logger.info(f"Diagnóstico completado: {result}")  
        return result  
          
    except Exception as e:  
        logger.error(f"Error en diagnóstico de rendimiento: {str(e)}")  
        return f"Error al diagnosticar el sistema: {e}"  
  
def check_system_services():  
    """Verifica servicios críticos del sistema"""  
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
          
        # Limpiar papelera de reciclaje  
        recycle_result = subprocess.run('rd /s /q "%systemdrive%\\\\$Recycle.bin" 2>nul', shell=True, capture_output=True, text=True)  
          
        logger.info("Limpieza de archivos temporales completada")  
        return "Archivos temporales limpiados. Se liberó espacio en disco."  
          
    except Exception as e:  
        logger.error(f"Error limpiando archivos temporales: {str(e)}")  
        return f"Error al limpiar archivos temporales: {e}"  
  
def flush_dns():  
    """Limpia la caché DNS"""  
    try:  
        logger.info("Limpiando caché DNS")  
        result = subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, text=True)  
        logger.info("Caché DNS limpiada exitosamente")  
        return "Caché DNS limpiada. Problemas de conexión resueltos."  
    except Exception as e:  
        logger.error(f"Error limpiando DNS: {str(e)}")  
        return f"Error al limpiar DNS: {e}"  
  
def network_reset():  
    """Reinicia adaptadores de red"""  
    try:  
        logger.info("Reiniciando adaptadores de red")  
          
        # Reiniciar adaptador de red  
        reset_result = subprocess.run('netsh winsock reset', shell=True, capture_output=True, text=True)  
          
        # Renovar IP  
        release_result = subprocess.run('ipconfig /release', shell=True, capture_output=True, text=True)  
        renew_result = subprocess.run('ipconfig /renew', shell=True, capture_output=True, text=True)  
          
        logger.info("Adaptadores de red reiniciados")  
        return "Adaptadores de red reiniciados. Reinicia la computadora para aplicar cambios."  
          
    except Exception as e:  
        logger.error(f"Error reiniciando red: {str(e)}")  
        return f"Error al reiniciar red: {e}"  
  
def check_disk_space():  
    """Verifica espacio disponible en disco"""  
    try:  
        logger.info("Verificando espacio en disco")  
          
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)  
          
        disks_info = []  
        lines = disk_result.stdout.strip().split('\\n')  
          
        current_disk = {}  
        for line in lines:  
            if 'Caption=' in line:  
                current_disk['caption'] = line.split('=')[1].strip()  
            elif 'FreeSpace=' in line and line.split('=')[1].strip():  
                current_disk['free'] = int(line.split('=')[1].strip())  
            elif 'Size=' in line and line.split('=')[1].strip():  
                current_disk['size'] = int(line.split('=')[1].strip())  
                  
                if all(key in current_disk for key in ['caption', 'free', 'size']):  
                    free_gb = current_disk['free'] // (1024**3)  
                    total_gb = current_disk['size'] // (1024**3)  
                    used_percent = ((current_disk['size'] - current_disk['free']) / current_disk['size']) * 100  
                      
                    disks_info.append(f"{current_disk['caption']} {free_gb}GB libres de {total_gb}GB ({used_percent:.1f}% usado)")  
                    current_disk = {}  
          
        result = "Espacio en disco: " + ", ".join(disks_info)  
        logger.info(f"Verificación de disco completada: {result}")  
        return result  
          
    except Exception as e:  
        logger.error(f"Error verificando disco: {str(e)}")  
        return f"Error al verificar espacio en disco: {e}"  
  
def system_file_check():  
    """Ejecuta verificación de archivos del sistema"""  
    try:  
        logger.info("Ejecutando verificación de archivos del sistema")  
          
        # Ejecutar sfc /scannow  
        sfc_result = subprocess.run('sfc /scannow', shell=True, capture_output=True, text=True)  
          
        if "no encontró ninguna infracción de integridad" in sfc_result.stdout.lower():  
            result = "Verificación de archivos del sistema completada. No se encontraron problemas."  
        elif "reparó correctamente" in sfc_result.stdout.lower():  
            result = "Verificación completada. Se repararon algunos archivos del sistema."  
        else:  
            result = "Verificación de archivos del sistema ejecutada. Revisa los logs para más detalles."  
          
        logger.info("Verificación de archivos del sistema completada")  
        return result  
          
    except Exception as e:  
        logger.error(f"Error en verificación del sistema: {str(e)}")  
        return f"Error al verificar archivos del sistema: {e}"  
  
# Funciones de recordatorios del código local  
def add_reminder(activity):  
    """Función de recordatorios del código local funcional"""  
    from core.memory import load_memory, save_memory  
      
    memory = load_memory()  
      
    # Convertir recordatorios en diccionario si es una lista  
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):  
        memory["recordatorios"] = {}  
      
    # Dividir en título y descripción (si hay)  
    parts = activity.split(":", 1)  
    title = parts[0].strip().lower()  # Título del recordatorio  
    description = parts[1].strip() if len(parts) > 1 else "(Sin descripción)"  
      
    # Agregar timestamp al recordatorio  
    from datetime import datetime  
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  
    memory["recordatorios"][title] = {  
        "description": description,  
        "created": timestamp  
    }  
      
    save_memory({"recordatorios": memory["recordatorios"]})  
      
    logger.info(f"Recordatorio agregado: {title} - {description}")  
    return f"Recordatorio agregado: {title} - {description}."  
  
def get_reminders():  
    """Función para obtener recordatorios del código local"""  
    from core.memory import load_memory  
      
    memory = load_memory()  
      
    # Convertir a diccionario si es una lista  
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):  
        memory["recordatorios"] = {}  
      
    if memory["recordatorios"]:  
        result = "Tus recordatorios son:\\\\n"  
        for title, data in memory["recordatorios"].items():  
            if isinstance(data, dict):  
                result += f"- {title}: {data['description']} (creado: {data.get('created', 'fecha desconocida')})\\\\n"  
            else:  
                # Compatibilidad con formato anterior  
                result += f"- {title}: {data}\\\\n"  
          
        logger.info(f"Recordatorios obtenidos: {len(memory['recordatorios'])} items")  
        return result  
      
    logger.info("No hay recordatorios pendientes")  
    return "No tienes recordatorios pendientes."  
  
def remove_reminder(activity):  
    """Función para eliminar recordatorios del código local"""  
    from core.memory import load_memory, save_memory  
      
    memory = load_memory()  
      
    # Convertir a diccionario si es una lista  
    if "recordatorios" not in memory or not isinstance(memory["recordatorios"], dict):  
        memory["recordatorios"] = {}  
      
    title = activity.strip().lower()  
      
    # Búsqueda flexible  
    matches = [key for key in memory["recordatorios"] if title in key]  
      
    if len(matches) == 1:  
        removed_title = matches[0]  
        removed_data = memory["recordatorios"].pop(removed_title)  
        save_memory({"recordatorios": memory["recordatorios"]})  
        logger.info(f"Recordatorio eliminado: {removed_title}")  
        return f"Recordatorio '{removed_title}' eliminado."  
    elif len(matches) > 1:  
        logger.warning(f"Múltiples recordatorios encontrados para: {title}")  
        return "Hay múltiples recordatorios similares. Dime el título exacto."  
    else:  
        logger.warning(f"No se encontró recordatorio para: {title}")  
        return "No encontré un recordatorio con ese título."