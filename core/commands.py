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
  
# NUEVO: Agregar estas tres funciones aquí  
  
def get_audio_processes():    
    """Enumera procesos que probablemente tengan audio activo (sin duplicados)"""    
    audio_apps = set()  # CAMBIO: usar set para evitar duplicados  
    common_audio_processes = [    
        'chrome.exe', 'firefox.exe', 'msedge.exe', 'brave.exe',  
        'spotify.exe', 'vlc.exe', 'wmplayer.exe', 'musicbee.exe',  
        'discord.exe', 'teams.exe', 'zoom.exe', 'slack.exe' 'youtube.exe', 
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
    
def duck_other_applications():    
    """Reduce volumen de apps conocidas al 20%"""    
    try:    
        logger.info("Reduciendo volumen de otras aplicaciones")    
        processes = get_audio_processes()    
          
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica  
            
        for proc_name in processes:    
            result = subprocess.run(    
                [nircmd_path, 'setappvolume', proc_name, '0.2'],    
                capture_output=True,    
                text=True,  
                timeout=2  # Evitar bloqueos  
            )    
            if result.returncode == 0:    
                logger.debug(f"Volumen reducido para {proc_name}")    
            else:    
                logger.warning(f"No se pudo reducir volumen de {proc_name}")    
                    
        return {"ok": True, "message": f"Volumen reducido en {len(processes)} aplicaciones"}    
    except Exception as e:    
        logger.error(f"Error en duck_other_applications: {e}")    
        return {"ok": False, "error": str(e)}    
    
def restore_application_volumes():    
    """Restaura volumen de apps al 100%"""    
    try:    
        logger.info("Restaurando volumen de aplicaciones")    
        processes = get_audio_processes()    
          
        nircmd_path = get_nircmd_path()  # Usar ruta dinámica  
            
        for proc_name in processes:    
            result = subprocess.run(    
                [nircmd_path, 'setappvolume', proc_name, '1.0'],    
                capture_output=True,    
                text=True,  
                timeout=2  # Evitar bloqueos  
            )    
            if result.returncode == 0:    
                logger.debug(f"Volumen restaurado para {proc_name}")    
                    
        return {"ok": True, "message": f"Volumen restaurado en {len(processes)} aplicaciones"}    
    except Exception as e:    
        logger.error(f"Error en restore_application_volumes: {e}")    
        return {"ok": False, "error": str(e)}


def analyze_file(file_path, analysis_type="general"):  
    """  
    Analiza un archivo y proporciona feedback inteligente.  
      
    Args:  
        file_path: Ruta al archivo a analizar  
        analysis_type: Tipo de análisis ("general", "code", "text", "improve")  
      
    Returns:  
        Dict con análisis del archivo  
    """  
    try:  
        # Expandir ruta  
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))  
          
        if not os.path.exists(expanded_path):  
            return f"El archivo no existe: {expanded_path}"  
          
        logger.info(f"Analizando archivo: {expanded_path}")  
          
        # Leer contenido del archivo  
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
          
        # Análisis básico  
        analysis = {  
            "file": expanded_path,  
            "size": f"{file_size} bytes",  
            "lines": line_count,  
            "extension": file_ext,  
            "content_preview": content[:500] if len(content) > 500 else content  
        }  
          
        # Análisis específico según tipo  
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
    
  
def try_web_fallback(app_name):  
    """Intenta abrir la versión web de una aplicación usando la tabla local web_apps (sin imports circulares)."""  
    name = (app_name or "").strip().lower()  
    if not name:  
        return None  
  
    # Coincidencia exacta  
    if name in web_apps:  
        webbrowser.open(web_apps[name])  
        return f"Abriendo {name.capitalize()} en el navegador como alternativa."  
  
    # Coincidencias parciales  
    for key, url in web_apps.items():  
        if key in name or name in key:  
            webbrowser.open(url)  
            return f"Abriendo {key.capitalize()} en el navegador como alternativa."  
  
    return None  
  
    
