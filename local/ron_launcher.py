
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
]

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
conversation_buffer = []

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
                
                # Check interruption BEFORE starting
                if interruption_event.is_set():
                    with tts_queue.mutex:
                        tts_queue.queue.clear()
                    print("🚫 Cola TTS limpiada por interrupción")
                    continue

                if not text:
                    continue

                speaking = True
                self._speak(text)
                speaking = False
                
            except Exception as e:
                print(f"❌ Error en TTS Worker: {e}")
                speaking = False

    def _speak(self, text):
        """Initializes a new engine instance for each phrase to avoid state corruption (pyttsx3 limitation)"""
        try:
            # Check interruption AGAIN just in case
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
    tts_queue.put(text)

def stop_speaking():
    """Signals interruption"""
    interruption_event.set()
    # Clear queue immediately
    with tts_queue.mutex:
        tts_queue.queue.clear()
    
# =========================================================================================
# VAD & LISTENER (Interruption Logic)
# =========================================================================================

def setup_streaming_recognition():
    r = sr.Recognizer()
    r.pause_threshold = 0.8
    r.dynamic_energy_threshold = True 
    r.energy_threshold = 300 # Baseline
    try:
        m = sr.Microphone()
        with m as source:
            r.adjust_for_ambient_noise(source, duration=1)
        return r, m
    except Exception as e:
        print(f"❌ Error de Micrófono: {e}")
        sys.exit(1)

def stream_audio_recognition(recognizer, microphone, q):
    """
    Background listener.
    CRITICAL: If it detects speech while 'speaking' is True, it triggers interruption.
    """
    def callback(recognizer, audio):
        global speaking, interruption_event

        try:
            # 1. Check for BARGE-IN (Interruption)
            if speaking:
                if interruption_event.is_set():
                    return # Already interrupted
                
                print("🛑 ¡INTERRUPCIÓN DETECTADA! Deteniendo audio.")
                stop_speaking()

            # 2. Recognize text
            text = recognizer.recognize_google(audio, language="es").lower().strip()
            
            if text:
                print(f"👂 Escuchado: {text}")
                q.put((text, time.time()))

        except sr.UnknownValueError:
            pass
        except sr.RequestError:
            pass
        except Exception as e:
            print(f"⚠️ Error en Listener: {e}")

    return recognizer.listen_in_background(microphone, callback, phrase_time_limit=5)

# =========================================================================================
# STREAMING BACKEND CLIENT
# =========================================================================================

def buffer_speech_sentences(text_stream):
    """
    Yields full sentences from a stream of characters/chunks.
    Used to feed the TTS worker smoothly.
    """
    buffer = ""
    # Delimiters for natural pauses
    endings = re.compile(r'([.?!,])') 
    
    for chunk in text_stream:
        buffer += chunk
        
        # Split by sentence endings
        parts = endings.split(buffer)
        
        # If we have complete sentences (pairs of text + punctuation)
        if len(parts) > 1:
            # Reconstruct sentences: ["Hola", ".", "Como", "?", "estas"] -> "Hola.", "Como?"
            
            # parts[-1] is the incomplete part (or empty string if ends with punctuation)
            to_process = parts[:-1]
            new_buffer = parts[-1]
            
            i = 0
            while i < len(to_process) - 1:
               sentence = to_process[i] + to_process[i+1]
               if sentence.strip():
                   yield sentence.strip()
               i += 2
            
            buffer = new_buffer

    # Yield remaining buffer
    if buffer.strip():
        yield buffer.strip()

def process_interaction(user_text):
    """
    Main logic: Sends text to backend, streams response, feeds TTS, handles interruption.
    """
    global interruption_event, speaking
    
    interruption_event.clear() # Reset flag for new turn
    
    api_url = os.getenv("RON_API_URL", "https://ron-production.up.railway.app")
    auth_token = os.getenv("RON_AUTH_TOKEN", "")
    
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    payload = {"text": user_text, "username": current_username or "default"}

    full_response = ""
    commands_to_exec = []
    
    print(f"📡 Solicitando: {user_text[:30]}...")

    try:
        # Use a session for persistent connection
        with requests.post(f"{api_url}/ron/stream", json=payload, headers=headers, stream=True, timeout=10) as r:
            
            # Iterator for text chunks from server
            def generate_chunks():
                for line in r.iter_lines():
                    if interruption_event.is_set(): break
                    if not line: continue
                    
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        data = json.loads(line_str[6:])
                        if data['type'] == 'chunk':
                            yield data['chunk']
                        elif data['type'] == 'result':
                            # Safe result (commands)
                            pass

            # Feed chunks to sentence splitter -> TTS Queue
            for sentence in buffer_speech_sentences(generate_chunks()):
                if interruption_event.is_set():
                    print("🛑 Stream de respuesta cancelado.")
                    break
                    
                # print(f"📝 Queuing: {sentence[:30]}")
                speak_async(sentence)
                full_response += " " + sentence

    except Exception as e:
        print(f"❌ Error de Backend: {e}")
        speak_async("Hubo un error de conexión.")
        return False # Should not stay active

    # Handle completion
    if interruption_event.is_set():
        return True # Stay active to listen to the new command
        
    return should_stay_active(user_text, full_response)

def should_stay_active(user_text, response_text):
    """Example logic to keep conversation open"""
    # Simple heuristic
    if "?" in response_text or "dime" in response_text.lower():
        return True
    return False

# =========================================================================================
# MAIN LOOP
# =========================================================================================

def detect_ron_activation(text):
    """Simple wake word detection"""
    tokens = text.lower().split()
    return any(w in ALLOWED_WAKE_WORDS for w in tokens)

if __name__ == "__main__":
    print("🟢 Ron 24/7 v2.0 (Streaming & Barge-In) Listo.")
    
    # Init TaskManager just for TTS callback compatibility
    task_manager = TaskManager(lambda t: speak_async(t))
    
    recognizer, microphone = setup_streaming_recognition()
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
    
    print("👂 Escuchando...")
    
    try:
        while True:
            try:
                # 1. Get Audio (Non-blocking check)
                try:
                    text, ts = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # 2. Wake Word Logic
                if not activado:
                    if detect_ron_activation(text):
                        print("✅ Palabra clave detectada!")
                        interruption_event.clear() # Reset any latent flag
                        stop_speaking() # Silence anything
                        speak_async(random.choice(activation_phrases))
                        activado = True
                        last_interaction = time.time()
                
                # 3. Active Conversation Logic
                else:
                    # Reset timeout
                    last_interaction = time.time()
                    
                    # If we were speaking and got text here, it means we were interrupted
                    # (handled by callback logic setting interruption_event).
                    # Now we just assume this text is the NEW command.
                    
                    # Wait a bit to accumulate loose phrases? 
                    # Naive implementation: one utterance = one command
                    
                    stay_active = process_interaction(text)
                    if not stay_active:
                        print("💤 Desactivando.")
                        activado = False

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error en Loop: {e}")
                
    finally:
        stop_listening(wait_for_stop=False)
