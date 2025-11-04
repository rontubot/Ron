import os      
import subprocess      
import webbrowser      
import requests      
import logging      
import re      
import psutil    
import sys   
from config import WEATHER_API_KEY     
from core.memory import (    
    add_to_memory,    
    get_user_data,    
    save_user_data,    
    load_user_memory,    
    save_user_memory,    
    # recordatorios (nueva API por usuario)    
    add_reminder_item,    
    list_reminders,    
    update_reminder,    
    remove_reminder_item,    
)     
    
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
      
  
def get_nircmd_path():    
    """Obtiene la ruta a nircmd.exe según el entorno"""    
    # Si está empaquetado con Electron    
    if getattr(sys, 'frozen', False):    
        # Ruta en aplicación empaquetada    
        base_path = os.path.dirname(sys.executable)    
        nircmd_path = os.path.join(base_path, 'resources', 'bin', 'nircmd.exe')    
    else:    
        # Desarrollo: buscar en PATH o usar ruta relativa    
        nircmd_path = 'nircmd'  # Asume que está en PATH    
        
    return nircmd_path  
    
# FUNCIONES DE AUDIO CON SOPORTE DE PROGRESO  
    
def get_audio_processes():      
    """Enumera procesos que probablemente tengan audio activo (sin duplicados)"""      
    audio_apps = set()  # CAMBIO: usar set para evitar duplicados    
    common_audio_processes = [      
        'chrome.exe', 'firefox.exe', 'msedge.exe', 'brave.exe',    
        'spotify.exe', 'vlc.exe', 'wmplayer.exe', 'musicbee.exe',    
        'discord.exe', 'teams.exe', 'zoom.exe', 'slack.exe', 'youtube.exe',   
        'netflix.exe', 'whatsapp.exe',   
    ]      
          
    try:      
        for proc in psutil.process_iter(['name']):      
            proc_name = proc.info['name'].lower()      
            if proc_name in common_audio_processes:      
                audio_apps.add(proc.info['name'])  # CAMBIO: add en lugar de append    
    except Exception as e:      
        logger.error(f"Error enumerando procesos de audio: {e}")      
          
    return list(audio_apps)  # CAMBIO: convertir set a list  
      
def duck_other_applications(progress_callback=None):      
    """Reduce volumen de apps conocidas al 20%"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔊 Reduciendo volumen de otras aplicaciones...")  
        processes = get_audio_processes()      
            
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica    
          
        reduced_count = 0  
        for proc_name in processes:      
            send_progress(f"🔉 Ajustando volumen de {proc_name}...")  
            result = subprocess.run(      
                [nircmd_path, 'setappvolume', proc_name, '0.2'],      
                capture_output=True,      
                text=True,    
                timeout=2  # Evitar bloqueos    
            )      
            if result.returncode == 0:      
                logger.debug(f"Volumen reducido para {proc_name}")  
                reduced_count += 1  
            else:      
                logger.warning(f"No se pudo reducir volumen de {proc_name}")      
          
        send_progress(f"✅ Volumen reducido en {reduced_count} aplicaciones")  
        return {"ok": True, "message": f"Volumen reducido en {reduced_count} aplicaciones"}      
    except Exception as e:      
        logger.error(f"Error en duck_other_applications: {e}")      
        return {"ok": False, "error": str(e)}      
      
def restore_application_volumes(progress_callback=None):      
    """Restaura volumen de apps al 100%"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔊 Restaurando volumen de aplicaciones...")  
        processes = get_audio_processes()      
            
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica    
          
        restored_count = 0  
        for proc_name in processes:      
            send_progress(f"🔊 Restaurando volumen de {proc_name}...")  
            result = subprocess.run(      
                [nircmd_path, 'setappvolume', proc_name, '1.0'],      
                capture_output=True,      
                text=True,    
                timeout=2  # Evitar bloqueos    
            )      
            if result.returncode == 0:      
                logger.debug(f"Volumen restaurado para {proc_name}")  
                restored_count += 1  
          
        send_progress(f"✅ Volumen restaurado en {restored_count} aplicaciones")  
        return {"ok": True, "message": f"Volumen restaurado en {restored_count} aplicaciones"}      
    except Exception as e:      
        logger.error(f"Error en restore_application_volumes: {e}")      
        return {"ok": False, "error": str(e)}


