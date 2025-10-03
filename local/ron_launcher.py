import speech_recognition as sr      
import pyttsx3            
import json      
import re      
import subprocess      
import sys      
import os      
import webbrowser      
import logging      
import threading      
import queue      
import time    
import random       
import argparse  # Nuevo import  
import io
import socket
import unicodedata    
from core.commands import run_command
from core.assistant import generate_response_with_user_memory, generate_response_no_memory as core_generate_response 
from core.memory import add_to_memory


# Reducir logs DEBUG  
logging.getLogger('urllib3').setLevel(logging.WARNING)  
logging.getLogger('httpcore').setLevel(logging.WARNING)  
logging.getLogger('httpx').setLevel(logging.WARNING)  
logging.getLogger('openai').setLevel(logging.WARNING)


# Modo voz: no bloquees por comandos y apaga clasificador por turno
os.environ.setdefault("RON_ASYNC_COMMANDS", "1")
os.environ.setdefault("RON_PROFILE_TURN_CLASSIFIER", "0")


# --- Asegurar UTF-8 primero ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# --- Guardar stdout/stderr originales ---
_orig_stdout, _orig_stderr = sys.stdout, sys.stderr

# --- Silenciar prints de arranque si se pide ---
_silenced_stdout = None
_silenced_stderr = None
if os.getenv("RON_SUPPRESS_STARTUP", "1") == "1":
    _silenced_stdout = sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    _silenced_stderr = sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

    
try:  
    from core.assistant import client  
    print("✅ Importación exitosa del cliente OpenAI")  
except ImportError as e:  
    print(f"❌ Error de importación: {e}")

# ===== Ventana de interacción tras la wake-word =====
SILENCE_TIMEOUT_SEC = 1.2   # si no llega nada nuevo en 1.2s, se manda la orden
MAX_BUFFER_TIME_SEC = 30.0  # seguridad: no acumular más de 30s por turno

# Estado para agrupar
conversation_buffer = []
last_speech_time = 0.0
activation_time = 0.0


# NUEVAS IMPORTACIONES para memoria unificada  
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  

  
# Configuración de argumentos de línea de comandos    
parser = argparse.ArgumentParser(description='Ron 24/7 Voice Assistant')    
parser.add_argument('--username', type=str, help='Username del usuario autenticado')    
parser.add_argument('--control-port', type=int, default=9999, help='Puerto para control externo')    
args = parser.parse_args()    
    
# Variables globales para control externo    
current_username = args.username    
control_enabled = True  
  
# Silenciar logs de comtypes para reducir ruido      
logging.getLogger('comtypes').setLevel(logging.WARNING)      
          
      
# Configurar logging para debugging      
logging.basicConfig(level=logging.INFO)      
logger = logging.getLogger(__name__)      
      
engine = pyttsx3.init()      
engine.setProperty('rate', 185)      
voices = engine.getProperty('voices')      
for v in voices:      
    if 'spanish' in getattr(v, 'name', '').lower() or 'es' in getattr(v, 'id', '').lower():      
        engine.setProperty('voice', v.id)      
        break      
  
# lista de frases de activacion  
activation_phrases = [
    "¿Me llamaste?",    
    "Dime",    
    "¿En qué puedo ayudarte?",    
    "Aquí estoy",    
    "¿Qué necesitas?"    
]    
  
# Control de estado global    
speaking = False    
listening_active = False
manual_recording = False  
manual_recording_buffer = []  
manual_recording_start_time = 0.0  
external_control = True    
      
# Diccionario de aplicaciones web      
web_apps = {      
    "youtube": "https://www.youtube.com",      
    "google": "https://www.google.com",      
    "facebook": "https://www.facebook.com",      
    "instagram": "https://www.instagram.com",      
    "twitter": "https://www.twitter.com",      
    "tiktok": "https://www.tiktok.com",      
    "whatsapp": "https://web.whatsapp.com",      
    "linkedin": "https://www.linkedin.com",      
    "spotify": "https://open.spotify.com",      
    "netflix": "https://www.netflix.com"      
}







def handle_external_control():  
    """Maneja comandos de control desde Electron"""  

    def control_server():  
        global listening_active, speaking, control_enabled, manual_recording, manual_recording_buffer, manual_recording_start_time  
        try:  
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  
            server.bind(('127.0.0.1', args.control_port))  
            server.listen(5)  
            server.settimeout(0.5)  
            print(f"🎛️ Control server listening on port {args.control_port}", flush=True)  

            while control_enabled:  
                try:  
                    socket_client, _ = server.accept()  
                except socket.timeout:  
                    continue  
                except Exception as e:  
                    print(f"Error en control server (accept): {e}", flush=True)  
                    continue  

                try:  
                    data = socket_client.recv(8192)  
                    if not data:  
                        socket_client.sendall(b'EMPTY'); socket_client.close(); continue  

                    # ⚠️ Mantener una versión CRUDA (para EXEC/CHAT) y otra upper (para START/STOP/etc.)
                    raw_cmd = (data.decode('utf-8', errors='ignore') or '').strip()
                    cmd = raw_cmd.upper()

                    # ---- Comandos simples (comparación insensible a mayúsculas) ----
                    if cmd == 'START':  
                        listening_active = True; speaking = False  
                        socket_client.sendall(b'OK')  
                        print("📨 Comando recibido: START", flush=True)  

                    elif cmd == 'STOP':  
                        listening_active = False; speaking = False  
                        socket_client.sendall(b'OK')  
                        print("📨 Comando recibido: STOP", flush=True)  

                    elif cmd == 'STATUS':  
                        socket_client.sendall(b'ACTIVE' if listening_active else b'INACTIVE')  

                    elif cmd == 'START_MANUAL_RECORDING':  
                        manual_recording = True  
                        manual_recording_buffer.clear()  
                        manual_recording_start_time = time.time()  
                        listening_active = True  
                        speaking = False  
                        socket_client.sendall(b'RECORDING_STARTED')  
                        print("📨 Comando recibido: START_MANUAL_RECORDING", flush=True)  

                    elif cmd == 'STOP_MANUAL_RECORDING':  
                        manual_recording = False  
                        listening_active = False  
                        socket_client.sendall(b'RECORDING_STOPPED')  
                        print("📨 Comando recibido: STOP_MANUAL_RECORDING", flush=True)  

                    # ---- Comandos con payload JSON / texto (usar la versión CRUDA) ----
                    elif raw_cmd.startswith('EXEC::'):
                        try:
                            payload = raw_cmd[len('EXEC::'):].strip()
                            obj = json.loads(payload)
                            cmds = obj.get('commands') or []
                            results = []
                            for c in cmds:
                                action = (c.get('action') or '').strip()
                                params = c.get('params') or {}
                                if not action:
                                    continue
                                r = run_command(action, params, {"username": current_username})
                                results.append({
                                    "action": action,
                                    "ok": r.get("ok", True),
                                    "message": r.get("message") or r.get("result")
                                })
                            socket_client.sendall(f'RESULT:{json.dumps(results, ensure_ascii=False)}'.encode('utf-8'))
                        except Exception as e:
                            socket_client.sendall(f'ERROR:{e}'.encode('utf-8'))

                    elif raw_cmd.startswith('CHAT::'):
                        try:
                            text = raw_cmd[len('CHAT::'):].strip()
                            user = (current_username or 'default')

                            reply = core_generate_response(text, user)        

                            socket_client.sendall(reply.encode('utf-8', errors='ignore'))

                        except Exception as e:
                            socket_client.sendall(f'ERROR:{e}'.encode('utf-8'))

                    else:  
                        socket_client.sendall(b'UNKNOWN')  
                        print(f"📨 Comando recibido: {raw_cmd}", flush=True)  

                except Exception as e:  
                    try: socket_client.sendall(f'ERROR:{e}'.encode('utf-8', errors='ignore'))  
                    except Exception: pass  
                    print(f"Error en control server: {e}", flush=True)  
                finally:  
                    try: socket_client.close()  
                    except Exception: pass  
        except Exception as e:  
            print(f"Error iniciando control server: {e}", flush=True)  

    threading.Thread(target=control_server, daemon=True).start()

 
  
