import speech_recognition as sr
import pyttsx3
import requests
import json
import re
import subprocess
import os
import webbrowser

# URL de tu API de Ron en Railway
RON_API_URL = "https://ron-production.up.railway.app/ron"

# Inicializar motor de texto a voz
engine = pyttsx3.init()
engine.setProperty('rate', 150)

# Configurar voz en español (si está disponible)
voices = engine.getProperty('voices')
for voice in voices:
    if 'spanish' in voice.name.lower() or 'es' in voice.id.lower():
        engine.setProperty('voice', voice.id)
        break

# Abrir apps locales
web_apps = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://www.twitter.com",
    "tiktok": "https://www.tiktok.com",
    "whatsapp": "https://web.whatsapp.com",
    "linkedin": "https://www.linkedin.com"
}

def ejecutar_comando_local(text):
    if text.startswith("abre "):
        app = text.replace("abre ", "").strip()
        if app in web_apps:
            webbrowser.open(web_apps[app])
            return f"Abriendo {app} en el navegador."
        try:
            subprocess.Popen(f'start {app}', shell=True)
            return f"Intentando abrir {app}."
        except Exception as e:
            return f"No pude abrir {app}: {e}"

    if text.startswith("cierra "):
        app = text.replace("cierra ", "").strip()
        try:
            proceso = app + ".exe"
            subprocess.run(f'taskkill /F /IM {proceso}', shell=True)
            return f"Cerrando {app}."
        except Exception as e:
            return f"Error al cerrar {app}: {e}"

    if text.startswith("investiga "):
        query = text.replace("investiga ", "").strip()
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Investigando en Google: {query}"

    return None

# Reconocer voz y convertir a texto
def transcribe_speech():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("🎤 Habla ahora...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language="es")
        print(f"🗣️ Tú: {text}")
        return text
    except sr.UnknownValueError:
        print("⚠️ No entendí lo que dijiste.")
        return ""
    except sr.RequestError:
        print("❌ Error con el servicio de reconocimiento de voz.")
        return ""

# Enviar texto a Ron y obtener respuesta
def talk_to_ron(text):
    local = ejecutar_comando_local(text)
    if local:
        print(f"⚙️ Acción local: {local}")
        engine.say(local)
        engine.runAndWait()
        return

    try:
        response = requests.post(RON_API_URL,
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"text": text}))
        if response.status_code == 200:
            ron_reply = response.json()["ron"]
            print(f"🤖 Ron: {ron_reply}")
            engine.say(ron_reply)
            engine.runAndWait()
        else:
            print("❌ Error al contactar con Ron")
    except Exception as e:
        print(f"❌ Error: {e}")

# Loop principal
if __name__ == "__main__":
    print("🟢 Ron está en modo escucha. Di 'Ron' para activarlo.")
    activado = False
    while True:
        texto = transcribe_speech()
        if not texto:
            continue

        if not activado:
            if re.search(r"\bron\b", texto, re.IGNORECASE):
                activado = True
                print("✅ Ron activado. Puedes hablarle.")
                engine.say("Hola, ¿en qué puedo ayudarte?")
                engine.runAndWait()
            continue

        if texto.lower() in ["hasta luego", "adiós"]:
            print("👋 Ron quedó en espera. Di 'Ron' para activarlo de nuevo.")
            engine.say("Hasta luego")
            engine.runAndWait()
            activado = False
            continue

        talk_to_ron(texto)
