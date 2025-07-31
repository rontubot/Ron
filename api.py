from fastapi import FastAPI, Request  
from pydantic import BaseModel  
from fastapi.responses import PlainTextResponse  
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
  
    # Detección amplia de despedidas - DESACTIVA EL BOT  
    farewell_phrases = [  
        "hasta luego", "adiós", "chao", "nos vemos", "me voy",  
        "vale hasta luego", "bueno adiós", "ok chao",   
        "desconéctate", "apágate", "ciérrate  
  
Wiki pages you might want to explore:  
- [Overview (rontubot/Ron)](/wiki/rontubot/Ron#1)  
- [Core System Architecture (rontubot/Ron)](/wiki/rontubot/Ron#2)  
- [API Layer (rontubot/Ron)](/wiki/rontubot/Ron#3)