def fix_common_json_errors(response):    
    """Corrige errores comunes de JSON de ChatGPT"""    
    # Corregir nombres de campos incorrectos    
    response = response.replace('"userresponse":', '"user_response":')    
    response = response.replace('"applicationname":', '"app_name":')    
    response = response.replace('"openapplication"', '"open_application"')    
        
    return response  
  
  
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


def set_volume(level):    
    """Ajusta el volumen del sistema"""    
    try:    
        logger.info(f"Ajustando volumen al {level}%")    
            
        # Convertir porcentaje a valor 0-100    
        if isinstance(level, str):    
            level = int(level.replace('%', ''))    
            
        # Usar PowerShell en lugar de nircmd    
        ps_command = f'(New-Object -ComObject WScript.Shell).SendKeys([char]175)' if level > 50 else f'(New-Object -ComObject WScript.Shell).SendKeys([char]174)'    
            
        # Mejor: usar pycaw (requiere pip install pycaw comtypes)    
        from ctypes import cast, POINTER    
        from comtypes import CLSCTX_ALL    
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume    
            
        devices = AudioUtilities.GetSpeakers()    
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)    
        volume = cast(interface, POINTER(IAudioEndpointVolume))    
        volume.SetMasterVolumeLevelScalar(level / 100, None)    
            
        return f"Volumen ajustado al {level}%"    
            
    except Exception as e:    
        logger.error(f"Error ajustando volumen: {str(e)}")    
        return f"Error ajustando volumen: {e}"  
    
def create_file(file_path, content=""):      
    """Crea un archivo con contenido opcional"""      
    try:      
        # NUEVO: Limpiar símbolos <> si el modelo los generó incorrectamente  
        file_path = file_path.replace('<ESCRITORIO>', 'escritorio')  
        file_path = file_path.replace('<DOCUMENTOS>', 'documentos')  
        file_path = file_path.replace('<DESCARGAS>', 'descargas')  
        file_path = file_path.replace('<IMAGENES>', 'imagenes')  
        file_path = file_path.replace('<MUSICA>', 'musica')  
        file_path = file_path.replace('<VIDEOS>', 'videos')  
          
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
          
        # Crear directorio padre si no existe      
        os.makedirs(os.path.dirname(expanded_path), exist_ok=True)      
          
        with open(expanded_path, 'w', encoding='utf-8') as f:      
            f.write(content)      
          
        return f"Archivo creado: {expanded_path}"      
              
    except Exception as e:      
        logger.error(f"Error creando archivo: {str(e)}")      
        return f"Error creando archivo: {e}"


def create_folder(folder_path):      
    """Crea una carpeta"""      
    try:      
        # NUEVO: Limpiar símbolos <> si el modelo los generó incorrectamente  
        folder_path = folder_path.replace('<ESCRITORIO>', 'escritorio')  
        folder_path = folder_path.replace('<DOCUMENTOS>', 'documentos')  
        folder_path = folder_path.replace('<DESCARGAS>', 'descargas')  
        folder_path = folder_path.replace('<IMAGENES>', 'imagenes')  
        folder_path = folder_path.replace('<MUSICA>', 'musica')  
        folder_path = folder_path.replace('<VIDEOS>', 'videos')  
          
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
          
        os.makedirs(expanded_path, exist_ok=True)      
        return f"Carpeta creada: {expanded_path}"      
              
    except Exception as e:      
        logger.error(f"Error creando carpeta: {str(e)}")      
        return f"Error creando carpeta: {e}"  
    
def move_file(source, destination):      
    """Mueve un archivo de origen a destino"""      
    try:      
        # NUEVO: Expandir variables de entorno y rutas de usuario  
        expanded_source = os.path.expandvars(os.path.expanduser(source))  
        expanded_dest = os.path.expandvars(os.path.expanduser(destination))  
          
        logger.info(f"Moviendo archivo de {expanded_source} a {expanded_dest}")      
              
        import shutil      
              
        # Crear directorio destino si no existe      
        os.makedirs(os.path.dirname(expanded_dest), exist_ok=True)      
              
        shutil.move(expanded_source, expanded_dest)      
              
        return f"Archivo movido de {expanded_source} a {expanded_dest}"      
              
    except Exception as e:      
        logger.error(f"Error moviendo archivo: {str(e)}")      
        return f"Error moviendo archivo: {e}"   
    