def analyze_file(file_path, analysis_type="general", progress_callback=None):    
    """    
    Analiza un archivo y proporciona feedback inteligente.    
        
    Args:    
        file_path: Ruta al archivo a analizar    
        analysis_type: Tipo de análisis ("general", "code", "text", "improve")  
        progress_callback: Función opcional para enviar mensajes de progreso  
        
    Returns:    
        Dict con análisis del archivo    
    """    
    def send_progress(msg):  
        """Helper para enviar progreso si hay callback"""  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:    
        # Expandir ruta    
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))    
            
        if not os.path.exists(expanded_path):    
            return f"El archivo no existe: {expanded_path}"    
            
        send_progress(f"📂 Iniciando análisis de {os.path.basename(expanded_path)}...")  
        logger.info(f"Analizando archivo: {expanded_path}")    
            
        # Leer contenido del archivo    
        send_progress("📖 Leyendo contenido del archivo...")  
        try:    
            with open(expanded_path, 'r', encoding='utf-8') as f:    
                content = f.read()    
        except UnicodeDecodeError:    
            # Intentar con encoding alternativo    
            with open(expanded_path, 'r', encoding='latin-1') as f:    
                content = f.read()    
            
        # Obtener información del archivo    
        file_size = os.path.getsize(expanded_path)    
        file_ext = os.path.splitext(expanded_path)[1].lower()    
        line_count = len(content.split('\n'))    
          
        send_progress(f"📊 Archivo leído: {file_size} bytes, {line_count} líneas")  
            
        # Análisis básico    
        analysis = {    
            "file": expanded_path,    
            "size": f"{file_size} bytes",    
            "lines": line_count,    
            "extension": file_ext,    
            "content_preview": content[:500] if len(content) > 500 else content    
        }    
            
        # Análisis específico según tipo    
        send_progress("🔍 Analizando estructura del código...")  
        if analysis_type == "code" or file_ext in ['.py', '.js', '.java', '.cpp', '.c', '.ts', '.jsx', '.tsx']:    
            # Análisis de código    
            analysis["type"] = "code"    
            analysis["functions"] = len(re.findall(r'\bdef\s+\w+\(|\bfunction\s+\w+\(|\bclass\s+\w+', content))    
            analysis["comments"] = len(re.findall(r'#.*|//.*|/\*.*?\*/', content))    
            analysis["imports"] = len(re.findall(r'\bimport\s+|\bfrom\s+.*\bimport\b|\brequire\(', content))    
                
        elif analysis_type == "text" or file_ext in ['.txt', '.md', '.doc', '.docx']:    
            # Análisis de texto    
            analysis["type"] = "text"    
            words = content.split()    
            analysis["words"] = len(words)    
            analysis["characters"] = len(content)    
            analysis["paragraphs"] = len(content.split('\n\n'))    
                
        else:    
            # Análisis general    
            analysis["type"] = "general"    
            
        # Formatear resultado para el usuario    
        send_progress("✅ Análisis completado, generando reporte...")  
        result = f"Análisis de {os.path.basename(expanded_path)}:\n"    
        result += f"- Tamaño: {analysis['size']}\n"    
        result += f"- Líneas: {analysis['lines']}\n"    
            
        if analysis["type"] == "code":    
            result += f"- Funciones/Clases: {analysis['functions']}\n"    
            result += f"- Comentarios: {analysis['comments']}\n"    
            result += f"- Imports: {analysis['imports']}\n"    
        elif analysis["type"] == "text":    
            result += f"- Palabras: {analysis['words']}\n"    
            result += f"- Caracteres: {analysis['characters']}\n"    
            result += f"- Párrafos: {analysis['paragraphs']}\n"    
            
        # Agregar preview del contenido    
        result += f"\nVista previa:\n{analysis['content_preview']}"    
            
        if len(content) > 500:    
            result += "\n...(contenido truncado)"    
          
        send_progress("📋 Reporte completo generado")  
        return result    
            
    except Exception as e:    
        logger.error(f"Error analizando archivo: {str(e)}")    
        return f"Error analizando archivo: {e}"  
  
  
def _username(ctx: dict, params: dict | None = None) -> str:    
    """    
    Obtiene el username de:    
    - params["username"]    
    - ctx["username"] o ctx["user"]    
    - (fallback) algo como 'default'    
    """    
    if params and isinstance(params, dict) and params.get("username"):    
        return str(params["username"]).strip()    
    if ctx and isinstance(ctx, dict):    
        if ctx.get("username"):    
            return str(ctx["username"]).strip()    
        if ctx.get("user"):    
            return str(ctx["user"]).strip()    
    return "default"  
  
  
def open_application(app_name, progress_callback=None):      
    """Función mejorada basada en el código local funcional"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        app_name_clean = app_name.lower().strip()      
        send_progress(f"🚀 Intentando abrir {app_name_clean}...")  
        logger.info(f"Intentando abrir aplicación: {app_name_clean}")      
              
        # Buscar en aplicaciones web primero      
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador")  
            send_progress(f"✅ {app_name.capitalize()} abierto en el navegador")  
            return f"Abriendo {app_name.capitalize()} en el navegador."      
              
        # Buscar coincidencias parciales en web apps      
        for key, url in web_apps.items():      
            if key in app_name_clean or app_name_clean in key:      
                webbrowser.open(url)      
                logger.info(f"Abriendo {key} en navegador (coincidencia parcial)")  
                send_progress(f"✅ {key.capitalize()} abierto en el navegador")  
                return f"Abriendo {key.capitalize()} en el navegador."      
              
        # Intentar abrir aplicación local con mejor manejo      
        cmd = f'start "" "{app_name}"'      
        logger.info(f"Ejecutando comando: {cmd}")      
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)      
              
        if result.returncode == 0:      
            logger.info(f"Aplicación {app_name} abierta exitosamente")  
            send_progress(f"✅ {app_name} abierto exitosamente")  
            return f"Abriendo {app_name}."      
        else:      
            logger.error(f"Error al abrir {app_name}: {result.stderr}")  
            send_progress(f"⚠️ Intentando abrir {app_name}...")  
            return f"Intentando abrir {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Excepción al abrir {app_name}: {str(e)}")      
        return f"No pude abrir {app_name}: {e}"  
  
  
def close_application(app_name, progress_callback=None):      
    """Cierra una aplicación por nombre"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🔴 Cerrando {app_name}...")  
        logger.info(f"Intentando cerrar aplicación: {app_name}")      
        cmd = f'taskkill /IM "{app_name}.exe" /F'      
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)      
              
        if result.returncode == 0:      
            logger.info(f"Aplicación {app_name} cerrada exitosamente")  
            send_progress(f"✅ {app_name} cerrado exitosamente")  
            return f"{app_name} cerrado."      
        else:      
            logger.error(f"Error al cerrar {app_name}: {result.stderr}")  
            send_progress(f"⚠️ No se pudo cerrar {app_name}")  
            return f"No pude cerrar {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Excepción al cerrar {app_name}: {str(e)}")      
        return f"Error al cerrar {app_name}: {e}"  
  
  
