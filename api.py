from fastapi import FastAPI, HTTPException, Depends, Header, Response, Request  
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
from fastapi.responses import StreamingResponse      
from core.memory import (    
    load_memory, add_to_memory, save_memory, get_github_token,    
    load_user_memory, save_user_memory, load_users_from_github, save_users_to_github    
)     
from core.assistant import generate_response_no_memory, parse_commands_only, construir_historial_usuario_openai, responder_a_usuario_streaming    
from core.memory import get_github_token as memory_get_github_token      
import requests      
import json      
import base64     
import traceback  
import re   
import logging    

  
# NUEVO: Limpiar markdown y emojis  
 

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
      


def clean_text_for_tts(text: str) -> str:  
    """Elimina caracteres especiales, emoticonos y markdown para TTS"""  
    
    # Eliminar emojis y símbolos especiales  
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑]+', '', text)  
      
    # Eliminar markdown (**, __, `, etc.)  
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **negrita**  
    text = re.sub(r'__([^_]+)__', r'\1', text)      # __negrita__  
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *cursiva*  
    text = re.sub(r'_([^_]+)_', r'\1', text)        # _cursiva_  
    text = re.sub(r'`([^`]+)`', r'\1', text)        # `código`  
      
    # Eliminar otros caracteres especiales comunes  
    text = re.sub(r'[✅❌🔍🔴🟢💤🔄🎤📨🤖]', '', text)  
      
    return text.strip()




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
  


