
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


# 🔹 Add current script dir to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Core imports
from core.task_manager import TaskManager
from core.commands import (
    run_command,
    duck_other_applications,
    restore_application_volumes
)
from core.memory import add_to_memory, get_display_name, set_display_name
from core.assistant import detect_farewell_patterns
import difflib  # For fuzzy matching (Echo Cancellation)

# =========================================================================================
# CONFIGURATION & LOGGING
# =========================================================================================

# Logging setup
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('comtypes').setLevel(logging.WARNING)
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
MAX_BUFFER_TIME_SEC = 30.0
ALLOWED_WAKE_WORDS = {"ron", "rom", "rron", "ronn", "ram"}

activation_phrases = [
    "Te escucho.",
    "Sí, estoy aquí.",
    "Dime.",
    "Aquí estoy."
    "Dime.",
    "Aquí estoy."
]

# 🔹 STRICT BARGE-IN: Palabras que permiten interrumpir a Ron
STOP_KEYWORDS = {
    # Wake Words
    "ron", "rom", "rron", "oye ron", "hola ron",
    # Stop Commands
    "silencio", "cállate", "callate", "stop", "para", "detente", "basta", 
    "espera", "escucha", "oye", "momento", "pausa"
}

# =========================================================================================
# GLOBAL STATE
# =========================================================================================
# Synchronization primitives
interruption_event = threading.Event()
tts_queue = queue.Queue()
audio_queue = queue.Queue()

# State flags
speaking = False
listening_active = True
activado = False
manual_recording = False
manual_buffer = []

# Buffers
# =========================================================================================
# ECHO CANCELLATION (Speech Buffer)
# =========================================================================================

class SpeechBuffer:
    """
    Tracks recently spoken text to detect if the microphone is hearing Ron's own voice (Echo).
    Entries expire after a few seconds.
    """
    def __init__(self, max_seconds=10.0):
        self.buffer = []  # List of (text, timestamp)
        self.max_seconds = max_seconds
        self.lock = threading.Lock()

    def _normalize(self, text):
        """Removes accents and non-alphanumeric chars for comparison"""
        if not text: return ""
        # Remove accents
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
        # Keep only alphanumeric and spaces
        text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        return text.lower().strip()

    def add(self, text):
        with self.lock:
            # Clean text for comparison
            clean = self._normalize(text)
            self.buffer.append((clean, time.time()))
            self._cleanup()

    def is_echo(self, recognized_text, threshold=0.6): # 🔹 TUNED: Lowered threshold from 0.8
        """
        Returns True if recognized_text is likely an echo of something Ron just said.
        """
        rec_clean = self._normalize(recognized_text)
        if not rec_clean:
            return False

        with self.lock:
            self._cleanup()
            if not self.buffer:
                return False
            
            # Check against all recent phrases
            for (spoken_text, _) in self.buffer:
                # 1. Direct containment (if recognized is a substring of spoken or vice versa)
                # Helps when mic picks up partial sentences.
                if len(rec_clean) > 8 and rec_clean in spoken_text: # 🔹 TUNED: Lowered len check
                    return True
                
                # 2. Fuzzy Matching
                ratio = difflib.SequenceMatcher(None, rec_clean, spoken_text).ratio()
                if ratio >= threshold:
                    return True
            
        return False

    def _cleanup(self):
        now = time.time()
        # Keep only items within the window
        self.buffer = [item for item in self.buffer if (now - item[1]) < self.max_seconds]

speech_buffer = SpeechBuffer()

# =========================================================================================
# TTS ENGINE & WORKER
# =========================================================================================

def clean_text_for_tts(text: str) -> str:
    """Cleans text for better TTS pronunciation"""
    text = text.replace('\\n', ' ').replace('\n', ' ')
    text = re.sub(r'[*_`#]', '', text) # Remove markdown chars
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑🧀-🫿]+', '', text) # Remove emojis
    return text.strip()