def setup_streaming_recognition():
    """Configura el reconocimiento de voz en streaming"""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 0.6  # más ágil
    recognizer.energy_threshold = 250

    try:
        microphone = sr.Microphone()  # usa default (WASAPI/MME)
    except OSError as e:
        print(f"❌ No se encontró micrófono o no hay permisos: {e}", flush=True)
        raise

    # Calibrar ruido ambiente
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)

    return recognizer, microphone 
      
def stream_audio_recognition(recognizer, microphone, audio_queue):  
    """Función que corre en background capturando audio"""  
    def callback(recognizer, audio):  
        global speaking, listening_active, manual_recording, manual_recording_buffer  
        if not speaking and listening_active:  
            try:  
                text = recognizer.recognize_google(audio, language="es")  
                text = (text or "").strip()  
                if text:  
                    if manual_recording:  
                        # Durante grabación manual, acumular todo el texto sin necesidad de wake word  
                        manual_recording_buffer.append(text.lower())  
                    else:  
                        # Lógica normal existente para detección de wake word  
                        audio_queue.put((text.lower(), time.time()))  
            except sr.UnknownValueError:  
                pass  
            except sr.RequestError:  
                pass  
  
    stop_listening = recognizer.listen_in_background(  
        microphone, callback, phrase_time_limit=6  
    )  
    return stop_listening
      

ALLOWED_WAKE_WORDS = {"ron", "rom", "rron", "ronn"}  # ajusta aquí las variantes permitidas

def _normalize_text(s: str) -> str:
    """Minúsculas y sin acentos/diacríticos para comparar tokens."""
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('utf-8', 'ignore')
    return s.lower()

def detect_ron_activation(text: str) -> bool:
    """
    Activa SOLO si aparece la palabra aislada 'ron' (o alguna variante explícita en ALLOWED_WAKE_WORDS).
    NO activa con subcadenas dentro de otras palabras (p. ej., 'chicharron', 'romel').
    """
    if not text:
        return False

    t = _normalize_text(text)

    # Tokenizar por límites de palabra: solo palabras alfanuméricas separadas
    tokens = re.findall(r'\b\w+\b', t)

    # Coincidencia exacta solo si el token completo está en la lista permitida
    # Esto cubre frases como "oye ron", "como estas ron", "ron", "oye rom", etc.
    return any(tok in ALLOWED_WAKE_WORDS for tok in tokens)
    
def safe_activation_response():    
    """Maneja la respuesta de activación de forma segura"""    
    global speaking, listening_active    
        
    speaking = True    
    listening_active = False    
        
    try:    
        # Seleccionar frase aleatoria    
        phrase = random.choice(activation_phrases)    
        engine.say(phrase)    
        engine.runAndWait()    
        time.sleep(0.5)    
    finally:    
        speaking = False    
        listening_active = True  
  


def load_device_memory():
    # TODO: cargar desde un JSON local si lo deseas
    return {"conversaciones": []}

def save_device_memory(mem):
    # TODO: persistir a un JSON local si lo deseas
    try:
        pass
    except Exception:
        pass



def should_stay_active(user_input, bot_response):  
    """Determina si Ron debe mantenerse activo basándose en el contexto mejorado"""  
      
    # Si el bot falló en ejecutar algo, mantener activo para retry  
    if any(indicator in bot_response for indicator in ["❌", "No pude", "Error", "no logré"]):  
        return True  
      
    # Si el bot pregunta algo o solicita más información, mantener activo  
    if any(indicator in bot_response for indicator in ["?", "¿", "dime", "cuéntame", "explícame"]):  
        return True  
      
    # Respuestas cortas del usuario indican continuación  
    short_responses = ["mmm", "ok", "sí", "no", "pero", "y", "entonces", "continúa", "sigue"]  
    if any(word in user_input.lower() for word in short_responses):  
        return True  
      
    # Frases que indican fin de conversación  
    end_phrases = ["hasta luego", "adiós", "nos vemos", "chao", "bye",   
                   "eso es todo", "gracias, eso es todo", "ya terminé", "perfecto", "listo"]  
      
    if any(phrase in user_input.lower() for phrase in end_phrases):  
        return False  
      
    # Si el bot ejecutó comandos exitosamente, preguntar si necesita algo más  
    if "✅ Completé" in bot_response:  
        return True  
      
    # Por defecto, no mantenerse activo para respuestas simples  
    return False


def research_system_commands(task_description, username):  
    """  
    Investiga comandos específicos de Windows para ejecutar tareas de forma completamente autónoma  
    """  
    research_prompt = f"""  
    TAREA: {task_description}  
      
    Eres un experto en comandos de Windows con acceso COMPLETO al sistema operativo.  
    PUEDES EJECUTAR CUALQUIER COMANDO que investigues y determines como seguro.  
      
    CAPACIDADES DISPONIBLES:  
    - PowerShell: Set-Volume, Get-Process, New-Item, Move-Item, Remove-Item, Set-ItemProperty, etc.  
    - CMD: nircmd, taskkill, mkdir, copy, move, del, reg add/delete, netsh, schtasks, etc.  
    - Herramientas del sistema: wmic, sc, bcdedit, diskpart, etc.  
    - APIs de Windows: rundll32, powercfg, control, etc.  
      
    EJEMPLOS DE LO QUE PUEDES HACER:  
    - Controlar volumen: nircmd setsysvolume [0-65535]  
    - Cambiar fondo: reg add "HKCU\\Control Panel\\Desktop" /v Wallpaper /t REG_SZ /d "ruta" /f  
    - Crear archivos: echo "contenido" > archivo.txt  
    - Mover archivos: move "origen" "destino"  
    - Configurar red: netsh wlan set profileparameter name="WiFi" cost=fixed  
    - Programar tareas: schtasks /create /tn "MiTarea" /tr "comando" /sc daily  
    - Controlar servicios: sc start/stop "servicio"  
    - Gestionar procesos: taskkill /f /im "proceso.exe"  
      
    INSTRUCCIONES:  
    1. INVESTIGA los comandos exactos necesarios para: {task_description}  
    2. ESTRUCTURA una secuencia lógica de comandos  
    3. MARCA como safe=true SOLO comandos que sean seguros de ejecutar  
    4. PROPORCIONA comandos REALES y EJECUTABLES, no explicaciones  
      
    Responde ÚNICAMENTE en formato JSON válido:  
    {{  
        "task_analysis": "descripción técnica de lo que se va a hacer",  
        "commands": [  
            {{"type": "cmd", "command": "comando_exacto_aquí", "description": "qué hace", "safe": true}},  
            {{"type": "powershell", "command": "comando_powershell", "description": "qué hace", "safe": true}}  
        ],  
        "prerequisites": ["requisitos si los hay"],  
        "estimated_time": 5,  
        "risk_level": "low"  
    }}  
      
    IMPORTANTE: Investiga y proporciona comandos REALES que funcionen en Windows.  
    """  
      
    try:  
        response = core_generate_response(research_prompt, username)  
        return parse_research_response(response)  
    except Exception as e:  
        print(f"❌ Error en investigación: {e}")  
        return None
  
