import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

class TaskManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TaskManager, cls).__new__(cls)
                #max_workers=2 avoids CPU over-saturation on small servers
                cls._instance.executor = ThreadPoolExecutor(max_workers=2)
                cls._instance.tasks = {}
        return cls._instance

    def submit_task(self, func, *args, **kwargs):
        task_id = str(uuid.uuid4())
        with self._lock:
            self.tasks[task_id] = {
                "status": "Running",
                "start_time": datetime.now().isoformat(),
                "result": None,
                "error": None,
                "logs": ["Task initialized..."]  
            }
        self.executor.submit(self._run_wrapper, task_id, func, *args, **kwargs)
        return task_id
 
    def _run_wrapper(self, task_id, func, *args, **kwargs):
        try:  
            result = func(*args, **kwargs)
            
            with self._lock:
                self.tasks[task_id]["status"] = "Completed"
                self.tasks[task_id]["result"] = result 
                self.tasks[task_id]["logs"].append("Solver finished successfully.")
        except Exception as e:
            with self._lock:
                self.tasks[task_id]["status"] = "Failed"
                self.tasks[task_id]["error"] = str(e)
                self.tasks[task_id]["logs"].append(f"Error: {str(e)}")

    def get_task_status(self, task_id):
        with self._lock:
            #return a copy to prevent accidental outside mutation
            task = self.tasks.get(task_id, {"status": "Not Found"})
            return dict(task)

    #method to update logs while the task is running
    def add_log(self, task_id, message):
        with self._lock:
            if task_id in self.tasks:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.tasks[task_id]["logs"].append(f"[{timestamp}] {message}")