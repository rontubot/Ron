from fastapi import FastAPI, HTTPException, Depends, Header, Response, Request
from fastapi.security import HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse, StreamingResponse

import os, json, base64, traceback, re, logging
import jwt, bcrypt
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI


from core.memory import (
    load_memory, add_to_memory, save_memory,
    load_user_memory, save_user_memory,
    load_users_from_github, save_users_to_github,
)

from core.assistant import (
    generate_response_no_memory, parse_commands_only,
    construir_historial_usuario_openai, responder_a_usuario_streaming
)


# NUEVO: Limpiar markdown y emojis 

MD_BLOCK = re.compile(r"```.+?```", re.DOTALL)                # bloque ```code```
MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)   # ### heading
MD_BOLD = re.compile(r"\*\*(.*?)\*\*")
MD_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.*?)\*(?<!\*)")
MD_INLINE_CODE = re.compile(r"`([^`]+)`")
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
MD_LIST = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
MD_TABLE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
EMOJIS = re.compile(r"[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑✅❌🔍🔴🟢💤🔄🎤📨🤖]")

def strip_markdown(s: str) -> str:
    if not s:
        return s or ""
    s = MD_BLOCK.sub("", s)
    s = MD_IMAGE.sub(r"\1", s)
    s = MD_LINK.sub(r"\1", s)
    s = MD_HEADING.sub("", s)
    s = MD_TABLE.sub("", s)
    s = MD_LIST.sub("", s)
    s = MD_BOLD.sub(r"\1", s)
    s = MD_ITALIC.sub(r"\1", s)
    s = MD_INLINE_CODE.sub(r"\1", s)
    s = EMOJIS.sub("", s)
    # limpiar líneas vacías extra y espacios raros
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

  
 
 
# === Config de GitHub login (manteniendo tu flujo real) ===
ENABLE_GITHUB_LOGIN = os.getenv("ENABLE_GITHUB_LOGIN", "true").lower() == "true"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

def ensure_github_ready():
    """
    Lanza 503 si el login/registro requieren GitHub y no hay token.
    Evita fallar con 401 "Credenciales inválidas" cuando en realidad
    el backend no puede leer/escribir usuarios.
    """
    if ENABLE_GITHUB_LOGIN and not GITHUB_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Auth de GitHub habilitada pero falta GITHUB_TOKEN en el entorno del servidor."
        )

# Desactivar logs DEBUG de librerías externas    
logging.getLogger("urllib3").setLevel(logging.WARNING)    
logging.getLogger("httpcore").setLevel(logging.WARNING)    
logging.getLogger("openai").setLevel(logging.WARNING)    
logging.getLogger("httpx").setLevel(logging.WARNING)    
    
# Mantener solo logs importantes de tu aplicación    
logging.getLogger("core.assistant").setLevel(logging.INFO)    
logging.getLogger("core.commands").setLevel(logging.INFO)    
logging.getLogger("core.memory").setLevel(logging.INFO)  
  
   
      
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


def sanitize_user_response(text: str) -> str:  
    """  
    Elimina referencias técnicas, comandos internos, saltos de línea explícitos,  
    y cualquier detalle de implementación del user_response antes de enviarlo al usuario.  
    """  
    if not text:  
        return text  
      
    # 1. Eliminar saltos de línea explícitos (\n, \\n)  
    text = text.replace('\\n', ' ')  
    text = text.replace('\n', ' ')  
      
    # 2. Eliminar encabezados markdown (###, ##, #)  
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE)  
      
    # 3. Eliminar listas markdown (-, *, +)  
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  
      
    # 4. Eliminar nombres de comandos técnicos  
    technical_terms = [  
        'open_application', 'close_application', 'search_youtube', 'search_google',  
        'add_reminder', 'get_reminders', 'remove_reminder', 'update_reminder',  
        'set_volume', 'get_weather', 'create_file', 'create_folder', 'move_file',  
        'copy_file', 'delete_file', 'list_files', 'create_shortcut',  
        'diagnose_system_performance', 'check_system_services', 'clean_temp_files',  
        'flush_dns', 'network_reset', 'check_disk_space', 'system_file_check',  
        'shutdown', 'restart', 'suspend', 'get_weather'  
    ]  
    for term in technical_terms:  
        text = re.sub(rf'\b{term}\b', '', text, flags=re.IGNORECASE)  
      
    # 5. Eliminar markdown  
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **negrita**  
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *cursiva*  
    text = re.sub(r'`([^`]+)`', r'\1', text)        # `código`  
      
    # 6. Eliminar emojis  
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑✅❌🔍🔴🟢💤🔄]+', '', text)  
      
    # 7. Normalizar espacios múltiples  
    text = re.sub(r'\s{2,}', ' ', text)  
      
    return text.strip()



      
