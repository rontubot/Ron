"""
Módulo para ejecutar comandos desde el móvil
"""
import json
import traceback
from core.assistant import parse_and_execute_commands_dynamic


def execute_commands_from_mobile(commands, username):
    """
    Ejecuta comandos cuando vienen del móvil
    
    Args:
        commands: Lista de comandos a ejecutar
        username: Usuario que envió el comando
        
    Returns:
        dict con resultados de ejecución
    """
    if not commands:
        return {"executed": 0, "errors": []}
    
    print(f"📱 Ejecutando {len(commands)} comandos desde móvil para {username}...")
    
    executed = 0
    errors = []
    
    for cmd in commands:
        if cmd.get("action"):
            try:
                # Ejecutar comando usando parse_and_execute_commands_dynamic
                result = parse_and_execute_commands_dynamic(
                    json.dumps({"commands": [cmd]}),
                    ctx={"username": username},
                    async_execute=False
                )
                print(f"✅ Comando ejecutado: {cmd.get('action')}")
                executed += 1
            except Exception as e:
                error_msg = f"Error ejecutando {cmd.get('action')}: {str(e)}"
                print(f"❌ {error_msg}")
                traceback.print_exc()
                errors.append(error_msg)
    
    return {
        "executed": executed,
        "errors": errors,
        "total": len(commands)
    }
