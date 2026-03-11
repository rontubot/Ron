import sys
import os
import json

# Add ron directory to path
sys.path.append(r'c:\Users\Luismishit\Pictures\RON\ron')

from core.memory import archive_expired_reminders, _load_reminders, _reminders_file

username = "default"
print(f"Checking for user: {username}")
items = _load_reminders(username)
print(f"Loaded {len(items)} reminders")

for r in items:
    print(f"Task: {r.get('title')} | Status: {r.get('status')} | Due: {r.get('due_date')} {r.get('due_time')}")

count = archive_expired_reminders(username)
print(f"\nArchived {count} reminders")
