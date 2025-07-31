import os  
import subprocess  
import webbrowser  
import requests  
import logging  
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
      
    memory["recordatorios"][title] = description  # Guardar en diccionario  
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
        result = "Tus recordatorios son:\\n" + "\\n".join(f"- {title}: {desc}" for title, desc in memory["recordatorios"].items())  
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
        removed_desc = memory["recordatorios"].pop(removed_title)  
        save_memory({"recordatorios": memory["recordatorios"]})  
        logger.info(f"Recordatorio eliminado: {removed_title}")  
        return f"Recordatorio '{removed_title}' eliminado."  
    elif len(matches) > 1:  
        logger.warning(f"Múltiples recordatorios encontrados para: {title}")  
        return "Hay múltiples recordatorios similares. Dime el título exacto."  
    else:  
        logger.warning(f"No se encontró recordatorio para: {title}")  
        return "No encontré un recordatorio con ese título."