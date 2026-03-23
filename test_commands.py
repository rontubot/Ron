import sys
import os

# Ensure the core module can be imported
sys.path.insert(0, r"c:\Users\Luismishit\Pictures\RON\ron")

from core.commands import run_command

print("Testing RON Commands...\n")

ctx = {"username": os.environ.get("USERNAME", "TestUser")}

tests = [
    # File Operations
    {"action": "create_file", "params": {"file_path": r"c:\Users\Luismishit\Desktop\ron_test.txt", "content": "Hello World"}},
    {"action": "read_file", "params": {"file_path": r"c:\Users\Luismishit\Desktop\ron_test.txt"}},
    {"action": "create_folder", "params": {"folder_path": r"c:\Users\Luismishit\Desktop\ron_folder"}},
    {"action": "move_file", "params": {"source": r"c:\Users\Luismishit\Desktop\ron_test.txt", "destination": r"c:\Users\Luismishit\Desktop\ron_folder\ron_test.txt"}},
    {"action": "copy_file", "params": {"source": r"c:\Users\Luismishit\Desktop\ron_folder\ron_test.txt", "destination": r"c:\Users\Luismishit\Desktop\ron_test_copy.txt"}},
    {"action": "delete_file", "params": {"file_path": r"c:\Users\Luismishit\Desktop\ron_test_copy.txt"}},
    
    # Utilities
    {"action": "diagnose_system_performance", "params": {}},
    {"action": "get_weather", "params": {"city": "Madrid"}},
    {"action": "search_youtube", "params": {"query": "test", "play_video": False}},
    {"action": "search_google", "params": {"query": "test query"}},
    
    # We will test others carefully later to avoid accidentally shutting down PC
]

for t in tests:
    print(f"--- Running {t['action']} ---")
    try:
        res = run_command(t["action"], t.get("params", {}), ctx)
        print("Result:", res)
    except Exception as e:
        print("Exception:", e)
    print("\n")
