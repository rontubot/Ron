"""  
core/autonomous.py  
Sistema autónomo de investigación y ejecución de comandos de Windows  
"""  
import json  
import re  
import subprocess  
import time  
from datetime import datetime  
from typing import Dict, List, Optional, Any  

import os

# 🔹 Hacer el cliente OpenAI lazy-loaded para que Ron 24/7 pueda iniciar sin API key
# Solo se crea cuando realmente se necesita para features autónomas
_openai_client = None

def _get_openai_client():
    """Obtiene el cliente OpenAI, creándolo solo cuando se necesita"""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY no configurada - features autónomas deshabilitadas")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client
  
  
def research_system_commands(task_description: str, username: str) -> Optional[Dict]:
    """Investiga qué comandos del sistema son necesarios para cualquier tarea usando OpenAI directo."""
    research_prompt = f"""
El usuario quiere: {task_description}

Como experto en Windows, determina los comandos exactos necesarios.

Responde SOLO con JSON válido (sin backticks):
{{
    "task_analysis": "descripción de qué harás",
    "commands": [
        {{"type": "cmd|powershell|python", "command": "comando_exacto", "description": "qué hace", "safe": true}}
    ]
}}

Comandos disponibles:
- Volumen: nircmd setsysvolume [0-65535]
- Archivos: copy, move, del, mkdir, echo "texto" > archivo.txt
- Aplicaciones: start "app", taskkill /f /im "proceso.exe"
- Sistema: shutdown /s /t 0, ipconfig /flushdns
- PowerShell: Set-Volume, New-Item, Get-Process, etc.
- Python: cualquier script Python válido

IMPORTANTE:
- Solo comandos seguros (safe: true)
- Comandos reales que funcionen en Windows
- Si no sabes cómo hacer algo, marca safe: false
"""

    try:
        client = _get_openai_client()  # Lazy load del cliente OpenAI
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Actúas como un experto en administración de Windows y solo respondes JSON.",
                },
                {"role": "user", "content": research_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=800,
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)

        if parsed and parsed.get("commands"):
            # Validar seguridad de cada comando
            safe_commands = []
            for cmd in parsed["commands"]:
                is_safe, reason = validate_command_safety(
                    cmd.get("command", ""), cmd.get("type", "cmd")
                )
                if is_safe or cmd.get("safe", False):
                    safe_commands.append(cmd)
                else:
                    print(f"⚠️ Comando rechazado por seguridad: {cmd.get('command')} - {reason}")

            if safe_commands:
                parsed["commands"] = safe_commands
                return parsed

        return None
    except Exception as e:
        print(f"❌ Error en investigación: {e}")
        return None

  
  
def parse_research_response(response: Any) -> Optional[Dict]:  
    """Parser robusto que puede extraer comandos de cualquier tipo de respuesta"""  
    if not response:  
        return None  
  
    try:  
        # Aceptar dict directamente  
        if isinstance(response, dict):  
            return response  
  
        # Normalizar a str  
        if isinstance(response, (bytes, bytearray)):  
            response = response.decode("utf-8", "replace")  
  
        text = response.strip()  
  
        # Intentar parsing directo del JSON  
        if text.startswith("{") and text.endswith("}"):  
            try:  
                return json.loads(text)  
            except Exception:  
                pass  # seguimos con las regex  
  
        # Buscar JSON embebido en la respuesta  
        json_patterns = [  
            r'\{[^{}]*"commands"[^{}]*\[[^\]]*\][^{}]*\}',  
            r'\{.*?"task_analysis".*?\}',  
            r'\{.*?"commands".*?\}',  
        ]  
  
        for pattern in json_patterns:  
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)  
            if m:  
                try:  
                    return json.loads(m.group(0))  
                except Exception:  
                    continue  
  
        # Parser de emergencia: extraer comandos de texto libre  
        commands = []  
        for raw_line in text.splitlines():  
            line = raw_line.strip()  
            lowered = line.lower()  
  
            # Detectar comandos comunes  
            if any(cmd in lowered for cmd in [  
                'nircmd', 'reg add', 'taskkill', 'move ', 'copy ', 'mkdir',  
                'echo ', 'powershell', 'wmic', 'sc ', 'netsh'  
            ]):  
                # Extraer el comando  
                if ':' in line:  
                    cmd_part = line.split(':', 1)[1].strip()  
                else:  
                    cmd_part = line  
  
                # Determinar tipo  
                cmd_type = "powershell" if (  
                    'powershell' in lowered or  
                    any(ps in lowered for ps in [' set-', ' get-', ' new-'])  
                ) else "cmd"  
  
                commands.append({  
                    "type": cmd_type,  
                    "command": cmd_part.strip("`\"\\'"),  
                    "description": f"comando extraído: {cmd_part[:50]}...",  
                    "safe": True  
                })  
  
        if commands:  
            return {  
                "task_analysis": f"Comandos extraídos para: {text[:100]}...",  
                "commands": commands,  
                "prerequisites": [],  
                "estimated_time": 10,  
                "risk_level": "medium"  
            }  
  
        return None  
  
    except Exception as e:  
        print(f"❌ Error parseando respuesta: {e}")  
        return None  
  
  
