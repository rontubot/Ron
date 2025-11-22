import speech_recognition as sr          
import pyttsx3                
import json          
import subprocess          
import sys          
import os          
import logging          
import threading          
import queue          
import time        
import random           
import argparse    
import io    
import socket    
import unicodedata    
import re    
import requests    
    
# Imports de core modules    
from core.task_manager import TaskManager    
from core.commands import (      
    run_command,      
    duck_other_applications,      
    restore_application_volumes      
)    
from core.memory import add_to_memory, get_display_name, set_display_name     
# CRÍTICO: Agregar detect_farewell_patterns al import  
from core.assistant import generate_response_with_user_memory, generate_response_no_memory as core_generate_response, detect_farewell_patterns  
  
# Función de limpieza de texto para TTS  
def clean_text_for_tts(text: str) -> str:      
    """Elimina caracteres especiales, emoticonos y markdown para TTS"""      
    # 1. Eliminar saltos de línea explícitos  
    text = text.replace('\\n', ' ')    
    text = text.replace('\n', ' ')    
        
    # 2. Eliminar encabezados markdown  
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE)    
    text = re.sub(r'\s+#{1,6}\s+', ' ', text)  
        
    # 3. Eliminar markdown de formato    
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **negrita**      
    text = re.sub(r'__([^_]+)__', r'\1', text)      # __negrita__      
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *cursiva*      
    text = re.sub(r'_([^_]+)_', r'\1', text)        # _cursiva_      
    text = re.sub(r'`([^`]+)`', r'\1', text)        # `código`      
        
    # 4. Eliminar TODOS los emojis  
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑🧀-🫿]+', '', text)  
    text = re.sub(r'[✅❌🔍🔴🟢💤🔄🎤📨🤖😄⚙️🗂️🧠]+', '', text)  
        
    # 5. Normalizar espacios múltiples    
    text = re.sub(r'\s{2,}', ' ', text)    
        
    return text.strip()  
  
# Reducir logs DEBUG    
logging.getLogger('urllib3').setLevel(logging.WARNING)    
logging.getLogger('httpcore').setLevel(logging.WARNING)    
logging.getLogger('httpx').setLevel(logging.WARNING)    
logging.getLogger('openai').setLevel(logging.WARNING)  
logging.getLogger('comtypes').setLevel(logging.WARNING)  
  
# Configurar logging  
logging.basicConfig(level=logging.INFO)  
  
# Asegurar UTF-8  
if hasattr(sys.stdout, "reconfigure"):  
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  
else:  
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")  
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")  
  
# Guardar stdout/stderr originales  
_orig_stdout, _orig_stderr = sys.stdout, sys.stderr  
  
# Silenciar prints de arranque si se pide  
_silenced_stdout = None  
_silenced_stderr = None  
if os.getenv("RON_SUPPRESS_STARTUP", "1") == "1":  
    _silenced_stdout = sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")  
    _silenced_stderr = sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")  
  
# Configuración de argumentos de línea de comandos      
parser = argparse.ArgumentParser(description='Ron 24/7 Voice Assistant')      
parser.add_argument('--username', type=str, help='Username del usuario autenticado')      
parser.add_argument('--control-port', type=int, default=9999, help='Puerto para control externo')      
args = parser.parse_args()      
      
# Variables globales  
current_username = args.username      
control_enabled = True  
external_control = True  # Habilitar control externo por defecto  
  
# Ventana de interacción tras la wake-word  
SILENCE_TIMEOUT_SEC = 1.2  
MAX_BUFFER_TIME_SEC = 30.0  
  
# Estado para agrupar conversación  
conversation_buffer = []  
last_speech_time = 0.0  
activation_time = 0.0  
  
# Variables de estado  
activado = False  
speaking = False  
listening_active = True  
manual_recording = False  
manual_recording_buffer = []  
manual_recording_start_time = 0.0  
  
# Inicializar motor TTS  
engine = pyttsx3.init()  
engine.setProperty('rate', 185)  
  
