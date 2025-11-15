import sys
import json
import io
import os
import traceback

# Aseguramos UTF-8 en stdout/stderr
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.commands import run_command  # tu función central


def main():
    """
    Bridge súper simple:
    - Lee JSON por stdin:
      {
        "username": "luis",
        "commands": [
          {"action": "add_reminder", "params": {...}},
          {"action": "get_reminders", "params": {...}}
        ]
      }

    - Ejecuta cada comando con run_command
    - Imprime SOLO un JSON en stdout al final: una lista de resultados
    """

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print("[]")
            return

        data = json.loads(raw)
    except Exception as e:
        # SIEMPRE devolvemos JSON, aunque haya error
        out = [{
            "action": None,
            "ok": False,
            "error": f"Error leyendo stdin: {e}"
        }]
        print(json.dumps(out, ensure_ascii=False))
        return

    commands = data.get("commands") or []
    username = data.get("username") or "default"

    # Callback para progreso -> SOLO stderr (no rompe el JSON)
    def progress_callback(msg: str):
        try:
            sys.stderr.write(str(msg) + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    ctx = {
        "username": username,
        "progress_callback": progress_callback,
    }

    results = []

    # 🔐 Redirigir prints de run_command a stderr para que no ensucien stdout
    real_stdout = sys.stdout

    class _StdoutToStderr(io.TextIOBase):
        def write(self, s):
            try:
                sys.stderr.write(str(s))
                return len(s)
            except Exception:
                return 0

        def flush(self):
            try:
                sys.stderr.flush()
            except Exception:
                pass

    try:
        sys.stdout = _StdoutToStderr()

        for item in commands:
            action = (item.get("action") or "").strip()
            params = item.get("params") or {}

            if not action:
                continue

            try:
                res = run_command(action, params, ctx) or {}
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                res = {
                    "ok": False,
                    "error": f"No se pudo ejecutar comando '{action}': {e}",
                }

            if not isinstance(res, dict):
                res = {
                    "ok": False,
                    "error": f"Resultado inesperado desde run_command: {res!r}",
                }

            # Forzar que siempre tengamos "action"
            res["action"] = action
            results.append(res)
    finally:
        # restaurar stdout real para imprimir el JSON limpio
        sys.stdout = real_stdout

    # IMPORTANTE: stdout SOLO lleva este JSON
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
