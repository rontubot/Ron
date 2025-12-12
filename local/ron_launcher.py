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

# 🔹 STRICT BARGE-IN: Palabras que permiten interrumpir a Ron
STOP_KEYWORDS = {
    # Wake Words
    "ron", "rom", "rron", "oye ron", "hola ron",
    # Stop Commands
    "silencio", "cállate", "callate", "stop", "detente", "basta", 
    "espera", "momento", "pausa", "parar"
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

def clean_text_for_tts(text: str) -> str:
    text = text.replace('\\n', ' ').replace('\n', ' ')
    text = re.sub(r'[*_`#]', '', text)
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑🧀-🫿]+', '', text)
    return text.strip()

class TTSWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)

    def run(self):
        global speaking
        while True:
            try:
                text = tts_queue.get()
                
                if interruption_event.is_set():
                    with tts_queue.mutex: tts_queue.queue.clear()
                    print("🚫 Cola TTS limpiada")
                    continue

                if not text: continue

                speaking = True
                # Log to echo buffer
                speech_buffer.add(text)
                
                self._speak(text)
                speaking = False
                
            except Exception as e:
                print(f"❌ Error TTS: {e}")
                speaking = False

    def _speak(self, text):
        if interruption_event.is_set(): return
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 190)
            engine.setProperty('volume', 1.0)
            cleaned = clean_text_for_tts(text)
            engine.say(cleaned)
            engine.runAndWait()
            if engine._inLoop: engine.endLoop()
        except: pass

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

# Disable debug logs from Whisper
logging.getLogger('faster_whisper').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('filelock').setLevel(logging.WARNING)

# Initialize Whisper model globally (load once)
print("🔄 Cargando modelo Whisper...")
from faster_whisper import WhisperModel
# Using "base" model - sweet spot between tiny and small
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
print("✅ Whisper listo (español optimizado)")

def setup_streaming_recognition():
    r = sr.Recognizer()
    r.pause_threshold = 0.8
    r.non_speaking_duration = 0.5
    r.dynamic_energy_threshold = False
    r.energy_threshold = 400
    try:
        m = sr.Microphone()
        print(f"🎤 Micrófono listo. Umbral fijo: {r.energy_threshold}")
        return r, m
    except Exception as e:
        print(f"❌ Error de Micrófono: {e}")
        sys.exit(1)

def transcribe_with_whisper(audio_data):
    """
    Transcribe audio using local Whisper model (FAST, no network)
    audio_data: AudioData object from speech_recognition
    """
    try:
        # Convert AudioData to WAV bytes
        wav_data = audio_data.get_wav_data()
        
        # Write to temp file for Whisper (it needs a file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_file.write(wav_data)
            tmp_path = tmp_file.name
        
        # Transcribe with Whisper - BALANCED FOR SPEED + SPANISH PRECISION
        segments, info = whisper_model.transcribe(
            tmp_path, 
            language="es",  # Force Spanish only
            beam_size=3,  # Balanced accuracy/speed (was 5)
            temperature=0.0,  # Deterministic
            vad_filter=True,  # Filter non-speech
            vad_parameters=dict(min_silence_duration_ms=300)  # Quick response
        )
        
        # Extract text
        text = " ".join([segment.text for segment in segments]).strip()
        
        # Cleanup
        os.unlink(tmp_path)
        
        return text
    except Exception as e:
        print(f"⚠️ Whisper error: {e}")
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
            # 🔹 2. RECOGNIZE TEXT with LOCAL WHISPER (INSTANT!)
            text = transcribe_with_whisper(audio).lower().strip()
            
            if not text: return

            # 🔹 3. "VIOLENT" ECHO ATTENUATION & INTERRUPTION LOGIC
            if speaking:
                if interruption_event.is_set(): return 

                # A. CHECK ECHO BUFFER
                if speech_buffer.is_echo(text):
                    print(f"🔇 Echo suprimido: '{text}'")
                    return

                # B. STRICT KEYWORD CHECK
                is_valid = False
                matched = ""
                for k in STOP_KEYWORDS:
                    if k in text:
                        is_valid = True; matched = k; break
                
                if not is_valid:
                    print(f"🛡️ Interrupción bloqueada (falta keyword): '{text}'")
                    return

                print(f"🛑 Interrupción VÁLIDA por '{matched}': '{text}'")
                stop_speaking()

                global activado
                activado = True

            print(f"👂 Escuchado: {text}")
            q.put((text, time.time()))

        except Exception as e:
            print(f"⚠️ Listener: {e}")

    return recognizer.listen_in_background(microphone, callback, phrase_time_limit=2)

# =========================================================================================
# STREAMING BACKEND
# =========================================================================================
def buffer_speech_sentences(text_stream):
    buffer = ""
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
               if sentence.strip(): yield sentence.strip()
               i += 2
            buffer = new_buffer
    if buffer.strip(): yield buffer.strip()

def process_interaction(user_text):
    global interruption_event
    interruption_event.clear()
    
    api_url = os.getenv("RON_API_URL", "https://ron-production.up.railway.app")
    auth_token = os.getenv("RON_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    payload = {"text": user_text, "username": current_username or "default"}

    full_response = ""
    commands_found = []
    
    print(f"📡 Solicitando: {user_text[:30]}...")

    try:
        with requests.post(f"{api_url}/ron/stream", json=payload, headers=headers, stream=True, timeout=10) as r:
            def generate_chunks():
                nonlocal commands_found
                for line in r.iter_lines():
                    if interruption_event.is_set(): break
                    if not line: continue
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        data = json.loads(line_str[6:])
                        if data['type'] == 'chunk': yield data['chunk']
                        elif data['type'] == 'result':
                            cmds = data.get('commands', [])
                            if cmds: commands_found.extend(cmds)

            for sentence in buffer_speech_sentences(generate_chunks()):
                if interruption_event.is_set():
                    print("🛑 Stream cancelado.")
                    break
                speak_async(sentence)
                full_response += " " + sentence

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
    # Remove punctuation before checking wake words
    clean_text = text.replace(',', '').replace('.', '').replace('!', '').replace('?', '').lower()
    tokens = clean_text.split()
    return any(w in ALLOWED_WAKE_WORDS for w in tokens)

if __name__ == "__main__":
    print("🟢 Ron 24/7 v2.0 (Violent Anti-Echo & Recording) Listo.")
    handle_external_control()
    task_manager = TaskManager(lambda t: speak_async(t))
    
    recognizer, microphone = setup_streaming_recognition()
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
    
    print("👂 Escuchando...")
    
    try:
        while True:
            try:
                try: text, ts = audio_queue.get(timeout=0.1)
                except queue.Empty: continue

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
                    last_interaction = time.time()
                    stay = process_interaction(text)
                    if not stay:
                        print("💤 Desactivando escucha activa.")
                        activado = False
            except KeyboardInterrupt: break
            except Exception as e: print(f"❌ Loop: {e}")
    finally:
        stop_listening(wait_for_stop=False)
