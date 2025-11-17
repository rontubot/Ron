import threading  
import queue  
import time  
import logging  
from typing import Callable, Optional, Dict, Any  
from datetime import datetime, timedelta  
  
logger = logging.getLogger(__name__)  
  
class TaskManager:  
    """Gestor de tareas asíncronas con capacidad de enviar mensajes progresivos"""  
      
    def __init__(self, tts_callback: Callable[[str], None]):  
        """  
        Args:  
            tts_callback: Función para enviar mensajes de voz (engine.say + runAndWait)  
        """  
        self.tts_callback = tts_callback  
        self.message_queue = queue.Queue()  
        self.active_tasks: Dict[str, threading.Thread] = {}  
        self.scheduled_tasks: list = []  
        self.running = True  
          
        # Iniciar worker threads  
        self.message_worker = threading.Thread(target=self._process_messages, daemon=True)  
        self.scheduler_worker = threading.Thread(target=self._process_scheduled_tasks, daemon=True)  
        self.message_worker.start()  
        self.scheduler_worker.start()  
          
        logger.info("TaskManager iniciado")  
      
    def _process_messages(self):  
        """Worker que procesa mensajes de la queue y los envía por TTS"""  
        while self.running:  
            try:  
                message = self.message_queue.get(timeout=0.5)  
                if message:  
                    logger.info(f"Enviando mensaje: {message}")  
                    self.tts_callback(message)  
            except queue.Empty:  
                continue  
            except Exception as e:  
                logger.error(f"Error procesando mensaje: {e}")  
      
    def _process_scheduled_tasks(self):  
        """Worker que verifica y ejecuta tareas programadas"""  
        while self.running:  
            try:  
                now = datetime.now()  
                tasks_to_execute = []  
                  
                # Buscar tareas que deben ejecutarse  
                for task in self.scheduled_tasks[:]:  
                    if now >= task['execute_at']:  
                        tasks_to_execute.append(task)  
                        self.scheduled_tasks.remove(task)  
                  
                # Ejecutar tareas pendientes  
                for task in tasks_to_execute:  
                    self.send_message(task['message'])  
                    if task.get('callback'):  
                        task['callback']()  
                  
                time.sleep(1)  # Verificar cada segundo  
            except Exception as e:  
                logger.error(f"Error en scheduler: {e}")  
      
    def send_message(self, message: str):  
        """Encola un mensaje para ser enviado por TTS"""  
        self.message_queue.put(message)  
      
    def schedule_message(self, message: str, delay_seconds: int, callback: Optional[Callable] = None):  
        """Programa un mensaje para ser enviado después de un delay"""  
        execute_at = datetime.now() + timedelta(seconds=delay_seconds)  
        self.scheduled_tasks.append({  
            'message': message,  
            'execute_at': execute_at,  
            'callback': callback  
        })  
        logger.info(f"Mensaje programado para {execute_at}: {message}")  
      
    def run_background_task(self, task_id: str, target: Callable, args: tuple = (), kwargs: dict = None):  
        """Ejecuta una tarea en background"""  
        if kwargs is None:  
            kwargs = {}  
          
        def wrapper():  
            try:  
                logger.info(f"Iniciando tarea: {task_id}")  
                target(*args, **kwargs)  
                logger.info(f"Tarea completada: {task_id}")  
            except Exception as e:  
                logger.error(f"Error en tarea {task_id}: {e}")  
                self.send_message(f"Hubo un error procesando la tarea: {str(e)}")  
            finally:  
                if task_id in self.active_tasks:  
                    del self.active_tasks[task_id]  
          
        thread = threading.Thread(target=wrapper, daemon=True)  
        self.active_tasks[task_id] = thread  
        thread.start()  
        return task_id  
      
    def run_command_background(
        self,
        task_id: str,
        command_name: str,
        params: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
    ):
        """
        Ejecuta un comando de core.commands en segundo plano.

        - Envía progress_callback al comando para que pueda ir mandando
          mensajes al banco (self.send_message).
        - Cuando el comando devuelve un 'message' o 'result' final, también
          lo manda al usuario.
        """
        params = params or {}

        # Import local para evitar ciclos de import
        from core.commands import run_command

        def target():
            try:
                ctx = {
                    "username": username or "default",
                    "progress_callback": self.send_message,  # <- aquí conectamos el progreso al banco de mensajes
                }
                result = run_command(command_name, params, ctx)

                # Normalizamos el resultado para mandar el mensaje final
                if isinstance(result, dict):
                    msg = result.get("message") or result.get("result")
                    if isinstance(msg, str) and msg.strip():
                        self.send_message(str(msg))

            except Exception as e:
                logger.error(f"Error en comando {command_name}: {e}")
                self.send_message(f"Error ejecutando comando '{command_name}': {e}")

        return self.run_background_task(task_id, target)


      
    def is_task_running(self, task_id: str) -> bool:  
        """Verifica si una tarea está en ejecución"""  
        return task_id in self.active_tasks and self.active_tasks[task_id].is_alive()  
      
    def shutdown(self):  
        """Detiene el TaskManager"""  
        self.running = False  
        self.message_worker.join(timeout=2)  
        self.scheduler_worker.join(timeout=2)  
        logger.info("TaskManager detenido")