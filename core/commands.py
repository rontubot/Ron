import os  
import subprocess  
import webbrowser  
import requests  
from config import WEATHER_API_KEY  
  
# Diccionario de sitios comunes  
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
    try:  
        app_name_clean = app_name.lower().strip()  
          
        # Buscar en aplicaciones web primero  
        if app_name_clean in web_apps:  
            webbrowser.open(web_apps[app_name_clean])  
            return f"Abriendo {app_name.capitalize()} en el navegador."  
          
        # Buscar coincidencias parciales en web apps  
        for key, url in web_apps.items():  
            if key in app_name_clean or app_name_clean in key:  
                webbrowser.open(url)  
                return f"Abriendo {key.capitalize()} en el navegador."  
          
        # Intentar abrir aplicación local  
        subprocess.Popen(f'start {app_name}', shell=True)  
        return f"Intentando abrir {app_name}."  
    except Exception as e:  
        return f"No pude abrir {app_name}: {e}"  
  
def close_application(app_name):  
    try:  
        process_name = app_name.lower() + ".exe"  
        result = subprocess.run(f'taskkill /F /IM {process_name}', shell=True, capture_output=True, text=True)  
        if "ERROR" in result.stdout:  
            return f"No se encontró el proceso {app_name}."  
        return f"Cerrando {app_name}."  
    except Exception as e:  
        return f"Error al cerrar {app_name}: {e}"  
  
def get_weather(city):  
    if not WEATHER_API_KEY:  
        return "No tengo configurada la API del clima. Necesitas configurar WEATHER_API_KEY."  
      
    params = {  
        "q": city,  
        "appid": WEATHER_API_KEY,  
        "units": "metric",  
        "lang": "es"  
    }  
    try:  
        response = requests.get("http://api.openweathermap.org/data/2.5/weather", params=params)  
        data = response.json()  
        if response.status_code == 200:  
            temp = data["main"]["temp"]  
            description = data["weather"][0]["description"]  
            return f"La temperatura en {city} es de {temp} grados con {description}."  
        else:  
            return f"No pude obtener el clima de {city}. Verifica que el nombre sea correcto."  
    except Exception as e:  
        return f"Error al obtener el clima: {e}"  
  
def search_google(query):  
    try:  
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"  
        webbrowser.open(url)  
        return f"Buscando en Google: {query}"  
    except Exception as e:  
        return f"Error al buscar en Google: {e}"  
  
def search_youtube(query):  
    try:  
        url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"  
        webbrowser.open(url)  
        return f"Buscando en YouTube: {query}"  
    except Exception as e:  
        return f"Error al buscar en YouTube: {e}"  
  
def shutdown():  
    try:  
        os.system("shutdown /s /t 1")  
        return "Apagando la computadora..."  
    except Exception as e:  
        return f"Error al apagar: {e}"  
  
def restart():  
    try:  
        os.system("shutdown /r /t 1")  
        return "Reiniciando la computadora..."  
    except Exception as e:  
        return f"Error al reiniciar: {e}"  
  
def suspend():  
    try:  
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")  
        return "Suspendiendo la computadora..."  
    except Exception as e:  
        return f"Error al suspender: {e}"