# Frases de activación  
activation_phrases = [  
    "Dime",  
    "¿Qué necesitas?",  
    "Estoy aquí",  
    "Te escucho",  
    "¿En qué puedo ayudarte?"  
]  
  
print("✅ Motor TTS inicializado")


# ===== TaskManager Callback =====  
def tts_callback(text: str):    
    """Callback para que TaskManager envíe mensajes por TTS"""    
    global speaking, listening_active    
    speaking = True    
    listening_active = False    
    try:    
        cleaned_text = clean_text_for_tts(text)    
        engine.say(cleaned_text)    
        engine.runAndWait()    
    finally:    
        speaking = False    
        listening_active = True    
  
# Inicializar TaskManager global    
task_manager = TaskManager(tts_callback)    
print("✅ TaskManager inicializado")  
  
  
# ===== Control Externo via Socket =====  
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
                        socket_client.sendall(b'EMPTY')  
                        socket_client.close()  
                        continue    
  
                    # Mantener versión cruda (para EXEC/CHAT) y otra upper (para START/STOP)  
                    raw_cmd = (data.decode('utf-8', errors='ignore') or '').strip()  
                    cmd = raw_cmd.upper()  
  
                    # ---- Comandos simples ----  
                    if cmd == 'START':    
                        listening_active = True  
                        speaking = False    
                        socket_client.sendall(b'OK')    
                        print("📨 Comando recibido: START", flush=True)    
  
                    elif cmd == 'STOP':    
                        listening_active = False  
                        speaking = False    
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
  
                    # ---- Comandos con payload JSON ----  
                    elif raw_cmd.startswith('EXEC::'):    
                        try:    
                            payload = raw_cmd[len('EXEC::'):].strip()    
                            obj = json.loads(payload)    
                            cmds = obj.get('commands') or []    
                            results = []    
                                
                            for c in cmds:    
                                action = (c.get('action') or '').strip()    
                                params = c.get('params') or {}    
                                  
                                # Ejecutar comando usando run_command  
                                try:  
                                    r = run_command(action, params, {'username': current_username})  
                                    results.append({    
                                        "action": action,    
                                        "ok": r.get("ok", True),    
                                        "message": r.get("message") or r.get("result")    
                                    })  
                                except Exception as e:  
                                    results.append({  
                                        "action": action,  
                                        "ok": False,  
                                        "message": str(e)  
                                    })  
                                
                            socket_client.sendall(f'RESULT:{json.dumps(results, ensure_ascii=False)}'.encode('utf-8'))    
                                
                        except json.JSONDecodeError as e:    
                            socket_client.sendall(f'ERROR:JSON inválido: {e}'.encode('utf-8'))    
                        except Exception as e:    
                            socket_client.sendall(f'ERROR:{e}'.encode('utf-8'))  
  
                    elif raw_cmd.startswith('CHAT::'):  
                        try:  
                            text = raw_cmd[len('CHAT::'):].strip()  
                            user = (current_username or 'default')  
                              
                            # Usar backend para procesar  
                            reply = "Procesando..."  # Placeholder  
                            socket_client.sendall(reply.encode('utf-8', errors='ignore'))  
  
                        except Exception as e:  
                            socket_client.sendall(f'ERROR:{e}'.encode('utf-8'))  
  
                    else:    
                        socket_client.sendall(b'UNKNOWN')    
                        print(f"📨 Comando recibido: {raw_cmd}", flush=True)    
  
                except Exception as e:    
                    try:  
                        socket_client.sendall(f'ERROR:{e}'.encode('utf-8', errors='ignore'))    
                    except Exception:  
                        pass    
                    print(f"Error en control server: {e}", flush=True)    
                finally:    
                    try:  
                        socket_client.close()    
                    except Exception:  
                        pass    
        except Exception as e:    
            print(f"Error iniciando control server: {e}", flush=True)    
  
    threading.Thread(target=control_server, daemon=True).start()  
  
  