def requires_autonomous_execution(text: str) -> bool:  
    """Determina si una solicitud requiere comandos que no están en el sistema básico"""  
    complex_keywords = [  
        "instalar programa", "desinstalar programa", "configurar red",  
        "cambiar configuración avanzada", "reparar registro", "modificar servicios",  
        "script personalizado", "automatización compleja", "limpia archivos",  
        "reinicia servicio", "configura firewall", "optimiza sistema"  
    ]  
      
    text_lower = text.lower()  
    return any(keyword in text_lower for keyword in complex_keywords)
        

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
        # Soportar tanto "sub" (nuevo) como "username" (antiguo) para compatibilidad  
        return payload.get("sub") or payload.get("username")  
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
    
    # 1) Generar respuesta CON HISTORIAL usando el sistema correcto  
    try:    
        from openai import OpenAI    
        from core.assistant import construir_historial_usuario_openai, parse_commands_only    
            
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))    
            
        # Construir historial CON las conversaciones previas del usuario      
        mensajes = construir_historial_usuario_openai(current_user)    
          
        # AGREGAR PROMPT COMPLETO CON EJEMPLOS FEW-SHOT  
        mensajes.append({  
            "role": "system",  
            "content": """  
        Eres Ron, un asistente que puede ejecutar CUALQUIER comando de Windows.  
          
        Formato de salida SIEMPRE:  
        {"user_response":"...","commands":[{"type":"cmd|powershell|python","command":"comando_exacto","safe":true}]}  
          
        REGLAS OBLIGATORIAS:  
        - NO uses markdown (**negrita**, *cursiva*, `código`), emojis (😀🔥✅), ni símbolos especiales en 'user_response'. Solo texto plano sin formato.  
        - NUNCA uses \n en 'user_response'. Usa puntos y comas para separar ideas.         
        - Para comandos básicos (abrir apps, YouTube, recordatorios), usa las acciones predefinidas: open_application, search_youtube, add_reminder, etc.  
        - Para comandos avanzados del sistema, genera comandos cmd/PowerShell/Python directamente.  
        - Marca safe:true solo si el comando es seguro (no destructivo).  
        - Si no estás seguro de cómo hacer algo, marca safe:false y explica por qué.  
          
        EJEMPLOS COMANDOS BÁSICOS:  
          
        Usuario: "abre chrome"  
        Asistente:  
        {"user_response":"Abriendo Google Chrome.","commands":[{"action":"open_application","params":{"app_name":"chrome"}}]}  
          
        Usuario: "busca en youtube cualquier cosa"  
        Asistente:  
        {"user_response":"Buscando en YouTube.","commands":[{"action":"search_youtube","params":{"query":"video popular","play_video":true}}]}  
          
        Usuario: "recuérdame llamar a mamá a las 8pm"  
        Asistente:  
        {"user_response":"Listo, te recordaré llamar a mamá a las 8pm.","commands":[{"action":"add_reminder","params":{"activity":"llamar a mamá","due_time":"20:00"}}]}  
          
        EJEMPLOS COMANDOS AVANZADOS:  
          
        Usuario: "sube el volumen al 80%"  
        Asistente:  
        {"user_response":"Subiendo volumen al 80%.","commands":[{"type":"powershell","command":"Set-Volume -Level 80","safe":true}]}  
          
        Usuario: "limpia archivos temporales"  
        Asistente:  
        {"user_response":"Limpiando archivos temporales.","commands":[{"type":"cmd","command":"del /q /f /s %TEMP%\\*","safe":true}]}  
          
        Usuario: "reinicia el servicio de audio"  
        Asistente:  
        {"user_response":"Reiniciando servicio de audio.","commands":[{"type":"cmd","command":"net stop audiosrv && net start audiosrv","safe":true}]}  
        """  
        })
                
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
          
        # Log para debugging  
        print(f"[DEBUG] GPT Response: {gpt_response[:200]}...")  
            
        # Usar parse_commands_only para extraer comandos SIN ejecutarlos    
        parsed = parse_commands_only(gpt_response)    
        
        # Limpiar markdown y emojis      
        user_response = parsed.get("user_response", "")  
        user_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', user_response)  # **negrita**  
        user_response = re.sub(r'\*([^*]+)\*', r'\1', user_response)      # *cursiva*  
        user_response = re.sub(r'`([^`]+)`', r'\1', user_response)        # `código`  
        user_response = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑✅❌🔍🔴🟢💤🔄]+', '', user_response)  # emojis   
        commands = parsed.get("commands", [])  

        # NUEVO: Detectar si hay comandos de Windows directos  
        windows_commands = []  
        basic_commands = []  
          
        for cmd in commands:  
            if cmd.get("type") in ["cmd", "powershell", "python"]:  
                windows_commands.append(cmd)  
            elif cmd.get("action"):  
                basic_commands.append(cmd)  
          
        # Si hay comandos de Windows, crear un plan de ejecución  
        if windows_commands:  
            from core.autonomous import create_execution_plan  
              
            # Convertir comandos de Windows a formato de plan  
            execution_plan = {  
                "task": user_text,  
                "steps": [  
                    {  
                        "order": i + 1,  
                        "command": cmd["command"],  
                        "type": cmd["type"],  
                        "description": f"Ejecutar: {cmd['command'][:50]}...",  
                        "timeout": 30  
                    }  
                    for i, cmd in enumerate(windows_commands) if cmd.get("safe", False)  
                ],  
                "estimated_time": len(windows_commands) * 5,  
                "requires_confirmation": False  
            }  
              
            # Agregar plan como comando especial  
            commands = basic_commands + [{  
                "action": "execute_autonomous_plan",  
                "params": {"plan": execution_plan}  
            }]  
        else:  
            commands = basic_commands  
          
        # Si NO hay comandos y la tarea requiere investigación autónoma  
        if not commands and requires_autonomous_execution(user_text):  
            from core.autonomous import research_system_commands, create_execution_plan  
              
            print(f"[DEBUG] Investigando comando autónomo para: {user_text}")  
            research_results = research_system_commands(user_text, current_user)  
              
            if research_results:  
                execution_plan = create_execution_plan(research_results)  
                if execution_plan:  
                    commands = [{  
                        "action": "execute_autonomous_plan",  
                        "params": {"plan": execution_plan}  
                    }]  
                    print(f"[DEBUG] Plan autónomo creado con {len(execution_plan['steps'])} pasos")
          
        # Log para debugging  
        print(f"[DEBUG] Parsed commands: {commands}")  
            
    except Exception as e:    
        print("ERROR /ron:", e)    
        traceback.print_exc()    
        fallback_msg = "Tuve un problema técnico al generar la respuesta. Intenta de nuevo en unos segundos."    
            
        # Registrar error en memoria    
        try:    
            from core.memory import add_to_memory  
            add_to_memory(current_user, user_text, f"[error] {fallback_msg}")  
        except Exception as _:    
            pass    
            
        return {"ron": fallback_msg, "error": str(e), "commands": []}    
    
    # 2) Guardar conversación    
    try:    
        from core.memory import add_to_memory  
        add_to_memory(current_user, user_text, user_response)  
    except Exception as e:    
        return {"ron": user_response, "commands": commands, "warning": f"No se pudo guardar la conversación: {str(e)}"}    
    
    # 3) Devolver respuesta CON comandos sin ejecutar    
    return {    
        "user_response": user_response,    
        "ron": user_response,    
        "reply": user_response,    
        "commands": commands    
    }



@app.post("/ron/stream")  
async def chat_with_ron_streaming(request: Request, authorization: str = Header(None)):  
    """Endpoint de streaming para respuestas progresivas"""  
    # Requiere token  
    if authorization is None:  
        raise HTTPException(status_code=401, detail="Autenticación requerida")  
      
    current_user = None  
    if authorization.startswith("Bearer "):  
        token = authorization.split(" ", 1)[1]  
        current_user = verify_jwt_token(token)  
    else:  
        raise HTTPException(status_code=401, detail="Autenticación requerida")  
      
    # Leer body  
    body = await request.json()  
    user_text = (body.get("text") or body.get("message") or "").strip()  
    if not user_text:  
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")  
      
    # Función generadora para SSE  
    async def generate_stream():  
        try:  
            from core.assistant import responder_a_usuario_streaming  
              
            # Generar chunks progresivamente  
            for chunk in responder_a_usuario_streaming(user_text, username=current_user):  
                # Formato SSE (Server-Sent Events)  
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"  
              
            # Señal de finalización  
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"  
              
        except Exception as e:  
            logger.exception("Error en streaming")  
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"  
      
    return StreamingResponse(  
        generate_stream(),  
        media_type="text/event-stream",  
        headers={  
            "Cache-Control": "no-cache",  
            "Connection": "keep-alive",  
            "X-Accel-Buffering": "no"  # Desactiva buffering en nginx  
        }  
    )


  
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