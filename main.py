import speech_recognition as sr  
import pyttsx3  
import requests  
import os  
import re  
import threading  
import queue  
import time  
import random
  
# URL por defecto de la API de Ron  
RON_API_URL = os.getenv("RON_API_URL", "https://ron-production.up.railway.app/ron")  
  
# Configuración del motor de voz  
engine = pyttsx3.init()  
engine.setProperty('rate', 150)  
voices = engine.getProperty('voices')  
for v in voices:  
    if 'spanish' in getattr(v, 'name', '').lower() or 'es' in getattr(v, 'id', '').lower():  
        engine.setProperty('voice', v.id)  
        break  
  
# lista de frases de activacion
activation_phrases = [  
    "Hola",  
    "Sí?",   
    "Me llamaste?",  
    "Dime",  
    "¿En qué puedo ayudarte?",  
    "Aquí estoy",  
    "¿Qué necesitas?"  
]  

# Control de estado global  
speaking = False  
listening_active = True  
  
def setup_streaming_recognition():  
    """Configura el reconocimiento de voz para streaming"""  
    recognizer = sr.Recognizer()  
    recognizer.pause_threshold = 1.0  # Más sensible para streaming  
    recognizer.energy_threshold = 4000  
    recognizer.dynamic_energy_threshold = True  
      
    microphone = sr.Microphone()  
    with microphone as source:  
        recognizer.adjust_for_ambient_noise(source, duration=1)  
      
    return recognizer, microphone  
  
def stream_audio_recognition(recognizer, microphone, audio_queue):  
    """Función que corre en background capturando audio"""  
    def callback(recognizer, audio):  
        global speaking, listening_active  
          
        # Solo procesar si no estamos hablando y el listening está activo  
        if not speaking and listening_active:  
            try:  
                text = recognizer.recognize_google(audio, language="es")  
                if text.strip():  # Solo añadir si hay texto válido  
                    audio_queue.put(text.lower())  
            except sr.UnknownValueError:  
                pass  # Ignorar audio no reconocido  
            except sr.RequestError:  
                pass  # Ignorar errores de conexión  
      
    # Iniciar escucha en background  
    stop_listening = recognizer.listen_in_background(microphone, callback, phrase_time_limit=2)  
    return stop_listening
  
def detect_ron_activation(text):  
    text_lower = text.lower().strip()  
    return re.search(r'\b(ron|ro)\b', text_lower) is not None

def talk_to_ron(text):  
    global speaking, listening_active  
      
    # Pausar completamente el reconocimiento  
    speaking = True  
    listening_active = False  
      
    try:  
        resp = requests.post(RON_API_URL, json={"text": text})  
        if resp.ok:  
            response_data = resp.json()  
            ron = response_data.get("ron", "No entendí.")  
            print(f"🤖 Ron: {ron}")  
              
            engine.say(ron)  
            engine.runAndWait()  
              
            # Pausa adicional para asegurar que el audio termine  
            time.sleep(0.5)  
              
            if response_data.get("shutdown") is True:  
                return True  
        else:  
            print("❌ Error al contactar con Ron")  
            engine.say("No puedo comunicarme con el servidor.")  
            engine.runAndWait()  
            time.sleep(0.5)  
    except Exception as e:  
        print(f"❌ {e}")  
        engine.say("Ocurrió un error al intentar responderte.")  
        engine.runAndWait()  
        time.sleep(0.5)  
    finally:  
        # Reanudar reconocimiento después de hablar  
        speaking = False  
        listening_active = True  
      
    return False  
  
def safe_activation_response():  
    """Maneja la respuesta de activación de forma segura"""  
    global speaking, listening_active  
      
    speaking = True  
    listening_active = False  
      
    try:  
        engine.say("Hola, ¿en qué puedo ayudarte?")  
        engine.runAndWait()  
        time.sleep(0.5)  
    finally:  
        speaking = False  
        listening_active = True  
  
# Loop principal mejorado  
if __name__ == "__main__":  
    print("🟢 Di 'Ron' para activarme.")  
      
    # Configurar streaming  
    recognizer, microphone = setup_streaming_recognition()  
    audio_queue = queue.Queue()  
      
    # Iniciar captura de audio en background  
    stop_listening = stream_audio_recognition(recognizer, microphone, audio_queue)  
      
    activado = False  
      
    try:  
        while True:  
            try:  
                # Timeout más corto para mayor responsividad  
                texto = audio_queue.get(timeout=0.05)  
                print(f"🗣 Detectado: {texto}")  
                  
                # Activación por palabra clave  
                if not activado and detect_ron_activation(texto):  
                    activado = True  
                    print("✅ Ron activado")  
                    safe_activation_response()  
                    continue  
                  
                if activado and texto and listening_active:  
                    should_shutdown = talk_to_ron(texto)  
                    if should_shutdown:  
                        activado = False  
                        print("🔴 Ron desconectado")  
                          
            except queue.Empty:  
                continue  
                  
    except KeyboardInterrupt:  
        print("🔴 Cerrando Ron...")  
    finally:  
        listening_active = False  
        stop_listening(wait_for_stop=False)