# ===== Reconocimiento de Voz en Streaming =====  
def setup_streaming_recognition():  
    """Configura el reconocimiento de voz en streaming"""  
    recognizer = sr.Recognizer()  
    recognizer.pause_threshold = 1.0  
    recognizer.energy_threshold = 250  
  
    try:  
        microphone = sr.Microphone()  
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
                        manual_recording_buffer.append(text.lower())    
                    else:    
                        audio_queue.put((text.lower(), time.time()))    
            except sr.UnknownValueError:    
                pass    
            except sr.RequestError:    
                pass    
    
    stop_listening = recognizer.listen_in_background(    
        microphone, callback, phrase_time_limit=6    
    )    
    return stop_listening  
  
  
# ===== Detección de Wake-Word =====  
ALLOWED_WAKE_WORDS = {"ron", "rom", "rron", "ronn", "ram"}  
  
def _normalize_text(s: str) -> str:  
    """Minúsculas y sin acentos/diacríticos para comparar tokens."""  
    if not s:  
        return ""  
    s = unicodedata.normalize('NFKD', s)  
    s = s.encode('ascii', 'ignore').decode('utf-8', 'ignore')  
    return s.lower()  
  
def detect_ron_activation(text: str) -> bool:  
    """  
    Activa SOLO si aparece la palabra aislada 'ron' (o variante en ALLOWED_WAKE_WORDS).  
    NO activa con subcadenas dentro de otras palabras.  
    """  
    if not text:  
        return False  
  
    t = _normalize_text(text)  
    tokens = re.findall(r'\b\w+\b', t)  
    return any(tok in ALLOWED_WAKE_WORDS for tok in tokens)  
  
  

