from fastapi import FastAPI, Request  
from pydantic import BaseModel  
from fastapi.responses import PlainTextResponse  
import os  
import openai  
import json  
import re  
import threading  
import time  
import requests  
from datetime import datetime  
from core.memory import load_memory, add_to_memory  
from core.assistant import generate_response  
from dotenv import load_dotenv  
  
load_dotenv()  
  
openai.api_key = os.getenv("OPENAI_API_KEY")  
  
app = FastAPI()  
  
class UserInput(BaseModel):  
    text: str  
  
# Sistema de auto-ping interno para mantener el servidor activo  
def keep_alive():  
    """Función que hace ping interno cada 4 minutos para mantener Railway activo"""  
    while True:  
        try:  
            time.sleep(240)  # 4 minutos  
            # Hacer ping a sí mismo  
            requests.get("https://ron-production.up.railway.app/health", timeout=10)  
            print("✅ Keep-alive ping enviado")  
        except Exception as e:  
            print(f"⚠️ Error en keep-alive: {e}")  
  
# Iniciar el hilo de keep-alive al arrancar la aplicación  
threading.Thread(target=keep_alive, daemon=True).start()  
  
@app.get("/")  
def read_root():  
    return {"message": "Ron API está corriendo"}  
  
@app.post("/ron")  
def chat_with_ron(data: UserInput):  
    text = data.text.strip().lower()  
  
    # Detección simplificada de despedidas - SOLO "hasta luego"  
    if "hasta luego" in text:  
        response = "Hasta luego. Que tengas un buen día."  
        # Guardar despedida en memoria antes de desactivar  
        try:  
            add_to_memory(data.text, response)  
        except:  
            pass  
          
        # Desactivar el servidor (esto terminará el proceso)  
        def shutdown_server():  
            time.sleep(1)  # Dar tiempo para enviar respuesta  
            os._exit(0)  
          
        threading.Thread(target=shutdown_server).start()  
        return {"ron": response, "shutdown": True}  
  
    try:  
        ron_response = generate_response(text)  
        return {"ron": ron_response}  
    except Exception as e:  
        return {"error": str(e)}  
  
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
  
@app.get("/keep-alive")  
def keep_alive_endpoint():  
    """Endpoint específico para mantener el servidor activo con actividad real"""  
    try:  
        # Generar actividad real del sistema  
        memory = load_memory()  
        conversations_count = len(memory.get("conversaciones", []))  
          
        return {  
            "status": "alive",  
            "timestamp": datetime.now().isoformat(),  
            "conversations": conversations_count,  
            "message": "Servidor activo y funcionando",  
            "uptime": "Railway container running"  
        }  
    except Exception as e:  
        return {  
            "status": "alive",  
            "timestamp": datetime.now().isoformat(),  
            "message": "Servidor activo (memoria no disponible)",  
            "error": str(e)  
        }  
  
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
  
@app.post("/webhook")  
def github_webhook():  
    """Endpoint para recibir webhooks de GitHub y mantener actividad"""  
    return {  
        "status": "webhook received",   
        "server": "active",  
        "timestamp": datetime.now().isoformat()  
    }