def try_web_fallback(app_name, progress_callback=None):      
    """Intenta abrir versión web de una aplicación"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        app_name_clean = app_name.lower().strip()      
        send_progress(f"🌐 Buscando versión web de {app_name_clean}...")  
        logger.info(f"Intentando fallback web para: {app_name_clean}")      
              
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador (fallback)")  
            send_progress(f"✅ {app_name.capitalize()} abierto en navegador")  
            return f"Abriendo {app_name.capitalize()} en el navegador."      
        else:      
            logger.warning(f"No hay fallback web para {app_name_clean}")  
            send_progress(f"⚠️ No hay versión web disponible para {app_name_clean}")  
            return f"No tengo una versión web para {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Error en fallback web: {str(e)}")      
        return f"Error al intentar abrir versión web: {e}"


 def search_google(query, progress_callback=None):      
    """Busca en Google"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🔍 Buscando en Google: {query}")  
        logger.info(f"Buscando en Google: {query}")      
        search_url = f"https://www.google.com/search?q={query}"      
        webbrowser.open(search_url)      
        send_progress(f"✅ Búsqueda abierta en navegador")  
        return f"Buscando '{query}' en Google."      
    except Exception as e:      
        logger.error(f"Error buscando en Google: {str(e)}")      
        return f"Error al buscar en Google: {e}"  
  
  
def search_youtube(query, play_video=False, progress_callback=None):      
    """Busca y opcionalmente reproduce un video de YouTube"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🎥 Buscando en YouTube: {query}")  
        logger.info(f"Buscando en YouTube: {query}")      
              
        if play_video:      
            send_progress("🔍 Buscando video específico...")  
            # Intentar usar youtube-search para reproducir video específico      
            try:      
                from youtube_search import YoutubeSearch      
                results = YoutubeSearch(query, max_results=1).to_dict()      
                      
                if results:      
                    video_id = results[0]['id']      
                    video_url = f"https://www.youtube.com/watch?v={video_id}"      
                    send_progress(f"▶️ Reproduciendo video...")  
                    webbrowser.open(video_url)      
                    logger.info(f"Reproduciendo video: {video_url}")      
                    send_progress(f"✅ Video abierto en navegador")  
                    return f"Reproduciendo '{query}' en YouTube."      
            except ImportError:      
                logger.warning("youtube-search no disponible, usando búsqueda simple")      
                      
        # Búsqueda simple      
        search_url = f"https://www.youtube.com/results?search_query={query}"      
        webbrowser.open(search_url)      
        send_progress(f"✅ Búsqueda abierta en YouTube")  
        return f"Buscando '{query}' en YouTube."      
              
    except Exception as e:      
        logger.error(f"Error buscando en YouTube: {str(e)}")      
        return f"Error al buscar en YouTube: {e}"  
  
  
def get_weather(city, progress_callback=None):      
    """Obtiene el clima de una ciudad"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🌤️ Consultando clima de {city}...")  
        logger.info(f"Obteniendo clima para: {city}")      
        api_key = WEATHER_API_KEY      
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=es"      
              
        send_progress("📡 Conectando con servicio meteorológico...")  
        response = requests.get(url, timeout=5)      
        data = response.json()      
              
        if response.status_code == 200:      
            temp = data['main']['temp']      
            description = data['weather'][0]['description']      
            humidity = data['main']['humidity']      
            result = f"En {city}: {temp}°C, {description}. Humedad: {humidity}%"      
            logger.info(f"Clima obtenido: {result}")      
            send_progress(f"✅ {result}")  
            return result      
        else:      
            error_msg = f"No pude obtener el clima de {city}"      
            logger.error(f"Error API clima: {data.get('message', 'Unknown')}")      
            send_progress(f"⚠️ {error_msg}")  
            return error_msg      
                  
    except Exception as e:      
        logger.error(f"Error obteniendo clima: {str(e)}")      
        return f"Error al obtener el clima: {e}"  
  
  
def shutdown(progress_callback=None):      
    """Función mejorada para apagar el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("⚠️ Apagando el sistema en 1 segundo...")  
        logger.info("Ejecutando comando de apagado")      
        os.system("shutdown /s /t 1")      
        send_progress("🔴 Sistema apagándose...")  
        return "Apagando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al apagar: {str(e)}")      
        return f"Error al apagar: {e}"      
      
def restart(progress_callback=None):      
    """Función mejorada para reiniciar el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("⚠️ Reiniciando el sistema en 1 segundo...")  
        logger.info("Ejecutando comando de reinicio")      
        os.system("shutdown /r /t 1")      
        send_progress("🔄 Sistema reiniciándose...")  
        return "Reiniciando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al reiniciar: {str(e)}")      
        return f"Error al reiniciar: {e}"      
      