def talk_to_ron(text):      
    """      
    Función principal que:      
    1. Envía el texto al backend de Railway vía streaming      
    2. Acumula la respuesta      
    3. Ejecuta comandos localmente      
    4. Habla la respuesta con TTS      
    """      
    global speaking, listening_active, activado      
          
    speaking = True      
    listening_active = False      
    response_text = ""      
          
    try:      
        # Verificar despedida ANTES de procesar      
        try:    
            from core.assistant import detect_farewell_patterns as core_detect    
            is_farewell = core_detect(text)    
        except ImportError:    
            farewell_keywords = [      
                "adiós", "adios", "chao", "chau", "hasta luego",      
                "nos vemos", "bye", "hasta pronto", "me voy"      
            ]      
            is_farewell = any(keyword in text.lower() for keyword in farewell_keywords)    
            
        if is_farewell:      
            response_text = "Hasta luego. Que tengas un buen día."      
            cleaned_response = clean_text_for_tts(response_text)      
            print(f"🤖 Ron: {cleaned_response}")      
              
            # TTS con manejo de errores  
            try:  
                engine.say(cleaned_response)      
                engine.runAndWait()      
                time.sleep(0.5)  
            except Exception as tts_error:  
                print(f"⚠️ Error en TTS: {tts_error}")  
                  
            if current_username:      
                add_to_memory(current_username, text, response_text)      
                  
            return {      
                "shutdown": False,      
                "stay_active": False,      
                "response": response_text      
            }      
              
        # Configurar API      
        api_url = os.getenv("RON_API_URL", "https://ron-production.up.railway.app")      
        auth_token = os.getenv("RON_AUTH_TOKEN", "")      
              
        headers = {      
            "Authorization": f"Bearer {auth_token}",      
            "Content-Type": "application/json"      
        }      
              
        payload = {      
            "text": text,      
            "username": current_username or "default"      
        }      
          
        print(f"📡 Enviando al backend: {text[:50]}...")  
              
        # Llamar al backend con streaming      
        commands_to_execute = []      
              
        with requests.post(      
            f"{api_url}/ron/stream",      
            headers=headers,      
            json=payload,      
            stream=True,      
            timeout=30      
        ) as r:      
            for line in r.iter_lines():      
                if not line:      
                    continue    
                        
                try:      
                    line_str = line.decode('utf-8', errors='ignore').strip()    
                        
                    if not line_str or line_str.startswith(':'):    
                        continue    
                            
                    if line_str.startswith('data: '):      
                        line_str = line_str[6:]      
                    else:    
                        continue    
                              
                    data = json.loads(line_str)      
                              
                    if data.get('type') == 'chunk':      
                        chunk = data.get('chunk', '')      
                        response_text += chunk      
                              
                    elif data.get('type') == 'done':      
                        full_text = data.get('full_text', '')      
                        if full_text and not response_text:      
                            response_text = full_text      
                                  
                        commands_to_execute = data.get('commands', [])      
                        break      
                              
                    elif data.get('type') == 'error':      
                        error_msg = data.get('error', 'Error desconocido')      
                        print(f"❌ Error del backend: {error_msg}")      
                        response_text = "Ocurrió un error procesando tu solicitud."      
                        break      
                          
                except json.JSONDecodeError as e:      
                    print(f"⚠️ Error parseando JSON: {e}, línea: {line_str[:100]}")    
                    continue      
          
        print(f"📥 Respuesta recibida del backend: {response_text[:100]}...")  
              
        # Si no hay respuesta, usar mensaje por defecto      
        if not response_text:      
            response_text = "No pude procesar tu solicitud."      
            print("⚠️ Backend no devolvió texto, usando mensaje por defecto")  
              
        # Ejecutar comandos localmente      
        if commands_to_execute:      
            print(f"🔧 Ejecutando {len(commands_to_execute)} comando(s)...")      
            for cmd in commands_to_execute:      
                action = cmd.get('action')      
                params = cmd.get('params', {})      
                if action:      
                    try:      
                        ctx = {'username': current_username or 'default'}      
                        run_command(action, params, ctx)      
                    except Exception as e:      
                        print(f"❌ Error ejecutando comando {action}: {e}")      
              
        # CRÍTICO: Limpiar y hablar la respuesta CON DEBUGGING  
        cleaned_response = clean_text_for_tts(response_text)      
        print(f"🤖 Ron: {cleaned_response}")      
        print(f"🔊 Intentando TTS con texto de {len(cleaned_response)} caracteres...")  
          
        # TTS con manejo de errores y reinicio si falla  
        try:  
            engine.say(cleaned_response)      
            engine.runAndWait()      
            print("✅ TTS completado exitosamente")  
            time.sleep(0.5)  
        except Exception as tts_error:  
            print(f"❌ Error en TTS: {tts_error}")  
            # Intentar reinicializar el motor TTS  
            try:  
                global engine  
                engine = pyttsx3.init()  
                engine.setProperty('rate', 185)  
                engine.say(cleaned_response)  
                engine.runAndWait()  
                print("✅ TTS completado después de reinicializar motor")  
            except Exception as retry_error:  
                print(f"❌ Error en TTS después de reintentar: {retry_error}")  
              
        # Guardar en memoria      
        if current_username:      
            add_to_memory(current_username, text, response_text)      
              
        # Determinar si debe mantenerse activo      
        stay_active = should_stay_active(text, response_text)      
              
        return {      
            "shutdown": False,      
            "stay_active": stay_active,      
            "response": response_text      
        }      
          
    except requests.exceptions.Timeout:      
        print("❌ Timeout al conectar con el backend")      
        error_response = "El servidor tardó demasiado en responder. Intenta de nuevo."      
        cleaned_error = clean_text_for_tts(error_response)      
        print(f"🤖 Ron: {cleaned_error}")      
          
        try:  
            engine.say(cleaned_error)      
            engine.runAndWait()  
        except Exception as tts_error:  
            print(f"⚠️ Error en TTS de timeout: {tts_error}")  
              
        return {"shutdown": False, "stay_active": True, "response": error_response}      
          
    except requests.exceptions.ConnectionError:      
        print("❌ No se pudo conectar con el backend")      
        error_response = "No puedo conectarme al servidor. Verifica tu conexión."      
        cleaned_error = clean_text_for_tts(error_response)      
        print(f"🤖 Ron: {cleaned_error}")      
          
        try:  
            engine.say(cleaned_error)      
            engine.runAndWait()  
        except Exception as tts_error:  
            print(f"⚠️ Error en TTS de conexión: {tts_error}")  
              
        return {"shutdown": False, "stay_active": True, "response": error_response}      
          
    except Exception as e:      
        print(f"❌ Error en talk_to_ron: {e}")      
        import traceback    
        traceback.print_exc()    
        error_response = "Ocurrió un error procesando tu solicitud. ¿Puedes intentar de nuevo?"      
        cleaned_error = clean_text_for_tts(error_response)      
        print(f"🤖 Ron: {cleaned_error}")      
          
        try:  
            engine.say(cleaned_error)      
            engine.runAndWait()  
        except Exception as tts_error:  
            print(f"⚠️ Error en TTS de excepción: {tts_error}")  
              
        return {"shutdown": False, "stay_active": True, "response": error_response}      
          
    finally:      
        speaking = False      
        listening_active = True
  
  
