from fastapi import FastAPI, HTTPException, Depends, Header, Response, Request, UploadFile, File
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
    add_reminder_item, list_reminders, update_reminder, remove_reminder_item
)

from core.assistant import (
    generate_response_no_memory, parse_commands_only,
    construir_historial_usuario_openai, responder_a_usuario_streaming,
    parse_and_execute_commands_dynamic
)
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
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑✅❌🔍🔴🟢💤🔄🎤📨🤖]+', '', text)  

    # 7. Normalizar espacios múltiples  
    text = re.sub(r'\s{2,}', ' ', text)

    # 8. Eliminar repeticiones consecutivas de frases
    #    (por ejemplo: "Hola...;Hola..." -> "Hola...")
    #    Partimos por separadores ; . ! ?
    parts = [p.strip() for p in re.split(r'[;.!?]+', text) if p.strip()]
    if len(parts) >= 2:
      dedup = []
      last = None
      for p in parts:
          if p == last:
              # si es igual a la anterior, lo saltamos
              continue
          dedup.append(p)
          last = p
      # Volvemos a unir con punto y coma suave
      text = '; '.join(dedup)

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
    """
    Endpoint principal de Ron (modo no streaming).
    Siempre devuelve JSON con este formato:

    {
        "user_response": "<texto plano para el usuario>",
        "commands": [ ... ],
        "shutdown": false,
        "ron": "<alias de user_response para compatibilidad antigua>"
    }
    """
    # --- 1) Autenticación básica ---
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticación requerida")

    token = authorization.split(" ", 1)[1]
    current_user = verify_jwt_token(token)

    # --- 2) Texto de usuario ---
    user_text = (data.text or data.message or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")

    try:
        # --- 3) Historial por usuario ---
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        mensajes = construir_historial_usuario_openai(current_user)

        # --- 4) System prompt unificado con MEMORIA DE CONTEXTO ---
        system_prompt_content = """
Eres Ron, un asistente que puede ejecutar comandos de Windows y automatizaciones locales.

🚨 VERIFICACIÓN EJECUTIVA (CRÍTICO):
1. ACCIÓN >>> PALABRAS: Tu objetivo PRINCIPAL es ejecutar comandos JSON. Hablar es secundario.
2. NO ALUCINES: Si el usuario pide "cambiar", "actualizar", "borrar" o "crear" algo, TUS PALABRAS NO VALEN NADA. Solo el JSON importa.
3. PROHIBIDO decir "He actualizado el recordatorio" si la lista "commands" está vacía. Eso es mentir.
4. Si vas a confirmar una acción, EL JSON DEBE ESTAR PRESENTE.

REGLA CRÍTICA DE INTERACCIÓN:
Si el usuario pregunta "¿qué puedes hacer?", "ayuda", "qué sabes hacer" o similar:
- NO listes funciones técnicas ni nombres de acciones internos.
- NO menciones comandos específicos (ni cmd, ni PowerShell, ni nombres de funciones).
- Responde de forma breve y genérica.
- Invita al usuario a hacer una solicitud específica.
- Intenta que todas tus respuestas sean rápidas: si te piden ejecutar algo y es seguro, hazlo sin pedir confirmación adicional.
"""

        # 🔹 Inyección de Contexto Dinámico (Memoria a Corto Plazo)
        try:
            ctx_path = os.path.join(os.getcwd(), 'temp', 'context_memory.json')
            if os.path.exists(ctx_path):
                import json
                with open(ctx_path, 'r', encoding='utf-8') as f:
                    ctx_data = json.load(f)
                    last_topic = ctx_data.get('last_reminder_topic')
                    ts = ctx_data.get('timestamp', 0)
                    
                    # Solo valido si fue en los últimos 60 segundos (contexto inmediato)
                    if last_topic and (time.time() - ts < 60):
                        system_prompt_content += f"\n\n🚨 CONTEXTO ACTIVO (IMPORTANTE): \nEl usuario acaba de interactuar sobre el recordatorio: '{last_topic}'.\nSi dice 'ese', 'cámbialo', 'ponle prioridad' o 'borra ese', SE REFIERE A '{last_topic}'.\nUsa 'original_title': '{last_topic}' en tus comandos."
        except Exception: pass

        system_prompt_content += """

⚠️ REGLA CRÍTICA PARA RUTAS DE ARCHIVOS:
- NUNCA uses rutas absolutas como "C:/Users/LMAR/Desktop/archivo.txt"
- SIEMPRE usa aliases relativos: "escritorio/archivo.txt", "documentos/archivo.txt", "descargas/archivo.txt"
- Los comandos de archivos (create_file, move_file, etc.) aceptan estos alias y los resuelven automáticamente al usuario actual
- Ejemplos válidos: "escritorio/notas.txt", "mis documentos/reporte.pdf", "descargas/imagen.jpg"
- NUNCA incluyas nombres de usuario específicos en las rutas

FORMATO DE RESPUESTA (OBLIGATORIO):

Siempre responde con UN SOLO JSON, sin texto extra, con esta forma general:
{
  "user_response": "texto plano para el usuario",
  "commands": [ ... ]
}

Los campos significan:

- user_response:
  - Resumen en lenguaje natural de lo que hiciste o vas a hacer.
  - SOLO texto plano; NO uses markdown (**negrita**, *cursiva*, `código`), ni emojis (😀🔥✅), ni símbolos especiales.
  - NO uses saltos de línea (\\n) ni viñetas; usa frases separadas por punto y coma.

- commands:
  - Lista que puede estar vacía [].
  - Cada elemento puede ser de DOS tipos:

  (A) COMANDO DE ALTO NIVEL (RECOMENDADO):

    {
      "action": "nombre_de_accion",
      "params": { ... },
      "safe": true
    }

    Acciones de alto nivel válidas incluyen, entre otras:
    - "open_application"
    - "close_application"
    - "search_youtube"
    - "search_google"
    - "add_reminder"
    - "get_reminders"
    - "remove_reminder"
    - "update_reminder"
    - "set_volume"
    - "create_file" (usa SOLO aliases: "escritorio/archivo.txt")
    - "create_folder" (usa SOLO aliases: "escritorio/mi_carpeta")
    - "move_file" (usa SOLO aliases en source y destination)
    - "diagnose_system_performance"
    - "clean_temp_files"
    - "execute_autonomous_plan"
    - "queue_local_task"

  (B) COMANDO DE SISTEMA (cmd/PowerShell/Python) PARA PLANES AUTÓNOMOS:

    {
      "type": "cmd" | "powershell" | "python",
      "command": "comando_exacto",
      "safe": true
    }

    - Usa este formato SOLO cuando realmente necesites un comando de sistema de bajo nivel.
    - "safe": true SI Y SOLO SI el comando no es destructivo.

⚠️ REGLA CRÍTICA PARA RECORDATORIOS (add_reminder):
- SIEMPRE extrae fecha y hora del texto del usuario
- Usa la FECHA DE HOY como referencia: %TODAY% (para calcular "mañana", "próximo sábado", etc.)
- Parámetros OBLIGATORIOS para add_reminder:
  * "title" o "activity": texto del recordatorio
  * "due_date": formato "YYYY-MM-DD" (ej: "%TOMORROW%" para mañana)
  * "due_time": formato "HH:MM" en 24h (ej: "15:00" para 3pm, "09:00" para 9am)

- Ejemplos de parsing:
  * "mañana a las 3pm" → due_date="%TOMORROW%", due_time="15:00"
  * "hoy 5pm" → due_date="%TODAY%", due_time="17:00"
  * "el lunes 10am" → calcular próximo lunes, due_time="10:00"  
  * "en 2 horas" → calcular desde ahora
  * "18 de diciembre 9am" → due_date="2025-12-18", due_time="09:00"
  
- Si NO se menciona hora, usa "09:00" por defecto.
- Si NO se menciona fecha, usa HOY (%TODAY%).
- NUNCA dejes due_date o due_time vacíos.

⚠️ REGLA PARA MODIFICAR RECORDATORIOS (update_reminder):
- Cuando el usuario quiera "cambiar", "modificar", "actualizar" o "corregir" un recordatorio:
  * USA "update_reminder". NO crees uno nuevo.
  * Params OBLIGATORIOS:
    - "original_title": el texto o título aproximado del recordatorio original (para buscarlo).
  * Params OPCIONALES (solo lo que cambia):
    - "due_date" / "due_time"
    - "new_title" (si cambia el texto)
    - "recurrence"
    - "priority": DEBE ser un ENTERO (1-5). PROHIBIDO usar strings como "alta" o "máxima".
  * Ejemplo: "cambia el recordatorio de la abuela para mañana a las 5"
    -> {"action": "update_reminder", "params": {"original_title": "abuela", "due_date": "%TOMORROW%", "due_time": "17:00"}}

  * Ejemplo: "ponle prioridad alta (5) al de sacar la basura"
    -> {"action": "update_reminder", "params": {"original_title": "basura", "priority": 5}}

  ⚠️ CRÍTICO - ANTI-ALUCINACIÓN:
  - Si tu respuesta dice "He actualizado...", "Lo he modificado...", etc., ES OBLIGATORIO generar el comando JSON.
  - NO respondas que lo hiciste si no incluyes el bloque {"action": "update_reminder"...} en "commands".
  - Si no estás seguro de cuál es el recordatorio, PREGUNTA antes de confirmar.


REGLAS OBLIGATORIAS PARA 'user_response':
- NO uses markdown, emojis ni símbolos especiales.
- NUNCA uses \\n ni * en 'user_response'. Usa puntos y comas para separar ideas.
- NO expliques detalles técnicos internos (no menciones 'open_application', 'execute_autonomous_plan', ni nombres de acciones internos).
- Habla siempre como un asistente amable y directo.

EJEMPLOS - PREGUNTAS SOBRE CAPACIDADES:

Usuario: "¿qué puedes hacer?"
Asistente:
{"user_response":"Puedo ayudarte con tareas del sistema, búsquedas, recordatorios y más; dime qué necesitas y lo hago","commands":[]}

Usuario: "ayuda"
Asistente:
{"user_response":"Estoy aquí para ayudarte; dime qué necesitas que haga","commands":[]}

Usuario: "qué sabes hacer"
Asistente:
{"user_response":"Puedo asistirte con diversas tareas en tu PC y con información; dime qué quieres que haga","commands":[]}

EJEMPLOS - COMANDOS CON ARCHIVOS (CRÍTICO - USA ALIASES):

Usuario: "crea un archivo hola.txt en el escritorio"
Asistente:
{"user_response":"Creando archivo hola.txt en el escritorio","commands":[{"action":"create_file","params":{"file_path":"escritorio/hola.txt","content":""},"safe":true}]}

Usuario: "guarda mis notas en documentos"
Asistente:
{"user_response":"Guardando archivo en documentos","commands":[{"action":"create_file","params":{"file_path":"documentos/notas.txt","content":"..."},"safe":true}]}

EJEMPLOS - COMANDOS BÁSICOS (ALTO NIVEL):

Usuario: "abre chrome"
Asistente:
{"user_response":"Abriendo Google Chrome","commands":[{"action":"open_application","params":{"app_name":"chrome"},"safe":true}]}

Usuario: "busca en youtube cualquier cosa"
Asistente:
{"user_response":"Buscando un video popular en YouTube","commands":[{"action":"search_youtube","params":{"query":"video popular","play_video":true},"safe":true}]}

Usuario: "recuérdame llamar a mamá a las 8pm"
Asistente:
{"user_response":"Voy a recordarte llamar a mamá a las ocho de la noche","commands":[{"action":"add_reminder","params":{"activity":"llamar a mamá","due_date":"%TODAY%","due_time":"20:00"},"safe":true}]}

EJEMPLOS - COMANDOS AVANZADOS (SISTEMA):

Usuario: "sube el volumen al 80%"
Asistente:
{"user_response":"Subiendo el volumen al ochenta por ciento","commands":[{"type":"powershell","command":"Set-Volume -Level 80","safe":true}]}

Usuario: "limpia archivos temporales"
Asistente:
{"user_response":"Limpiando archivos temporales","commands":[{"type":"cmd","command":"del /q /f /s %TEMP%\\\\*","safe":true}]}

Usuario: "reinicia el servicio de audio"
Asistente:
{"user_response":"Reiniciando el servicio de audio","commands":[{"type":"cmd","command":"net stop audiosrv && net start audiosrv","safe":true}]}
"""
        mensajes.append({
            "role": "system",
            "content": system_prompt_content
        })

        mensajes.append({"role": "user", "content": user_text})

        # --- 5) Llamada al modelo en modo JSON ---
        respuesta = client.chat.completions.create(
            model="gpt-5-chat-latest",
            messages=mensajes,
            response_format={"type": "json_object"},
            max_tokens=900,
            temperature=0.7,
        )

        gpt_response = (respuesta.choices[0].message.content or "").strip()

        # --- 6) Parsear JSON a estructura {user_response, commands} ---
        parsed = parse_commands_only(gpt_response) or {}

        # user_response: limpiar markdown, saltos y referencias técnicas
        raw_user_resp = parsed.get("user_response", "") or ""
        user_response = strip_markdown(raw_user_resp) or ""
        user_response = user_response.replace("\r", "")
        user_response = re.sub(r"\s*\n+\s*", " ", user_response)
        user_response = sanitize_user_response(user_response) or ""

        # commands tal como vienen del modelo
        commands = parsed.get("commands", []) or []

        # --- 7) Separar comandos de sistema (cmd/powershell/python) vs de alto nivel ---
        windows_commands, basic_commands = [], []
        for cmd in commands:
            if cmd.get("type") in ["cmd", "powershell", "python"]:
                windows_commands.append(cmd)
            elif cmd.get("action"):
                basic_commands.append(cmd)

        # --- 8) Si hay comandos de sistema, crear un plan autónomo ---
        if windows_commands:
            from core.autonomous import create_execution_plan

            execution_plan = {
                "task": user_text,
                "steps": [
                    {
                        "order": i + 1,
                        "command": c.get("command", ""),
                        "type": c.get("type", ""),
                        "description": f"Ejecutar: {c.get('command','')[:50]}...",
                        "timeout": 30,
                    }
                    for i, c in enumerate(windows_commands)
                    if c.get("safe", False)
                ],
                "estimated_time": len(windows_commands) * 5,
                "requires_confirmation": False,
            }

            commands = basic_commands + [{
                "action": "execute_autonomous_plan",
                "params": {"plan": execution_plan},
                "safe": True,
            }]
        else:
            commands = basic_commands

        # --- 9) Si no hay comandos pero el texto sugiere tarea compleja, intenta crear plan autónomo ---
        if not commands and requires_autonomous_execution(user_text):
            from core.autonomous import research_system_commands, create_execution_plan
            research_results = research_system_commands(user_text, current_user)
            if research_results:
                plan = create_execution_plan(research_results)
                if plan:
                    commands = [{
                        "action": "execute_autonomous_plan",
                        "params": {"plan": plan},
                        "safe": True,
                    }]

    except Exception as e:
        traceback.print_exc()
        fallback_msg = "Tuve un problema técnico al generar la respuesta; intenta de nuevo."
        try:
            add_to_memory(current_user, user_text, f"[error] {fallback_msg}")
        except Exception:
            pass

        # Respuesta de error NORMALIZADA
        return {
            "user_response": fallback_msg,
            "commands": [],
            "shutdown": False,
            "error": str(e),
            "ron": fallback_msg,  # alias de compat
        }

    # --- 10) Guardar conversación en memoria ---
    try:
        add_to_memory(current_user, user_text, user_response)
    except Exception as e:
        # Si falla la memoria, igual devolvemos respuesta al usuario
        return {
            "user_response": user_response,
            "commands": commands,
            "shutdown": False,
            "warning": f"No se pudo guardar la conversación: {str(e)}",
            "ron": user_response,  # alias de compat
        }

    # --- 11) NUEVO: Ejecutar comandos si vienen del móvil ---
    source = data.source or "unknown"
    if source == "mobile" and commands:
        print(f"📱 Ejecutando {len(commands)} comandos desde móvil...")
        
        # Importar aquí para evitar ciclos si no está arriba
        from core.commands import run_command
        
        extra_responses = []
        
        for cmd in commands:
            action = cmd.get("action")
            if action:
                try:
                    # Ejecutar comando directamente para capturar el resultado
                    print(f"▶️ Ejecutando acción: {action}")
                    res = run_command(action, cmd.get("params", {}), ctx={"username": current_user})
                    
                    # Extraer mensaje de resultado
                    cmd_result = res.get("message") or res.get("result") or ""
                    if cmd_result:
                        extra_responses.append(cmd_result)
                        print(f"✅ Resultado: {cmd_result[:50]}...")
                    else:
                        print(f"✅ Comando ejecutado (sin resultado visible)")
                        
                except Exception as e:
                    print(f"❌ Error ejecutando comando {action}: {e}")
                    traceback.print_exc()
                    extra_responses.append(f"Error al ejecutar {action}: {str(e)}")

        # Si hubo resultados de comandos, agregarlos a la respuesta del usuario
        if extra_responses:
            # Unir con saltos de línea limpios
            additional_text = "\n".join(extra_responses)
            if user_response:
                user_response += "\n\n" + additional_text
            else:
                user_response = additional_text
                
            # Actualizar memoria con la respuesta completa
            try:
                # Actualizamos la memoria para incluir el resultado de los comandos
                add_to_memory(current_user, user_text, user_response)
            except Exception:
                pass

    # --- 12) Respuesta normalizada (SIEMPRE JSON) ---
    payload = {
        "user_response": user_response,
        "commands": commands,
        "shutdown": False,
        "ron": user_response,  # alias para código viejo que aún lea 'ron'
    }

    return payload


@app.post("/ron/stream")  
async def chat_with_ron_streaming(request: Request, authorization: str = Header(None)):  
    """  
    Versión streaming que sanitiza correctamente la respuesta antes de enviarla.  
    """  
    if authorization is None or not authorization.startswith("Bearer "):  
        raise HTTPException(status_code=401, detail="Autenticación requerida")  
  
    token = authorization.split(" ", 1)[1]  
    current_user = verify_jwt_token(token)  
  
    body = await request.json()  
    user_text = (body.get("text") or body.get("message") or "").strip()  
    if not user_text:  
        raise HTTPException(status_code=400, detail="Falta 'text' o 'message' en el body")  
  
    async def event_generator():  
        import asyncio  
        try:  
            # 1) Construir el payload  
            data_model = UserInput(  
                text=user_text,  
                message=user_text,  
                return_json=True,  
                source=body.get("source") or "desktop-stream",  
                username=body.get("username") or current_user,  
            )  
  
            # 2) Obtener la respuesta completa de /ron  
            core_payload = chat_with_ron(data_model, authorization)  
  
            # 3) Extraer y sanitizar SOLO el user_response  
            user_response_only = core_payload.get("user_response") or ""  
              
            # 🔹 CRÍTICO: Sanitizar para eliminar cualquier JSON residual  
            user_response_only = sanitize_user_response(user_response_only)  
              
            # 🔹 NUEVO: Eliminar cualquier JSON que pueda haber quedado  
            import re  
            user_response_only = re.sub(r'\{[\s\S]*?"user_response"[\s\S]*?"commands"[\s\S]*?\}', '', user_response_only)  
            user_response_only = user_response_only.strip()  
  
            commands = core_payload.get("commands") or []  
  
            # 4) Enviar la respuesta como chunks (solo texto limpio)  
            if user_response_only:  
                for i in range(0, len(user_response_only), 3):  
                    chunk = user_response_only[i:i+3]  
                    yield (  
                        "data: "  
                        + json.dumps({"type": "chunk", "chunk": chunk}, ensure_ascii=False)  
                        + "\n\n"  
                    )  
                    await asyncio.sleep(0.01)  
  
            # 5) Evento final con comandos  
            done_payload = {  
                "type": "done",  
                "full_text": user_response_only,  
                "commands": commands,  
            }  
            yield "data: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n"  
  
        except Exception as e:  
            err_payload = {"type": "error", "error": str(e)}  
            yield "data: " + json.dumps(err_payload, ensure_ascii=False) + "\n\n"  
  
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

# Global Whisper model instance (Lazy loaded)
local_whisper_model = None

def get_whisper_model():
    global local_whisper_model
    if local_whisper_model is None:
        print("🔄 Loading local Faster-Whisper model...")
        try:
            from faster_whisper import WhisperModel
            # Int8 for speed and low memory on CPU
            local_whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            print("✅ Faster-Whisper model loaded.")
        except Exception as e:
            print(f"❌ Failed to load Faster-Whisper: {e}")
            raise e
    return local_whisper_model

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), authorization: str = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    
    # Verify token
    token = authorization.split(" ", 1)[1]
    verify_jwt_token(token)

    temp_filename = f"temp_{file.filename}"
    try:
        # Save temp file
        with open(temp_filename, "wb") as buffer:
            buffer.write(await file.read())
            
        # Transcribe using LOCAL Whisper
        model = get_whisper_model()
        segments, _ = model.transcribe(temp_filename, language="es", beam_size=1)
        
        text = " ".join([segment.text for segment in segments]).strip()
            
        # Cleanup
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        
        return {"text": text}
        
    except Exception as e:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        print(f"Transcription error: {str(e)}")
        # Improve error message for client
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

