# Análisis Completo de Arquitectura: Proyecto "Ron"

Este documento contiene un análisis técnico detallado del asistente "Ron" para ser utilizado como referencia por un agente de desarrollo web.

## 1. Visión General del Proyecto
"Ron" es un asistente de IA híbrido (Local + Nube) diseñado para automatización de escritorio, interacción por voz y control del sistema. No es solo un chatbot; es un agente con capacidad de ejecución de comandos (PowerShell/CMD), gestión de archivos y memoria persistente.

### Arquitectura de Alto Nivel
El sistema opera bajo una arquitectura **Cliente-Servidor**, donde el "Cerebro" es una API de Python que puede correr localmente o en la nube, y existen múltiples "Cuerpos" (Clientes) que interactúan con él.

```mermaid
graph TD
    User((Usuario))
    
    subgraph "Clientes (Frontend)"
        Desktop[Escritorio: Electron + React]
        Mobile[Móvil: React Native / Expo]
        Launcher[Launcher: Vite + React]
    end
    
    subgraph "Cerebro (Backend / Core)"
        API[FastAPI Server (Python)]
        Planner[Motor de Autonomía]
        Memory[Memoria & Perfiles]
        Sys[Control de Sistema (psutil/cmds)]
    end
    
    subgraph "Integraciones Externas"
        OpenAI[OpenAI API (GPT-4o/mini)]
        GitHub[GitHub (Storage/Sync)]
    end

    User -->|Voz/Texto| Desktop
    User -->|Voz/Texto| Mobile
    Desktop -->|HTTP/WS| API
    Mobile -->|HTTP/WS| API
    Launcher -->|Ejecuta| Desktop
    
    API --> Planner
    API --> Memory
    API --> Sys
    API --> OpenAI
    Memory <--> GitHub
```

## 2. Stack Tecnológico Detallado

### A. Backend ("El Cerebro")
Ubicación: `rontubot/ron`
*   **Lenguaje**: Python 3.x
*   **Framework API**: `FastAPI` + `Uvicorn`
*   **IA/LLM**: `OpenAI API` (gpt-5-chat-latest / gpt-4o)
*   **Seguridad**: `PyJWT` (Tokens JWT), `bcrypt` (Hashing de contraseñas)
*   **Sistema**: `psutil` (Monitorización), `subprocess` (Ejecución de comandos PowerShell/CMD)
*   **Persistencia**: Sincronización de usuarios y memoria JSON contra repositorios de GitHub (como base de datos remota).

### B. Frontend Escritorio ("El Cuerpo Principal")
Ubicación: `rontubot/ron-web-app`
*   **Contenedor**: `Electron` (v27.0.0)
*   **Framework UI**: `React` (v18.2.0, Create React App)
*   **Estilos**: CSS Puro / Vanilla
*   **Visualización**: `Three.js` + `@react-three/fiber` (Esferas 3D reactivas al audio)
*   **Empaquetado**: `electron-builder` (Genera instaladores NSIS para Windows)
*   **Características Clave**:
    *   Embed de Python portable (corre el backend localmente).
    *   Gestión de actualizaciones automática (`electron-updater`).

### C. Frontend Móvil ("Control Remoto")
Ubicación: `rontubot/ron-web-app/ron-web-app/ron-mobile`
*   **Framework**: `React Native` + `Expo`
*   **Funcionalidad**: Walkie-Talkie, chat remoto, sincronización con backend en PC.

### D. Launcher ("El Gestor")
Ubicación: `rontubot/ron-web-app/ron-web-app/ron-launcher`
*   **Framework**: `React` + `Vite`
*   **Propósito**: Interfaz ligera para instalar, reparar o lanzar la aplicación principal.

## 3. Capacidades y Módulos Clave

### 1. Sistema de Memoria y Perfiles
*   **Gestión de Usuarios**: Soporte multi-usuario con login/registro.
*   **Memoria Persistente**: Guarda conversaciones, preferencias y recordatorios.
*   **Sincronización Cloud**: Usa GitHub como backend de almacenamiento para perfiles, permitiendo "roaming" de usuarios entre dispositivos.
*   **Instrucciones Personalizadas**: Los usuarios pueden definir cómo quieren que Ron se comporte (guardado en `UserMemory`).

### 2. Motor de Ejecución Autónoma (`core/autonomous.py`)
*   Capacidad para generar **Planes de Ejecución** complejos.
*   Desglose de tareas en pasos secuenciales (ej: "Limpia temporales y luego busca virus").
*   Validación de seguridad (`safe: true/false`) antes de ejecutar comandos de sistema.

### 3. Sistema de Comandos Dinámicos (`core/commands.py`)
Ron no solo responde texto, devuelve objetos JSON con acciones:
*   **Nativo**: `add_reminder`, `open_application`, `search_youtube`.
*   **Sistema**: Ejecución directa de scripts `Powershell` o `Python` para control total del OS (volumen, archivos, diagnósticos).

### 4. Interfaz de Voz y Audio
*   **TTS (Text-to-Speech)**: Sistema integrado para que Ron hable.
*   **STT (Speech-to-Text)**: Integración con Whisper (Faster-Whisper local mencionado en historial) y OpenAI.
*   **Visualizador**: La UI de Electron incluye un componente 3D que reacciona a la amplitud del audio en tiempo real.

## 4. Estructura de Archivos Relevante

### Backend (`ron/`)
*   `api.py`: Punto de entrada principal. Define rutas `/ron` (chat), `/auth` (login).
*   `core/`: Lógica de negocio.
    *   `assistant.py`: Construcción de prompts y manejo de contexto de OpenAI.
    *   `commands.py`: Biblioteca de funciones ejecutables.
    *   `memory.py`: CRUD de memoria y logs.
*   `requirements.txt`: Dependencias mínimas (`fastapi`, `openai`, `pydantic`).

### Frontend Desktop (`ron-web-app/`)
*   `public/electron.js`: Proceso principal de Electron. Maneja ventanas y ciclo de vida.
*   `src/`: Código fuente React.
*   `python-embed/`: Carpeta donde se aloja el intérprete de Python para distribución.

## 5. Puntos Clave para la Web de Marketing/Presentación
Si vas a crear una web para Ron, deberías destacar:
1.  **"Control Total"**: No es un chat web, es una app que controla tu PC.
2.  **"Memoria Real"**: Recuerda quién eres y qué hiciste ayer.
3.  **"Híbrido"**: Inteligencia de GPT-5/4o con ejecución local y privada.
4.  **"Ecosistema"**: App de escritorio + App móvil conectadas.
5.  **"Visual"**: Interfaz futurista con elementos 3D (React Three Fiber).
