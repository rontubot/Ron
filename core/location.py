import requests
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

def get_location_from_ip(ip: str) -> dict:
    """
    Obtiene información de ubicación y zona horaria a partir de una IP.
    Usa el servicio gratuito ip-api.com.
    """
    if not ip or ip in ["127.0.0.1", "localhost", "::1"]:
        return {}

    try:
        # Nota: ip-api.com es gratuito para uso no comercial y permite hasta 45 req/min.
        url = f"http://ip-api.com/json/{ip}?fields=status,message,country,city,timezone,offset"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return {
                    "country": data.get("country"),
                    "city": data.get("city"),
                    "timezone": data.get("timezone"),
                    "offset": data.get("offset") # en segundos
                }
            else:
                logger.warning(f"Error en ip-api para IP {ip}: {data.get('message')}")
        else:
            logger.warning(f"Error de conexión con ip-api: {response.status_code}")
    except Exception as e:
        logger.error(f"Error obteniendo ubicación de IP {ip}: {e}")
    
    return {}

def get_now_localized(timezone_str: str = "UTC") -> datetime:
    """
    Obtiene la fecha y hora actual en la zona horaria especificada.
    """
    try:
        if not timezone_str:
            timezone_str = "UTC"
        
        # 🔹 Normalización de zonas comunes que pueden fallar
        tz_map = {
            "America/Argentina/Buenos_Aires": "America/Buenos_Aires",
            "America/Argentina/Cordoba": "America/Cordoba",
            "America/Argentina/Salta": "America/Salta",
            "America/Argentina/Jujuy": "America/Jujuy",
            "America/Argentina/Tucuman": "America/Tucuman",
            "America/Argentina/Catamarca": "America/Catamarca",
            "America/Argentina/La_Rioja": "America/La_Rioja",
            "America/Argentina/San_Juan": "America/San_Juan",
            "America/Argentina/Mendoza": "America/Mendoza",
            "America/Argentina/San_Luis": "America/San_Luis",
            "America/Argentina/Rio_Gallegos": "America/Rio_Gallegos",
            "America/Argentina/Ushuaia": "America/Ushuaia"
        }
        
        target_tz = tz_map.get(timezone_str, timezone_str)
        
        try:
            return datetime.now(ZoneInfo(target_tz))
        except:
            # Si falla la mapeada, intentar con UTC como último recurso
            if target_tz != "UTC":
                return datetime.now(ZoneInfo("UTC"))
            raise
    except Exception as e:
        logger.warning(f"Error al obtener hora para zona {timezone_str}, usando UTC: {e}")
        return datetime.now(ZoneInfo("UTC"))

def format_localized_now(timezone_str: str = "UTC") -> str:
    """
    Devuelve la fecha y hora actual formateada para el sistema.
    """
    now = get_now_localized(timezone_str)
    return now.strftime("%Y-%m-%d %H:%M:%S")
