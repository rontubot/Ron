from fastapi import FastAPI, HTTPException, Depends, Header    
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials    
from fastapi.middleware.cors import CORSMiddleware    
from pydantic import BaseModel    
from fastapi.responses import PlainTextResponse    
import os    
import openai    
import jwt    
import bcrypt    
from datetime import datetime, timedelta    
from dotenv import load_dotenv    
from core.memory import (  
    load_memory, add_to_memory, save_memory, get_github_token,  
    load_user_memory, save_user_memory, load_users_from_github, save_users_to_github  
)   
from core.assistant import generate_response_no_memory    
from core.memory import get_github_token    
import requests    
import json    
import base64   
  
load_dotenv()    
    
openai.api_key = os.getenv("OPENAI_API_KEY")    
    
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
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-this")    
JWT_ALGORITHM = "HS256"    
security = HTTPBearer()   
    
# Modelos Pydantic    
class UserInput(BaseModel):    
    text: str    
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
  
class UserLogin(BaseModel):    
    username: str    
    password: str    
    
# Funciones de autenticación    
def hash_password(password: str) -> str:    
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')    
    
def verify_password(password: str, hashed: str) -> bool:    
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))    
    
def create_jwt_token(username: str) -> str:    
    payload = {    
        "username": username,    
        "exp": datetime.utcnow() + timedelta(hours=24)    
    }    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)    
    
def verify_jwt_token(token: str) -> str:    
    try:    
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])    
        return payload["username"]    
    except jwt.ExpiredSignatureError:    
        raise HTTPException(status_code=401, detail="Token expirado")    
    except jwt.InvalidTokenError:    
        raise HTTPException(status_code=401, detail="Token inválido")    
    
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:    
    return verify_jwt_token(credentials.credentials)    
    
# Función para cargar memoria por usuario    
def load_user_memory(username: str):    
    """Carga la memoria específica del usuario"""    
    from core.memory import get_github_token    
    import requests    
    import json    
        
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
    from core.memory import get_github_token    
    import requests    
    import json    
    import base64    
        
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
    from core.memory import get_github_token    
    import requests    
    import json    
        
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
def login(credentials: UserCredentials):  
    # AGREGAR: Logging para debugging  
    print(f"🔍 Login recibido - Username: {credentials.username}")  
    print(f"🔍 Datos completos: {credentials}")  
      
    # Cargar usuarios desde GitHub      
    users_db = load_users_from_github()      
          
    user = users_db.get(credentials.username)      
    if not user or not verify_password(credentials.password, user["password"]):      
        raise HTTPException(status_code=401, detail="Credenciales inválidas")      
          
    token = create_jwt_token(credentials.username)      
    return {      
        "access_token": token,      
        "token_type": "bearer",      
        "username": credentials.username      
    }
    
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
    # Verificar si hay token de autenticación    
    current_user = None    
    is_web_client = False    
        
    if authorization and authorization.startswith("Bearer "):    
        try:    
            token = authorization.split(" ")[1]    
            current_user = verify_jwt_token(token)    
            is_web_client = True    
        except:    
            # Si hay token pero es inválido, rechazar para clientes web    
            raise HTTPException(status_code=401, detail="Token de autenticación inválido")    
        
    # Para clientes web (con header Authorization), la autenticación es obligatoria    
    if authorization is not None and not is_web_client:    
        raise HTTPException(status_code=401, detail="Autenticación requerida")    
    
    # Manejar despedidas    
    if detect_farewell_in_api(data.text):    
        response = "Hasta luego. Que tengas un buen día."    
            
        if is_web_client and current_user:    
            # Para usuarios autenticados, usar memoria por usuario    
            try:    
                memory = load_user_memory(current_user)    
                memory["conversaciones"].append({    
                    "user": data.text,    
                    "ron": response,    
                    "timestamp": datetime.utcnow().isoformat()    
                })    
                save_user_memory(current_user, memory)    
            except Exception as e:    
                print(f"Error guardando despedida: {e}")    
        else:    
            # Para clientes de voz, usar sistema original    
            try:    
                add_to_memory(data.text, response)    
            except:    
                pass    
                    
        return {"ron": response, "shutdown": True}    
    
    try:    
        # Generar respuesta usando generate_response_no_memory para usuarios web    
        from core.assistant import generate_response_with_user_memory  
        ron_response = generate_response_with_user_memory(data.text, current_user)    
            
        # Guardar en memoria según el tipo de cliente    
        if is_web_client and current_user:    
            # Para usuarios autenticados web, usar memoria por usuario    
            try:    
                memory = load_user_memory(current_user)    
                memory["conversaciones"].append({    
                    "user": data.text,    
                    "ron": ron_response,    
                    "timestamp": datetime.utcnow().isoformat()    
                })    
                # Mantener solo las últimas 100 conversaciones    
                if len(memory["conversaciones"]) > 100:    
                    memory["conversaciones"] = memory["conversaciones"][-100:]    
                save_user_memory(current_user, memory)    
            except Exception as e:    
                print(f"Error guardando conversación: {e}")    
        else:    
            # Para clientes de voz sin autenticación, guardar en sistema original    
            try:    
                add_to_memory(data.text, ron_response)    
            except Exception as e:    
                print(f"Error guardando en memoria original: {e}")    
            
        return {"ron": ron_response}    
    except Exception as e:    
        return {"error": str(e)}   
    
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
def get_github_token():    
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