def parse_research_response(response):
    """
    Parser robusto que puede extraer comandos de cualquier tipo de respuesta
    """
    if not response:
        return None

    try:
        # Aceptar dict directamente
        if isinstance(response, dict):
            return response

        # Normalizar a str
        if isinstance(response, (bytes, bytearray)):
            response = response.decode("utf-8", "replace")

        text = response.strip()

        # Intentar parsing directo del JSON
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                pass  # seguimos con las regex

        # Buscar JSON embebido en la respuesta (regex corregidas)
        json_patterns = [
            r'\{[^{}]*"commands"[^{}]*\[[^\]]*\][^{}]*\}',
            r'\{.*?"task_analysis".*?\}',
            r'\{.*?"commands".*?\}',
        ]

        for pattern in json_patterns:
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    continue

        # Parser de emergencia: extraer comandos de texto libre
        commands = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            lowered = line.lower()

            # Detectar comandos comunes
            if any(cmd in lowered for cmd in [
                'nircmd', 'reg add', 'taskkill', 'move ', 'copy ', 'mkdir',
                'echo ', 'powershell', 'wmic', 'sc ', 'netsh'
            ]):
                # Extraer el comando
                if ':' in line:
                    cmd_part = line.split(':', 1)[1].strip()
                else:
                    cmd_part = line

                # Determinar tipo
                cmd_type = "powershell" if (
                    'powershell' in lowered or
                    any(ps in lowered for ps in [' set-', ' get-', ' new-'])
                ) else "cmd"

                commands.append({
                    "type": cmd_type,
                    "command": cmd_part.strip("`\"\\'"),
                    "description": f"comando extraído: {cmd_part[:50]}...",
                    "safe": True
                })

        if commands:
            return {
                "task_analysis": f"Comandos extraídos para: {text[:100]}...",
                "commands": commands,
                "prerequisites": [],
                "estimated_time": 10,
                "risk_level": "medium"
            }

        return None

    except Exception as e:
        print(f"❌ Error parseando respuesta: {e}")
        return None

        

def autonomous_command_execution(user_request, username):  
    """  
    Sistema completamente autónomo que puede ejecutar CUALQUIER comando de Windows  
    """  
    print(f"🔍 Detectada solicitud que requiere investigación autónoma...")  
      
    # 1. Buscar en base de aprendizaje primero  
    learned_commands = search_learned_commands(user_request)  
    if learned_commands:  
        print("📚 Usando comandos de base de aprendizaje")  
        execution_plan = {  
            "task": user_request,  
            "steps": [{"command": cmd["command"], "type": cmd["type"], "description": cmd["description"]}   
                     for cmd in learned_commands],  
            "source": "learned"  
        }  
    else:  
        print("📚 Base de aprendizaje no tiene esta tarea, investigando...")  
          
        # 2. Investigación autónoma  
        research_results = research_system_commands(user_request, username)  
        if not research_results:  
            return {"success": False, "summary": "No pude investigar cómo realizar esta tarea"}  
          
        # 3. Crear plan de ejecución  
        execution_plan = create_execution_plan(research_results)  
        if not execution_plan:  
            return {"success": False, "summary": "No pude crear un plan de ejecución"}  
      
    # 4. Ejecutar plan  
    print(f"🚀 Ejecutando plan: {execution_plan.get('task', 'tarea')}")  
    execution_results = execute_autonomous_plan(execution_plan, username)  
      
    # 5. Si fue exitoso, guardar en base de aprendizaje  
    if execution_results.get("success") and execution_plan.get("source") != "learned":  
        save_successful_command(user_request, execution_plan["steps"], username)  
      
    return execution_results

def save_successful_command(task_description, commands, username):  
    """  
    Guarda comandos exitosos en base de datos de aprendizaje  
    """  
    try:  
        learned_commands_file = "learned_commands.json"  
          
        # Cargar comandos existentes  
        try:  
            with open(learned_commands_file, 'r', encoding='utf-8') as f:  
                learned_data = json.load(f)  
        except:  
            learned_data = {"commands": [], "contributors": {}}  
          
        # Agregar nuevo comando exitoso  
        new_entry = {  
            "task": task_description.lower(),  
            "commands": commands,  
            "success_count": 1,  
            "contributor": username,  
            "timestamp": time.time(),  
            "keywords": task_description.lower().split()  
        }  
          
        # Buscar si ya existe  
        existing = None  
        for i, cmd in enumerate(learned_data["commands"]):  
            if cmd["task"] == new_entry["task"]:  
                existing = i  
                break  
          
        if existing is not None:  
            learned_data["commands"][existing]["success_count"] += 1  
            learned_data["commands"][existing]["timestamp"] = time.time()  
        else:  
            learned_data["commands"].append(new_entry)  
          
        # Actualizar estadísticas de contribuidores  
        if username not in learned_data["contributors"]:  
            learned_data["contributors"][username] = 0  
        learned_data["contributors"][username] += 1  
          
        # Guardar  
        with open(learned_commands_file, 'w', encoding='utf-8') as f:  
            json.dump(learned_data, f, ensure_ascii=False, indent=2)  
              
        print(f"📚 Comando guardado en base de aprendizaje por {username}")  
          
    except Exception as e:  
        print(f"❌ Error guardando comando: {e}")  
  
def search_learned_commands(task_description):  
    """  
    Busca comandos aprendidos previamente para tareas similares  
    """  
    try:  
        learned_commands_file = "learned_commands.json"  
          
        with open(learned_commands_file, 'r', encoding='utf-8') as f:  
            learned_data = json.load(f)  
          
        task_lower = task_description.lower()  
        task_words = set(task_lower.split())  
          
        # Buscar coincidencias exactas primero  
        for cmd in learned_data["commands"]:  
            if cmd["task"] == task_lower:  
                print(f"📚 Comando encontrado en base de aprendizaje (exacto)")  
                return cmd["commands"]  
          
        # Buscar coincidencias por palabras clave  
        best_match = None  
        best_score = 0  
          
        for cmd in learned_data["commands"]:  
            cmd_words = set(cmd["keywords"])  
            intersection = task_words.intersection(cmd_words)  
            score = len(intersection) / len(task_words.union(cmd_words))  
              
            if score > 0.5 and score > best_score:  
                best_match = cmd  
                best_score = score  
          
        if best_match:  
            print(f"📚 Comando similar encontrado en base de aprendizaje (score: {best_score:.2f})")  
            return best_match["commands"]  
              
        return None  
          
    except Exception as e:  
        print(f"❌ Error buscando comandos aprendidos: {e}")  
        return None

  
