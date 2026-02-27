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
from datetime import datetime, timezone

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

# 🔹 Set Electron tasks path for memory synchronization
if not os.getenv("RON_TASKS_PATH"):
    app_data = os.getenv("APPDATA")
    if app_data:
        tasks_path = os.path.join(app_data, "ron-web-app", "tasks.json")
        if os.path.exists(tasks_path):
            os.environ["RON_TASKS_PATH"] = tasks_path
            logging.info(f"🔗 RON_TASKS_PATH set to: {tasks_path}")
from core.tts import speak as tts_speak

# =========================================================================================
# UTILITIES
# =========================================================================================
def get_internet_time():
    """
    Obtiene la hora actual de una API confiable. 
    Retorna ISO 8601 UTC (ending in Z) para consistencia global.
    """
    try:
        r = requests.get("https://worldtimeapi.org/api/ip", timeout=5)
        if r.status_code == 200:
            data = r.json()
            dt_str = data.get("datetime")
            if dt_str: return dt_str
    except: pass
    
    # Fallback robusto: UTC real con sufijo Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def drain_queue(q):
    """Vacía completamente una cola."""
    while not q.empty():
        try: q.get_nowait()
        except queue.Empty: break

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
parser.add_argument("--microphone-index", type=int, default=None, help="Índice del micrófono a usar")
args = parser.parse_known_args()[0]

current_username = args.username
control_enabled = True

# Constants
SILENCE_TIMEOUT_SEC = 0.8 # Tiempo de silencio para detener auto-grabación ("silencio grande")
ALLOWED_WAKE_WORDS = {"ron", "ro", "rum", "run", "ru", "rom"}


# 🔹 DEACTIVATE: Palabras que apagan la escucha activa
DEACTIVATE_KEYWORDS = {
    "descansa", "reposo", "dormir", "adios", "adiós", "hasta luego", 
    "terminamos", "ya está", "ya esta", "nada más", "nada mas", "silencio",
    "desactivar", "desactívate", "desactivarse", "apágate", "cierra la boca",
    "nos vemos", "chao", "bye", "nos vimos", "corta", "cortala",
    "listo", "vale", "entendido", "okey", "ok", "perfecto", "suficiente",
    "hasta mañana", "vete a dormir", "apaga", "silencio por favor"
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
last_speech_at = 0.0 # 🔹 Para evitar eco inmediato

# MANUAL RECORDING STATE
manual_recording = False
manual_audio_buffer = []  # List of small audio chunks
recording_start_time = 0
manual_recording_lock = threading.Lock()

# 🔹 Global Recognizer & Microphone (Initialize early for control server)
recognizer = None
microphone = None
stop_listening = None
last_ron_response = "" # Para filtro anti-eco directo

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

class TTSWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)

    def run(self):
        global speaking, last_speech_at
        while True:
            try:
                text = tts_queue.get()
                if not text: continue
                
                if interruption_event.is_set():
                    with tts_queue.mutex: tts_queue.queue.clear()
                    continue

                speaking = True
                speech_buffer.add(text)
                
                import base64
                b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')

                # print(f"🤖 Ron hablando: {text[:60]}...") # ❌ Removido para evitar redundancia en Electron
                
                tts_script = f"""
import pyttsx3, sys, base64, os
try:
    text = base64.b64decode('{b64_text}').decode('utf-8')
    e = pyttsx3.init('sapi5') if os.name == 'nt' else pyttsx3.init()
    e.setProperty('rate', 195)
    e.setProperty('volume', 1.0)
    voices = e.getProperty('voices')
    v_id = next((v.id for v in voices if any(x in v.name.lower() for x in ['mexico','helena','sabina','spanish','es-es','es-mx'])), None)
    if v_id: e.setProperty('voice', v_id)
    e.say(text)
    e.runAndWait()
except:
    pass
"""
                try:
                    p = subprocess.Popen([sys.executable, "-c", tts_script])
                    while p.poll() is None:
                        if interruption_event.is_set():
                            p.terminate()
                            break
                        time.sleep(0.01)
                    p.wait()
                except Exception as ex:
                    print(f"❌ Error al lanzar TTS: {ex}")
                
                speaking = False
                last_speech_at = time.time()
            except Exception as e:
                print(f"❌ TTS Worker exception: {e}")
                import traceback
                traceback.print_exc()
                speaking = False
                last_speech_at = time.time()

def stop_speaking():
    interruption_event.set()
    with tts_queue.mutex:
        tts_queue.queue.clear()

