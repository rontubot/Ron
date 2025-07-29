from core.recognizer import transcribe_audio_to_text, get_recent_transcripts, clear_recent_transcripts
from core.tts import speak
from core.assistant import generate_response
from core.memory import add_to_memory
from core import commands
import re
import os
from dotenv import load_dotenv

load_dotenv()
MODO = os.getenv("MODO", "personal")

FEATURES = {
    "personal": {
        "abrir_apps": True,
        "clima": True,
        "buscar_google": True,
        "youtube": True,
        "apagar_pc": True
    },
    "cliente": {
        "abrir_apps": False,
        "clima": False,
        "buscar_google": False,
        "youtube": False,
        "apagar_pc": False
    }
}

def procesar_comando(texto):
    text = texto.lower().strip()

    # --- Comandos protegidos por configuración ---
    if text.startswith("abre ") and FEATURES[MODO]["abrir_apps"]:
        return commands.open_application(text.replace("abre ", "").strip())

    if text.startswith("cierra ") and FEATURES[MODO]["abrir_apps"]:
        return commands.close_application(text.replace("cierra ", "").strip())

    if "clima en" in text and FEATURES[MODO]["clima"]:
        ciudad = text.split("clima en")[-1].strip()
        return commands.get_weather(ciudad)

    if text.startswith("investiga ") and FEATURES[MODO]["buscar_google"]:
        return commands.search_google(text.replace("investiga ", "").strip())

    if text.startswith("youtube ") and FEATURES[MODO]["youtube"]:
        return commands.search_youtube(text.replace("youtube ", "").strip())

    if "apaga la computadora" in text and FEATURES[MODO]["apagar_pc"]:
        return commands.shutdown()

    if "reinicia la computadora" in text and FEATURES[MODO]["apagar_pc"]:
        return commands.restart()

    if "suspende la computadora" in text and FEATURES[MODO]["apagar_pc"]:
        return commands.suspend()

    return None

def main():
    print(f"Ron iniciado en modo: {MODO.upper()}")
    print("Esperando activación con 'Ron'...")

    while True:
        text = transcribe_audio_to_text()

        if re.search(r"\bron\b", text, re.IGNORECASE):
            print("Ron activado.")
            if re.search(r"(o[ií]ste|escuchaste).*(ron)", text, re.IGNORECASE):
                contexto_prev = "Esto fue lo que se dijo antes:\n" + "\n".join(get_recent_transcripts())
                clear_recent_transcripts()
                speak("Sí, escuché. Déjame pensar un momento.")
                response = generate_response(contexto_prev)
                add_to_memory(contexto_prev, response)
                speak(response)
            else:
                speak("Hola, ¿en qué puedo ayudarte?")

            while True:
                text = transcribe_audio_to_text()
                if not text:
                    continue

                if "hasta luego" in text or "adiós" in text:
                    speak("Hasta luego.")
                    break

                print(f"Tú: {text}")
                comando = procesar_comando(text)
                if comando:
                    speak(comando)
                else:
                    respuesta = generate_response(text)
                    speak(respuesta)

if __name__ == "__main__":
    main()