def extract_commands_from_text(text):  
    """  
    Extrae comandos básicos del texto de respuesta  
    """  
    commands = []  
      
    # Patrones comunes de comandos  
    powershell_pattern = r'Set-AudioDevice|Get-Process|New-Item|Move-Item'  
    cmd_pattern = r'nircmd|tasklist|echo|move|copy|del'  
      
    if re.search(powershell_pattern, text, re.IGNORECASE):  
        commands.append({  
            "type": "powershell",  
            "command": "# Comando extraído del análisis",  
            "description": "Comando identificado automáticamente",  
            "safe": False  
        })  
      
    if re.search(cmd_pattern, text, re.IGNORECASE):  
        commands.append({  
            "type": "cmd",   
            "command": "# Comando extraído del análisis",  
            "description": "Comando identificado automáticamente",  
            "safe": False  
        })  
      
    return commands


def save_successful_command(task_description, command_info, username):  
    """  
    Guarda comandos exitosos en una base de datos de aprendizaje  
    """  
    try:  
          
        # Estructura del comando aprendido  
        learned_command = {  
            "task": task_description.lower().strip(),  
            "command": command_info["command"],  
            "type": command_info["type"],  
            "description": command_info["description"],  
            "success_count": 1,  
            "last_used": datetime.now().isoformat(),  
            "added_by": username,  
            "verified": True  
        }  
          
        # Cargar base de datos existente  
        try:  
            with open("learned_commands.json", "r", encoding="utf-8") as f:  
                learned_db = json.load(f)  
        except FileNotFoundError:  
            learned_db = {"commands": [], "version": "1.0"}  
          
        # Buscar si ya existe un comando similar  
        task_key = task_description.lower().strip()  
        existing_cmd = None  
        for cmd in learned_db["commands"]:  
            if cmd["task"] == task_key:  
                existing_cmd = cmd  
                break  
          
        if existing_cmd:  
            # Incrementar contador de éxito  
            existing_cmd["success_count"] += 1  
            existing_cmd["last_used"] = datetime.now().isoformat()  
            print(f"📚 Comando actualizado en base de aprendizaje (éxitos: {existing_cmd['success_count']})")  
        else:  
            # Agregar nuevo comando  
            learned_db["commands"].append(learned_command)  
            print(f"📚 Nuevo comando agregado a base de aprendizaje")  
          
        # Guardar base de datos actualizada  
        with open("learned_commands.json", "w", encoding="utf-8") as f:  
            json.dump(learned_db, f, ensure_ascii=False, indent=2)  
              
        return True  
          
    except Exception as e:  
        print(f"❌ Error guardando comando aprendido: {e}")  
        return False  
  
def search_learned_commands(task_description):  
    """  
    Busca comandos previamente aprendidos para la tarea  
    """  
    try:  
        import json  
          
        with open("learned_commands.json", "r", encoding="utf-8") as f:  
            learned_db = json.load(f)  
          
        task_key = task_description.lower().strip()  
          
        # Buscar coincidencia exacta  
        for cmd in learned_db["commands"]:  
            if cmd["task"] == task_key:  
                print(f"🎯 Comando encontrado en base de aprendizaje: {cmd['command']}")  
                return {  
                    "task_analysis": f"Comando aprendido para: {task_description}",  
                    "commands": [cmd],  
                    "execution_order": ["Ejecutar comando aprendido"],  
                    "estimated_success": min(95, 70 + (cmd["success_count"] * 5))  
                }  
          
        # Buscar coincidencias parciales  
        for cmd in learned_db["commands"]:  
            if any(word in cmd["task"] for word in task_key.split() if len(word) > 3):  
                print(f"🔍 Comando similar encontrado: {cmd['command']}")  
                return {  
                    "task_analysis": f"Comando similar para: {task_description}",  
                    "commands": [cmd],  
                    "execution_order": ["Ejecutar comando similar"],  
                    "estimated_success": min(80, 60 + (cmd["success_count"] * 3))  
                }  
          
        return None  
          
    except FileNotFoundError:  
        print("📚 Base de aprendizaje no existe aún")  
        return None  
    except Exception as e:  
        print(f"❌ Error buscando comandos aprendidos: {e}")  
        return None



def create_execution_plan(research_results):  
    """Crea un plan de ejecución estructurado basado en la investigación"""  
    if not research_results or not research_results.get("commands"):  
        print("❌ No hay comandos válidos para crear plan")  
        return None  
      
    execution_plan = {  
        "task": research_results.get("task_analysis", "Tarea no especificada"),  
        "steps": [],  
        "estimated_time": 5,  
        "requires_confirmation": False  
    }  
      
    for i, cmd in enumerate(research_results["commands"]):  
        if cmd.get("safe", False):  # Solo comandos marcados como seguros  
            step = {  
                "order": i + 1,  
                "command": cmd["command"],  
                "type": cmd["type"],  
                "description": cmd["description"],  
                "timeout": 30  
            }  
            execution_plan["steps"].append(step)  
      
    if not execution_plan["steps"]:  
        print("❌ No hay pasos seguros para ejecutar")  
        return None  
          
    print(f"✅ Plan creado con {len(execution_plan['steps'])} pasos")  
    return execution_plan
  
def validate_command_safety(command, command_type):  
    """  
    Valida si un comando es seguro para ejecutar  
    """  
    # Lista de comandos peligrosos  
    dangerous_patterns = [  
        r'format\\s+[c-z]:', r'del\\s+/s', r'rmdir\\s+/s',   
        r'shutdown', r'restart', r'reboot',  
        r'reg\\s+delete', r'sc\\s+delete'  
    ]  
      
    for pattern in dangerous_patterns:  
        if re.search(pattern, command, re.IGNORECASE):  
            return False, f"Comando potencialmente peligroso detectado: {pattern}"  
      
    # Comandos seguros conocidos  
    safe_patterns = [  
        r'nircmd\\s+setsysvolume', r'Set-AudioDevice',  
        r'echo\\s+.*>\\s*[^\\\\/:*?"<>|]+\\.txt',  
        r'New-Item.*-ItemType\\s+File',  
        r'tasklist', r'Get-Process'  
    ]  
      
    for pattern in safe_patterns:  
        if re.search(pattern, command, re.IGNORECASE):  
            return True, "Comando verificado como seguro"  
      
    return False, "Comando no verificado - requiere confirmación"