def suspend(progress_callback=None):      
    """Función mejorada para suspender el sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("💤 Suspendiendo el sistema...")  
        logger.info("Ejecutando comando de suspensión")      
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")      
        send_progress("✅ Sistema suspendido")  
        return "Suspendiendo la computadora..."      
    except Exception as e:      
        logger.error(f"Error al suspender: {str(e)}")      
        return f"Error al suspender: {e}"  
  
  
def set_volume(level, progress_callback=None):      
    """Ajusta el volumen del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"🔊 Ajustando volumen al {level}%...")  
        logger.info(f"Ajustando volumen al {level}%")      
              
        # Convertir porcentaje a valor 0-100      
        if isinstance(level, str):      
            level = int(level.replace('%', ''))      
              
        # Usar pycaw (requiere pip install pycaw comtypes)      
        from ctypes import cast, POINTER      
        from comtypes import CLSCTX_ALL      
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume      
              
        devices = AudioUtilities.GetSpeakers()      
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)      
        volume = cast(interface, POINTER(IAudioEndpointVolume))      
        volume.SetMasterVolumeLevelScalar(level / 100, None)      
              
        send_progress(f"✅ Volumen ajustado al {level}%")  
        return f"Volumen ajustado al {level}%"      
              
    except Exception as e:      
        logger.error(f"Error ajustando volumen: {str(e)}")      
        return f"Error ajustando volumen: {e}"



def create_file(file_path, content="", progress_callback=None):        
    """Crea un archivo con contenido opcional"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:        
        # NUEVO: Limpiar símbolos <> si el modelo los generó incorrectamente    
        file_path = file_path.replace('<ESCRITORIO>', 'escritorio')    
        file_path = file_path.replace('<DOCUMENTOS>', 'documentos')    
        file_path = file_path.replace('<DESCARGAS>', 'descargas')    
        file_path = file_path.replace('<IMAGENES>', 'imagenes')    
        file_path = file_path.replace('<MUSICA>', 'musica')    
        file_path = file_path.replace('<VIDEOS>', 'videos')    
            
        send_progress(f"📝 Creando archivo: {file_path}")  
        logger.info(f"Creando archivo: {file_path}")        
            
        # Expandir ruta    
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))    
            
        # Si es un nombre de ubicación estándar, resolverlo    
        if "/" in file_path or "\\" in file_path:    
            parts = file_path.split("/") if "/" in file_path else file_path.split("\\")    
            first_part = parts[0].lower()    
                
            standard_locations = {    
                "escritorio": os.path.join(os.path.expanduser("~"), "Desktop"),    
                "documentos": os.path.join(os.path.expanduser("~"), "Documents"),    
                "descargas": os.path.join(os.path.expanduser("~"), "Downloads"),    
                "imagenes": os.path.join(os.path.expanduser("~"), "Pictures"),    
                "musica": os.path.join(os.path.expanduser("~"), "Music"),    
                "videos": os.path.join(os.path.expanduser("~"), "Videos"),    
            }    
                
            if first_part in standard_locations:    
                # Reemplazar primera parte con ruta real    
                parts[0] = standard_locations[first_part]    
                expanded_path = os.path.join(*parts)    
          
        send_progress("📁 Creando directorio padre si es necesario...")  
        # Crear directorio padre si no existe        
        os.makedirs(os.path.dirname(expanded_path), exist_ok=True)        
          
        send_progress("✍️ Escribiendo contenido del archivo...")  
        with open(expanded_path, 'w', encoding='utf-8') as f:        
            f.write(content)        
          
        send_progress(f"✅ Archivo creado exitosamente: {expanded_path}")  
        return f"Archivo creado: {expanded_path}"        
                
    except Exception as e:        
        logger.error(f"Error creando archivo: {str(e)}")        
        return f"Error creando archivo: {e}"  
  
  
def create_folder(folder_path, progress_callback=None):        
    """Crea una carpeta"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:        
        # NUEVO: Limpiar símbolos <> si el modelo los generó incorrectamente    
        folder_path = folder_path.replace('<ESCRITORIO>', 'escritorio')    
        folder_path = folder_path.replace('<DOCUMENTOS>', 'documentos')    
        folder_path = folder_path.replace('<DESCARGAS>', 'descargas')    
        folder_path = folder_path.replace('<IMAGENES>', 'imagenes')    
        folder_path = folder_path.replace('<MUSICA>', 'musica')    
        folder_path = folder_path.replace('<VIDEOS>', 'videos')    
            
        send_progress(f"📁 Creando carpeta: {folder_path}")  
        logger.info(f"Creando carpeta: {folder_path}")        
            
        # Expandir ruta    
        expanded_path = os.path.expandvars(os.path.expanduser(folder_path))    
            
        # Si es un nombre de ubicación estándar, resolverlo    
        if "/" in folder_path or "\\" in folder_path:    
            parts = folder_path.split("/") if "/" in folder_path else folder_path.split("\\")    
            first_part = parts[0].lower()    
                
            standard_locations = {    
                "escritorio": os.path.join(os.path.expanduser("~"), "Desktop"),    
                "documentos": os.path.join(os.path.expanduser("~"), "Documents"),    
                "descargas": os.path.join(os.path.expanduser("~"), "Downloads"),    
                "imagenes": os.path.join(os.path.expanduser("~"), "Pictures"),    
                "musica": os.path.join(os.path.expanduser("~"), "Music"),    
                "videos": os.path.join(os.path.expanduser("~"), "Videos"),    
            }    
                
            if first_part in standard_locations:    
                # Reemplazar primera parte con ruta real    
                parts[0] = standard_locations[first_part]    
                expanded_path = os.path.join(*parts)    
          
        send_progress("🔨 Creando estructura de directorios...")  
        os.makedirs(expanded_path, exist_ok=True)        
        send_progress(f"✅ Carpeta creada exitosamente: {expanded_path}")  
        return f"Carpeta creada: {expanded_path}"        
                
    except Exception as e:        
        logger.error(f"Error creando carpeta: {str(e)}")        
        return f"Error creando carpeta: {e}"    
      