class TTSWorker(threading.Thread):
    """
    Dedicated thread for TTS. Consumes sentences from tts_queue.
    Checks interruption_event before speaking each sentence.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self.engine = None
        self._lock = threading.Lock()

    def run(self):
        global speaking
        while True:
            try:
                # Get sentence (blocking)
                text = tts_queue.get()
                
                # Check interruption BEFORE speaking
                if interruption_event.is_set():
                    # Clear queue if interrupted
                    with tts_queue.mutex:
                        tts_queue.queue.clear()
                    print("🚫 Cola TTS limpiada por interrupción")
                    continue

                if not text:
                    continue

                speaking = True
                
                # 🔹 Record what we are about to say to the Echo Buffer
                speech_buffer.add(text)
                
                self._speak(text)
                speaking = False
                
            except Exception as e:
                print(f"❌ Error en TTS Worker: {e}")
                speaking = False

    def _speak(self, text):
        """Initializes a new engine instance for each phrase to avoid state corruption (pyttsx3 limitation)"""
        try:
            # Last second check
            if interruption_event.is_set():
                return

            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 190) # Slightly faster rate
            engine.setProperty('volume', 1.0)
            
            cleaned = clean_text_for_tts(text)
            if not cleaned: return

            engine.say(cleaned)
            engine.runAndWait()
            
            if engine._inLoop:
                engine.endLoop()
        except Exception as e:
            pass

# Start TTS Worker
tts_worker = TTSWorker()
tts_worker.start()

def speak_async(text: str):
    """Enqueues text for TTS"""
    if not text: return
    # If interrupted, don't queue
    if interruption_event.is_set():
        return
    tts_queue.put(text)

def stop_speaking():
    """Signals interruption"""
    interruption_event.set()
    # Clear queue immediately
    with tts_queue.mutex:
        tts_queue.queue.clear()
    
# =========================================================================================
# CONTROL SERVER (Restored & Fixed)
# =========================================================================================

def handle_external_control():    
    """Maneja comandos de control desde Electron via Socket"""    
    def control_server():    
        global listening_active, speaking, control_enabled   
        try:    
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)    
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)    
            server.bind(('127.0.0.1', args.control_port))    
            server.listen(5)    
            print(f"🎛️ Servidor de control escuchando en puerto {args.control_port}", flush=True)    
  
            while control_enabled:    
                try:    
                    client, _ = server.accept()
                    client.settimeout(2.0)
                except Exception:    
                    continue    
  
                try:    
                    data = client.recv(4096)    
                    if not data:    
                        client.close()  
                        continue    
  
                    cmd = data.decode('utf-8', errors='ignore').strip().upper()  
  
                    if cmd == 'STATUS':    
                        # Si está escuchando O hablando, está activo
                        state = b'ACTIVE' if (listening_active or speaking or activado) else b'INACTIVE'
                        client.sendall(state)    
  
                    elif cmd == 'START':
                        # listening_active = True
                        client.sendall(b'OK')

                    elif cmd == 'STOP':
                        # listening_active = False
                        stop_speaking()
                        client.sendall(b'OK')
                        
                    elif cmd.startswith('EXEC::'):
                        client.sendall(b'OK')

                    else:
                        client.sendall(b'UNKNOWN')
                    
                    client.close()

                except Exception as e:    
                    print(f"❌ Error en socket: {e}")
                    try: client.close()
                    except: pass

        except Exception as e:    
            print(f"❌ Error fatal en control server: {e}")    
  
    threading.Thread(target=control_server, daemon=True).start()

# =========================================================================================
# VAD & LISTENER 
# =========================================================================================

def setup_streaming_recognition():
    r = sr.Recognizer()
    r.pause_threshold = 0.8
    r.dynamic_energy_threshold = False  # DESACTIVADO para evitar adaptación al ruido
    r.energy_threshold = 400            # Umbral fijo más alto para filtrar ruido
    try:
        m = sr.Microphone()
        with m as source:
            r.adjust_for_ambient_noise(source, duration=0.5)
        return r, m
    except Exception as e:
        print(f"❌ Error de Micrófono: {e}")
        sys.exit(1)

def stream_audio_recognition(recognizer, microphone, q):
    """
    Background listener.
    Updated Logic: Only interrupt IF valid text is recognized.
    """
    def callback(recognizer, audio):
        global speaking, interruption_event

        try:
            # Recognize text FIRST (Filter noise)
            try:
                text = recognizer.recognize_google(audio, language="es").lower().strip()
            except sr.UnknownValueError:
                return
            except sr.RequestError:
                return

            if not text:
                return

            # Check for BARGE-IN (Interruption)
            # Only if we are speaking AND the text is significant
            if speaking:
                if interruption_event.is_set():
                    return 
                
                # 🔹 STRICT BARGE-IN CHECK
                # Solo interrumpir si menciona "Ron" o una palabra de parada
                # Esto filtra letras de canciones o ruido de fondo
                text_lower = text.lower()
                is_valid_interruption = False
                
                # 1. Check Stop Keywords / Wake Words
                if any(k in text_lower for k in STOP_KEYWORDS):
                    is_valid_interruption = True
                
                # 2. Check Wake Words (Global list)
                if not is_valid_interruption:
                     if any(w in text_lower for w in ALLOWED_WAKE_WORDS):
                         is_valid_interruption = True

                if not is_valid_interruption:
                    print(f"🎵 Ruido/Música ignorado durante habla: '{text}'")
                    return

                # 🔹 ECHO CHECK: Is this just me talking? (Secondary check)
                if speech_buffer.is_echo(text):
                    print(f"🔇 Echo ignorado: '{text}'")
                    return

                print(f"🛑 ¡INTERRUPCIÓN VALIDADA! ('{text}')")
                stop_speaking()
                
                # 🔹 FIX: Force active state so the main loop processes this text
                # even if we were technically "inactive" (finishing a turn)
                global activado
                activado = True

            # Pass text to main loop
            print(f"👂 Escuchado: {text}")
            q.put((text, time.time()))

        except Exception as e:
            print(f"⚠️ Error en Listener: {e}")

    return recognizer.listen_in_background(microphone, callback, phrase_time_limit=5)

# =========================================================================================
# STREAMING BACKEND CLIENT
# =========================================================================================

def buffer_speech_sentences(text_stream):
    """Yields full sentences from a stream of characters/chunks."""
    buffer = ""
    # Delimiters for natural pauses
    endings = re.compile(r'([.?!,])') 
    
    for chunk in text_stream:
        buffer += chunk
        parts = endings.split(buffer)
        if len(parts) > 1:
            to_process = parts[:-1]
            new_buffer = parts[-1]
            i = 0
            while i < len(to_process) - 1:
               sentence = to_process[i] + to_process[i+1]
               if sentence.strip():
                   yield sentence.strip()
               i += 2
            buffer = new_buffer
    if buffer.strip():
        yield buffer.strip()

def process_interaction(user_text):
    """
    Main logic: Sends text to backend, streams response, feeds TTS, EXECUTES COMMANDS.
    """
    global interruption_event, speaking
    
    interruption_event.clear() # Reset flag for new turn
    
    api_url = os.getenv("RON_API_URL", "https://ron-production.up.railway.app")
    auth_token = os.getenv("RON_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    payload = {"text": user_text, "username": current_username or "default"}

    full_response = ""
    commands_found = []
    
    print(f"📡 Solicitando: {user_text[:30]}...")

    try:
        # Use a session for persistent connection
        with requests.post(f"{api_url}/ron/stream", json=payload, headers=headers, stream=True, timeout=10) as r:
            
            # Iterator for text chunks from server
            def generate_chunks():
                nonlocal commands_found
                for line in r.iter_lines():
                    if interruption_event.is_set(): break
                    if not line: continue
                    
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        data = json.loads(line_str[6:])
                        
                        if data['type'] == 'chunk':
                            yield data['chunk']
                        
                        elif data['type'] == 'result':
                            # 🔹 CAPTURE COMMANDS FROM STREAM
                            # Server sends { "type": "result", "commands": [...] }
                            cmds = data.get('commands', [])
                            if cmds:
                                commands_found.extend(cmds)

            # Feed chunks to sentence splitter -> TTS Queue
            for sentence in buffer_speech_sentences(generate_chunks()):
                if interruption_event.is_set():
                    print("🛑 Stream de respuesta cancelado.")
                    break
                    
                speak_async(sentence)
                full_response += " " + sentence

    except Exception as e:
        print(f"❌ Error de Backend: {e}")
        speak_async("Hubo un error de conexión.")
        return False 

    # Handle completion
    if interruption_event.is_set():
        return True 

    # 🔹 EXECUTE COMMANDS
    if commands_found:
        print(f"⚡ Ejecutando {len(commands_found)} comando(s)...")
        for cmd in commands_found:
            action = cmd.get('action') 
            params = cmd.get('params', {})
            try:
                run_command(action, params, {'username': current_username})
                # Feedback?
            except Exception as e:
                print(f"❌ Error ejecutando {action}: {e}")

    return should_stay_active(user_text, full_response)

def should_stay_active(user_text, response_text):
    """Logic to keep conversation open and NOTIFY USER"""
    response_lower = response_text.lower()
    
    # 1. Asking questions?
    if "?" in response_text or any(k in response_lower for k in ["dime", "cuéntame", "qué necesitas", "algo más"]):
        # print("🔄 Conversación continúa (esperando respuesta)...") 
        return True
    
    # 2. explicit continuation
    if any(k in response_lower for k in ["luego", "ahora", "espera"]):
        # print("🔄 Conversación continúa...")
        return True

    # print("💤 Conversación completada.")
    return False

# =========================================================================================
# MAIN LOOP
# =========================================================================================

def detect_ron_activation(text):
    tokens = text.lower().split()
    return any(w in ALLOWED_WAKE_WORDS for w in tokens)

if __name__ == "__main__":
    print("🟢 Ron 24/7 v2.0 (Streaming & Barge-In) Listo.")
    
    # 🔹 FIX: START CONTROL SERVER
    handle_external_control()
    
    task_manager = TaskManager(lambda t: speak_async(t))
    
    recognizer, microphone = setup_streaming_recognition()
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
    
    print("👂 Escuchando...")
    
    try:
        while True:
            try:
                try:
                    text, ts = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if not activado:
                    if detect_ron_activation(text):
                        print("✅ Palabra clave detectada!")
                        
                        # 🔹 FIX: Clear interruption flag BEFORE greeting
                        # Stop anything currently playing
                        stop_speaking() 
                        # Essential: Wait a tiny bit for queue to clear if threaded
                        time.sleep(0.05)
                        # Reset flag so greeting is accepted
                        interruption_event.clear()
                        
                        greeting = random.choice(activation_phrases)
                        # print(f"🤖 Ron: {greeting}")
                        speak_async(greeting)
                        
                        # 🔹 LOGGING: Registrar el saludo en la memoria del usuario
                        # Esto hace que aparezca en el chat
                        try:
                            # User said "Ron" (text) -> Ron said greeting
                            add_to_memory(current_username or "default", text, greeting, source="voice")
                        except Exception as log_err:
                            print(f"⚠️ Error logueando saludo: {log_err}")
                        
                        activado = True
                        last_interaction = time.time()
                
                else:
                    last_interaction = time.time()
                    stay_active = process_interaction(text)
                    if not stay_active:
                        print("💤 Desactivando escucha activa.")
                        activado = False

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error en Loop: {e}")
                
    finally:
        stop_listening(wait_for_stop=False)