def execute_autonomous_plan(execution_plan, username):  
    """  
    Ejecuta el plan de comandos de forma autónoma con feedback  
    """  
    if not execution_plan:  
        return {"success": False, "message": "No hay plan de ejecución"}  
      
    results = {  
        "success": True,  
        "executed_commands": [],  
        "failed_commands": [],  
        "summary": "",  
        "total_steps": execution_plan["total_steps"]  
    }  
      
    print(f"🔧 Iniciando ejecución autónoma: {execution_plan['task_summary']}")  
      
    for step in execution_plan["execution_steps"]:  
        step_result = execute_single_command(step)  
          
        if step_result["success"]:  
            results["executed_commands"].append({  
                "step": step["step_number"],  
                "description": step["description"],  
                "output": step_result["output"]  
            })  
            print(f"✅ Paso {step['step_number']}: {step['description']}")  
        else:  
            results["failed_commands"].append({  
                "step": step["step_number"],  
                "description": step["description"],  
                "error": step_result["error"]  
            })  
            print(f"❌ Paso {step['step_number']} falló: {step_result['error']}")  
            results["success"] = False  
      
    # Generar resumen  
    if results["success"]:  
        results["summary"] = f"Tarea completada exitosamente. Ejecuté {len(results['executed_commands'])} comandos."  
    else:  
        results["summary"] = f"Tarea parcialmente completada. {len(results['executed_commands'])} exitosos, {len(results['failed_commands'])} fallaron."  
      
    return results  
  
def execute_single_command(command_info, username):  
    """  
    Ejecuta un comando individual del sistema operativo  
    """  
    command = command_info["command"]  
    cmd_type = command_info.get("type", "cmd")  
    timeout = command_info.get("timeout", 30)  
      
    print(f"🔧 Ejecutando: {command}")  
      
    try:  
        if cmd_type == "powershell":  
            # Ejecutar comando PowerShell  
            full_command = ["powershell", "-Command", command]  
        elif cmd_type == "cmd":  
            # Ejecutar comando CMD  
            full_command = ["cmd", "/c", command]  
        else:  
            # Comando directo  
            full_command = command.split()  
          
        # Ejecutar con timeout  
        result = subprocess.run(  
            full_command,  
            capture_output=True,  
            text=True,  
            timeout=timeout,  
            shell=False  
        )  
          
        if result.returncode == 0:  
            output = result.stdout.strip() if result.stdout else "Comando ejecutado exitosamente"  
            print(f"✅ Éxito: {output}")  
            return {  
                "success": True,  
                "output": output,  
                "command": command  
            }  
        else:  
            error = result.stderr.strip() if result.stderr else f"Error código {result.returncode}"  
            print(f"❌ Error: {error}")  
            return {  
                "success": False,  
                "error": error,  
                "command": command  
            }  
              
    except subprocess.TimeoutExpired:  
        print(f"⏰ Timeout ejecutando comando: {command}")  
        return {  
            "success": False,  
            "error": "Comando tardó demasiado en ejecutarse",  
            "command": command  
        }  
    except Exception as e:  
        print(f"❌ Excepción ejecutando comando: {e}")  
        return {  
            "success": False,  
            "error": str(e),  
            "command": command  
        }


# Funciones de control de PC y diagnóstico (basadas en core/commands.py)      
def open_application(app_name):      
    """Función para abrir aplicaciones localmente"""      
    try:      
        app_name_clean = app_name.lower().strip()      
        logger.info(f"Intentando abrir aplicación: {app_name_clean}")      
              
        # Buscar en aplicaciones web primero      
        if app_name_clean in web_apps:      
            webbrowser.open(web_apps[app_name_clean])      
            logger.info(f"Abriendo {app_name_clean} en navegador")      
            return f"Abriendo {app_name.capitalize()} en el navegador."      
              
        # Buscar coincidencias parciales en web apps      
        for key, url in web_apps.items():      
            if key in app_name_clean or app_name_clean in key:      
                webbrowser.open(url)      
                logger.info(f"Abriendo {key} en navegador (coincidencia parcial)")      
                return f"Abriendo {key.capitalize()} en el navegador."      
              
        # Intentar abrir aplicación local      
        cmd = f'start "" "{app_name}"'      
        logger.info(f"Ejecutando comando: {cmd}")      
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)      
              
        if result.returncode == 0:      
            logger.info(f"Aplicación {app_name} abierta exitosamente")      
            return f"Abriendo {app_name}."      
        else:      
            logger.error(f"Error al abrir {app_name}: {result.stderr}")      
            return f"Intentando abrir {app_name}."      
                  
    except Exception as e:      
        logger.error(f"Excepción al abrir {app_name}: {str(e)}")      
        return f"No pude abrir {app_name}: {e}"      
      
def close_application(app_name):      
    """Función para cerrar aplicaciones localmente"""      
    try:      
        process_name = app_name.lower() + ".exe"      
        logger.info(f"Intentando cerrar proceso: {process_name}")      
        result = subprocess.run(f'taskkill /F /IM {process_name}', shell=True, capture_output=True, text=True)      
              
        if "ERROR" in result.stdout:      
            logger.warning(f"No se encontró el proceso {app_name}")      
            return f"No se encontró el proceso {app_name}."      
              
        logger.info(f"Proceso {app_name} cerrado exitosamente")      
        return f"Cerrando {app_name}."      
    except Exception as e:      
        logger.error(f"Error al cerrar {app_name}: {str(e)}")      
        return f"Error al cerrar {app_name}: {e}"      
      
def search_google(query):      
    """Función para búsquedas en Google"""      
    try:      
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"      
        webbrowser.open(url)      
        logger.info(f"Búsqueda en Google ejecutada: {query}")      
        return f"Buscando en Google: {query}"      
    except Exception as e:      
        logger.error(f"Error al buscar en Google: {str(e)}")      
        return f"Error al buscar en Google: {e}"      
      

def search_youtube(query, play_video=False):
    try:
        if play_video:
            try:
                from youtube_search import YoutubeSearch
                logger.info(f"Buscando video para reproducir: {query}")
                results = YoutubeSearch(query, max_results=1).to_dict()
                if results:
                    url_suffix = results[0].get("url_suffix")
                    video_id = results[0].get("id")
                    video_url = f"https://www.youtube.com{url_suffix}" if url_suffix else (
                        f"https://www.youtube.com/watch?v={video_id}" if video_id else None
                    )
                    if video_url:
                        webbrowser.open(video_url)
                        logger.info(f"Video reproducido: {video_url}")
                        return f"Reproduciendo {query} en YouTube."
                logger.warning(f"No se encontraron resultados para: {query}")
                return "No encontré resultados para eso en YouTube."
            except ImportError:
                logger.warning("youtube-search no disponible, usando búsqueda normal")
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
                webbrowser.open(url)
                return f"Buscando en YouTube: {query}"
        else:
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(url)
            logger.info(f"Búsqueda en YouTube ejecutada: {query}")
            return f"Buscando en YouTube: {query}"
    except Exception as e:
        logger.error(f"Error al buscar en YouTube: {str(e)}")
        return f"Error al buscar en YouTube: {e}"

      