def move_file(source, destination, progress_callback=None):        
    """Mueve un archivo de origen a destino"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:        
        # NUEVO: Expandir variables de entorno y rutas de usuario    
        expanded_source = os.path.expandvars(os.path.expanduser(source))    
        expanded_dest = os.path.expandvars(os.path.expanduser(destination))    
            
        send_progress(f"📦 Moviendo archivo de {expanded_source} a {expanded_dest}")  
        logger.info(f"Moviendo archivo de {expanded_source} a {expanded_dest}")        
                
        import shutil        
          
        send_progress("📁 Verificando directorio destino...")  
        # Crear directorio destino si no existe        
        os.makedirs(os.path.dirname(expanded_dest), exist_ok=True)        
          
        send_progress("🚚 Moviendo archivo...")  
        shutil.move(expanded_source, expanded_dest)        
          
        send_progress(f"✅ Archivo movido exitosamente")  
        return f"Archivo movido de {expanded_source} a {expanded_dest}"        
                
    except Exception as e:        
        logger.error(f"Error moviendo archivo: {str(e)}")        
        return f"Error moviendo archivo: {e}"     
      
def copy_file(source, destination, progress_callback=None):        
    """Copia un archivo de origen a destino"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:        
        # NUEVO: Expandir variables de entorno y rutas de usuario    
        expanded_source = os.path.expandvars(os.path.expanduser(source))    
        expanded_dest = os.path.expandvars(os.path.expanduser(destination))    
            
        send_progress(f"📋 Copiando archivo de {expanded_source} a {expanded_dest}")  
        logger.info(f"Copiando archivo de {expanded_source} a {expanded_dest}")        
                
        import shutil        
          
        send_progress("📁 Verificando directorio destino...")  
        # Crear directorio destino si no existe        
        os.makedirs(os.path.dirname(expanded_dest), exist_ok=True)        
          
        send_progress("📄 Copiando archivo...")  
        shutil.copy2(expanded_source, expanded_dest)        
          
        send_progress(f"✅ Archivo copiado exitosamente")  
        return f"Archivo copiado de {expanded_source} a {expanded_dest}"        
                
    except Exception as e:        
        logger.error(f"Error copiando archivo: {str(e)}")        
        return f"Error copiando archivo: {e}"  
  
  
def create_shortcut(target, shortcut_path, progress_callback=None):  
    """Crea un acceso directo"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:  
        send_progress(f"🔗 Creando acceso directo a {target}")  
        logger.info(f"Creando acceso directo: {shortcut_path} -> {target}")  
          
        import win32com.client  
        shell = win32com.client.Dispatch("WScript.Shell")  
        shortcut = shell.CreateShortCut(shortcut_path)  
        shortcut.Targetpath = target  
        shortcut.save()  
          
        send_progress(f"✅ Acceso directo creado exitosamente")  
        return f"Acceso directo creado: {shortcut_path}"  
    except Exception as e:  
        logger.error(f"Error creando acceso directo: {str(e)}")  
        return f"Error creando acceso directo: {e}"  
  
  
def delete_file(file_path, progress_callback=None):  
    """Elimina un archivo"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:  
        send_progress(f"🗑️ Eliminando archivo: {file_path}")  
        logger.info(f"Eliminando archivo: {file_path}")  
          
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))  
        os.remove(expanded_path)  
          
        send_progress(f"✅ Archivo eliminado exitosamente")  
        return f"Archivo eliminado: {expanded_path}"  
    except Exception as e:  
        logger.error(f"Error eliminando archivo: {str(e)}")  
        return f"Error eliminando archivo: {e}"  
  
  
