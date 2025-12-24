# Ron Assistant - Cliente Local

Asistente de voz en español conectado a una API de OpenAI (vía Railway). Escucha tu voz, interpreta comandos y responde por voz.

## 🧠 ¿Qué puede hacer?

- Escuchar por comando de activación: **Ron**
- Responder usando voz con GPT-4 (vía API en Railway)
- Ejecutar comandos como:
  - `abre Google`
  - `cierra Chrome`
  - `investiga inteligencia artificial`
- Leer el clima, recordar cosas, conversar, etc.

### 5. UI Hygiene (Global)
- **Aggressive Sanitization**: The `[Contexto actual: ...]` prefix is now stripped not only from live messages but also from the conversation history (both User and Ron bubbles). Your history is now 100% clean.
- **Improved Filtering**: Enhanced the internal logic to remove any technical logs or system metadata that might appear in the chat.

### 6. Permanent Voice Fix
- **Subprocess TTS Worker**: Switched from a persistent voice thread to a subprocess-per-sentence model. This ensures the Windows voice engine (SAPI5) is reset for every phrase, preventing the " Ron speaks once and then blocks" issue permanently.
- **Base64 Encoding**: Text is now transmitted to the voice engine using base64, preventing special characters from breaking the speech flow.

### 7. STT Speed Optimization

## 📦 Requisitos

- Python 3.8 o superior
- Micrófono funcional

Instala dependencias:

```bash
pip install -r requirements.txt
