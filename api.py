from fastapi import FastAPI, HTTPException, Depends, Header, Response      
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials      
from fastapi.middleware.cors import CORSMiddleware      
from pydantic import BaseModel      
from fastapi.responses import PlainTextResponse     
import os      
from openai import OpenAI      
import jwt      
import bcrypt      
from datetime import datetime, timedelta      
from dotenv import load_dotenv      
from core.memory import (    
    load_memory, add_to_memory, save_memory, get_github_token,    
    load_user_memory, save_user_memory, load_users_from_github, save_users_to_github    
)     
from core.assistant import generate_response_no_memory, parse_commands_only, construir_historial_usuario_openai    
from core.memory import get_github_token as memory_get_github_token      
import requests      
import json      
import base64     
import traceback  
  
import logging    
    
# Desactivar logs DEBUG de librerías externas    
logging.getLogger("urllib3").setLevel(logging.WARNING)    
logging.getLogger("httpcore").setLevel(logging.WARNING)    
logging.getLogger("openai").setLevel(logging.WARNING)    
logging.getLogger("httpx").setLevel(logging.WARNING)    
    
# Mantener solo logs importantes de tu aplicación    
logging.getLogger("core.assistant").setLevel(logging.INFO)    
logging.getLogger("core.commands").setLevel(logging.INFO)    
logging.getLogger("core.memory").setLevel(logging.INFO)  
  
load_dotenv()      
      
app = FastAPI()      
      
# Configurar CORS      
app.add_middleware(      
    CORSMiddleware,      
    allow_origins=["*"],      
    allow_credentials=True,      
    allow_methods=["*"],      
    allow_headers=["*"],      
)      
      
# Configuración JWT (solo una vez)      
JWT_SECRET = os.getenv("JWT_SECRET", "1925e2a0e6c8d8c196af044c77cc52dc")      
JWT_ALGORITHM = "HS256"      
security = HTTPBearer()     
      
# Modelos Pydantic      
class UserInput(BaseModel):      
    text: str | None = None   
    message: str | None = None  
    return_json: bool | None = None  
    source: str | None = None  
    username: str | None = None  
      
class UserCredentials(BaseModel):      
    username: str      
    password: str      
      
class UserRegister(BaseModel):      
    username: str      
    password: str      
    email: str      
  
# Funciones de autenticación  
def hash_password(password: str) -> str:      
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')      
      
def verify_password(password: str, hashed: str) -> bool:      
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))      
      
def create_jwt_token(username: str) -> str:      
    payload = {      
        "sub": username,      
        "exp": datetime.utcnow() + timedelta(days=30)      
    }      
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)      
      
def verify_jwt_token(token: str) -> str:      
    try:      
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])      
        return payload["sub"]      
    except jwt.ExpiredSignatureError:      
        raise HTTPException(status_code=401, detail="Token expirado")      
    except jwt.InvalidTokenError:      
        raise HTTPException(status_code=401, detail="Token inválido")      
      
def get_current_user(authorization: str = Header(None)) -> str:      
    if not authorization or not authorization.startswith("Bearer "):      
        raise HTTPException(status_code=401, detail="Token no proporcionado")      
    token = authorization.split(" ", 1)[1]      
    return verify_jwt_token(token)      
  
# Función para cargar memoria por usuario      
def load_user_memory(username: str):      
    """Carga la memoria específica del usuario"""         
          
    token = get_github_token()      
    if not token:      
        return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}      
          
    file_path = f"memory/users/{username}.json"      
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}?ref=main"      
    headers = {      
        "Authorization": f"token {token}",      
        "Accept": "application/vnd.github.v3.raw"      
    }      
          
    try:      
        r = requests.get(url, headers=headers, timeout=15)      
        if r.status_code == 200:      
            return json.loads(r.content)      
        elif r.status_code == 404:      
            return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}      
    except Exception as e:      
        print(f"Error cargando memoria de usuario: {e}")      
          
    return {"datos": {"ron_nombre": "Ron", "creador": username}, "conversaciones": []}      
      
def save_user_memory(username: str, memory_data: dict):      
    """Guarda la memoria específica del usuario"""      
  
    token = get_github_token()      
    if not token:      
        return False      
          
    file_path = f"memory/users/{username}.json"      
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}"      
          
    # Obtener SHA del archivo existente      
    headers = {"Authorization": f"token {token}"}      
    existing_file = requests.get(url, headers=headers)      
    sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None      
          
    # Preparar datos para GitHub      
    content = base64.b64encode(json.dumps(memory_data, indent=2).encode()).decode()      
    data = {      
        "message": f"Actualizar memoria de {username}",      
        "content": content,      
        "branch": "main"      
    }      
    if sha:      
        data["sha"] = sha      
          
    try:      
        response = requests.put(url, json=data, headers=headers)      
        return response.status_code in [200, 201]      
    except Exception as e:      
        print(f"Error guardando memoria de usuario: {e}")      
        return False      
      
