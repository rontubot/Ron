import os  
from fastapi import FastAPI  
from fastapi.responses import PlainTextResponse  
from pydantic import BaseModel  
from dotenv import load_dotenv  
import openai  
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
  
@app.post("/ron")  
def chat_with_ron(data: UserInput):  
    text = data.text.strip().lower()  
      
    # Detección amplia de despedidas - DESACTIVA EL BOT  
    farewell_phrases = [  
        "hasta luego", "adiós", "chao", "nos vemos", "me voy",  
        "vale hasta luego", "bueno adiós", "ok chao",   
        "desconéctate", "apágate", "ciérrate", "termina",  
        "hasta la vista", "que tengas buen día", "gracias y adiós"  
    ]  
      
    # Verificar si contiene alguna frase de despedida  
    for phrase in farewell_phrases:  
        if phrase in text:  
            response = "Hasta luego. Que tengas un buen día."  
            # Guardar despedida en memoria antes de desactivar  
            try:  
                add_to_memory(data.text, response)  
            except:  
                pass  
              
            # Desactivar el servidor (esto terminará el proceso)  
            import threading  
            import time  
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