def autonomous_command_execution(user_request: str, username: str) -> Dict:  
    """Sistema completamente autónomo que puede ejecutar CUALQUIER comando de Windows"""  
    print(f"🔍 Detectada solicitud que requiere investigación autónoma...")  
      
    # 1. Buscar en base de aprendizaje primero  
    learned_commands = search_learned_commands(user_request)  
    if learned_commands:  
        print("📚 Usando comandos de base de aprendizaje")  
        execution_plan = {  
            "task": user_request,  
            "steps": [{"command": cmd["command"], "type": cmd["type"], "description": cmd["description"]}  
                     for cmd in learned_commands],  
            "source": "learned"  
        }  
    else:  
        print("📚 Base de aprendizaje no tiene esta tarea, investigando...")  
          
        # 2. Investigación autónoma  
        research_results = research_system_commands(user_request, username)  
        if not research_results:  
            return {"success": False, "summary": "No pude investigar cómo realizar esta tarea"}  
          
        # 3. Crear plan de ejecución  
        execution_plan = create_execution_plan(research_results)  
        if not execution_plan:  
            return {"success": False, "summary": "No pude crear un plan de ejecución"}  
      
    # 4. Ejecutar plan  
    print(f"🚀 Ejecutando plan: {execution_plan.get('task', 'tarea')}")  
    execution_results = execute_autonomous_plan(execution_plan, username)  
      
    # 5. Si fue exitoso, guardar en base de aprendizaje  
    if execution_results.get("success") and execution_plan.get("source") != "learned":  
        save_successful_command(user_request, execution_plan["steps"], username)  
      
    return execution_results  
  
  
def save_successful_command(task_description: str, commands: List[Dict], username: str) -> bool:  
    """Guarda comandos exitosos en base de datos de aprendizaje"""  
    try:  
        learned_commands_file = "learned_commands.json"  
          
        # Cargar comandos existentes  
        try:  
            with open(learned_commands_file, 'r', encoding='utf-8') as f:  
                learned_data = json.load(f)  
        except:  
            learned_data = {"commands": [], "contributors": {}}  
          
        # Agregar nuevo comando exitoso  
        new_entry = {  
            "task": task_description.lower(),  
            "commands": commands,  
            "success_count": 1,  
            "contributor": username,  
            "timestamp": time.time(),  
            "keywords": task_description.lower().split()  
        }  
          
        # Buscar si ya existe  
        existing = None  
        for i, cmd in enumerate(learned_data["commands"]):  
            if cmd["task"] == new_entry["task"]:  
                existing = i  
                break  
          
        if existing is not None:  
            learned_data["commands"][existing]["success_count"] += 1  
            learned_data["commands"][existing]["timestamp"] = time.time()  
        else:  
            learned_data["commands"].append(new_entry)  
          
        # Actualizar estadísticas de contribuidores  
        if username not in learned_data["contributors"]:  
            learned_data["contributors"][username] = 0  
        learned_data["contributors"][username] += 1  
          
        # Guardar  
        with open(learned_commands_file, 'w', encoding='utf-8') as f:  
            json.dump(learned_data, f, ensure_ascii=False, indent=2)  
          
        print(f"📚 Comando guardado en base de aprendizaje por {username}")  
        return True  
          
    except Exception as e:  
        print(f"❌ Error guardando comando: {e}")  
        return False  
  
  
