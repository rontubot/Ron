import pyttsx3
import re
import unicodedata

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
        _engine = pyttsx3.init()
        _engine.setProperty('rate', 190)
        _engine.setProperty('volume', 1.0)

        voices = _engine.getProperty('voices')
        # Buscar Helena o Sabina (Windows) o cualquier voz en español
        spanish_voice = next(
            (v.id for v in voices 
             if "mexico" in v.name.lower() or "helena" in v.name.lower() or "sabina" in v.name.lower() or "spanish" in v.name.lower()),
            None
        )
        if spanish_voice:
            _engine.setProperty('voice', spanish_voice)
        else:
            # Búsqueda secundaria por ID
            spanish_voice = next((v.id for v in voices if "es" in v.id.lower() or "spanish" in v.id.lower()), None)
            if spanish_voice:
                _engine.setProperty('voice', spanish_voice)

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