def copy_file(source, destination):      
    """Copia un archivo de origen a destino"""      
    try:      
        # NUEVO: Expandir variables de entorno y rutas de usuario  
        expanded_source = os.path.expandvars(os.path.expanduser(source))  
        expanded_dest = os.path.expandvars(os.path.expanduser(destination))  
          
        logger.info(f"Copiando archivo de {expanded_source} a {expanded_dest}")      
              
        import shutil      
              
        # Crear directorio destino si no existe      
        os.makedirs(os.path.dirname(expanded_dest), exist_ok=True)      
              
        shutil.copy2(expanded_source, expanded_dest)      
              
        return f"Archivo copiado de {expanded_source} a {expanded_dest}"      
              
    except Exception as e:      
        logger.error(f"Error copiando archivo: {str(e)}")      
        return f"Error copiando archivo: {e}"    

def read_file(file_path):  
    """Lee el contenido de un archivo de texto"""  
    try:  
        # Expandir ruta completa  
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))  
          
        logger.info(f"Leyendo archivo: {expanded_path}")  
          
        # Verificar que existe  
        if not os.path.exists(expanded_path):  
            return f"El archivo no existe: {expanded_path}"  
          
        # Leer contenido (máximo 10KB para evitar sobrecarga)  
        with open(expanded_path, 'r', encoding='utf-8', errors='ignore') as f:  
            content = f.read(10240)  # Limitar a 10KB  
          
        # Detectar tipo de archivo  
        ext = os.path.splitext(expanded_path)[1].lower()  
        file_type = {  
            '.py': 'Python', '.js': 'JavaScript', '.txt': 'Texto',  
            '.json': 'JSON', '.md': 'Markdown', '.html': 'HTML',  
            '.css': 'CSS', '.java': 'Java', '.cpp': 'C++'  
        }.get(ext, 'Desconocido')  
          
        return {  
            "ok": True,  
            "file_path": expanded_path,  
            "file_type": file_type,  
            "content": content,  
            "size_bytes": len(content),  
            "message": f"Archivo leído: {os.path.basename(expanded_path)} ({file_type})"  
        }  
          
    except Exception as e:  
        logger.error(f"Error leyendo archivo: {str(e)}")  
        return {"ok": False, "error": f"Error leyendo archivo: {e}"}