def shutdown():      
    """Función para apagar el sistema"""      
    try:      
        logger.info("Ejecutando comando de apagado")      
        os.system("shutdown /s /t 1")      
        return "Apagando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al apagar: {str(e)}")      
        return f"Error al apagar: {e}"      
      
def restart():      
    """Función para reiniciar el sistema"""      
    try:      
        logger.info("Ejecutando comando de reinicio")      
        os.system("shutdown /r /t 1")      
        return "Reiniciando la computadora..."      
    except Exception as e:      
        logger.error(f"Error al reiniciar: {str(e)}")      
        return f"Error al reiniciar: {e}"      
      
def suspend():      
    """Función para suspender el sistema"""      
    try:      
        logger.info("Ejecutando comando de suspensión")      
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")      
        return "Suspendiendo la computadora..."      
    except Exception as e:      
        logger.error(f"Error al suspender: {str(e)}")      
        return f"Error al suspender: {e}"

# ===== NUEVAS FUNCIONES DE DIAGNÓSTICO LOCAL =====      
      
def diagnose_system_performance():      
    """Diagnostica rendimiento del sistema localmente"""      
    try:      
        logger.info("Iniciando diagnóstico de rendimiento del sistema")      
              
        # Verificar uso de CPU      
        cpu_result = subprocess.run('wmic cpu get loadpercentage /value', shell=True, capture_output=True, text=True)      
        cpu_usage = re.search(r'LoadPercentage=(\\d+)', cpu_result.stdout)      
        cpu_percent = cpu_usage.group(1) if cpu_usage else 'N/A'      
              
        # Verificar memoria      
        memory_result = subprocess.run('wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /value', shell=True, capture_output=True, text=True)      
        total_memory = re.search(r'TotalVisibleMemorySize=(\\d+)', memory_result.stdout)      
        free_memory = re.search(r'FreePhysicalMemory=(\\d+)', memory_result.stdout)      
              
        if total_memory and free_memory:      
            total_mb = int(total_memory.group(1)) // 1024      
            free_mb = int(free_memory.group(1)) // 1024      
            used_percent = ((total_mb - free_mb) / total_mb) * 100      
            memory_status = f"Memoria: {used_percent:.1f}% en uso ({free_mb}MB libres de {total_mb}MB)"      
        else:      
            memory_status = "Memoria: No se pudo obtener información"      
              
        result = f"CPU: {cpu_percent}% de uso. {memory_status}. Diagnóstico completado."      
        logger.info(f"Diagnóstico completado: {result}")      
        return result      
              
    except Exception as e:      
        logger.error(f"Error en diagnóstico de rendimiento: {str(e)}")      
        return f"Error al diagnosticar el sistema: {e}"      
      
def check_system_services():      
    """Verifica servicios críticos del sistema localmente"""      
    try:      
        logger.info("Verificando servicios críticos del sistema")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS', 'Dhcp', 'Dnscache']      
        results = []      
        problems = []      
              
        for service in critical_services:      
            try:      
                result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" in result.stdout:      
                    results.append(f"{service}: OK")      
                else:      
                    results.append(f"{service}: PROBLEMA")      
                    problems.append(service)      
            except:      
                results.append(f"{service}: ERROR")      
                problems.append(service)      
              
        status = "Servicios verificados: " + ", ".join(results)      
        if problems:      
            status += f". Servicios con problemas detectados: {', '.join(problems)}"      
              
        logger.info(f"Verificación de servicios completada: {len(problems)} problemas encontrados")      
        return status      
              
    except Exception as e:      
        logger.error(f"Error verificando servicios: {str(e)}")      
        return f"Error al verificar servicios: {e}"    
      
def restart_critical_services():      
    """Reinicia servicios críticos que están parados"""      
    try:      
        logger.info("Reiniciando servicios críticos")      
        critical_services = ['Spooler', 'Themes', 'AudioSrv', 'BITS']      
        restarted = []      
              
        for service in critical_services:      
            try:      
                # Verificar estado actual      
                check_result = subprocess.run(f'sc query "{service}"', shell=True, capture_output=True, text=True)      
                if "RUNNING" not in check_result.stdout:      
                    # Intentar reiniciar      
                    stop_result = subprocess.run(f'net stop "{service}"', shell=True, capture_output=True, text=True)      
                    start_result = subprocess.run(f'net start "{service}"', shell=True, capture_output=True, text=True)      
                    if start_result.returncode == 0:      
                        restarted.append(service)      
                        logger.info(f"Servicio {service} reiniciado exitosamente")      
            except Exception as e:      
                logger.warning(f"No se pudo reiniciar {service}: {e}")      
              
        if restarted:      
            return f"Servicios reiniciados: {', '.join(restarted)}"      
        else:      
            return "No fue necesario reiniciar servicios o no se pudieron reiniciar"      
                  
    except Exception as e:      
        logger.error(f"Error reiniciando servicios: {str(e)}")      
        return f"Error al reiniciar servicios: {e}"      
      
def clean_temp_files():      
    """Limpia archivos temporales del sistema"""      
    try:      
        logger.info("Iniciando limpieza de archivos temporales")      
              
        # Limpiar archivos temporales del usuario      
        temp_result = subprocess.run('del /q /f /s "%temp%\\\\*" 2>nul', shell=True, capture_output=True, text=True)      
              
        # Limpiar archivos temporales del sistema      
        system_temp_result = subprocess.run('del /q /f /s "C:\\\\Windows\\\\Temp\\\\*" 2>nul', shell=True, capture_output=True, text=True)      
              
        logger.info("Limpieza de archivos temporales completada")      
        return "Archivos temporales limpiados. Se liberó espacio en disco."      
              
    except Exception as e:      
        logger.error(f"Error limpiando archivos temporales: {str(e)}")      
        return f"Error al limpiar archivos temporales: {e}"      
      