# --- Endpoints de Recordatorios (REST) ---

class ReminderModel(BaseModel):
    title: str
    description: str | None = None
    category: str | None = "inbox"
    status: str | None = "todo"
    priority: str | None = "normal"
    due_date: str | None = None
    due_time: str | None = None

class ReminderUpdateModel(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    due_time: str | None = None

@app.get("/reminders")
def get_reminders_endpoint(current_user: str = Depends(get_current_user)):
    return list_reminders(current_user)

@app.post("/reminders")
def create_reminder_endpoint(reminder: ReminderModel, current_user: str = Depends(get_current_user)):
    # Mapear campos opcionales
    return add_reminder_item(
        username=current_user,
        title=reminder.title,
        description=reminder.description or "",
        category=reminder.category or "inbox",
        status=reminder.status or "todo",
        priority=reminder.priority or "normal",
        due_date=reminder.due_date,
        due_time=reminder.due_time
    )

@app.put("/reminders/{reminder_id}")
def update_reminder_endpoint(reminder_id: str, reminder: ReminderUpdateModel, current_user: str = Depends(get_current_user)):
    # Filtrar campos no nulos
    update_data = {k: v for k, v in reminder.dict().items() if v is not None}
    updated = update_reminder(current_user, reminder_id, **update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    return updated

@app.delete("/reminders/{reminder_id}")
def delete_reminder_endpoint(reminder_id: str, current_user: str = Depends(get_current_user)):
    success = remove_reminder_item(current_user, reminder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    return {"status": "deleted", "id": reminder_id}