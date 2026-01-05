# core/profile.py
from datetime import datetime, timedelta
import math

DEFAULT_PREFS = {
    "language": "es",
    "tone": "directo, técnico, con ejemplos",
    "formats": ["paso-a-paso","snippet","patch"],
}

def now_iso():
    return datetime.utcnow().isoformat()

def get_or_init_profile(mem: dict) -> dict:
    prof = mem.get("profile") or {}
    prof.setdefault("enabled", True)
    prof.setdefault("message_count", 0)
    prof.setdefault("updated_at", now_iso())
    prof.setdefault("recent_window", [])
    prof.setdefault("tags", {})
    prof.setdefault("traits", {})
    prof.setdefault("interests", {})
    prof.setdefault("preferences", DEFAULT_PREFS.copy())
    prof.setdefault("dos", [])
    prof.setdefault("donts", [])
    prof.setdefault("facts", [])       # items con ttl ({"key","value","expires_at"})
    prof.setdefault("last_labels", [])
    prof.setdefault("history", [])     # log de operaciones
    prof.setdefault("custom_instructions", "") # 🔹 NUEVO: Instrucciones manuales del usuario
    mem["profile"] = prof
    return prof

def append_to_profile_window(prof: dict, user_text: str, maxlen: int = 20):
    win = prof["recent_window"]
    win.append(user_text)
    if len(win) > maxlen:
        win.pop(0)

def decay_all(d: dict, decay: float = 0.98, floor: float = 0.01):
    for k in list(d.keys()):
        d[k] *= decay
        if d[k] < floor:
            d.pop(k, None)

def decay_and_add(d: dict, key: str, inc: float = 1.0, decay: float = 0.98):
    decay_all(d, decay=decay)
    d[key] = d.get(key, 0.0) + inc

def ema_trait(traits: dict, name: str, alpha: float = 0.15):
    name = name.strip().lower()
    traits[name] = (1 - alpha) * traits.get(name, 0.0) + alpha

def add_history(prof: dict, entry: dict):
    entry["ts"] = now_iso()
    prof["history"].append(entry)
    if len(prof["history"]) > 2000:
        prof["history"] = prof["history"][-1000:]

def purge_expired_facts(prof: dict):
    now = datetime.utcnow()
    prof["facts"] = [f for f in prof["facts"] if datetime.fromisoformat(f["expires_at"]) > now]

def add_fact(prof: dict, key: str, value, ttl_seconds: int):
    exp = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    prof["facts"].append({"key": key, "value": value, "expires_at": exp.isoformat()})

def build_persona(prof: dict) -> str:
    prefs = prof.get("preferences", {})
    tags = prof.get("tags", {})
    interests = prof.get("interests", {})
    traits = prof.get("traits", {})
    dos = prof.get("dos", [])
    donts = prof.get("donts", [])
    last_labels = prof.get("last_labels", [])
    custom_instructions = prof.get("custom_instructions", "").strip()

    top_tags = ", ".join(sorted(tags, key=tags.get, reverse=True)[:3])
    top_interests = ", ".join(sorted(interests, key=interests.get, reverse=True)[:4])
    top_traits = ", ".join(sorted(traits, key=traits.get, reverse=True)[:2])

    base_persona = (
        "[Perfil del usuario]\n"
        f"- Idioma preferido: {prefs.get('language','es')}\n"
        f"- Tono preferido: {prefs.get('tone','directo')}\n"
        f"- Formatos preferidos: {', '.join(prefs.get('formats',[]))}\n"
        f"- Intereses recientes: {top_interests}\n"
        f"- Rasgos inferidos: {top_traits}\n"
        f"- Últimas etiquetas: {', '.join(last_labels)}\n"
        f"- DO: {', '.join(dos)}\n"
        f"- DON'T: {', '.join(donts)}\n"
        "Usa este perfil para ajustar estilo y contenido. "
        "Si hay conflicto con la petición actual, prioriza la petición."
    )

    if custom_instructions:
        base_persona += f"\n\n🚨 INSTRUCCIONES PERSONALIZADAS DEL USUARIO (PRIORIDAD MÁXIMA):\n{custom_instructions}"

    return base_persona
