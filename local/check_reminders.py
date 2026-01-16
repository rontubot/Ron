#!/usr/bin/env python3
"""
check_reminders.py
Script ejecutado por Electron para verificar recordatorios vencidos.
Imprime JSON con recordatorios que necesitan notificación.
"""

import sys
import json
from datetime import datetime

# Add search paths for core modules
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Check where 'core' is located
if os.path.exists(os.path.join(current_dir, 'core')):
    # Production: check_reminders.py is valid sibling of core/
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
elif os.path.exists(os.path.join(parent_dir, 'core')):
    # Development: local/check_reminders.py waiting for ../core
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

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
        
        due_now = [] # Real-time alerts (missed by less than 1 hour)
        overdue_old = [] # Background notifications (missed by more than 1 hour)
        
        for rem in reminders:
            if not rem.get("due_date") or not rem.get("due_time"):
                continue
            
            try:
                due_dt_str = f"{rem['due_date']}T{rem['due_time']}"
                due_dt = datetime.fromisoformat(due_dt_str)
                
                if now >= due_dt:
                    from datetime import timedelta
                    diff = now - due_dt
                    
                    item = {
                        "id": rem["id"],
                        "title": rem["title"],
                        "description": rem.get("description", ""),
                        "due_date": rem["due_date"],
                        "due_time": rem["due_time"],
                        "missed_by_hours": int(diff.total_seconds() // 3600)
                    }
                    
                    # Si tiene más de 5 minutos de retraso, lo consideramos "vencido por ausencia"
                    if diff > timedelta(minutes=5):
                        overdue_old.append(item)
                    else:
                        due_now.append(item)
                    
                    # Marcar como completado (o 'notified') para que no se repita
                    update_reminder(username, rem["id"], status="done")
                    
            except (ValueError, TypeError):
                continue
        
        return {
            "due_now": due_now,
            "overdue_old": overdue_old
        }
        
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