def search_learned_commands(task_description: str) -> Optional[List[Dict]]:  
    """Busca comandos aprendidos previamente para tareas similares"""  
    try:  
        learned_commands_file = "learned_commands.json"  
          
        with open(learned_commands_file, 'r', encoding='utf-8') as f:  
            learned_data = json.load(f)  
          
        task_lower = task_description.lower()  
        task_words = set(task_lower.split())  
          
        # Buscar coincidencias exactas primero  
        for cmd in learned_data["commands"]:  
            if cmd["task"] == task_lower:  
                print(f"📚 Comando encontrado en base de aprendizaje (exacto)")  
                return cmd["commands"]  
          
        # Buscar coincidencias por palabras clave  
        best_match = None  
        best_score = 0  
          
        for cmd in learned_data["commands"]:  
            cmd_words = set(cmd["keywords"])  
            intersection = task_words.intersection(cmd_words)  
            score = len(intersection) / len(task_words.union(cmd_words))  
              
            if score > 0.5 and score > best_score:  
                best_match = cmd  
                best_score = score  
          
        if best_match:  
            print(f"📚 Comando similar encontrado en base de aprendizaje (score: {best_score:.2f})")  
            return best_match["commands"]  
          
        return None  
          
    except Exception as e:  
        print(f"❌ Error buscando comandos aprendidos: {e}")  
        return None


def create_execution_plan(research_results: Dict) -> Optional[Dict]:  
    """Crea un plan de ejecución estructurado basado en la investigación"""  
    if not research_results or not research_results.get("commands"):  
        print("❌ No hay comandos válidos para crear plan")  
        return None  
      
    execution_plan = {  
        "task": research_results.get("task_analysis", "Tarea no especificada"),  
        "steps": [],  
        "estimated_time": 5,  
        "requires_confirmation": False  
    }  
      
    for i, cmd in enumerate(research_results["commands"]):  
        if cmd.get("safe", False):  # Solo comandos marcados como seguros  
            step = {  
                "order": i + 1,  
                "command": cmd["command"],  
                "type": cmd["type"],  
                "description": cmd["description"],  
                "timeout": 30  
            }  
            execution_plan["steps"].append(step)  
      
    if not execution_plan["steps"]:  
        print("❌ No hay pasos seguros para ejecutar")  
        return None  
      
    print(f"✅ Plan creado con {len(execution_plan['steps'])} pasos")  
    return execution_plan  
  
  
def validate_command_safety(command: str, command_type: str) -> tuple:  
    """Valida si un comando es seguro para ejecutar - versión más permisiva"""  
    if not command:  
        return False, "Comando vacío"  
      
    # Comandos absolutamente prohibidos  
    dangerous_patterns = [  
        r'format\s+[c-z]:', r'del\s+/s\s+/q', r'rmdir\s+/s\s+/q',  
        r'reg\s+delete.*HKEY_LOCAL_MACHINE', r'sc\s+delete\s+\w+',  
        r'diskpart', r'fdisk', r'bcdedit', r'bootrec',  
        r'net\s+user.*\s+/delete', r'net\s+localgroup.*administrators.*\s+/delete'  
    ]  
      
    for pattern in dangerous_patterns:  
        if re.search(pattern, command, re.IGNORECASE):  
            return False, f"Comando peligroso detectado: {pattern}"  
      
    # Comandos explícitamente seguros  
    safe_patterns = [  
        r'nircmd\s+', r'echo\s+.*>\s*[^\\/:*?"<>|]+',  
        r'copy\s+', r'move\s+', r'mkdir\s+', r'dir\s*',  
        r'tasklist', r'ipconfig\s+/flushdns', r'ping\s+',  
        r'Set-Volume', r'Get-Process', r'New-Item.*-ItemType\s+File',  
        r'start\s+"[^"]*"', r'python\s+-c\s+"[^"]*"'  
    ]  
      
    for pattern in safe_patterns:  
        if re.search(pattern, command, re.IGNORECASE):  
            return True, "Comando verificado como seguro"  
      
    # Para comandos no reconocidos, permitir si son simples  
    if len(command.split()) <= 5 and not any(char in command for char in ['&', '|', ';', '>', '<']):  
        return True, "Comando simple - permitido"  
      
    return False, "Comando complejo - requiere verificación manual"  
  
  
