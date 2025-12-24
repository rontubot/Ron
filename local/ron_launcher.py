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
import wave
import tempfile
import difflib

# 🔹 Add project root to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir) # ron root
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Core imports
from core.task_manager import TaskManager
from core.commands import (
    run_command,
    duck_other_applications,
    restore_application_volumes
)
from core.memory import add_to_memory, get_display_name, set_display_name
from core.tts import speak as tts_speak

# =========================================================================================
# UTILITIES
# =========================================================================================
def get_internet_time():
    """Obtiene la hora real desde internet para evitar alucinaciones."""
    try:
        # worldtimeapi es rápido y no requiere API KEY
        r = requests.get("https://worldtimeapi.org/api/ip", timeout=2)
        if r.status_code == 200:
            data = r.json()
            # ISO format 2024-12-24T16:20:01...
            dt = data["datetime"].split(".")[0]
            return dt
    except:
        pass
    # Fallback a hora de sistema
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# =========================================================================================
# CONFIGURATION & LOGGING
# =========================================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Argument parsing
parser = argparse.ArgumentParser(description='Ron 24/7 Voice Assistant')
parser.add_argument('--username', type=str, help='Username del usuario autenticado')
parser.add_argument('--control-port', type=int, default=9999, help='Puerto para control externo')
args = parser.parse_args()

current_username = args.username
control_enabled = True

# Constants
SILENCE_TIMEOUT_SEC = 1.2
ALLOWED_WAKE_WORDS = {"ron", "rom", "rron", "ronn", "ram"}

# 🔹 DEACTIVATE: Palabras que apagan la escucha activa
DEACTIVATE_KEYWORDS = {
    "descansa", "reposo", "dormir", "adios", "adiós", "hasta luego", 
    "terminamos", "ya está", "ya esta", "nada más", "nada mas", "silencio"
}

# 🔹 STRICT BARGE-IN: Palabras que permiten interrumpir a Ron
STOP_KEYWORDS = {
    # Stop Commands (SÓLO estas comandos detendrán a Ron)
    "silencio", "cállate", "callate", "stop", "detente", "basta", 
    "para", "parar", "espera", "momento"
}

activation_phrases = ["Te escucho.", "Sí, estoy aquí.", "Dime.", "Aquí estoy."]

# =========================================================================================
# GLOBAL STATE
# =========================================================================================
interruption_event = threading.Event()
tts_queue = queue.Queue()
audio_queue = queue.Queue()

# State flags
speaking = False
listening_active = True
activado = False

# MANUAL RECORDING STATE
manual_recording = False
manual_audio_buffer = []  # List of small audio chunks
manual_recording_lock = threading.Lock()

# =========================================================================================
# ECHO CANCELLATION BUFFER
# =========================================================================================
class SpeechBuffer:
    def __init__(self, max_seconds=15.0):
        self.buffer = []
        self.max_seconds = max_seconds
        self.lock = threading.Lock()

    def add(self, text):
        with self.lock:
            # Normalize text to remove accents and punctuation
            norm = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
            norm = re.sub(r'[^a-zA-Z0-9\s]', '', norm).lower().strip()
            self.buffer.append((norm, time.time()))
            self._cleanup()

    def is_echo(self, recognized_text):
        norm_rec = unicodedata.normalize('NFKD', recognized_text).encode('ASCII', 'ignore').decode('utf-8')
        norm_rec = re.sub(r'[^a-zA-Z0-9\s]', '', norm_rec).lower().strip()
        
        if not norm_rec: return False

        with self.lock:
            self._cleanup()
            for (history_text, _) in self.buffer:
                # 1. Exact or Substring Match (Strong Echo)
                if norm_rec in history_text or history_text in norm_rec:
                    # Only if length is significant to avoid "si" matching "simbolo"
                    if len(norm_rec) > 4: 
                        return True
                
                # 2. Fuzzy Match
                ratio = difflib.SequenceMatcher(None, norm_rec, history_text).ratio()
                if ratio > 0.6: # 60% similarity is enough to be suspicious
                    return True
        return False

    def _cleanup(self):
        now = time.time()
        self.buffer = [x for x in self.buffer if (now - x[1]) < self.max_seconds]

speech_buffer = SpeechBuffer()

# =========================================================================================
# TTS ENGINE & WORKER
# =========================================================================================

# tts_worker uses core.tts now

class TTSWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)

    def run(self):
        global speaking
        while True:
            try:
                text = tts_queue.get()
                if not text: continue
                
                if interruption_event.is_set():
                    with tts_queue.mutex: tts_queue.queue.clear()
                    print("🚫 TTS Interrumpido (Saltando)")
                    continue

                speaking = True
                speech_buffer.add(text)
                
                # Saneamiento y Base64 para evitar errores de escape
                import base64
                b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')

                print(f"🤖 Ron hablando: {text[:60]}...")
                
                tts_script = f"""
import pyttsx3, sys, base64
try:
    text = base64.b64decode('{b64_text}').decode('utf-8')
    e = pyttsx3.init()
    e.setProperty('rate', 195)
    e.setProperty('volume', 1.0)
    voices = e.getProperty('voices')
    v_id = next((v.id for v in voices if any(x in v.name.lower() for x in ['mexico','helena','sabina','spanish'])), None)
    if v_id: e.setProperty('voice', v_id)
    e.say(text)
    e.runAndWait()
except Exception as ex:
    print(ex)
"""
                try:
                    subprocess.run(
                        [sys.executable, "-c", tts_script],
                        capture_output=True,
                        text=True,
                        timeout=40
                    )
                except subprocess.TimeoutExpired:
                    print("⚠️ TTS Subprocess Timeout.")
                except Exception as e:
                    print(f"❌ Error en TTS Subprocess: {e}")

                speaking = False
            except Exception as e:
                print(f"❌ TTS Worker: {e}")
                speaking = False

tts_worker = TTSWorker()
tts_worker.start()

def speak_async(text: str):
    if not text or interruption_event.is_set(): return
    tts_queue.put(text)

def stop_speaking():
    interruption_event.set()
    with tts_queue.mutex:
        tts_queue.queue.clear()

# =========================================================================================
# CONTROL SERVER (Audio Recording & Status)
# =========================================================================================
def handle_external_control():    
    def control_server():    
        global listening_active, speaking, control_enabled, manual_recording, manual_audio_buffer
        try:    
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)    
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)    
            server.bind(('127.0.0.1', args.control_port))    
            server.listen(5)
            # 🔹 FIX for UI: Must be exact English string "Control server listening"    
            print(f"Control server listening on port {args.control_port}", flush=True)    
  
            while control_enabled:    
                try:    
                    client, _ = server.accept()
                    client.settimeout(2.0)
                    data = client.recv(4096)    
                    if not data:
                        client.close(); continue    
  
                    cmd = data.decode('utf-8', errors='ignore').strip().upper()  
  
                    if cmd == 'STATUS':    
                        state = b'ACTIVE' if (listening_active or speaking or activado) else b'INACTIVE'
                        client.sendall(state)    
  
                    elif cmd == 'START':
                        client.sendall(b'OK')

                    elif cmd == 'STOP':
                        stop_speaking()
                        client.sendall(b'OK')

                    elif cmd.startswith('SPEAK:'):
                        text_to_speak = cmd[6:].strip()
                        if text_to_speak:
                            interruption_event.clear()  # 🔹 Force speech even if interrupted recently
                            speak_async(text_to_speak)
                        client.sendall(b'OK')
                    
                    # 🔹 MANUAL RECORDING COMMANDS
                    elif cmd == 'START_RECORDING':
                        print("🎙️ Iniciando grabación manual...")
                        with manual_recording_lock:
                            manual_recording = True
                            manual_audio_buffer = [] # Reset buffer
                        client.sendall(b'OK')
                        
                    elif cmd == 'STOP_RECORDING':
                        print("🎙️ Deteniendo grabación manual...")
                        filename = f"rec_{int(time.time())}.wav"
                        filepath = os.path.join(os.getcwd(), 'temp', filename)
                        os.makedirs(os.path.join(os.getcwd(), 'temp'), exist_ok=True)
                        
                        # Save WAV
                        with manual_recording_lock:
                            manual_recording = False
                            frames = list(manual_audio_buffer) # Copy
                        
                        try:
                            # Detect sample rate from first audio chunk if available
                            # Default to common 44100 if not detectable
                            sample_rate = 44100
                            
                            wf = wave.open(filepath, 'wb')
                            wf.setnchannels(1)
                            wf.setsampwidth(2) # 16 bit
                            wf.setframerate(sample_rate)
                            wf.writeframes(b''.join(frames))
                            wf.close()
                            client.sendall(f"RECORDED:{filepath}".encode('utf-8'))
                        except Exception as e:
                            print(f"❌ Error guardando WAV: {e}")
                            client.sendall(b'ERROR')

                    else:
                        client.sendall(b'UNKNOWN')
                    client.close()
                except: pass
        except Exception as e:    
            print(f"❌ Error fatal en control server: {e}")    
  
    threading.Thread(target=control_server, daemon=True).start()