def safe_activation_response():  
    """Respuesta de activación con TTS"""  
    global speaking, listening_active  
      
    speaking = True  
    listening_active = False  
      
    try:  
        # Ducking de audio para mejor claridad  
        duck_other_applications()  
          
        # Seleccionar frase aleatoria  
        phrase = random.choice(activation_phrases)  
        print(f"🤖 Ron: {phrase}")  
        engine.say(phrase)  
        engine.runAndWait()  
        time.sleep(0.5)  
    finally:  
        speaking = False  
        listening_active = True


def should_stay_active(user_text: str, response: str) -> bool:  
    """  
    Determina si Ron debe mantenerse activo después de una respuesta.  
    Basado en preguntas del asistente o contexto conversacional.  
    """  
    response_lower = response.lower()  
      
    # Preguntas directas que requieren respuesta  
    question_indicators = [  
        "¿", "?",  
        "dime", "cuéntame", "explícame",  
        "qué quieres", "qué necesitas", "qué deseas",  
        "algo más", "otra cosa"  
    ]  
      
    if any(indicator in response_lower for indicator in question_indicators):  
        return True  
      
    # Comandos que naturalmente continúan la conversación  
    continuation_phrases = [  
        "ahora", "luego", "después",  
        "también", "además",  
        "espera", "un momento"  
    ]  
      
    if any(phrase in response_lower for phrase in continuation_phrases):  
        return True  
      
    return False  
  
  
def detect_farewell_patterns(text: str) -> bool:  
    """  
    Detecta patrones de despedida en el texto del usuario.  
    Reutiliza la función de core.assistant si está disponible.  
    """  
    try:  
        from core.assistant import detect_farewell_patterns as core_detect  
        return core_detect(text)  
    except ImportError:  
        # Fallback local si no está disponible  
        farewell_keywords = [  
            "adiós", "adios", "chao", "chau", "hasta luego",  
            "nos vemos", "bye", "hasta pronto", "me voy"  
        ]  
        text_lower = text.lower()  
        return any(keyword in text_lower for keyword in farewell_keywords)  
  
  