@app.head("/health")
def health_head():
    return Response(status_code=200)

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
  



# Endpoints de autenticación      
@app.post("/auth/register")      
def register(user_data: UserRegister):
    ensure_github_ready()      
    # Cargar usuarios existentes desde GitHub      
    users_db = load_users_from_github() or {}      
          
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
    ensure_github_ready()

    users_db = load_users_from_github() or {} 
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
    if authorization is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    token = authorization.split(" ", 1)[1]
    current_user = verify_jwt_token(token)

    user_text = (data.text or data.message or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        mensajes = construir_historial_usuario_openai(current_user)
        # AGREGAR PROMPT COMPLETO CON EJEMPLOS FEW-SHOT  
        mensajes.append({      
            "role": "system",      
            "content": """      
        Eres Ron, un asistente que puede ejecutar CUALQUIER comando de Windows.      
          
        REGLA CRÍTICA - NUNCA LISTAR CAPACIDADES:  
        Si el usuario pregunta "¿qué puedes hacer?", "ayuda", "qué sabes hacer", o similar:  
        - NO listes funciones técnicas  
        - NO menciones comandos específicos  
        - Responde de forma breve y genérica  
        - Invita al usuario a hacer una solicitud específica  
          
        Formato de salida SIEMPRE:      
        {"user_response":"...","commands":[{"type":"cmd|powershell|python","command":"comando_exacto","safe":true}]}      
                  
        REGLAS OBLIGATORIAS:      
        - NO uses markdown (**negrita**, *cursiva*, `código`), emojis (😀🔥✅), ni símbolos especiales en 'user_response'. Solo texto plano sin formato.      
        - NUNCA uses \n en 'user_response'. Usa puntos y comas para separar ideas.             
        - Para comandos básicos (abrir apps, YouTube, recordatorios), usa las acciones predefinidas: open_application, search_youtube, add_reminder, etc.      
        - Para comandos avanzados del sistema, genera comandos cmd/PowerShell/Python directamente.      
        - Marca safe:true solo si el comando es seguro (no destructivo).      
        - Si no estás seguro de cómo hacer algo, marca safe:false y explica por qué.      
          
        EJEMPLOS - PREGUNTAS SOBRE CAPACIDADES (IMPORTANTE):  
          
        Usuario: "¿qué puedes hacer?"  
        Asistente:  
        {"user_response":"Puedo ayudarte con tareas del sistema, búsquedas, recordatorios y más. ¿En qué necesitas ayuda?","commands":[]}  
          
        Usuario: "ayuda"  
        Asistente:  
        {"user_response":"Estoy aquí para ayudarte. ¿Qué necesitas que haga?","commands":[]}  
          
        Usuario: "qué sabes hacer"  
        Asistente:  
        {"user_response":"Puedo asistirte con diversas tareas. ¿Hay algo específico que quieras que haga?","commands":[]}  
                  
        EJEMPLOS - COMANDOS BÁSICOS:      
                  
        Usuario: "abre chrome"      
        Asistente:      
        {"user_response":"Abriendo Google Chrome.","commands":[{"action":"open_application","params":{"app_name":"chrome"}}]}      
                  
        Usuario: "busca en youtube cualquier cosa"      
        Asistente:      
        {"user_response":"Buscando en YouTube.","commands":[{"action":"search_youtube","params":{"query":"video popular","play_video":true}}]}      
                  
        Usuario: "recuérdame llamar a mamá a las 8pm"      
        Asistente:      
        {"user_response":"Listo, te recordaré llamar a mamá a las 8pm.","commands":[{"action":"add_reminder","params":{"activity":"llamar a mamá","due_time":"20:00"}}]}      
                  
        EJEMPLOS - COMANDOS AVANZADOS:      
                  
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

        respuesta = client.chat.completions.create(
            model="gpt-5-chat-latest",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=900,
            temperature=0.7,
        )

        gpt_response = respuesta.choices[0].message.content.strip()
        parsed = parse_commands_only(gpt_response)

        user_response = strip_markdown(parsed.get("user_response", "")) or ""
        user_response = user_response.strip()
        user_response = user_response.replace("\r", "")
        user_response = re.sub(r"\s*\n+\s*", " ", user_response)

        # Sanitizar user_response para eliminar referencias técnicas  
        user_response = sanitize_user_response(parsed.get("user_response", ""))  
        commands = parsed.get("commands", [])

        commands = parsed.get("commands", [])

        # Promover comandos de Windows a "plan" si aplica (idéntico a lo tuyo)
        windows_commands, basic_commands = [], []
        for cmd in commands:
            if cmd.get("type") in ["cmd", "powershell", "python"]:
                windows_commands.append(cmd)
            elif cmd.get("action"):
                basic_commands.append(cmd)

        if windows_commands:
            from core.autonomous import create_execution_plan
            execution_plan = {
                "task": user_text,
                "steps": [{
                    "order": i + 1,
                    "command": c["command"],
                    "type": c["type"],
                    "description": f"Ejecutar: {c['command'][:50]}...",
                    "timeout": 30
                } for i, c in enumerate(windows_commands) if c.get("safe", False)],
                "estimated_time": len(windows_commands) * 5,
                "requires_confirmation": False
            }
            commands = basic_commands + [{
                "action": "execute_autonomous_plan",
                "params": {"plan": execution_plan}
            }]
        else:
            commands = basic_commands

        if not commands and requires_autonomous_execution(user_text):
            from core.autonomous import research_system_commands, create_execution_plan
            research_results = research_system_commands(user_text, current_user)
            if research_results:
                plan = create_execution_plan(research_results)
                if plan:
                    commands = [{"action": "execute_autonomous_plan", "params": {"plan": plan}}]

    except Exception as e:
        traceback.print_exc()
        fallback_msg = "Tuve un problema técnico al generar la respuesta. Intenta de nuevo."
        try:
            add_to_memory(current_user, user_text, f"[error] {fallback_msg}")
        except Exception:
            pass
        return {"ron": fallback_msg, "error": str(e), "commands": []}

    # Guardar conversación
    try:
        add_to_memory(current_user, user_text, user_response)
    except Exception as e:
        return {"ron": user_response, "commands": commands,
                "warning": f"No se pudo guardar la conversación: {str(e)}"}
    if data.return_json:
        return {"user_response": user_response, "commands": commands}
    else:
        return PlainTextResponse(user_response)

@app.post("/ron/stream")
async def chat_with_ron_streaming(request: Request, authorization: str = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    current_user = verify_jwt_token(authorization.split(" ", 1)[1])

    body = await request.json()
    user_text = (body.get("text") or body.get("message") or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")

    async def event_generator():    
        full_text = ""    
        try:    
            import asyncio    
                
            # 1. Acumular todo el stream  
            for chunk in responder_a_usuario_streaming(user_text, current_user):    
                full_text += str(chunk or "")    
                
            # 2. Parsear JSON completo  
            try:    
                response_data = json.loads(full_text)    
                user_response_only = response_data.get("user_response", "")    
                commands = response_data.get("commands", [])    
            except json.JSONDecodeError:    
                # Si no es JSON válido, usar el texto completo  
                user_response_only = full_text    
                commands = []    
                
            # 3. Sanitizar para eliminar referencias técnicas  
            user_response_only = sanitize_user_response(user_response_only)    
                
            # 4. Enviar chunks pequeños del texto sanitizado  
            for i in range(0, len(user_response_only), 3):    
                chunk = user_response_only[i:i+3]    
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"    
                await asyncio.sleep(0.01)    
                
            # 5. Guardar conversación  
            try:    
                add_to_memory(current_user, user_text, user_response_only)    
            except Exception:    
                pass    
            
            # 6. Evento final con comandos  
            yield f"data: {json.dumps({'done': True, 'full_text': user_response_only, 'commands': commands}, ensure_ascii=False)}\n\n"    
            
        except Exception as e:    
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
              
            # Parsear el JSON completo  
            try:  
                parsed = json.loads(full_text)  
                user_response_only = parsed.get("user_response", "")  
                commands = parsed.get("commands", [])  
            except json.JSONDecodeError:  
                # Si no es JSON válido, usar el texto completo  
                user_response_only = full_text  
                commands = []  
              
            # Limpiar el texto final  
            user_response_only = strip_markdown(user_response_only)  
            user_response_only = user_response_only.replace("\r", "")  
            # NO eliminar espacios, solo normalizar saltos de línea múltiples  
            user_response_only = re.sub(r"\n{2,}", " ", user_response_only)  
            user_response_only = user_response_only.strip()  
              
            # Enviar el texto limpio chunk por chunk (con espacios preservados)  
            chunk_size = 5  # caracteres por chunk  
            for i in range(0, len(user_response_only), chunk_size):  
                chunk = user_response_only[i:i+chunk_size]  
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"  
                await asyncio.sleep(0.02)  # delay para efecto de escritura  
              
            # Guardar conversación  
            try:  
                add_to_memory(current_user, user_text, user_response_only)  
            except Exception:  
                pass  
      
            # Evento final  
            yield f"data: {json.dumps({'done': True, 'full_text': user_response_only, 'commands': commands}, ensure_ascii=False)}\n\n"  
      
        except Exception as e:  
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
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