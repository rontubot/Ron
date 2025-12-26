import pyttsx3
import re
import unicodedata
import os

_engine = None

def clean_text_for_tts(text: str) -> str:
    """Limpia el texto de símbolos, emojis y saltos de línea para un habla fluida."""
    # Eliminar saltos de línea y formateo markdown
    text = text.replace('\\n', ' ').replace('\n', ' ')
    text = re.sub(r'[*_`#]', '', text)
    # Eliminar emojis y caracteres no ASCII problemáticos
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿✂-➰Ⓜ-🉑🧀-🫿]+', '', text)
    return text.strip()

def _get_engine():
    global _engine
    if _engine is None:
        try:
            # En Windows, forzar el uso de SAPI5 para mayor estabilidad
            _engine = pyttsx3.init('sapi5') if os.name == 'nt' else pyttsx3.init()
            _engine.setProperty('rate', 195)
            _engine.setProperty('volume', 1.0)

            voices = _engine.getProperty('voices')
            # Buscar Helena o Sabina (Windows) o cualquier voz en español
            spanish_voice = next(
                (v.id for v in voices 
                 if any(n in v.name.lower() for n in ["mexico", "helena", "sabina", "spanish", "castellano", "español"])),
                None
            )
            if spanish_voice:
                _engine.setProperty('voice', spanish_voice)
            else:
                # Búsqueda secundaria por ID
                spanish_voice = next((v.id for v in voices if "es" in v.id.lower() or "es-es" in v.id.lower() or "es-mx" in v.id.lower()), None)
                if spanish_voice:
                    _engine.setProperty('voice', spanish_voice)
        except Exception as e:
            print(f"⚠️ Error inicializando pyttsx3: {e}")
            # Reintentar sin driver específico
            _engine = pyttsx3.init()

    return _engine

def speak(text: str):
    """Interfaz principal para hablar desde cualquier parte del sistema."""
    if not text: return
    try:
        engine = _get_engine()
        cleaned = clean_text_for_tts(text)
        print(f"🤖 Ron hablando: {cleaned[:50]}...")
        engine.say(cleaned)
        engine.runAndWait()
    except Exception as e:
        print(f"❌ Error en core.tts: {e}")