# Detección de despedida      
def detect_farewell_in_api(text: str) -> bool:      
    farewells = [      
        "hasta luego", "adiós", "nos vemos", "chau",      
        "me voy", "cerrar sesión", "hasta pronto",      
        "bye", "see you", "goodbye"      
    ]      
    return any(farewell in text.lower() for farewell in farewells)      
      
def load_users_from_github():      
    """Carga la base de datos de usuarios desde GitHub"""      
  
    token = get_github_token()      
    if not token:      
        return {}      
          
    file_path = "users/users.json"      
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}?ref=main"      
    headers = {      
        "Authorization": f"token {token}",      
        "Accept": "application/vnd.github.v3.raw"      
    }      
          
    try:      
        r = requests.get(url, headers=headers, timeout=15)      
        if r.status_code == 200:      
            return json.loads(r.content)      
        elif r.status_code == 404:      
            return {}      
    except Exception as e:      
        print(f"Error cargando usuarios: {e}")      
          
    return {}      
      
def save_users_to_github(users_data: dict):      
    """Guarda la base de datos de usuarios en GitHub"""      
    token = get_github_token()      
    if not token:      
        return False      
          
    file_path = "users/users.json"      
    url = f"https://api.github.com/repos/rontubot/ron-memory-store/contents/{file_path}"      
          
    # Obtener SHA del archivo existente      
    headers = {"Authorization": f"token {token}"}      
    existing_file = requests.get(url, headers=headers)      
    sha = existing_file.json().get("sha") if existing_file.status_code == 200 else None      
          
    # Preparar datos para GitHub      
    content = base64.b64encode(json.dumps(users_data, indent=2).encode()).decode()      
    data = {      
        "message": "Actualizar base de datos de usuarios",      
        "content": content,      
        "branch": "main"      
    }      
    if sha:      
        data["sha"] = sha      
          
    try:      
        response = requests.put(url, json=data, headers=headers)      
        return response.status_code in [200, 201]      
    except Exception as e:      
        print(f"Error guardando usuarios: {e}")      
        return False

# Endpoints de autenticación      
@app.post("/auth/register")      
def register(user_data: UserRegister):      
    # Cargar usuarios existentes desde GitHub      
    users_db = load_users_from_github()      
          
    if user_data.username in users_db:      
        raise HTTPException(status_code=400, detail="Usuario ya existe")      
          
    # Agregar nuevo usuario      
    users_db[user_data.username] = {      
        "password": hash_password(user_data.password),      
        "email": user_data.email,      
        "created_at": datetime.utcnow().isoformat()      
    }      
          
    # Guardar en GitHub      
    if save_users_to_github(users_db):      
        return {"message": "Usuario registrado exitosamente"}      
    else:      
        raise HTTPException(status_code=500, detail="Error guardando usuario")    
      
  
@app.post("/auth/login")  
def login(credentials: UserCredentials, response: Response):  
    print(f"🔍 Login recibido - Username: {credentials.username}")  
  
    users_db = load_users_from_github()  
    user = users_db.get(credentials.username)  
    if not user or not verify_password(credentials.password, user["password"]):  
        raise HTTPException(status_code=401, detail="Credenciales inválidas")  
  
    token = create_jwt_token(credentials.username)  
  
    # OPCIONAL: cookie HttpOnly (útil si tu front decide leerla o la envías por fetch con credentials)  
    response.set_cookie(  
        key="ron_token",  
        value=token,  
        httponly=True,  
        samesite="lax",  
        secure=False  # True si sirves por HTTPS estrictamente  
    )  
  
    # Devolver ambas claves por compat  
    return {  
        "access_token": token,  
        "token": token,                # <- compat con front que espera 'token'  
        "token_type": "bearer",  
        "username": credentials.username  
    }  
  
  
@app.get("/auth/me")  
def auth_me(current_user: str = Depends(get_current_user)):  
    return {"ok": True, "username": current_user}  
  
  
  
@app.post("/auth/logout")      
def logout(current_user: str = Depends(get_current_user)):      
    # En una implementación real, podrías invalidar el token en una blacklist      
    return {"message": "Sesión cerrada exitosamente"}      
      
# Endpoints principales      
@app.get("/")      
def read_root():      
    return {"message": "Ron API está corriendo con autenticación"}      
      
  
