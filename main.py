import speech_recognition as sr
import pyttsx3
import requests
import os
import re

# URL por defecto de la API de Ron (puedes cambiarla si usas local o desarrollo)
RON_API_URL = os.getenv("RON_API_URL", "https://ron-production.up.railway.app/ron")

# Configuración del motor de voz
engine = pyttsx3.init()
engine.setProperty('rate', 150)
voices = engine.getProperty('voices')
for v in voices:
    if 'spanish' in getattr(v, 'name', '').lower() or 'es' in getattr(v, 'id', '').lower():
        engine.setProperty('voice', v.id)
        break

def transcribe_speech():    
    recognizer = sr.Recognizer()    
    recognizer.pause_threshold = 2.0  # Aumentar a 2 segundos  
    recognizer.energy_threshold = 4000  # Aumentar threshold de energía  
    with sr.Microphone() as source:    
        print("🎤 Habla ahora...")    
        recognizer.adjust_for_ambient_noise(source, duration=2)  # Más tiempo de calibración  
        audio = recognizer.listen(source, phrase_time_limit=10, timeout=15)  # Más tiempo  
    try:  
        text = recognizer.recognize_google(audio, language="es")  
        print(f"🗣 Tú: {text}")  
        return text.lower()  
    except:  
        return ""

def detect_ron_activation(text):
    text_lower = text.lower().strip()
    return re.search(r'\bron\b', text_lower) is not None

def talk_to_ron(text):
    try:
        resp = requests.post(RON_API_URL, json={"text": text})
        if resp.ok:
            response_data = resp.json()
            ron = response_data.get("ron", "No entendí.")
            print(f"🤖 Ron: {ron}")
            engine.say(ron)
            engine.runAndWait()

            # 🔴 Si la API indica que se debe desconectar
            if response_data.get("shutdown") is True:
                return True
        else:
            print("❌ Error al contactar con Ron")
            engine.say("No puedo comunicarme con el servidor.")
            engine.runAndWait()
    except Exception as e:
        print(f"❌ {e}")
        engine.say("Ocurrió un error al intentar responderte.")
        engine.runAndWait()
    return False

# 🔁 Loop principal
if __name__ == "__main__":
    print("🟢 Di 'Ron' para activarme.")
    activado = False

    while True:
        texto = transcribe_speech()

        # Activación por palabra clave
        if not activado and detect_ron_activation(texto):
            activado = True
            print("✅ Ron activado")
            engine.say("Hola, ¿en qué puedo ayudarte?")
            engine.runAndWait()
            continue

        if activado and texto:
            should_shutdown = talk_to_ron(texto)
            if should_shutdown:
                activado = False
                print("🔴 Ron desconectado")
