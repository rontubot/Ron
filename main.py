import os
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import openai
from core.memory import load_memory, add_to_memory
from core.assistant import generate_response

from core.auth import login_prompt, set_current_user  
  
def main():  
    # Realizar login antes de iniciar Ron  
    username, user_data = login_prompt()  
    set_current_user(username, user_data)  
      
    print(f"\\n🤖 Ron iniciado para {user_data['full_name']}")  
    print("Puedes comenzar a hablar...") 

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
    if text in ["hasta luego", "adiós"]:
        return {"ron": "Hasta luego."}
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