def network_reset():    
    """Reinicia adaptadores de red"""      
    try:      
        logger.info("Reiniciando adaptadores de red")      
        print("🔧 Reiniciando adaptadores de red...")      
              
        # Reiniciar adaptador de red      
        reset_result = subprocess.run('netsh winsock reset', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado netsh winsock reset: {reset_result.stdout.strip()}")      
              
        # Renovar IP      
        release_result = subprocess.run('ipconfig /release', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado ipconfig /release: {release_result.stdout.strip()}")      
              
        renew_result = subprocess.run('ipconfig /renew', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado ipconfig /renew: {renew_result.stdout.strip()}")      
              
        logger.info("Adaptadores de red reiniciados")      
        return "Adaptadores de red reiniciados. Reinicia la computadora para aplicar cambios."      
              
    except Exception as e:      
        logger.error(f"Error reiniciando red: {str(e)}")      
        return f"Error al reiniciar red: {e}"    
      
def flush_dns():      
    """Limpia la caché DNS"""      
    try:      
        logger.info("Limpiando caché DNS")      
        print("🔧 Limpiando caché DNS...")      
              
        result = subprocess.run('ipconfig /flushdns', shell=True, capture_output=True, text=True)      
        print(f"📋 Resultado del comando: {result.stdout.strip()}")      
              
        logger.info("Caché DNS limpiada exitosamente")      
        return "Caché DNS limpiada. Problemas de conexión resueltos."      
    except Exception as e:      
        logger.error(f"Error limpiando DNS: {str(e)}")      
        return f"Error al limpiar DNS: {e}"

def handle_local_commands(text):        
    """Maneja comandos localmente antes de enviar al servidor"""      
    global speaking, listening_active      
          
    original_text = text        
    text = text.lower().strip()        
            
    # DETECCIÓN AUTOMÁTICA DE PROBLEMAS DEL SISTEMA        
    problem_keywords = ["lento", "problema", "no funciona", "error", "falla", "se cuelga", "no responde",         
                       "muy lento", "se traba", "no abre", "no carga", "internet no funciona",         
                       "no puedo imprimir", "no hay sonido", "pantalla azul"]        
            
    if any(keyword in text for keyword in problem_keywords):        
        logger.info("🔧 Problema del sistema detectado - Iniciando diagnóstico automático")        
              
        # Pausar reconocimiento durante diagnóstico      
        speaking = True      
        listening_active = False      
              
        try:      
            # Ejecutar diagnóstico automático        
            diagnostic_result = diagnose_system_performance()        
            services_result = check_system_services()        
                    
            # Analizar resultados y proponer solución        
            analysis = f"He diagnosticado tu sistema automáticamente. {diagnostic_result} {services_result}"        
                    
            # Ejecutar reparación automática si es necesario        
            repairs_made = []        
                    
            if "PROBLEMA" in services_result or "ERROR" in services_result:        
                repair_result = restart_critical_services()        
                repairs_made.append(repair_result)        
                analysis += f" He reparado los servicios problemáticos: {repair_result}"        
                    
            # Si hay problemas de rendimiento, limpiar archivos temporales        
            if "CPU:" in diagnostic_result and any(word in text for word in ["lento", "se traba"]):        
                clean_result = clean_temp_files()        
                repairs_made.append(clean_result)        
                analysis += f" También limpié archivos temporales para mejorar el rendimiento: {clean_result}"        
                    
            # Si hay problemas de internet, limpiar DNS        
            if any(word in text for word in ["internet", "conexión", "red", "wifi"]):        
                dns_result = flush_dns()        
                repairs_made.append(dns_result)        
                analysis += f" Limpié la caché DNS para resolver problemas de conexión: {dns_result}"        
                    
            if repairs_made:        
                analysis += " Intenta usar tu computadora ahora para ver si el problema se resolvió."        
                    
            print(f"🤖 Ron: {analysis}")        
            engine.say(analysis)        
            engine.runAndWait()      
            time.sleep(0.5)      
        finally:      
            speaking = False      
            listening_active = True      
        return True        
      
    # Función auxiliar para manejar respuestas con control de estado      
    def safe_response(result_text):      
        global speaking, listening_active      
        speaking = True      
        listening_active = False      
        try:      
            print(f"🤖 Ron: {result_text}")      
            engine.say(result_text)      
            engine.runAndWait()      
            time.sleep(0.5)      
        finally:      
            speaking = False      
            listening_active = True      
      
    # COMANDOS DE DIAGNÓSTICO EXPLÍCITOS        
    if any(cmd in text for cmd in ["diagnostica el sistema", "verifica la memoria", "revisa el rendimiento"]):        
        result = diagnose_system_performance()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["verifica servicios", "estado de servicios", "revisa servicios"]):        
        result = check_system_services()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["repara servicios", "reinicia servicios", "arregla servicios"]):        
        result = restart_critical_services()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["limpia archivos temporales", "optimiza el sistema", "limpia la computadora"]):        
        result = clean_temp_files()        
        safe_response(result)      
        return True        
      
    if any(cmd in text for cmd in ["limpia dns", "reinicia dns", "arregla internet"]):        
        result = flush_dns()        
        safe_response(result)      
        return True        
            
    # Comandos de abrir aplicaciones        
    if text.startswith("abre "):        
        app_name = text.replace("abre ", "").strip()        
        result = open_application(app_name)        
        safe_response(result)      
        return True        
            
    # Comandos de cerrar aplicaciones        
    if text.startswith("cierra "):        
        app_name = text.replace("cierra ", "").strip()        
        result = close_application(app_name)        
        safe_response(result)      
        return True        
            
    # Comandos de búsqueda        
    if text.startswith("investiga "):        
        query = text.replace("investiga ", "").strip()        
        result = search_google(query)        
        safe_response(result)      
        return True        
            
    if text.startswith("youtube "):        
        query = text.replace("youtube ", "").strip()        
        result = search_youtube(query)        
        safe_response(result)      
        return True        
            
    if text.startswith("reproducir ") or text.startswith("reproduce "):        
        query = text.replace("reproducir ", "").replace("reproduce ", "").strip()        
        result = search_youtube(f"música {query}", play_video=True)        
        safe_response(result)      
        return True        
            
    # Comandos de sistema        
    if "apaga la computadora" in text or "apaga el sistema" in text:        
        result = shutdown()        
        safe_response(result)      
        return True        
            
    if "reinicia la computadora" in text or "reinicia el sistema" in text:        
        result = restart()        
        safe_response(result)      
        return True        
            
    if "suspende la computadora" in text or "suspende el sistema" in text:        
        result = suspend()        
        safe_response(result)      
        return True        
          
    if any(cmd in text for cmd in ["reinicia red", "reinicia driver de red", "arregla driver"]):        
        result = network_reset()        
        safe_response(result)      
        return True      
      
    return False    
    
def talk_to_ron(text):  
    """Versión con sistema de aprendizaje integrado"""  
    global speaking, listening_active, activado  
      
    speaking = True  
    listening_active = False  
      
    try:  
        # Verificar si requiere investigación autónoma  
        if requires_autonomous_execution(text):  
            print("🔍 Detectada solicitud que requiere investigación autónoma...")  
              
            # Primero buscar en comandos aprendidos  
            learned_result = search_learned_commands(text)  
            if learned_result:  
                print("🎯 Usando comando aprendido...")  
                autonomous_result = execute_autonomous_plan(learned_result, current_username)  
            else:  
                print(f"🔍 Investigando: {text}")  
                autonomous_result = autonomous_command_research_and_execution(text, current_username)  
              
            if autonomous_result.get("success", False):  
                executed_commands = autonomous_result.get("executed_commands", [])  
                response = f"✅ Completé tu solicitud. Ejecuté {len(executed_commands)} comando(s)."  
                for cmd in executed_commands[:3]:  # Mostrar máximo 3 comandos  
                    response += f"\\n• {cmd}"  
                  
                # Preguntar si funcionó para aprendizaje  
                response += "\\n\\n¿Funcionó correctamente? Esto me ayuda a aprender."  
                  
                # Guardar comandos exitosos (se confirmará después)  
                if learned_result is None:  # Solo si no era un comando ya aprendido  
                    for cmd_info in autonomous_result.get("command_details", []):  
                        save_successful_command(text, cmd_info, current_username)  
                          
            else:  
                response = f"❌ No pude completar tu solicitud: {autonomous_result.get('summary', 'Error desconocido')}. ¿Quieres que lo intente de otra manera?"  
        else:  
            # Flujo normal de conversación  
            response = core_generate_response(text, current_username)  
          
        if response:  
            print(f"🤖 Ron: {response}")  
            engine.say(response)  
            engine.runAndWait()  
            time.sleep(0.5)  
              
            # Guardar en memoria  
            if current_username:  
                add_to_memory(current_username, text, response)  
              
            # Determinar si debe mantenerse activo  
            stay_active = should_stay_active(text, response)  
              
            return {  
                "shutdown": False,   
                "stay_active": stay_active,   
                "response": response  
            }  
              
    except Exception as e:  
        print(f"❌ Error: {e}")  
        engine.say("Ocurrió un error.")  
        engine.runAndWait()  
        return {"shutdown": False, "stay_active": False, "response": "Error"}  
          
    finally:  
        speaking = False  
        listening_active = True  
      
    return {"shutdown": False, "stay_active": False, "response": ""}

  