# ===== MAIN LOOP =====  
if __name__ == "__main__":  
    # Restaurar stdout/stderr originales para logs visibles  
    try:  
        sys.stdout = _orig_stdout  
        sys.stderr = _orig_stderr  
    except Exception:  
        pass  
      
    print("🟢 Ron 24/7 iniciado.")  
    if current_username:  
        print(f"👤 Usuario autenticado: {current_username}")  
    else:  
        print("👤 Modo sin autenticación")  
      
    # Iniciar control externo si está habilitado  
    if external_control:  
        handle_external_control()  
      
    # Configurar streaming de reconocimiento de voz  
    recognizer, microphone = setup_streaming_recognition()  
    audio_queue = queue.Queue()  
      
    # Iniciar captura de audio en background  
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)  
      
    # Estado inicial  
    activado = False  
    restore_application_volumes()  
      
    print("Estado inicial: Inactivo")  
      
    try:  
        while True:  
            try:  
                # Si no está escuchando, esperar  
                if not listening_active:  
                    time.sleep(0.05)  
                    continue  
                  
                # Esperar audio del queue  
                try:  
                    txt_ts = audio_queue.get(timeout=0.1)  
                except queue.Empty:  
                    # Verificar grabación manual  
                    if not manual_recording and manual_recording_buffer:  
                        manual_text = " ".join(manual_recording_buffer).strip()  
                        manual_recording_buffer.clear()  
                          
                        if manual_text:  
                            print(f"🎤 Procesando grabación manual: {manual_text}")  
                            result = talk_to_ron(manual_text)  
                              
                            if result.get("shutdown", False):  
                                print("🔴 Ron desactivado por despedida")  
                                activado = False  
                                restore_application_volumes()  
                                break  
                              
                            if result.get("stay_active", False):  
                                print("🔄 Conversación continúa...")  
                                activado = True  
                                activation_time = time.time()  
                                last_speech_time = time.time()  
                      
                    # Verificar timeout en conversación activa  
                    if activado and conversation_buffer:  
                        time_since_last = time.time() - last_speech_time  
                        if time_since_last >= SILENCE_TIMEOUT_SEC:  
                            utterance = " ".join(conversation_buffer).strip()  
                            conversation_buffer.clear()  
                              
                            if utterance:  
                                result = talk_to_ron(utterance)  
                                  
                                if result.get("shutdown", False):  
                                    print("🔴 Ron desactivado por despedida")  
                                    activado = False  
                                    restore_application_volumes()  
                                    break  
                                  
                                if result.get("stay_active", False):  
                                    print("🔄 Conversación continúa...")  
                                    activation_time = time.time()  
                                    last_speech_time = time.time()  
                                else:  
                                    print("💤 Conversación normal completada - volviendo a escucha pasiva")  
                                    activado = False  
                                    restore_application_volumes()  
                      
                    continue  
                  
                # Parsear audio recibido  
                if not isinstance(txt_ts, tuple) or len(txt_ts) != 2:  
                    txt, ts = str(txt_ts), time.time()  
                else:  
                    txt, ts = txt_ts  
                  
                print(f"🗣 Detectado: {txt}")  
                  
                # Si no está activado, buscar wake-word  
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
                  
                # Ya activado: acumular texto  
                conversation_buffer.append(txt)  
                last_speech_time = ts  
                  
                # Verificar timeouts  
                now = time.time()  
                time_since_last = now - last_speech_time  
                time_since_activation = now - activation_time  
                  
                # ¿Se acabó la frase?  
                if time_since_last >= SILENCE_TIMEOUT_SEC or time_since_activation >= MAX_BUFFER_TIME_SEC:  
                    utterance = " ".join(conversation_buffer).strip()  
                    conversation_buffer.clear()  
                      
                    if utterance:  
                        # Procesar con Ron  
                        result = talk_to_ron(utterance)  
                          
                        # Verificar shutdown  
                        if result.get("shutdown", False):  
                            print("🔴 Ron desactivado por despedida o comando")  
                            activado = False  
                            restore_application_volumes()  
                            break  
                          
                        # Verificar si debe continuar  
                        if result.get("stay_active", False):  
                            print("🔄 Conversación continúa...")  
                            activation_time = time.time()  
                            last_speech_time = time.time()  
                        else:  
                            print("💤 Conversación normal completada - volviendo a escucha pasiva")  
                            activado = False  
                            restore_application_volumes()  
                    else:  
                        activado = False  
                        restore_application_volumes()  
              
            except Exception as e:  
                print(f"❌ Error en loop principal: {e}")  
                time.sleep(0.1)  
      
    except KeyboardInterrupt:  
        print("🔴 Cerrando Ron...")  
      
    finally:  
        # Cleanup del TaskManager  
        if 'task_manager' in globals():  
            print("🔄 Deteniendo TaskManager...")  
            task_manager.shutdown()  
          
        control_enabled = False  
          
        # Restaurar volumen SIEMPRE al cerrar  
        try:  
            restore_application_volumes()  
            print("🔊 Volumen restaurado al cerrar Ron")  
        except Exception as e:  
            print(f"⚠️ No se pudo restaurar volumen: {e}")  
          
        try:  
            stop_listening(wait_for_stop=False)  
        except Exception:  
            pass  
          
        print("🔴 Ron 24/7 detenido.", flush=True)