def list_directory_detailed(directory_path):  
    """Lista archivos en un directorio con información detallada"""  
    try:  
        # Expandir ruta  
        expanded_path = os.path.expandvars(os.path.expanduser(directory_path))  
          
        logger.info(f"Listando directorio detallado: {expanded_path}")  
          
        if not os.path.exists(expanded_path):  
            return f"El directorio no existe: {expanded_path}"  
          
        if not os.path.isdir(expanded_path):  
            return f"La ruta no es un directorio: {expanded_path}"  
          
        # Obtener información de archivos  
        files_info = []  
        total_size = 0  
          
        for item in os.listdir(expanded_path):  
            item_path = os.path.join(expanded_path, item)  
            try:  
                stat = os.stat(item_path)  
                is_dir = os.path.isdir(item_path)  
                  
                files_info.append({  
                    "name": item,  
                    "type": "Carpeta" if is_dir else "Archivo",  
                    "size_bytes": 0 if is_dir else stat.st_size,  
                    "size_readable": "N/A" if is_dir else f"{stat.st_size / 1024:.1f} KB",  
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),  
                    "extension": "" if is_dir else os.path.splitext(item)[1]  
                })  
                  
                if not is_dir:  
                    total_size += stat.st_size  
                      
            except Exception as e:  
                logger.warning(f"No se pudo obtener info de {item}: {e}")  
          
        # Ordenar: carpetas primero, luego archivos por nombre  
        files_info.sort(key=lambda x: (x["type"] != "Carpeta", x["name"].lower()))  
          
        # Generar resumen  
        num_files = sum(1 for f in files_info if f["type"] == "Archivo")  
        num_folders = sum(1 for f in files_info if f["type"] == "Carpeta")  
          
        summary = f"📁 {expanded_path}\n"  
        summary += f"Total: {num_folders} carpetas, {num_files} archivos ({total_size / 1024:.1f} KB)\n\n"  
          
        # Listar items (máximo 50)  
        for item in files_info[:50]:  
            icon = "📁" if item["type"] == "Carpeta" else "📄"  
            summary += f"{icon} {item['name']}"  
            if item["type"] == "Archivo":  
                summary += f" ({item['size_readable']}, {item['modified']})"  
            summary += "\n"  
          
        if len(files_info) > 50:  
            summary += f"\n... y {len(files_info) - 50} elementos más"  
          
        return {  
            "ok": True,  
            "directory": expanded_path,  
            "files": files_info,  
            "summary": summary,  
            "total_files": num_files,  
            "total_folders": num_folders,  
            "total_size_bytes": total_size  
        }  
          
    except Exception as e:  
        logger.error(f"Error listando directorio: {str(e)}")  
        return {"ok": False, "error": f"Error listando directorio: {e}"}


def get_standard_path(location_name):  
    """Resuelve nombres de ubicaciones estándar a rutas absolutas"""  
    try:  
        import os  
          
        # Mapeo de nombres comunes a rutas de Windows  
        standard_paths = {  
            "escritorio": os.path.join(os.path.expanduser("~"), "Desktop"),  
            "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),  
            "documentos": os.path.join(os.path.expanduser("~"), "Documents"),  
            "documents": os.path.join(os.path.expanduser("~"), "Documents"),  
            "descargas": os.path.join(os.path.expanduser("~"), "Downloads"),  
            "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),  
            "imagenes": os.path.join(os.path.expanduser("~"), "Pictures"),  
            "pictures": os.path.join(os.path.expanduser("~"), "Pictures"),  
            "musica": os.path.join(os.path.expanduser("~"), "Music"),  
            "music": os.path.join(os.path.expanduser("~"), "Music"),  
            "videos": os.path.join(os.path.expanduser("~"), "Videos"),  
            "temp": os.environ.get("TEMP", "C:\\Windows\\Temp"),  
            "appdata": os.environ.get("APPDATA", ""),  
            "home": os.path.expanduser("~"),  
        }  
          
        location_key = location_name.lower().strip()  
          
        if location_key in standard_paths:  
            path = standard_paths[location_key]  
            return {  
                "ok": True,  
                "location": location_name,  
                "path": path,  
                "exists": os.path.exists(path),  
                "message": f"{location_name} → {path}"  
            }  
        else:  
            return {  
                "ok": False,  
                "error": f"Ubicación desconocida: {location_name}",  
                "available": list(standard_paths.keys())  
            }  
              
    except Exception as e:  
        logger.error(f"Error resolviendo ruta estándar: {str(e)}")  
        return {"ok": False, "error": str(e)}        

    
def create_shortcut(target_path, shortcut_path, description=""):    
    """Crea un acceso directo"""    
    try:    
        logger.info(f"Creando acceso directo: {shortcut_path} -> {target_path}")    
            
        # Usar PowerShell para crear acceso directo    
        ps_command = f'''    
        $WshShell = New-Object -comObject WScript.Shell    
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")    
        $Shortcut.TargetPath = "{target_path}"    
        $Shortcut.Description = "{description}"    
        $Shortcut.Save()    
        '''    
            
        result = subprocess.run(['powershell', '-Command', ps_command], capture_output=True, text=True)    
            
        if result.returncode == 0:    
            return f"Acceso directo creado: {shortcut_path}"    
        else:    
            return f"Error creando acceso directo: {result.stderr}"    
                
    except Exception as e:    
        logger.error(f"Error creando acceso directo: {str(e)}")    
        return f"Error creando acceso directo: {e}"    
    