def requires_autonomous_execution(text):  
    """  
    Determina si una solicitud requiere investigación y ejecución autónoma  
    """  
    autonomous_keywords = [  
        "volumen", "crear archivo", "mover archivo", "abrir carpeta",  
        "cambiar configuración", "ajustar", "configurar", "instalar",  
        "desinstalar", "limpiar", "optimizar", "reparar", "verificar estado"  
    ]  
      
    return any(keyword in text.lower() for keyword in autonomous_keywords)  
  
def autonomous_command_research_and_execution(user_request, username):  
    """  
    Sistema completo de investigación, planificación y ejecución autónoma  
    """  
    print(f"🔍 Investigando: {user_request}")  
      
    # 1. Investigación  
    research_results = research_system_commands(user_request, username)  
    if not research_results:  
        return {"success": False, "summary": "No pude investigar cómo realizar esta tarea"}  
      
    # 2. Planificación  
    execution_plan = create_execution_plan(research_results)  
    if not execution_plan:  
        return {"success": False, "summary": "No pude crear un plan de ejecución"}  
      
    # 3. Ejecución  
    execution_results = execute_autonomous_plan(execution_plan, username)  
      
    return execution_results
    
try:
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
except Exception:
    pass    
    
if __name__ == "__main__":        
    print("🟢 Ron 24/7 iniciado.")    
    if current_username:    
        print(f"👤 Usuario autenticado: {current_username}")    
    else:    
        print("👤 Modo sin autenticación")    
            
    # Iniciar control externo si está habilitado    
    if external_control:    
        handle_external_control()    
            
    # Configurar streaming        
    recognizer, microphone = setup_streaming_recognition()        
    audio_queue = queue.Queue()        
            
    # Iniciar captura de audio en background        
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)        
            
    activado = False
    try:  
        while True:  
            try:  
                if not listening_active:  
                    time.sleep(0.05)  
                    continue  
      
                # Esperamos trozos de audio  
                txt_ts = audio_queue.get(timeout=0.1)  
                if not isinstance(txt_ts, tuple) or len(txt_ts) != 2:  
                    txt, ts = str(txt_ts), time.time()  
                else:  
                    txt, ts = txt_ts  
      
                print(f"🗣 Detectado: {txt}")  
      
                # 1) Si no está activado, buscar wake-word  
                if not activado:  
                    if detect_ron_activation(txt):  
                        activado = True  
                        activation_time = ts  
                        conversation_buffer.clear()  
                        last_speech_time = ts  
                        print("✅ Ron activado")  
                        safe_activation_response()  
                        continue  
                    else:  
                        continue  
      
                # 2) Ya activado: acumular texto  
                conversation_buffer.append(txt)  
                last_speech_time = ts  
      
                # 3) Verificar timeouts  
                now = time.time()  
                time_since_last = now - last_speech_time  
                time_since_activation = now - activation_time  
      
                # ¿Se acabó la frase?  
                if time_since_last >= SILENCE_TIMEOUT_SEC or time_since_activation >= MAX_BUFFER_TIME_SEC:  
                    utterance = " ".join(conversation_buffer).strip()  
                    conversation_buffer.clear()  
      
                    if utterance:  
                        # Primero comandos locales  
                        if handle_local_commands(utterance):  
                            activado = False  # Volver a escucha pasiva  
                            print("🔁 Vuelvo a escucha pasiva (comando local).")  
                            continue  
      
                        # Enviar a Ron con análisis dinámico  
                        result = talk_to_ron(utterance)  
                          
                        # CORRECCIÓN: Usar la nueva lógica de activación dinámica  
                        if result.get("stay_active", False):  
                            print("🔄 Conversación continúa...")  
                            # Mantener activado = True, resetear buffers para continuar conversación  
                            activation_time = time.time()  
                            last_speech_time = time.time()  
                            # NO cambiar activado = False aquí  
                        else:  
                            activado = False  # Volver a escucha pasiva (esperando "Ron")  
                            print("💤 Volviendo a escucha pasiva (esperando 'Ron')")  
                          
                        if result.get("shutdown", False):  
                            print("🔴 Ron desconectado")  
                            break  
                    else:  
                        activado = False  
      
            except queue.Empty:  
                # Verificar grabación manual  
                if not manual_recording and manual_recording_buffer:  
                    manual_text = " ".join(manual_recording_buffer).strip()  
                    manual_recording_buffer.clear()  
      
                    if manual_text:  
                        print(f"🎤 Procesando grabación manual: {manual_text}")  
                        if not handle_local_commands(manual_text):  
                            result = talk_to_ron(manual_text)  
                            # Aplicar la misma lógica para grabación manual  
                            if result.get("stay_active", False):  
                                print("🔄 Conversación continúa...")  
                                activado = True  # Activar conversación desde grabación manual  
                                activation_time = time.time()  
                                last_speech_time = time.time()  
                            if result.get("shutdown", False):  
                                print("🔴 Ron desconectado")  
                                break  
      
                # Verificar timeout en conversación activa  
                if activado and (time.time() - last_speech_time) >= SILENCE_TIMEOUT_SEC and conversation_buffer:  
                    utterance = " ".join(conversation_buffer).strip()  
                    conversation_buffer.clear()  
                    if utterance:  
                        if handle_local_commands(utterance):  
                            activado = False  # Volver a escucha pasiva  
                        else:  
                            result = talk_to_ron(utterance)  
                            if result.get("stay_active", False):  
                                print("🔄 Conversación continúa...")  
                                activation_time = time.time()  
                                last_speech_time = time.time()  
                            else:  
                                activado = False  # Volver a escucha pasiva  
                            if result.get("shutdown", False):  
                                print("🔴 Ron desconectado")  
                                break  
                continue  
      
    except KeyboardInterrupt:  
        print("🔴 Cerrando Ron...")  
      
    finally:  
        control_enabled = False  
        try:  
            stop_listening(wait_for_stop=False)  
        except Exception:  
            pass  
        print("🔴 Ron 24/7 detenido.", flush=True)