def list_files(directory_path, progress_callback=None):      
    """Lista archivos en un directorio"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress(f"📂 Listando archivos en: {directory_path}")  
        logger.info(f"Listando archivos en: {directory_path}")      
              
        import os      
        files = os.listdir(directory_path)      
          
        send_progress(f"📊 Encontrados {len(files)} archivos")  
              
        if files:      
            file_list = "\\n".join(files[:20])  # Limitar a 20 archivos      
            send_progress(f"✅ Lista generada")  
            return f"Archivos en {directory_path}:\\n{file_list}"      
        else:      
            send_progress(f"⚠️ Directorio vacío")  
            return f"No hay archivos en {directory_path}"      
                  
    except Exception as e:      
        logger.error(f"Error listando archivos: {str(e)}")      
        return f"Error listando archivos: {e}"  
  
  
def diagnose_system_performance(progress_callback=None):      
    """Diagnostica rendimiento del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Iniciando diagnóstico de rendimiento del sistema...")  
        logger.info("Iniciando diagnóstico de rendimiento del sistema")      
          
        # Verificar uso de CPU  
        send_progress("📊 Verificando uso de CPU...")  
        cpu_result = subprocess.run('wmic cpu get loadpercentage /value', shell=True, capture_output=True, text=True)      
        cpu_usage = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)      
        cpu_percent = cpu_usage.group(1) if cpu_usage else 'N/A'      
          
        # Verificar memoria  
        send_progress("💾 Verificando memoria RAM...")  
        memory_result = subprocess.run('wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /value', shell=True, capture_output=True, text=True)      
        total_memory = re.search(r'TotalVisibleMemorySize=(\d+)', memory_result.stdout)      
        free_memory = re.search(r'FreePhysicalMemory=(\d+)', memory_result.stdout)      
              
        if total_memory and free_memory:      
            total_mb = int(total_memory.group(1)) // 1024      
            free_mb = int(free_memory.group(1)) // 1024      
            used_percent = ((total_mb - free_mb) / total_mb) * 100      
            memory_status = f"Memoria: {used_percent:.1f}% en uso ({free_mb}MB libres de {total_mb}MB)"      
        else:      
            memory_status = "Memoria: No se pudo obtener información"      
          
        # Verificar espacio en disco  
        send_progress("💿 Verificando espacio en disco...")  
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)      
              
        result = f"CPU: {cpu_percent}% de uso. {memory_status}. Diagnóstico completado."      
        logger.info(f"Diagnóstico completado: {result}")      
        send_progress(f"✅ {result}")  
        return result      
              
    except Exception as e:      
        logger.error(f"Error en diagnóstico de rendimiento: {str(e)}")      
        return f"Error al diagnosticar el sistema: {e}"


def check_system_services(progress_callback=None):      
    """Verifica servicios críticos del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Verificando servicios críticos del sistema...")  
        logger.info("Verificando servicios críticos del sistema")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS', 'Dhcp', 'Dnscache']      
        results = []      
        problems = []      
          
        for service in critical_services:      
            send_progress(f"⚙️ Verificando servicio: {service}")  
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
          
        send_progress(f"✅ Verificación completada: {len(problems)} problemas encontrados")  
        logger.info(f"Verificación de servicios completada: {len(problems)} problemas encontrados")      
        return status      
              
    except Exception as e:      
        logger.error(f"Error verificando servicios: {str(e)}")      
        return f"Error al verificar servicios: {e}"      
      
def restart_critical_services(progress_callback=None):      
    """Reinicia servicios críticos que están parados"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔄 Reiniciando servicios críticos...")  
        logger.info("Reiniciando servicios críticos")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS']      
        restarted = []      
          
        for service in critical_services:      
            send_progress(f"⚙️ Procesando servicio: {service}")  
            try:      
                # Verificar estado actual      
                check_result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" not in check_result.stdout:      
                    send_progress(f"🔧 Reiniciando {service}...")  
                    # Intentar reiniciar      
                    stop_result = subprocess.run(f'net stop "{service}"', shell=True, capture_output=True, text=True)      
                    start_result = subprocess.run(f'net start "{service}"', shell=True, capture_output=True, text=True)      
                    if start_result.returncode == 0:      
                        restarted.append(service)      
                        logger.info(f"Servicio {service} reiniciado exitosamente")  
                        send_progress(f"✅ {service} reiniciado exitosamente")  
            except Exception as e:      
                logger.warning(f"No se pudo reiniciar {service}: {e}")      
          
        if restarted:      
            result = f"Servicios reiniciados: {', '.join(restarted)}"  
        else:      
            result = "No fue necesario reiniciar servicios o no se pudieron reiniciar"  
          
        send_progress(f"✅ Proceso completado")  
        return result      
              
    except Exception as e:      
        logger.error(f"Error reiniciando servicios: {str(e)}")      
        return f"Error al reiniciar servicios: {e}"      
      
def clean_temp_files(progress_callback=None):      
    """Limpia archivos temporales del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🧹 Iniciando limpieza de archivos temporales...")  
        logger.info("Limpiando archivos temporales")      
          
        send_progress("📁 Limpiando carpeta Temp de Windows...")  
        temp_result = subprocess.run('del /q /f /s %TEMP%\\*', shell=True, capture_output=True, text=True)      
          
        send_progress("📁 Limpiando carpeta Prefetch...")  
        prefetch_result = subprocess.run('del /q /f /s C:\\Windows\\Prefetch\\*', shell=True, capture_output=True, text=True)      
          
        send_progress("✅ Limpieza de archivos temporales completada")  
        return "Archivos temporales limpiados exitosamente."      
              
    except Exception as e:      
        logger.error(f"Error limpiando archivos temporales: {str(e)}")      
        return f"Error al limpiar archivos temporales: {e}"      
      
def flush_dns(progress_callback=None):      
    """Limpia la caché DNS"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🌐 Limpiando caché DNS...")  
        logger.info("Limpiando caché DNS")      
        result = subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, text=True)      
          
        if result.returncode == 0:      
            send_progress("✅ Caché DNS limpiada exitosamente")  
            return "Caché DNS limpiada exitosamente."      
        else:      
            send_progress("⚠️ Error al limpiar caché DNS")  
            return "Error al limpiar caché DNS."      
                  
    except Exception as e:      
        logger.error(f"Error limpiando DNS: {str(e)}")      
        return f"Error al limpiar DNS: {e}"      
      