def delete_file(file_path):      
    """Elimina un archivo"""      
    try:      
        # NUEVO: Expandir variables de entorno y rutas de usuario  
        expanded_path = os.path.expandvars(os.path.expanduser(file_path))  
          
        logger.info(f"Eliminando archivo: {expanded_path}")      
              
        os.remove(expanded_path)      
              
        return f"Archivo eliminado: {expanded_path}"      
              
    except Exception as e:      
        logger.error(f"Error eliminando archivo: {str(e)}")      
        return f"Error eliminando archivo: {e}"
    
def list_files(directory_path):    
    """Lista archivos en un directorio"""    
    try:    
        logger.info(f"Listando archivos en: {directory_path}")    
            
        import os    
        files = os.listdir(directory_path)    
            
        if files:    
            file_list = "\\n".join(files[:20])  # Limitar a 20 archivos    
            return f"Archivos en {directory_path}:\\n{file_list}"    
        else:    
            return f"No hay archivos en {directory_path}"    
                
    except Exception as e:    
        logger.error(f"Error listando archivos: {str(e)}")    
        return f"Error listando archivos: {e}"


def diagnose_system_performance():    
    """Diagnostica rendimiento del sistema"""    
    try:    
        logger.info("Iniciando diagnóstico de rendimiento del sistema")    
            
        # Verificar uso de CPU    
        cpu_result = subprocess.run('wmic cpu get loadpercentage /value', shell=True, capture_output=True, text=True)    
        cpu_usage = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)    
        cpu_percent = cpu_usage.group(1) if cpu_usage else 'N/A'    
            
        # Verificar memoria    
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
        temp_result = subprocess.run('del /q /f /s "%temp%\\*" 2>nul', shell=True, capture_output=True, text=True)    
            
        # Limpiar archivos temporales del sistema    
        system_temp_result = subprocess.run('del /q /f /s "C:\\Windows\\Temp\\*" 2>nul', shell=True, capture_output=True, text=True)    
            
        # Limpiar papelera de reciclaje    
        recycle_result = subprocess.run('rd /s /q "%systemdrive%\\$Recycle.bin" 2>nul', shell=True, capture_output=True, text=True)    
            
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
        lines = disk_result.stdout.strip().split('\n')    
            
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
    "read_file": read_file,  
    "analyze_file": analyze_file,  
    "list_directory_detailed": list_directory_detailed,  
    "get_standard_path": get_standard_path,    
    
    # ——— Comandos Básicos Nuevos    
    "set_volume": set_volume,    
    "create_file": create_file,    
    "create_folder": create_folder,    
    "move_file": move_file,    
    "copy_file": copy_file,    
    "create_shortcut": create_shortcut,    
    "delete_file": delete_file,    
    "list_files": list_files,
    "analyze_file": analyze_file,    
    
    # ——— Utilidad    
    "get_weather": get_weather,  
    "duck_other_applications": duck_other_applications,  # NUEVO  
    "restore_application_volumes": restore_application_volumes,  # NUEVO  
}  
  
  
def run_command(cmd_name: str, params: dict | None = None, ctx: dict | None = None) -> dict:  
    """  
    Ejecuta un comando del registry y normaliza el resultado.  
    - Siempre devuelve un dict con {ok: bool, ...}  
    - Detecta handlers estilo (params, ctx) por nombre de parámetros, no por cantidad.  
    - Filtra kwargs para funciones normales según su firma.  
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
  
        # Handler estilo comandos: def cmd_x(params, ctx)  
        if len(arg_names) >= 2 and arg_names[0] == "params" and arg_names[1] == "ctx":  
            result = fn(params, ctx)  
        else:  
            # Función "normal": ajustamos kwargs a su firma  
            allowed = set(arg_names)  
            filtered = {k: v for k, v in (params or {}).items() if k in allowed}  
  
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


