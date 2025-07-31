import os  
import json  
import hashlib  
import getpass  
from core.memory import save_memory, load_memory  
  
# Base de datos simple de usuarios (en producción usar una DB real)  
USERS_FILE = "users.json"  
  
def hash_password(password):  
    """Genera hash seguro de la contraseña"""  
    return hashlib.sha256(password.encode()).hexdigest()  
  
def load_users():  
    """Carga la base de datos de usuarios"""  
    if os.path.exists(USERS_FILE):  
        with open(USERS_FILE, 'r') as f:  
            return json.load(f)  
    return {}  
  
def save_users(users):  
    """Guarda la base de datos de usuarios"""  
    with open(USERS_FILE, 'w') as f:  
        json.dump(users, indent=4)  
  
def register_user(username, password, full_name):  
    """Registra un nuevo usuario"""  
    users = load_users()  
    if username in users:  
        return False, "Usuario ya existe"  
      
    users[username] = {  
        "password_hash": hash_password(password),  
        "full_name": full_name,  
        "created_at": datetime.now().isoformat()  
    }  
    save_users(users)  
    return True, "Usuario registrado exitosamente"  
  
def authenticate_user(username, password):  
    """Autentica un usuario"""  
    users = load_users()  
    if username not in users:  
        return False, "Usuario no encontrado"  
      
    if users[username]["password_hash"] != hash_password(password):  
        return False, "Contraseña incorrecta"  
      
    return True, users[username]  
  
def login_prompt():  
    """Prompt de login en terminal"""  
    print("=== RON - Sistema de Autenticación ===")  
      
    while True:  
        print("\\n1. Iniciar sesión")  
        print("2. Registrar nuevo usuario")  
        print("3. Salir")  
          
        choice = input("Selecciona una opción: ").strip()  
          
        if choice == "1":  
            username = input("Usuario: ").strip()  
            password = getpass.getpass("Contraseña: ")  
              
            success, result = authenticate_user(username, password)  
            if success:  
                print(f"¡Bienvenido {result['full_name']}!")  
                return username, result  
            else:  
                print(f"Error: {result}")  
                  
        elif choice == "2":  
            username = input("Nuevo usuario: ").strip()  
            full_name = input("Nombre completo: ").strip()  
            password = getpass.getpass("Contraseña: ")  
            password_confirm = getpass.getpass("Confirmar contraseña: ")  
              
            if password != password_confirm:  
                print("Las contraseñas no coinciden")  
                continue  
                  
            success, message = register_user(username, password, full_name)  
            print(message)  
              
        elif choice == "3":  
            print("Saliendo...")  
            exit(0)  
        else:  
            print("Opción inválida")  
  
# Variable global para el usuario actual  
current_user = None  
  
def set_current_user(username, user_data):  
    """Establece el usuario actual de la sesión"""  
    global current_user  
    current_user = {  
        "username": username,  
        "data": user_data  
    }  
  
def get_current_user():  
    """Obtiene el usuario actual"""  
    return current_user