def network_reset(progress_callback=None):      
    """Reinicia la configuración de red"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🌐 Reiniciando configuración de red...")  
        logger.info("Reiniciando configuración de red")      
          
        send_progress("🔄 Ejecutando netsh winsock reset...")  
        winsock_result = subprocess.run('netsh winsock reset', shell=True, capture_output=True, text=True)      
          
        send_progress("🔄 Ejecutando netsh int ip reset...")  
        ip_result = subprocess.run('netsh int ip reset', shell=True, capture_output=True, text=True)      
          
        send_progress("✅ Configuración de red reiniciada. Se recomienda reiniciar el sistema.")  
        return "Configuración de red reiniciada. Se recomienda reiniciar el sistema."      
              
    except Exception as e:      
        logger.error(f"Error reiniciando red: {str(e)}")      
        return f"Error al reiniciar red: {e}"      
      
def check_disk_space(progress_callback=None):      
    """Verifica el espacio disponible en disco"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("💿 Verificando espacio en disco...")  
        logger.info("Verificando espacio en disco")      
          
        disk_result = subprocess.run('wmic logicaldisk get size,freespace,caption /value', shell=True, capture_output=True, text=True)      
          
        # Parsear resultados  
        disks = []  
        lines = disk_result.stdout.split('\n')  
        current_disk = {}  
          
        for line in lines:  
            if 'Caption=' in line:  
                current_disk['caption'] = line.split('=')[1].strip()  
            elif 'FreeSpace=' in line:  
                try:  
                    free_bytes = int(line.split('=')[1].strip())  
                    current_disk['free_gb'] = free_bytes / (1024**3)  
                except:  
                    pass  
            elif 'Size=' in line:  
                try:  
                    size_bytes = int(line.split('=')[1].strip())  
                    current_disk['size_gb'] = size_bytes / (1024**3)  
                    if 'free_gb' in current_disk and 'caption' in current_disk:  
                        disks.append(current_disk)  
                        current_disk = {}  
                except:  
                    pass  
          
        result = "Espacio en disco:\n"  
        for disk in disks:  
            used_percent = ((disk['size_gb'] - disk['free_gb']) / disk['size_gb']) * 100  
            result += f"{disk['caption']}: {disk['free_gb']:.1f}GB libres de {disk['size_gb']:.1f}GB ({used_percent:.1f}% usado)\n"  
            send_progress(f"💿 {disk['caption']}: {disk['free_gb']:.1f}GB libres ({used_percent:.1f}% usado)")  
          
        send_progress("✅ Verificación de espacio completada")  
        return result.strip()      
              
    except Exception as e:      
        logger.error(f"Error verificando espacio en disco: {str(e)}")      
        return f"Error al verificar espacio en disco: {e}"      
      
def system_file_check(progress_callback=None):      
    """Ejecuta verificación de archivos del sistema"""  
    def send_progress(msg):  
        if progress_callback:  
            progress_callback(msg)  
        logger.info(msg)  
      
    try:      
        send_progress("🔍 Ejecutando verificación de archivos del sistema (esto puede tardar varios minutos)...")  
        logger.info("Ejecutando verificación de archivos del sistema")      
          
        send_progress("⏳ Ejecutando sfc /scannow...")  
        # Ejecutar sfc /scannow      
        sfc_result = subprocess.run('sfc /scannow', shell=True, capture_output=True, text=True)      
          
        if "no encontró ninguna infracción de integridad" in sfc_result.stdout.lower():      
            result = "Verificación de archivos del sistema completada. No se encontraron problemas."      
        elif "reparó correctamente" in sfc_result.stdout.lower():      
            result = "Verificación completada. Se repararon algunos archivos del sistema."      
        else:      
            result = "Verificación de archivos del sistema ejecutada. Revisa los logs para más detalles."      
          
        send_progress(f"✅ {result}")  
        logger.info("Verificación de archivos del sistema completada")      
        return result      
              
    except Exception as e:      
        logger.error(f"Error en verificación del sistema: {str(e)}")      
        return f"Error al verificar archivos del sistema: {e}"  
  
  
# Funciones de recordatorios del código local      
def cmd_add_reminder(params, ctx):    
    username = _username(ctx, params)    
    
    raw_title = (params.get("title") or "").strip()    
    raw_activity = (params.get("activity") or "").strip()    
    raw_text = (params.get("text") or "").strip()    
    description = (params.get("description") or "").strip()    
    
    # Priorizamos: title > activity > text    
    candidate = raw_title or raw_activity or raw_text    
    
    title = candidate    
    if ":" in candidate:    
        left, right = candidate.split(":", 1)    
        title = left.strip()    
        # si no pasaron description explícita, usamos la de activity/text    
        if not description:    
            description = right.strip()    
    
    if not title:    
        return {"ok": False, "error": "Falta 'title' (puedes pasar 'activity' en formato 'Título: descripción')"}    
    
    category = (params.get("category") or "inbox").strip().lower()    
    status   = (params.get("status") or "todo").strip().lower()    
    priority = (params.get("priority") or "normal").strip().lower()    
    due_date = params.get("due_date")  # "YYYY-MM-DD"    
    due_time = params.get("due_time")  # "HH:MM"    
    
    # Asegura lista    
    raw_tags = params.get("tags")    
    tags = raw_tags if isinstance(raw_tags, list) else []    
    
    item = add_reminder_item(    
        username=username,    
        title=title,    
        description=description,    
        category=category,    
        status=status,    
        priority=priority,    
        due_date=due_date,    
        due_time=due_time,    
        tags=tags,    
    )    
    return {"ok": True, "reminder": item}    
    
  