@app.post("/ron")    
def chat_with_ron(data: UserInput, authorization: str = Header(None)):    
    # Requiere token    
    if authorization is None:    
        raise HTTPException(status_code=401, detail="Autenticación requerida")    
    
    current_user = None    
    if authorization.startswith("Bearer "):    
        token = authorization.split(" ", 1)[1]    
        current_user = verify_jwt_token(token)    
    else:    
        raise HTTPException(status_code=401, detail="Autenticación requerida")    
    
    # Aceptar 'text' o 'message'    
    user_text = (data.text or data.message or "").strip()    
    if not user_text:    
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")    
    
    # Username de trabajo    
    username_for_assistant = (data.username or current_user or "default").strip() or "default"    
    
    # 1) Generar respuesta RAW del LLM CON HISTORIAL    
    try:    
        from openai import OpenAI    
        from core.assistant import construir_historial_usuario_openai, parse_commands_only    
            
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))    
            
        # CLAVE: Construir historial CON las conversaciones previas del usuario    
        mensajes = construir_historial_usuario_openai(username_for_assistant)    
        mensajes.append({"role": "user", "content": user_text})    
            
        # Llamar a OpenAI    
        respuesta = client.chat.completions.create(    
            model="gpt-5-chat-latest",    
            messages=mensajes,    
            response_format={"type": "json_object"},    
            max_tokens=900,    
            temperature=0.7,    
        )    
            
        gpt_response = respuesta.choices[0].message.content.strip()    
            
        # CLAVE: Usar parse_commands_only en lugar de parse_and_execute_commands_dynamic    
        parsed = parse_commands_only(gpt_response)    
            
        user_response = parsed.get("user_response", "")    
        commands = parsed.get("commands", [])    
            
    except Exception as e:    
        print("ERROR /ron:", e)    
        traceback.print_exc()    
        fallback_msg = "Tuve un problema técnico al generar la respuesta. Intenta de nuevo en unos segundos."    
            
        # Registrar error en memoria    
        try:    
            mem = load_user_memory(current_user) or {"conversaciones": [], "datos": {}}    
            mem.setdefault("conversaciones", [])    
            mem["conversaciones"].append({    
                "user": user_text,    
                "ron": f"[error] {fallback_msg}",    
                "timestamp": datetime.utcnow().isoformat(),    
                "source": data.source or "web"    
            })    
            mem["conversaciones"] = mem["conversaciones"][-100:]    
            save_user_memory(current_user, mem)    
        except Exception as _:    
            pass    
            
        return {"ron": fallback_msg, "error": str(e), "commands": []}    
    
    # 2) Guardar conversación con add_to_memory (función pública)  
    try:    
        from core.memory import add_to_memory  
        # add_to_memory guarda en el formato correcto que construir_historial_usuario_openai espera  
        add_to_memory(username_for_assistant, user_text, user_response)  
    except Exception as e:    
        return {"ron": user_response, "commands": commands, "warning": f"No se pudo guardar la conversación: {str(e)}"}    
    
    # 3) Devolver respuesta CON comandos sin ejecutar    
    return {    
        "user_response": user_response,    
        "ron": user_response,    
        "reply": user_response,    
        "commands": commands    
    }  
  
  
@app.get("/user/profile")      
def get_user_profile(current_user: str = Depends(get_current_user)):      
    # Cargar usuarios desde GitHub      
    users_db = load_users_from_github()      
    user_data = users_db.get(current_user)      
          
    if not user_data:      
        raise HTTPException(status_code=404, detail="Usuario no encontrado")      
          
    return {      
        "username": current_user,      
        "email": user_data["email"],      
        "created_at": user_data["created_at"]      
    }     
      
@app.get("/user/conversations")      
def get_user_conversations(current_user: str = Depends(get_current_user)):      
    memory = load_user_memory(current_user)      
    return {      
        "conversations": memory.get("conversaciones", []),      
        "total": len(memory.get("conversaciones", []))      
    }      
      
@app.get("/github-token", response_class=PlainTextResponse)      
def get_github_token_endpoint():      
    token = os.getenv("GITHUB_TOKEN")      
    if not token:      
        return PlainTextResponse("Token no configurado", status_code=404)      
    return token      
      
@app.get("/health")      
def health_check():      
    return {"status": "ok", "authenticated": True}      
      
@app.get("/memory-status")      
def memory_status(current_user: str = Depends(get_current_user)):      
    try:      
        memory = load_user_memory(current_user)      
        conversations_count = len(memory.get("conversaciones", []))      
        reminders_count = len(memory.get("recordatorios", {}))      
        return {      
            "status": "ok",      
            "conversations": conversations_count,      
            "reminders": reminders_count,      
            "user": current_user      
        }      
    except Exception as e:      
        return {"status": "error", "message": str(e)}