# =========================================================================================
# VAD & LISTENER (Local Whisper Recognition)
# =========================================================================================

# Disable debug logs from Whisper and TTS
logging.getLogger('faster_whisper').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('filelock').setLevel(logging.WARNING)
logging.getLogger('comtypes').setLevel(logging.WARNING)
logging.getLogger('comtypes.client').setLevel(logging.WARNING)
logging.getLogger('comtypes._post_coinit').setLevel(logging.WARNING)
logging.getLogger('comtypes._comobject').setLevel(logging.WARNING)
logging.getLogger('comtypes._vtbl').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# 🔹 Progress Helper for Electron
def send_progress(p, s):
    try:
        print(json.dumps({"progress": p, "status": s}), flush=True)
    except: pass

# 🔹 Initialize STT Engine (Default to Google for speed)
# We can still keep whisper_model as None and load it only if needed
whisper_model = None
STT_ENGINE = os.getenv("STT_ENGINE", "google") # 'google' or 'whisper'

def load_whisper():
    global whisper_model
    if whisper_model: return
    print("🔄 Cargando modelo Whisper (modo offline)...")
    try:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)
        print("✅ Whisper listo (base cargado)")
    except Exception as e:
        print(f"❌ Error cargando Whisper: {e}")

if STT_ENGINE == "whisper":
    load_whisper()

    # 🔹 Aggressive TQDM Patching for HuggingFace Hub
    # Skip unnecessary patches if not using whisper
    try:
        import tqdm
        import tqdm.auto
        import tqdm.std

        class JsonTqdm(tqdm.std.tqdm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                # Send initial 0%
                send_progress(0, "Iniciando descarga (3GB)...")

            def update(self, n=1):
                super().update(n)
                try:
                    if self.total and self.total > 0:
                        pct = (self.n / self.total) * 100
                        # Throttle: output every ~1% or if finished
                        if self.n >= self.total or (self.n % (self.total // 100 + 1) == 0):
                            send_progress(pct, f"Descargando núcleo de voz: {int(pct)}%")
                except: pass

        # Patch EVERYWHERE
        tqdm.tqdm = JsonTqdm
        tqdm.auto.tqdm = JsonTqdm
        tqdm.std.tqdm = JsonTqdm
        # Some libs import tqdm directly, we try to catch them
        sys.modules['tqdm'].tqdm = JsonTqdm
        sys.modules['tqdm.auto'].tqdm = JsonTqdm
        
    except Exception as e:
        print(f"TQDM Patch Warning: {e}")
        send_progress(5, "Descarga iniciada...")

    # 🔹 Explicit Download (Blocks until done, but TQDM should report)
    from faster_whisper import download_model

    print("Bot: 🔄 Verificando/Descargando modelo small (equilibrado)...")
    try:
        # Explicitly download to default cache
        # This triggers the patched tqdm for 'huggingface_hub'
        model_path = download_model("small")
        send_progress(100, "Modelo cargado. Iniciando...")
        
        # Init from local path
        # cpu_threads=8 is still good to keep it snappy
        whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=8)

    except Exception as e:
        print(f"Error cargando modelo: {e}")
        send_progress(100, "Error en carga. Usando fallback...")
        # Fallback/Retry
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

    print("✅ Whisper listo (small cargado)")
else:
    print("🚀 Usando STT básico (Google) para máxima velocidad.")

def setup_streaming_recognition():
    r = sr.Recognizer()
    r.pause_threshold = 0.8  # ⚡ Reducido para mayor rapidez (era 1.0)
    r.non_speaking_duration = 0.5 # Snappier cut
    r.dynamic_energy_threshold = False
    r.energy_threshold = 400
    try:
        m = sr.Microphone()
        print(f"🎤 Micrófono listo. Umbral fijo: {r.energy_threshold}")
        return r, m
    except Exception as e:
        print(f"❌ Error de Micrófono: {e}")
        sys.exit(1)

def transcribe_audio(recognizer, audio_data):
    """
    Transcribe audio usando el motor configurado (Google por defecto para rapidez)
    """
    global whisper_model
    
    if STT_ENGINE == "google":
        try:
            # Google es muy rápido para frases cortas y tiene buena precisión en español
            return recognizer.recognize_google(audio_data, language="es-ES")
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"☁️ Google API Error: {e}")
            # Si falla Google (internet), intentar cargar Whisper como fallback si el usuario lo permite
            return ""
            
    elif STT_ENGINE == "whisper":
        if not whisper_model: load_whisper()
        if not whisper_model: return ""
        try:
            wav_data = audio_data.get_wav_data()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(wav_data)
                tmp_path = tmp_file.name
            
            segments, _ = whisper_model.transcribe(
                tmp_path, 
                language="es",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False
            )
            text = " ".join([segment.text for segment in segments]).strip()
            os.unlink(tmp_path)
            return text
        except Exception as e:
            print(f"⚠️ Whisper error: {e}")
            return ""
            
    return ""

def stream_audio_recognition(recognizer, microphone, q):
    def callback(recognizer, audio):
        global speaking, interruption_event, manual_recording, manual_audio_buffer

        # 🔹 1. HANDLE MANUAL RECORDING
        if manual_recording:
            with manual_recording_lock:
                manual_audio_buffer.append(audio.get_raw_data())
            return

        try:
            # 🔹 2. RECOGNIZE TEXT with chosen Engine
            text = transcribe_audio(recognizer, audio).lower().strip()
            
            if not text: return

            # 🔹 3. "STRICT" KEYWORD INTERRUPTION LOGIC
            if speaking:
                if interruption_event.is_set(): return 

                # Solo interrumpir si detecta un comando de parada específico
                matched = None
                for k in STOP_KEYWORDS:
                    if k in text:
                        matched = k; break
                
                if matched:
                    print(f"🛑 Interrupción VÁLIDA por comando '{matched}': '{text}'")
                    stop_speaking()
                    global activado
                    activado = True # Asegurar que sigue en modo escucha si lo callamos
                else:
                    # Si está hablando y no es una palabra de parada, ignoramos para evitar cortes por ruido
                    return

            print(f"👂 Escuchado: {text}")
            q.put((text, time.time()))

        except Exception as e:
            print(f"⚠️ Listener: {e}")

    return recognizer.listen_in_background(microphone, callback, phrase_time_limit=10) # ⚡ Permitir frases más largas si el usuario no pausa

# =========================================================================================
# STREAMING BACKEND
# =========================================================================================
def buffer_speech_sentences(text_stream):
    buffer = ""
    # Dividir por puntos, pero no esperar demasiado
    endings = re.compile(r'([.?!:;])') 
    for chunk in text_stream:
        if not chunk: continue
        buffer += chunk
        
        # Si el buffer es muy largo (+100 chars), forzar una división por espacios si no hay puntos
        if len(buffer) > 100 and not endings.search(buffer):
            parts = buffer.rsplit(' ', 1)
            if len(parts) > 1:
                yield parts[0].strip()
                buffer = parts[1]
                continue

        parts = endings.split(buffer)
        if len(parts) > 1:
            to_process = parts[:-1]
            new_buffer = parts[-1]
            i = 0
            while i < len(to_process) - 1:
               sentence = (to_process[i] + to_process[i+1]).strip()
               if sentence: yield sentence
               i += 2
            buffer = new_buffer
    if buffer.strip(): yield buffer.strip()

def process_interaction(user_text):
    global interruption_event
    interruption_event.clear()
    
    api_url = os.getenv("RON_API_URL", "https://ron-production.up.railway.app")
    auth_token = os.getenv("RON_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    # 🔹 Incluir contexto de fecha/hora para evitar alucinaciones
    now_str = get_internet_time()
    context_prefix = f"[Contexto actual: {now_str}] "
    
    payload = {
        "text": context_prefix + user_text, 
        "username": current_username or "default",
        "source": "desktop_launcher"
    }

    full_response = ""
    commands_found = []
    
    print(f"📡 Solicitando: {user_text[:30]}...")

    try:
        with requests.post(f"{api_url}/ron/stream", json=payload, headers=headers, stream=True, timeout=10) as r:
            def generate_chunks():
                nonlocal commands_found
                for line in r.iter_lines():
                    # 🔹 FIX: Don't break on interruption, keep reading to get commands at the end
                    if not line: continue
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        data = json.loads(line_str[6:])
                        if data['type'] == 'chunk': yield data['chunk']
                        elif data['type'] in ('result', 'done'):
                            cmds = data.get('commands', [])
                            if cmds: commands_found.extend(cmds)

            for sentence in buffer_speech_sentences(generate_chunks()):
                if interruption_event.is_set():
                    # 🔹 FIX: If interrupted, silence TTS but CONTINUE reading stream
                    # print("🛑 Stream silenciado (buscando comandos...)")
                    continue
                
                # ⚡ ASYNC COMMAND EXECUTION (Inside Loop)
                # If commands arrived with this chunk (or before), run them NOW.
                if commands_found:
                    pending_cmds = list(commands_found)
                    commands_found = [] # Clear processed
                    print(f"⚡ Ejecutando {len(pending_cmds)} comandos EN PARALELO...")
                    
                    def run_cmds_async(cmds):
                        nonlocal full_response
                        for cmd in cmds:
                            try: 
                                # 🔹 Inject Task Manager into Command Context
                                run_command(
                                    cmd.get('action'), 
                                    cmd.get('params', {}), 
                                    {
                                        'username': current_username,
                                        'task_manager': task_manager # Pass the global task_manager
                                    }
                                )
                            except: pass
                    
                    # Run synchronously to ensure output is captured in history
                    run_cmds_async(pending_cmds)

                speak_async(sentence)
                full_response += " " + sentence

            # 🔹 SAVE TO MEMORY (GitHub/JSON)
            if full_response.strip():
                try:
                    add_to_memory(current_username, user_text, full_response.strip())
                except Exception as ex:
                    print(f"⚠️ Error guardando memoria: {ex}")

    except Exception as e:
        print(f"❌ Backend: {e}")
        speak_async("Error de conexión.")
        return False

    if interruption_event.is_set(): return True

    if commands_found:
        print(f"⚡ Ejecutando {len(commands_found)} comandos...")
        for cmd in commands_found:
            try: run_command(cmd.get('action'), cmd.get('params', {}), {'username': current_username})
            except: pass

    # Heuristic to stay active
    response_lower = full_response.lower()
    if "?" in full_response or any(k in response_lower for k in ["dime", "cuéntame", "necesitas", "algo más"]):
        return True
    return False

# =========================================================================================
# MAIN
# =========================================================================================
def detect_ron_activation(text):
    if not text: return False
    # Regex strict word boundary. 
    # Matches 'ron', 'oye ron', 'hola ron' but NOT 'chicharron', 'electron', 'patron'
    pattern = r'\b(' + '|'.join(re.escape(w) for w in ALLOWED_WAKE_WORDS) + r')\b'
    return bool(re.search(pattern, text, re.IGNORECASE))

if __name__ == "__main__":
    print("🟢 Ron 24/7 v2.0 (Violent Anti-Echo & Recording) Listo.")
    handle_external_control()
    task_manager = TaskManager(lambda t: speak_async(t))
    
    recognizer, microphone = setup_streaming_recognition()
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
    
    print("👂 Escuchando...")
    
    try:
        last_interaction = time.time()
        while True:
            try:
                # 🔹 Heartbeat / Timeout: Si pasan 60s sin nada, desactivar
                if activado and (time.time() - last_interaction > 60):
                    print("💤 Timeout: Ron vuelve a reposo.")
                    activado = False

                try: text, ts = audio_queue.get(timeout=0.1)
                except queue.Empty: continue

                # Normalizar texto para busqueda de keywords
                norm_text = text.lower().strip()

                if not activado:
                    if detect_ron_activation(text):
                        print("✅ Palabra clave detectada!")
                        stop_speaking()
                        time.sleep(0.05)
                        interruption_event.clear()
                        speak_async(random.choice(activation_phrases))
                        activado = True
                        last_interaction = time.time()
                else:
                    # 1. ¿Es una palabra de despedida/reposo?
                    if any(k in norm_text for k in DEACTIVATE_KEYWORDS):
                        print(f"💤 Comando de reposo detectado: '{norm_text}'")
                        speak_async("Entendido, estaré en reposo. Avísame si me necesitas.")
                        activado = False
                        continue

                    # 2. Procesar interacción normal
                    last_interaction = time.time()
                    stay = process_interaction(text)
                    if not stay:
                        print("💤 Desactivando escucha activa.")
                        activado = False
            except KeyboardInterrupt: break
            except Exception as e: print(f"❌ Loop: {e}")
    finally:
        stop_listening(wait_for_stop=False)