def cmd_get_reminders(params, ctx):    
    username = _username(ctx, params)    
    category = params.get("category")    
    status   = params.get("status")    
    items = list_reminders(username, category=category, status=status)    
    return {"ok": True, "reminders": items}    
    
    
def cmd_update_reminder(params, ctx):    
    username = _username(ctx, params)    
    reminder_id = params.get("id") or params.get("reminder_id")    
    if not reminder_id:    
        return {"ok": False, "error": "Falta 'id' del recordatorio"}    
    fields = {k: v for k, v in params.items() if k in {    
        "title","description","category","status","priority","due_date","due_time","tags"    
    }}    
    updated = update_reminder(username, reminder_id, **fields)    
    if not updated:    
        return {"ok": False, "error": "No se encontró el recordatorio"}    
    return {"ok": True, "reminder": updated}    
    
    
      
def cmd_remove_reminder(params, ctx):    
    username = _username(ctx, params)    
    reminder_id = params.get("id") or params.get("reminder_id")    
    if not reminder_id:    
        return {"ok": False, "error": "Falta 'id' del recordatorio"}    
    ok = remove_reminder_item(username, reminder_id)    
    return {"ok": ok}



COMMANDS = {      
    # ——— Recordatorios      
    "add_reminder": cmd_add_reminder,      
    "get_reminders": cmd_get_reminders,      
    "update_reminder": cmd_update_reminder,      
    "remove_reminder": cmd_remove_reminder,      
      
    # Sinónimos (opcional)      
    "agregar_recordatorio": cmd_add_reminder,      
    "listar_recordatorios": cmd_get_reminders,      
    "actualizar_recordatorio": cmd_update_reminder,      
    "eliminar_recordatorio": cmd_remove_reminder,      
      
    # ——— Apps / web      
    "open_application": open_application,      
    "close_application": close_application,      
    "try_web_fallback": try_web_fallback,      
    "search_google": search_google,      
    "search_youtube": search_youtube,      
      
    # ——— Sistema      
    "shutdown": shutdown,      
    "restart": restart,      
    "suspend": suspend,      
    "diagnose_system_performance": diagnose_system_performance,      
    "check_system_services": check_system_services,      
    "restart_critical_services": restart_critical_services,      
    "clean_temp_files": clean_temp_files,      
    "flush_dns": flush_dns,      
    "network_reset": network_reset,      
    "check_disk_space": check_disk_space,      
    "system_file_check": system_file_check,  
  
    # ——— Análisis de archivos  
    "analyze_file": analyze_file,    
      
    # ——— Comandos Básicos Nuevos      
    "set_volume": set_volume,      
    "create_file": create_file,      
    "create_folder": create_folder,      
    "move_file": move_file,      
    "copy_file": copy_file,      
    "create_shortcut": create_shortcut,      
    "delete_file": delete_file,      
    "list_files": list_files,  
      
    # ——— Utilidad      
    "get_weather": get_weather,    
    "duck_other_applications": duck_other_applications,    
    "restore_application_volumes": restore_application_volumes,    
}    
  
def run_command(cmd_name: str, params: dict | None = None, ctx: dict | None = None) -> dict:    
    """    
    Ejecuta un comando del registry y normaliza el resultado.    
    - Siempre devuelve un dict con {ok: bool, ...}    
    - Detecta handlers estilo (params, ctx) por nombre de parámetros, no por cantidad.    
    - Filtra kwargs para funciones normales según su firma.  
    - Inyecta progress_callback desde ctx si el comando lo soporta.  
    """    
    import inspect  
      
    params = params or {}    
    ctx = ctx or {}    
    fn = COMMANDS.get(cmd_name)    
    if not fn:    
        return {"ok": False, "error": f"Comando desconocido: {cmd_name}"}    
    
    try:    
        sig = inspect.signature(fn)    
        arg_names = [p.name for p in sig.parameters.values()]    
          
        # Extraer progress_callback del contexto si existe  
        progress_callback = ctx.get('progress_callback')  
    
        # Handler estilo comandos: def cmd_x(params, ctx)    
        if len(arg_names) >= 2 and arg_names[0] == "params" and arg_names[1] == "ctx":    
            result = fn(params, ctx)    
        else:    
            # Función "normal": ajustamos kwargs a su firma    
            allowed = set(arg_names)    
            filtered = {k: v for k, v in (params or {}).items() if k in allowed}    
              
            # Si el comando soporta progress_callback, inyectarlo  
            if 'progress_callback' in allowed and progress_callback:  
                filtered['progress_callback'] = progress_callback  
    
            if len(arg_names) == 0:    
                result = fn()    
            else:    
                result = fn(**filtered)    
    
        # Normalización de salida    
        if isinstance(result, str):    
            return {"ok": True, "message": result}    
        if isinstance(result, dict):    
            return {"ok": result.get("ok", True), **result}    
        return {"ok": True, "result": result}    
    
    except Exception as e:    
        logger.exception(f"Error ejecutando comando '{cmd_name}'")    
        return {"ok": False, "error": str(e)}