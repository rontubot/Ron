from fastapi import FastAPI, Request
from pydantic import BaseModel
import os
import openai
import json
import re
from core.memory import load_memory, add_to_memory
from core.assistant import generate_response
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

class UserInput(BaseModel):
    text: str

@app.get("/")
def read_root():
    return {"message": "Ron API está corriendo"}

@app.post("/ron")
def chat_with_ron(data: UserInput):
    text = data.text.strip().lower()

    # Lógica opcional para desactivación
    if text in ["hasta luego", "adiós"]:
        return {"ron": "Hasta luego."}

    try:
        ron_response = generate_response(text)
        return {"ron": ron_response}
    except Exception as e:
        return {"error": str(e)}
