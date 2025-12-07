import sys

# Read current date for the prompt
from datetime import datetime, timedelta
today = datetime.now()
tomorrow = today + timedelta(days=1)
today_str = today.strftime("%Y-%m-%d")
tomorrow_str = tomorrow.strftime("%Y-%m-%d")

# Read the file
with open('api.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the line with the old reminder example
old_example = '{\"user_response\":\"Voy a recordarte llamar a mamá a las ocho de la noche\",\"commands\":[{\"action\":\"add_reminder\",\"params\":{\"activity\":\"llamar a mamá\",\"due_time\":\"20:00\"},\"safe\":true}]}'

new_example = f'{{"user_response":"Voy a recordarte llamar a mamá a las ocho de la noche","commands":[{{"action":"add_reminder","params":{{"activity":"llamar a mamá","due_date":"{today_str}","due_time":"20:00"}},"safe":true}}]}}'

# Replace
content = content.replace(old_example, new_example)

# Now add the reminder rules section before "REGLAS OBLIGATORIAS"
marker = 'REGLAS OBLIGATORIAS PARA \'user_response\':'

reminder_rules = f'''⚠️ REGLA CRÍTICA PARA RECORDATORIOS (add_reminder):
- SIEMPRE extrae fecha y hora del texto del usuario
- Usa la FECHA DE HOY como referencia: {today_str} (para calcular "mañana", "próximo sábado", etc.)
- Parámetros OBLIGATORIOS para add_reminder:
  * "title" o "activity": texto del recordatorio
  * "due_date": formato "YYYY-MM-DD" (ej: "{tomorrow_str}" para mañana)
  * "due_time": formato "HH:MM" en 24h (ej: "15:00" para 3pm, "09:00" para 9am)

- Ejemplos de parsing:
  * "mañana a las 3pm" → due_date="{tomorrow_str}", due_time="15:00"
  * "hoy 5pm" → due_date="{today_str}", due_time="17:00"
  * "el lunes 10am" → calcular próximo lunes, due_time="10:00"  
  * "en 2 horas" → calcular desde ahora
  * "18 de diciembre 9am" → due_date="2025-12-18", due_time="09:00"
  
- Si NO se menciona hora, usa "09:00" por defecto
- Si NO se menciona fecha, usa HOY ({today_str})
- NUNCA dejes due_date o due_time vacíos

'''

content = content.replace(marker, reminder_rules + marker)

# Write back
with open('api.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("System prompt updated successfully")
print(f"Today: {today_str}")
print(f"Tomorrow: {tomorrow_str}")
