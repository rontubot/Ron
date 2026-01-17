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
        return datetime.now(ZoneInfo(timezone_str))
    except Exception as e:
        logger.warning(f"Error al obtener hora para zona {timezone_str}, usando UTC: {e}")
        return datetime.now(ZoneInfo("UTC"))

def format_localized_now(timezone_str: str = "UTC") -> str:
    """
    Devuelve la fecha y hora actual formateada para el sistema.
    """
    now = get_now_localized(timezone_str)
    return now.strftime("%Y-%m-%d %H:%M:%S")
