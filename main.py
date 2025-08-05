import os
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import openai
import re
from core.memory import load_memory, add_to_memory
from core.assistant import generate_response

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

class UserInput(BaseModel):
    text: str

# ✅ ESTA función debe ir antes del endpoint
def detect_farewell_in_api(text: str) -> bool:
    farewells = [
        "hasta luego", "adiós", "nos vemos", "chau",
        "me voy", "cerrar sesión", "hasta pronto",
        "bye", "see you", "goodbye"
    ]
    return any(farewell in text for farewell in farewells)

@app.get("/")
def read_root():
    return {"message": "Ron API está corriendo"}

@app.post("/ron")
def chat_with_ron(data: UserInput):
    text = data.text.strip().lower()

    if detect_farewell_in_api(text):
        response = "Hasta luego. Que tengas un buen día."
        try:
            add_to_memory(data.text, response)
        except:
            pass
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
    return {"status": "ok"}

@app.get("/memory-status")
def memory_status():
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
