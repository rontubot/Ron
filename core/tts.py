import pyttsx3

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty('rate', 185)
        _engine.setProperty('volume', 1.0)

        voices = _engine.getProperty('voices')
        spanish_voice = next(
            (v.id for v in voices
             if ("spanish" in getattr(v, "languages", []) or "es" in v.id.lower())),
            None
        )
        if spanish_voice:
            _engine.setProperty('voice', spanish_voice)
        else:
            print("⚠ No se encontró una voz en español. Usando la predeterminada.")

    return _engine


def speak(text: str):
    engine = _get_engine()
    # logs tipo los que ves en consola
    before_vol = engine.getProperty('volume')
    before_rate = engine.getProperty('rate')
    print(f"[TTS] Antes -> volume={before_vol}, rate={before_rate}")
    print(f"🤖 Ron: {text}")

    engine.say(text)
    engine.runAndWait()

    after_vol = engine.getProperty('volume')
    after_rate = engine.getProperty('rate')
    print(f"[TTS] Después -> volume={after_vol}, rate={after_rate}")
    print("Ron: ✅ TTS OK")