# =========================================================================================
# CONTROL SERVER (Audio Recording & Status)
# =========================================================================================
def trigger_internal_stop():
    """Simula un comando STOP_RECORDING vía socket local para disparar el procesamiento."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('127.0.0.1', args.control_port))
        s.sendall(b'STOP_RECORDING')
        s.close()
    except: pass

def start_smart_recording():
    """OBSOLETO: Ahora Ron usa escucha pasiva continua."""
    pass

def ensure_recorder_thread_internal():
    """Asegura que el hilo de grabación global esté activo sin disparar una grabación."""
    global_recorder_thread = [t for t in threading.enumerate() if t.name == 'GlobalRawRecorder']
    if not global_recorder_thread:
        print("[Python] [Recorder] Iniciando Hilo Global de Grabación...")
        def raw_recorder_loop():
            global manual_recording, manual_audio_buffer
            p = None
            stream = None
            try:
                import pyaudio
                dev_idx = args.microphone_index
                
                while True:
                    is_rec = False
                    with manual_recording_lock:
                        is_rec = manual_recording
                    
                    if is_rec:
                        if p is None:
                            try:
                                print("[Python] [Recorder] Inicializando PyAudio lazily...", flush=True)
                                p = pyaudio.PyAudio()
                            except Exception as e:
                                print(f"[Python] ❌ Error inicializando PyAudio: {e}", flush=True)
                                time.sleep(1)
                                continue

                        if stream is None:
                            try:
                                print(f"[Python] [Recorder] Abriendo stream en device_index={dev_idx}", flush=True)
                                stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, 
                                                frames_per_buffer=1024, input_device_index=dev_idx)
                            except Exception as e:
                                print(f"[Python] ❌ Error abriendo stream: {e}", flush=True)
                                time.sleep(0.5)
                                continue
                        
                        try:
                            # Leemos en trozos pequeños para no bloquear mucho
                            data = stream.read(1024, exception_on_overflow=False)
                            if data:
                                with manual_recording_lock:
                                    manual_audio_buffer.append(data)
                        except Exception as e:
                            print(f"[Python] ❌ Error leyendo stream: {e}", flush=True)
                            if stream:
                                try: stream.stop_stream(); stream.close()
                                except: pass
                                stream = None
                            time.sleep(0.1)
                    else:
                        if stream is not None:
                            print("[Python] [Recorder] Cerrando stream y liberando PyAudio (reposo)", flush=True)
                            try:
                                stream.stop_stream()
                                stream.close()
                            except: pass
                            stream = None
                        
                        if p is not None:
                            try: p.terminate()
                            except: pass
                            p = None
                            
                        time.sleep(0.1) # Reposo cuando no graba
            except Exception as e:
                print(f"[Python] ❌ Error en Global Recorder loop: {e}", flush=True)
            finally:
                if stream:
                    try: stream.stop_stream(); stream.close()
                    except: pass
                if p:
                    try: p.terminate()
                    except: pass

        t = threading.Thread(target=raw_recorder_loop, name='GlobalRawRecorder', daemon=True)
        t.start()

def ensure_recorder_thread():
    """Versión que puede llamarse internamente o desde el main loop."""
    ensure_recorder_thread_internal()

def handle_external_control():    
    def control_server():    
        global listening_active, speaking, control_enabled, manual_recording, manual_audio_buffer, activado, stop_listening, recognizer, microphone
        try:    
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)    
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)    
            server.bind(('127.0.0.1', args.control_port))    
            server.listen(5)
            print(f"Control server listening on port {args.control_port}", flush=True)    
  
            while control_enabled:    
                try:    
                    client, _ = server.accept()
                    client.settimeout(2.0)
                    data = client.recv(4096)    
                    if not data:
                        client.close(); continue    
  
                    raw_data = data.decode('utf-8', errors='ignore').strip()
                    if not raw_data:
                        client.close(); continue
                    
                    cmd = raw_data.upper()
  
                    if cmd == 'STATUS':    
                        state = b'ACTIVE' if (listening_active or speaking or activado) else b'INACTIVE'
                        client.sendall(state)    
  
                    elif cmd == 'START':
                        client.sendall(b'OK')

                    elif cmd == 'STOP':
                        stop_speaking()
                        client.sendall(b'OK')

                    elif cmd.startswith('SPEAK:'):
                        text_to_speak = raw_data[6:].strip()
                        if text_to_speak:
                            interruption_event.clear()
                            speak_async(text_to_speak)
                        client.sendall(b'OK')

                    elif cmd.startswith('UPDATE_TOKEN:'):
                        new_token = raw_data[13:].strip()
                        if new_token:
                            os.environ["RON_AUTH_TOKEN"] = new_token
                            # 🔹 DEBUG: Mostrar que el token se recibió (truncado por seguridad)
                            safe_token = f"{new_token[:5]}...{new_token[-5:]}" if len(new_token) > 10 else "***"
                            print(f"[Python] 🔑 Token actualizado: {safe_token}")
                        client.sendall(b'OK')

                    elif cmd.startswith('UPDATE_USER:'):
                        new_user = raw_data[12:].strip()
                        if new_user:
                            global current_username
                            current_username = new_user
                            print(f"[Python] 👤 Username actualizado: {new_user}")
                        client.sendall(b'OK')
                    
                    elif cmd == 'START_RECORDING':
                        client.sendall(b'OK') # ACK Inmediato para evitar timeouts en Electron
                        print("[Python] START_RECORDING: Ack enviado.", flush=True)
                        
                        # 1. Detener escucha de fondo SI existe
                        if stop_listening:
                            print("[Python] 👂 Deteniendo escucha de fondo para grabación manual...", flush=True)
                            try:
                                stop_listening(wait_for_stop=False)
                            except: pass
                            stop_listening = None
                            time.sleep(0.3) # 🔹 Margen para que Windows libere el driver
                        
                        # 2. Iniciar grabación
                        with manual_recording_lock:
                            manual_recording = True
                            manual_audio_buffer = [] 
                        
                        # Asegurar que el hilo existe y empezará a grabar
                        ensure_recorder_thread_internal()
                        print("[Python] 🎙️ Grabación manual INICIADA.", flush=True)
                        
                    elif cmd == 'STOP_RECORDING':
                        client.sendall(b'OK:PROCESSING') # ACK Inmediato
                        print("[Python] STOP_RECORDING: Ack enviado.", flush=True)
                        print("🎙️ Deteniendo grabación (Manual/Auto)...")
                        
                        with manual_recording_lock:
                            manual_recording = False
                                                
                        # El hilo sigue corriendo, pero ya no escribe en el buffer.
                        # No cerramos nada.

                        if stop_listening:
                            # Ya no manipulamos stop_listening aquí
                            pass

                        filename = f"rec_{int(time.time())}.wav"
                        filepath = os.path.join(os.getcwd(), 'temp', filename)
                        os.makedirs(os.path.join(os.getcwd(), 'temp'), exist_ok=True)
                        
                        with manual_recording_lock:
                            frames = list(manual_audio_buffer) 
                            # NO limpiamos el buffer aquí si queremos debugging, pero sí para la próxima.
                            manual_audio_buffer = []

                        try:
                            # 🔹 Relaxed threshold: Si hay al menos un poco de data
                            if not frames or len(frames) < 2: 
                                print("[Python] ⚠️ Grabación vacía (Buffer < 2 chunks).")
                                print(json.dumps({"type": "recording_state", "state": "idle" if activado else "inactive"}), flush=True)
                            else:
                                # Notificar que estamos procesando inmediatamente tras el STOP
                                print(json.dumps({"type": "recording_state", "state": "processing"}), flush=True)

                                def async_transcribe_and_process(audio_frames, wav_path):
                                    global activado
                                    try:
                                        # Guardar WAV
                                        with wave.open(wav_path, 'wb') as wf:
                                            wf.setnchannels(1)
                                            wf.setsampwidth(2) # 16-bit
                                            wf.setframerate(16000)
                                            wf.writeframes(b''.join(audio_frames))
                                        
                                        print(f"[Python] ✅ WAV guardado ({len(audio_frames)} chunks): {wav_path}", flush=True)
                                        
                                        # 🔹 Transcribir
                                        import speech_recognition as sr
                                        with sr.AudioFile(wav_path) as source:
                                            audio_data = recognizer.record(source)
                                            transcription = transcribe_audio(recognizer, audio_data)
                                            
                                            if transcription and len(transcription.strip()) > 1:
                                                print(f"[USER_VOICE] {transcription}")
                                                
                                                # (Redundancia eliminada: ya estamos en 'processing' desde el STOP)
                                                
                                                # 🔹 FILTRO ANTI-ECO
                                                global last_ron_response, activado
                                                if transcription.lower().strip() == (last_ron_response or "").lower().strip():
                                                    print(f"[Python] 🔇 Eco detectado e ignorado: '{transcription}'")
                                                    if os.path.exists(wav_path): os.remove(wav_path)
                                                    # if activado: start_smart_recording() # Quitamos el auto-reinicio agresivo
                                                    return

                                                stay_active = process_interaction(transcription)
                                                
                                                # 🔹 ELIMINADO: Cadeneo automático agresivo. 
                                                # Ahora dejaremos que Ron vuelva a su estado pasivo o active Smart Record 
                                                # solo si el loop principal lo decide (basado en 'activado').
                                                if not stay_active:
                                                    activado = False
                                                    print(json.dumps({"type": "recording_state", "state": "inactive"}), flush=True)
                                                else:
                                                    # Ron sigue activo, regresamos a espera pasiva
                                                    print(json.dumps({"type": "recording_state", "state": "idle"}), flush=True)
                                                    time.sleep(0.2)
                                            else:
                                                print("[Python] ⚠️ No se detectó voz.")
                                                # En caso de no detectar nada, volver a reposo
                                                print(json.dumps({"type": "recording_state", "state": "idle" if activado else "inactive"}), flush=True)
                                    except Exception as ex:
                                        print(f"[Python] ❌ Error en proceso asíncrono: {ex}")
                                        print(json.dumps({"type": "recording_state", "state": "idle" if activado else "inactive"}), flush=True)
                                    finally:
                                        # 🔹 LIMPIEZA
                                        try: 
                                            if os.path.exists(wav_path): os.remove(wav_path)
                                        except: pass

                                threading.Thread(target=async_transcribe_and_process, args=(frames, filepath), daemon=True).start()

                        except Exception as e:
                            print(f"[Python] ❌ Error enviando ACK: {e}")
                            client.sendall(b'ERROR')

                        except Exception as e:
                            print(f"[Python] ❌ Error guardando WAV: {e}")
                            client.sendall(b'ERROR')
                        
                        # 3. Reiniciar el escucha de fondo (si se detuvo)
                        if not stop_listening and not activado:
                            try:
                                stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
                            except: pass

                    elif cmd == 'CANCEL_RECORDING':
                        print("[Python] 🚫 Grabación CANCELADA.")
                        with manual_recording_lock:
                            manual_recording = False
                            manual_audio_buffer = []

                        client.sendall(b'CANCELED')

                    elif cmd == 'ACTIVATE':
                        print("🤖 Activación forzada vía Control Server.")
                        stop_speaking()
                        interruption_event.clear()
                        activado = True # Forzar a Ron a escuchar
                        client.sendall(b'OK')

                    elif cmd == 'DEACTIVATE':
                        print("💤 Desactivación forzada vía Control Server.")
                        activado = False
                        client.sendall(b'OK')

                    else:
                        client.sendall(b'UNKNOWN')
                    client.close()
                except: pass
        except Exception as e:    
            print(f"❌ Error fatal en control server: {e}")    
  
    threading.Thread(target=control_server, daemon=True).start()

def speak_async(text: str):
    if not text or interruption_event.is_set(): return
    tts_queue.put(text)

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
whisper_model = None
STT_ENGINE = os.getenv("STT_ENGINE", "google") 

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
    try:
        import tqdm
        import tqdm.auto
        import tqdm.std

        class JsonTqdm(tqdm.std.tqdm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                send_progress(0, "Iniciando descarga (3GB)...")

            def update(self, n=1):
                super().update(n)
                try:
                    if self.total and self.total > 0:
                        pct = (self.n / self.total) * 100
                        if self.n >= self.total or (self.n % (self.total // 100 + 1) == 0):
                            send_progress(pct, f"Descargando núcleo de voz: {int(pct)}%")
                except: pass

        tqdm.tqdm = JsonTqdm
        tqdm.auto.tqdm = JsonTqdm
        tqdm.std.tqdm = JsonTqdm
        sys.modules['tqdm'].tqdm = JsonTqdm
        sys.modules['tqdm.auto'].tqdm = JsonTqdm
        
    except Exception as e:
        print(f"TQDM Patch Warning: {e}")
        send_progress(5, "Descarga iniciada...")

    from faster_whisper import download_model

    print("Bot: 🔄 Verificando/Descargando modelo small (equilibrado)...")
    try:
        model_path = download_model("small")
        send_progress(100, "Modelo cargado. Iniciando...")
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=8)
    except Exception as e:
        print(f"Error cargando modelo: {e}")
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

    print("✅ Whisper listo (small cargado)")
else:
    print("🚀 Usando STT básico (Google) para máxima velocidad.")

def setup_streaming_recognition(device_index=None):
    r = sr.Recognizer()
    r.pause_threshold = 1.2 # Aumentado para dar más margen al hablar
    r.non_speaking_duration = 0.3 # Ajustado
    r.dynamic_energy_threshold = True # Habilitado para adaptarse al entorno
    r.energy_threshold = 150 # Reducido un poco más para máxima sensibilidad
    try:
        try:
            # 🔹 Optimización: Usar PyAudio directo para filtrar "Outputs" y duplicados
            import pyaudio
            p = pyaudio.PyAudio()
            valid_devices = []
            seen_names = set()
            
            # Palabras clave a excluir (drivers genéricos o salidas disfrazadas)
            EXCLUDE_KEYWORDS = ["mapper", "asignador", "controlador primario", "primary sound", "display audio", "stereo mix", "mezcla estéreo"]

            print(f"🔍 Escaneando dispositivos de audio (Total raw: {p.get_device_count()})...")

            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    name = info.get("name", "")
                    inputs = info.get("maxInputChannels", 0)
                    
                    # 1. Filtro básico: Debe ser INPUT
                    if inputs <= 0: continue

                    # 2. Filtro de nombre: Evitar wrappers genéricos de Windows
                    lower_name = name.lower()
                    if any(k in lower_name for k in EXCLUDE_KEYWORDS): continue
                    
                    # 3. Deduplicación por nombre exacto (Windows suele listar MME, DirectSound, WASAPI por separado)
                    # Nos quedamos con la primera ocurrencia (usualmente MME/Default)
                    if name in seen_names: continue
                    
                    seen_names.add(name)
                    valid_devices.append({"index": i, "name": name})

                except Exception as e:
                    print(f"⚠️ Error leyendo device {i}: {e}")
            
            p.terminate()

            print(f"🎤 Micrófonos ÚTILES detectados ({len(valid_devices)}):")
            for d in valid_devices:
                idx, nm = d['index'], d['name']
                is_selected = " [SELECCIONADO]" if device_index is not None and idx == device_index else ""
                print(f"   [{idx}] {nm}{is_selected}")
            
            # 🔹 Guardar lista filtrada para la UI
            try:
                json_path = os.path.join(os.getcwd(), 'audio_devices.json')
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(valid_devices, f)
            except Exception as e:
                print(f"⚠️ Error guardando audio_devices.json: {e}")

        except Exception as e:
            print(f"⚠️ Error listando micrófonos (fallback): {e}")
            # Fallback a lista básica si falla PyAudio filter
            try:
                mics = sr.Microphone.list_microphone_names()
                device_list = [{"index": i, "name": name} for i, name in enumerate(mics)]
                with open(os.path.join(os.getcwd(), 'audio_devices.json'), 'w', encoding='utf-8') as f:
                    json.dump(device_list, f)
            except: pass

        # Configurar índice de dispositivo específico si se proporciona
        if device_index is not None:
            print(f"🎤 Inicializando micrófono con índice específico: {device_index}")
            m = sr.Microphone(device_index=device_index)
        else:
            m = sr.Microphone()
            
        print(f"🎤 Micrófono listo. Umbral fijo: {r.energy_threshold}")
        return r, m
    except Exception as e:
        print(f"❌ Error de Micrófono (Idx: {device_index}): {e}")
        sys.exit(1)

def transcribe_audio(recognizer, audio_data):
    global whisper_model
    if STT_ENGINE == "google":
        try:
            return recognizer.recognize_google(audio_data, language="es-ES")
        except sr.UnknownValueError: return ""
        except sr.RequestError as e:
            print(f"☁️ Google API Error: {e}")
            return ""
    elif STT_ENGINE == "whisper":
        if not whisper_model: load_whisper()
        if not whisper_model: return ""
        try:
            wav_data = audio_data.get_wav_data()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(wav_data)
                tmp_path = tmp_file.name
            segments, _ = whisper_model.transcribe(tmp_path, language="es", beam_size=1, best_of=1, temperature=0.0, condition_on_previous_text=False)
            text = " ".join([segment.text for segment in segments]).strip()
            os.unlink(tmp_path)
            return text
        except Exception as e:
            print(f"⚠️ Whisper error: {e}")
            return ""
    return ""

def stream_audio_recognition(recognizer, microphone, q):
    def callback(recognizer, audio):
        global speaking, interruption_event, manual_recording, manual_audio_buffer, last_speech_at

        # 🔹 1. ECHO COOLDOWN & SPEAKING CHECK
        if speaking or (time.time() - last_speech_at < 0.5):
            return

        # 🔹 2. HANDLE MANUAL RECORDING (Deprecated via background callback)
        # if manual_recording:
        #    ...
        #    return

        try:
            # 🔹 3. RECOGNIZE TEXT
            text = transcribe_audio(recognizer, audio).lower().strip()
            if not text or len(text) < 2: return # Evitar micro-ruidos

            # 🔹 4. ECHO FILTER (Fuzzy match with recent history)
            if speech_buffer.is_echo(text):
                print(f"[Python] 🔇 Eco detectado e ignorado: '{text}'")
                return

            # 🔹 5. PRINT USER VOICE FOR UI LOGGER
            if not activado:
                print(f"[USER_PASSIVE] {text}")
            else:
                # Feedback instantáneo para modo activo (se quita del loop principal para evitar duplicado)
                print(f"[USER_VOICE] {text}")

            # Normal log for activity feed
            q.put((text, time.time()))

        except Exception as e:
            print(f"⚠️ Listener: {e}")

    # 🔹 PROTECCIÓN: AssertionError fix (Microphone context)
    if getattr(microphone, 'stream', None) is not None:
        print("[Python] ⚠️ Micrófono ya en uso. Saltando escucha en background.")
        return lambda wait_for_stop=False: None

    return recognizer.listen_in_background(microphone, callback, phrase_time_limit=10)

def buffer_speech_sentences(text_stream):
    """
    Yields full sentences as soon as they are completed in the stream.
    Sentence delimiters: . ! ? \n
    """
    buffer = ""
    for chunk in text_stream:
        if not chunk: continue
        buffer += chunk
        
        # Detectar delimitadores de fin de oración
        # Usamos regex para no romper decimales (ej: 3.5) idealmente, 
        # pero para velocidad buscaremos espacio tras el punto o fin de linea.
        
        while True:
            # Buscar el primer delimitador que tenga un espacio después o sea el final
            match = re.search(r'([.!?])(?:\s+|$)', buffer)
            if match:
                end_pos = match.end()
                sentence = buffer[:end_pos].strip()
                if sentence:
                    yield sentence
                buffer = buffer[end_pos:]
            elif '\n' in buffer:
                idx = buffer.find('\n')
                sentence = buffer[:idx].strip()
                if sentence:
                    yield sentence
                buffer = buffer[idx+1:]
            else:
                break
    
    if buffer.strip():
        yield buffer.strip()

def process_interaction(user_text):
    global interruption_event, activado
    interruption_event.clear()
    
    api_url = os.getenv("RON_API_URL", "http://localhost:8000")
    auth_token = os.getenv("RON_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    # Normalizar username: preferir minúsculas si viene del sistema (ej: LMAR -> lmar)
    user_to_send = (current_username or "default").lower()
    
    now_str = get_internet_time()
    context_prefix = f"[Contexto actual: {now_str}] "
    
    # 🔹 0. Detectar hibernación manual (Keyword check rápido)
    norm_text = user_text.lower().strip()
    if any(k in norm_text for k in DEACTIVATE_KEYWORDS):
        print(f"💤 Hibernación por comando: '{user_text}'")
        speak_async("Entendido, ya no escucho.")
        activado = False
        print(json.dumps({"type": "recording_state", "state": "inactive"}), flush=True)
        return False

    payload = {
        "text": context_prefix + user_text, 
        "username": user_to_send,
        "source": "desktop"
    }

    full_response = ""
    commands_found = []
    
    print(f"📡 Solicitando: {user_text[:40]}...")

    try:
        # 🔹 Usar streamed response para obtener texto lo antes posible
        with requests.post(f"{api_url}/ron/stream", json=payload, headers=headers, stream=True, timeout=60) as r:
            print(f"[Python] 📡 Respuesta HTTP recibida: {r.status_code}", flush=True)
            if r.status_code != 200:
                print(f"❌ Error API: {r.status_code} (User: {user_to_send})", flush=True)
                # Fallback to non-streaming
                return _process_interaction_fallback(user_text, api_url, headers, user_to_send)

            full_content = ""
            # 🔹 Procesar por oraciones para que hable mientras descarga
            def generate_chunks():
                for line in r.iter_lines():
                    if not line: continue
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        try:
                            data = json.loads(line_str[6:])
                            if data['type'] == 'chunk':
                                chunk = data['chunk']
                                print(f"[RON_PARTIAL] {chunk}", flush=True)
                                yield chunk
                                has_any_chunk = True
                            elif data.get('type') == 'done' or data.get('done'):
                                # Extract full text or commands from done event
                                if not has_any_chunk and data.get('full_text'):
                                    yield data['full_text']
                                has_any_chunk = True
                                cmds = data.get('commands', [])
                                if cmds: 
                                    commands_found.extend(cmds)
                        except: continue

            # 🔹 Enviar a TTS por oraciones
            has_any_content = False
            for sentence in buffer_speech_sentences(generate_chunks()):
                if sentence:
                    if not has_any_content:
                        # 🔹 Liberar a la UI del estado 'processing' en cuanto Ron empieza a hablar
                        print(json.dumps({"type": "recording_state", "state": "idle" if activado else "inactive"}), flush=True)
                    
                    has_any_content = True
                    print(f"[RON_VOICE] {sentence}", flush=True)
                    full_content += " " + sentence
                    speak_async(sentence)

            if not has_any_content:
                print("⚠️ Stream finished with no content. Trying fallback...")
                return _process_interaction_fallback(user_text, api_url, headers, user_to_send)

            full_response = full_content.strip()
            global last_ron_response
            last_ron_response = full_response
            
            # 🔹 Esperar a que termine de hablar antes de purgar eco
            # Debemos esperar a que el hilo de habla termine TODA la cola
            while speaking or not tts_queue.empty(): 
                time.sleep(0.01)
            
            # Pequeño margen extra de "respiración" para el motor de audio
            # para que el eco se disipe y el VAD no se active solo.
            time.sleep(0.5)
            drain_queue(audio_queue)
            
            # 🔹 Ejecutar comandos si los hay
            # 🔹 Ejecutar comandos si los hay
            if commands_found:
                print(f"⚡ Ejecutando {len(commands_found)} comandos...")
                
                # Definir comandos que SOLO debe manejar la UI (Electron) para evitar duplicados
                UI_ONLY_COMMANDS = {
                    'add_reminder', 'add_reminder_item', 'agregar_recordatorio',
                    'update_reminder', 'remove_reminder', 
                    'add_recurring_reminder', 'tasks:update', 'tasks:delete',
                    'add_multiple_reminders', 'notify', 'browse', 'search',
                    'open_url', 'minimize', 'update-mic-config', 'queue_local_task'
                }

                # 🔹 CONTEXTO: Guardar tema del último recordatorio interactuado
                def save_context_memory(cmd_list):
                    try:
                        ctx_file = os.path.join(os.getcwd(), 'temp', 'context_memory.json')
                        last_topic = None
                        
                        for c in cmd_list:
                            act = c.get('action', '')
                            p = c.get('params', {})
                            if act in ['add_reminder', 'add_reminder_item', 'add_recurring_reminder']:
                                last_topic = p.get('activity') or p.get('title')
                            elif act in ['update_reminder', 'remove_reminder']:
                                last_topic = p.get('original_title') or p.get('title')
                        
                        if last_topic:
                            with open(ctx_file, 'w', encoding='utf-8') as f:
                                json.dump({"last_reminder_topic": last_topic, "timestamp": time.time()}, f)
                            print(f"[Memory] Contexto guardado: '{last_topic}'")
                    except Exception as e:
                        print(f"[Memory] Error guardando contexto: {e}")

                save_context_memory(commands_found)


                # 1. Enviar TODOS los comandos a Electron primero para que la UI reaccione
                # 🔹 PROTOCOLO SEGURO: Usar delimitadores para que el regex en Electron no falle con llaves anidadas
                json_str = json.dumps({"type": "commands", "commands": commands_found})
                print(f"\n<<RON_CMD>>{json_str}<<END_CMD>>\n", flush=True)
                
                for cmd in commands_found:
                    action = cmd.get('action')
                    params = cmd.get('params', {})
                    
                    if action == 'stop_listening':
                        print("💤 Ron se desactiva por orden del cerebro.")
                        activado = False
                        print(json.dumps({"type": "recording_state", "state": "inactive"}), flush=True)
                        return False

                    # 🔹 Si es un comando de UI, SALTAR ejecución local (ya se envió a Electron)
                    if action in UI_ONLY_COMMANDS:
                        print(f"⏭️ Delegando '{action}' a la UI (Electron).")
                        continue

                    try: 
                        # Capture command results to relay to Electron
                        cmd_result = run_command(action, params, {'username': current_username, 'task_manager': task_manager})
                        
                        # 🔹 FEEDBACK VOCAL OBLIGATORIO (Para queries como 'get_reminders')
                        if cmd_result and isinstance(cmd_result, dict):
                            # Si el comando retorna 'user_response', lo hablamos
                            response_text = cmd_result.get('user_response') or cmd_result.get('message')
                            if response_text:
                                # Serialize newlines so Electron receives 1 line
                                safe_text = response_text.replace('\n', '\\n')
                                print(f"[RON_VOICE] {safe_text}") 
                                speak_async(response_text)
                            
                            # Relay follow-up commands (like UI updates)
                            if 'commands' in cmd_result:
                                print(json.dumps({"type": "commands", "commands": cmd_result['commands']}))
                                
                    except Exception as ce:
                        print(f"⚠️ Error ejec. comando: {ce}")
                
                # Si se ejecutaron comandos que NO son stop_listening, 
                # Ron se mantiene activo para permitir seguimiento.
                print("✨ Interacción completada. Ron permanece atento.")
                return True

            if full_response:
                # Explicitly print Ron's voice for Electron interceptor
                # Serialize newlines
                safe_resp = full_response.replace('\n', '\\n')
                print(f"[RON_VOICE] {safe_resp}")
                # Memory is now handled by the API centrally to avoid duplicates and metadata noise
                # try: add_to_memory(current_username, user_text, full_response)
                # except: pass

                # 🔹 AUTO-DEACTIVATE: Si la respuesta del LLM sugiere despedida
                low_response = full_response.lower()
                farewell_phrases = [
                    "hasta luego", "nos vemos", "me mantendré inactivo", "estaré aquí cuando me necesites", 
                    "me desactivaré", "modo reposo", "si necesitas algo más", "estaré inactivo", "me quedo a la espera",
                    "que tengas un buen día", "adiós", "hasta pronto", "chau", "estoy a la espera", "en reposo"
                ]
                
                if any(phrase in low_response for phrase in farewell_phrases):
                    print(f"💤 Auto-desactivación por respuesta del LLM: '{full_response[:30]}...'")
                    activado = False
                    print(json.dumps({"type": "recording_state", "state": "inactive"}), flush=True)
                    return False
                
                # 🔹 NUEVO: Hibernación si la conversación se considera terminada (sin comandos ni prompts pendientes)
                # Si llegamos aquí y no hubo comandos de desactivación, pero tampoco hubo comandos de acción,
                # e incluimos un pequeño chequeo de "ayuda" o similar.
                if not commands_found and len(full_response) > 5:
                    # Si la respuesta es conclusiva, podemos optar por hibernar tras un pequeño delay
                    # o simplemente dejar que el timeout de 30s del loop principal actúe.
                    # Por ahora confiaremos en los keywords y el timeout de 30s.
                    pass

    except Exception as e:
        print(f"❌ Backend Error: {e}")
        # Try fallback on connection error too
        return _process_interaction_fallback(user_text, api_url, headers, user_to_send)

    return True

def _process_interaction_fallback(user_text, api_url, headers, user_to_send):
    """Fallback to non-streaming /ron endpoint if stream fails."""
    global last_ron_response
    print(f"📡 Fallback Solicitando: {user_text[:40]}...")
    try:
        now_str = get_internet_time()
        print(f"[Python] [Fallback] Enviando a /ron para {user_to_send}", flush=True)
        payload = {
            "text": f"[Contexto actual: {now_str}] {user_text}",
            "username": user_to_send,
            "source": "desktop",
            "return_json": True
        }
        r = requests.post(f"{api_url}/ron", json=payload, headers=headers, timeout=60)
        if r.status_code == 200:
            data = r.json()
            full_response = data.get("user_response") or data.get("ron") or ""
            if full_response:
                safe_resp = full_response.replace('\n', '\\n')
                print(f"[RON_VOICE] {safe_resp}")
                speak_async(full_response)
                last_ron_response = full_response
                
                cmds = data.get("commands", [])
                if cmds:
                    # Treat as safe commands and send to Electron
                    json_str = json.dumps({"type": "commands", "commands": cmds})
                    print(f"\n<<RON_CMD>>{json_str}<<END_CMD>>\n", flush=True)
                return True
        print(f"❌ Fallback API Error: {r.status_code}")
    except Exception as e:
        print(f"❌ Fallback Exception: {e}")
    
    speak_async("Error de conexión.")
    # Reset UI state on total failure
    print(json.dumps({"type": "recording_state", "state": "inactive"}), flush=True)
    return False

# =========================================================================================
# MAIN
# =========================================================================================
def detect_ron_activation(text):
    if not text: return False
    pattern = r'\b(' + '|'.join(re.escape(w) for w in ALLOWED_WAKE_WORDS) + r')\b'
    return bool(re.search(pattern, text, re.IGNORECASE))

if __name__ == "__main__":
    print(f"🟢 Ron 24/7 v2.0 (Violent Anti-Echo & Recording) Listo. User: {args.username}, MicIdx: {args.microphone_index}")
    task_manager = TaskManager(lambda t: speak_async(t))
    
    # Iniciar hardware de audio primero
    if not recognizer:
        recognizer, microphone = setup_streaming_recognition(device_index=args.microphone_index)
    
    # Luego el control externo
    handle_external_control()
    
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)
    
    # 🔹 Iniciar trabajador de voz
    TTSWorker().start()
    
    # Asegurar que el recorder thread esté listo para START_RECORDING inmediato
    ensure_recorder_thread()
    
    # 🔹 LIMPIEZA INICIAL: Borrar wavs viejos de sesiones previas
    try:
        temp_dir = os.path.join(os.getcwd(), 'temp')
        if os.path.exists(temp_dir):
            for f in os.listdir(temp_dir):
                if f.endswith(".wav"):
                    try: os.remove(os.path.join(temp_dir, f))
                    except: pass
            print(f"🧹 Carpeta temporal '{temp_dir}' purgada.")
    except: pass

    print("👂 Escuchando...")
    
    try:
        last_interaction = time.time()
        while True:
            try:
                # 🔹 Heartbeat / Timeout: Si pasan 30s sin nada, desactivar
                if activado and (time.time() - last_interaction > 30):
                    print("💤 Timeout: Ron vuelve a reposo.")
                    activado = False

                try: text, ts = audio_queue.get(timeout=0.1)
                except queue.Empty: continue

                norm_text = text.lower().strip()

                if not activado:
                    if detect_ron_activation(text):
                        print("✅ Palabra clave detectada!")
                        stop_speaking()
                        interruption_event.clear()
                        phrase = random.choice(activation_phrases)
                        print(f"[RON_VOICE] {phrase}")
                        speak_async(phrase)
                        
                        while speaking or not tts_queue.empty(): time.sleep(0.01)
                        drain_queue(audio_queue)
                        
                        activado = True 
                        last_interaction = time.time()
                else:
                    # SI ESTA ACTIVADO, CUALQUIER TEXTO ES UNA INTERACCION
                    print(f"[USER_VOICE] {text}", flush=True)
                    last_interaction = time.time()
                    
                    # 🔹 El filtro de despedida / hibernación se hace dentro de process_interaction
                    stay_active = process_interaction(text)
                    if not stay_active:
                        activado = False
                    
                    # Tras interactuar, limpiamos el audio pendiente de lo que Ron acaba de decir
                    while speaking or not tts_queue.empty(): time.sleep(0.01)
                    time.sleep(0.5) # Aumentado para seguridad de eco
                    drain_queue(audio_queue)
                    last_interaction = time.time()
            except KeyboardInterrupt: break
            except Exception as e: print(f"❌ Loop: {e}")
    finally:
        stop_listening(wait_for_stop=False)