def execute_autonomous_plan(execution_plan: Dict, username: str) -> Dict:  
    """Ejecuta el plan de comandos de forma autónoma con feedback"""  
    if not execution_plan or not execution_plan.get("steps"):  
        return {"success": False, "summary": "No hay plan de ejecución válido"}  
      
    results = {  
        "success": True,  
        "executed_commands": [],  
        "failed_commands": [],  
        "summary": ""  
    }  
      
    print(f"🔧 Iniciando ejecución autónoma: {execution_plan.get('task', 'tarea')}")  
      
    for step in execution_plan["steps"]:  
        step_result = execute_single_command(step, username)  
          
        if step_result["success"]:  
            results["executed_commands"].append({  
                "step": step.get("order", 0),  
                "description": step.get("description", ""),  
                "output": step_result.get("output", "")  
            })  
            print(f"✅ Paso {step.get('order', 0)}: {step.get('description', '')}")  
        else:  
            results["failed_commands"].append({  
                "step": step.get("order", 0),  
                "description": step.get("description", ""),  
                "error": step_result.get("error", "")  
            })  
            print(f"❌ Paso {step.get('order', 0)} falló: {step_result.get('error', '')}")  
            results["success"] = False  
      
    # Generar resumen  
    if results["success"]:  
        results["summary"] = f"Tarea completada exitosamente. Ejecuté {len(results['executed_commands'])} comandos."  
    else:  
        results["summary"] = f"Tarea parcialmente completada. {len(results['executed_commands'])} exitosos, {len(results['failed_commands'])} fallaron."  
      
    return results  
  
  
def execute_single_command(command_info: Dict, username: str) -> Dict:  
    """Ejecuta un comando individual - soporta cmd, powershell y python"""  
    command = command_info.get("command", "")  
    cmd_type = command_info.get("type", "cmd")  
    timeout = command_info.get("timeout", 30)  
      
    if not command:  
        return {"success": False, "error": "Comando vacío"}  
      
    print(f"🔧 Ejecutando ({cmd_type}): {command}")  
      
    try:  
        if cmd_type == "powershell":  
            full_command = ["powershell", "-Command", command]  
        elif cmd_type == "python":  
            full_command = ["python", "-c", command]  
        elif cmd_type == "cmd":  
            full_command = ["cmd", "/c", command]  
        else:  
            # Comando directo  
            full_command = command.split()  
          
        # Ejecutar con timeout  
        result = subprocess.run(  
            full_command,  
            capture_output=True,  
            text=True,  
            timeout=timeout,  
            shell=False  
        )  
          
        if result.returncode == 0:  
            output = result.stdout.strip() if result.stdout else "Comando ejecutado exitosamente"  
            print(f"✅ Éxito: {output[:100]}")  
            return {  
                "success": True,  
                "output": output,  
                "command": command  
            }  
        else:  
            error = result.stderr.strip() if result.stderr else f"Error código {result.returncode}"  
            print(f"❌ Error: {error[:100]}")  
            return {  
                "success": False,  
                "error": error,  
                "command": command  
            }  
      
    except subprocess.TimeoutExpired:  
        print(f"⏰ Timeout ejecutando comando: {command}")  
        return {  
            "success": False,  
            "error": f"Comando tardó más de {timeout}s en ejecutarse",  
            "command": command  
        }  
    except Exception as e:  
        print(f"❌ Excepción ejecutando comando: {e}")  
        return {  
            "success": False,  
            "error": str(e),  
            "command": command  
        }  
  
  
def requires_autonomous_execution(text: str) -> bool:  
    """Determina si una solicitud requiere comandos que no están en el sistema básico"""  
    complex_keywords = [  
        "instalar programa", "desinstalar programa", "configurar red",  
        "cambiar configuración avanzada", "reparar registro", "modificar servicios",  
        "script personalizado", "automatización compleja", "limpia archivos",  
        "reinicia servicio", "configura firewall", "optimiza sistema"  
    ]  
      
    text_lower = text.lower()  
    return any(keyword in text_lower for keyword in complex_keywords)