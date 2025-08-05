from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse
import os
import openai
from dotenv import load_dotenv
from core.memory import load_memory, add_to_memory
from core.assistant import generate_response

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

class UserInput(BaseModel):
    text: str

# ✅ Función de detección de despedidas (era lo que faltaba antes)
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
        return PlainTextResponse("T
