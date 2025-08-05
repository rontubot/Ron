import os  
from fastapi import FastAPI  
from fastapi.responses import PlainTextResponse  
from pydantic import BaseModel  
from dotenv import load_dotenv  
import openai  
import re  
import threading  
import time  
from core.memory import load_memory, add_to_memory  
from core.assistant import generate_response  
  
load_dotenv()  
openai.api_key = os.getenv("OPENAI_API_KEY")  
  
app = FastAPI()  
  
class UserInput(BaseModel):  
    text: str  
  
@app.get("/")  
def read_root():  
    return {"message": "Ron API está corriendo"}  
  
def detect_farewell_in_api(text):  
    """Detección amplia de despedidas en la API - igual que en assistant.py"""  
    farewell_patterns = [  
        r"(gracias|thanks)\\s+.*?(hasta luego|adiós|chao|nos vemos)",  
        r"(vale|bueno|ok|bien)?\\s*(hasta luego|adiós|chao|nos vemos|me voy|hasta la vista)",  
        r"(vale|bueno|ok|bien)?\\s*(desconéctate|apágate|ciérrate|termina)",  
        r"(hasta|nos)\\s+(luego|vemos|pronto)",  
        r"(me|ya)\\s+(voy|retiro|despido)",  
        r"(que tengas|ten)\\s+(buen|buena)\\s+(día|tarde|noche)",  
        r".*ronald.*hasta luego.*",  
        r".*ron.*hasta luego.*",  
        r"^(adiós|chao|bye|hasta luego)$"  
    ]  
      
    for pattern in farewell_patterns:  
        if re.search(pattern, text, re.IGNORECASE):  
            return True  
    return False  
  
@app.post("/ron")  
def chat_with_ron(data: UserInput):  
    text = data.text.strip().lower()  
      
    # Detección amplia de despedidas - DESACTIVA EL BOT  
def detect_farewell_in_api(text: str) -> bool:
    farewells = [
        "hasta luego", "adiós", "nos vemos", "chau", 
        "me voy", "cerrar sesión", "hasta pronto", 
        "bye", "see you", "goodbye"
    ]
    return any(farewell in text for farewell in farewells)

  
@app.get("/github-token", response_class=PlainTextResponse)  
def get_github_token():  
    token = os.getenv("GITHUB_TOKEN")  
    if not token:  
        return PlainTextResponse("Token no configurado", status_code=404)  
    return token  
  
@app.get("/health")  
def health_check():  
    """Endpoint de salud para verificar que el bot está funcionando"""  
    return {"status": "healthy", "message": "Ron está funcionando correctamente"}  
  
@app.get("/memory-status")  
def memory_status():  
    """Endpoint para verificar el estado de la memoria"""  
    try:  
        memory = load_memory()  
        conversations_count = len(memory.get("conversaciones", []))  
        reminders_count = len(memory.get("recordatorios", {}))  
        return {  
            "status": "ok",  
            "conversations": conversations_count,  
            "reminders": reminders_count,  
            "device_id": memory.get("datos", {}).get("device_id", "unknown")  
        }  
    except Exception as e:  
        return {"status": "error", "message": str(e)}