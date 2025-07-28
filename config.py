# config.py

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "15c30023b60c8e8cb03ebde003c3166a")

TV_IP = os.getenv("TV_IP", "192.168.1.45")

MEMORY_FILE = "data/ron_memory.json"
TOKEN_FILE = "data/samsung_token.json"
