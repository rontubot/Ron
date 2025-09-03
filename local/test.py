import socket  
  
def test_ron_control(command):  
    try:  
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  
        client.connect(('localhost', 9999))  
        client.send(command.encode('utf-8'))  
        response = client.recv(1024).decode('utf-8')  
        print(f"Comando: {command} -> Respuesta: {response}")  
        client.close()  
    except Exception as e:  
        print(f"Error: {e}")  
  
# Probar comandos  
test_ron_control("START")  
test_ron_control("STATUS")  
test_ron_control("STOP")