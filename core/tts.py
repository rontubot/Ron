import pyttsx3

# Inicializa el motor
engine = pyttsx3.init()
engine.setProperty('rate', 150)

# Configura voz en español si está disponible
voices = engine.getProperty('voices')
spanish_voice = next((v.id for v in voices if "spanish" in v.languages or "es" in v.id.lower()), None)
if spanish_voice:
    engine.setProperty('voice', spanish_voice)
else:
    print("⚠ No se encontró una voz en español. Usando la predeterminada.")

def speak(text):
    print(f"Ron: {text}")
    engine.say(text)
    engine.runAndWait()
