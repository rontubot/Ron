#!/usr/bin/env python3
"""
check_reminders.py
Script ejecutado por Electron para verificar recordatorios vencidos.
Imprime JSON con recordatorios que necesitan notificación.
"""

import sys
import json
from datetime import datetime

# Add parent directory to path to import core modules
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory import list_reminders, update_reminder

def check_due_reminders(username):
    """
    Verifica qué recordatorios han llegado a su fecha/hora programada.
    Retorna lista de recordatorios que necesitan notificación.
    """
    try:
        # Cargar recordatorios pendientes
        reminders = list_reminders(username, status="todo")
        now = datetime.now()
        
        due_reminders = []
        
        for rem in reminders:
            # Skip si no tiene fecha/hora
            if not rem.get("due_date") or not rem.get("due_time"):
                continue
            
            try:
                # Parse la fecha/hora del recordatorio
                due_dt_str = f"{rem['due_date']}T{rem['due_time']}"
                due_dt = datetime.fromisoformat(due_dt_str)
                
                # Si ya pasó la hora, agregar a la lista
                if now >= due_dt:
                    due_reminders.append({
                        "id": rem["id"],
                        "title": rem["title"],
                        "description": rem.get("description", ""),
                        "due_date": rem["due_date"],
                        "due_time": rem["due_time"]
                    })
                    
                    # Marcar como completado
                    update_reminder(username, rem["id"], status="done")
                    
            except (ValueError, TypeError) as e:
                # Si hay error parseando la fecha, skip
                continue
        
        return due_reminders
        
    except Exception as e:
        # En caso de error, retornar lista vacía
        sys.stderr.write(f"Error checking reminders: {str(e)}\n")
        return []


if __name__ == "__main__":
    # Obtener username de argumentos
    username = sys.argv[1] if len(sys.argv) > 1 else "default"
    
    # Verificar recordatorios
    due = check_due_reminders(username)
    
    # Imprimir JSON para que Electron lo lea
    print(json.dumps(due, ensure_ascii=False))
