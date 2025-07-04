from queue import Queue
import threading
from typing import Callable, Dict

class EventQueue:
    def __init__(self, parent, maxsize:int = 0, interval_ms:int = 100):
        self._Q = Queue(maxsize)
        self._parent = parent
        self._evt:Dict[str, Callable] = {}
        self._interval_ms = interval_ms
    
    def do(self):
        """Process all events in the queue."""
        prod_next = True
        while not self._Q.empty():
            name, args, kwargs = self._Q.get()
            if name == "__quit__":
                self._Q.task_done()
                prod_next = False
                break
            if name in self._evt:
                try:
                    self._evt[name](*args, **kwargs)
                except Exception as e:
                    print(f"Error processing event '{name}': {e}")
            else:
                print(f"Event '{name}' is not registered.")
            self._Q.task_done()
        if prod_next:
            self._parent.after(self._interval_ms, self.do)

    def register(self, name:str, callback:Callable):
        """Register an event handler for a specific event name."""
        if name in self._evt:
            raise ValueError(f"Event '{name}' is already registered.")
        self._evt[name] = callback
    
    def trigger(self, name:str, *args, **kwargs):
        """Trigger an event by its name with optional arguments."""
        if name not in self._evt:
            raise ValueError(f"Event '{name}' is not registered.")
        self._Q.put((name, args, kwargs))
    
    def submit(self, name:str, func:Callable, *args, **kwargs):
        """Run a function asychoronously and submit the results to trigger an event."""
        def _run_and_trigger(name, func, *args, **kwargs):
            try:
                result = func(*args, **kwargs)
                self.trigger(name, *result)
            except Exception as e:
                print(f"Error in function '{func.__name__}': {e}")
        threading.Thread(target=_run_and_trigger, args=(name, func, *args), kwargs=kwargs).start()
    
    def delegate(self, func:Callable, *args, **kwargs):
        """Run a no-return function asynchronously on the main thread."""
        def _run(func, *args, **kwargs):
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"Error in function '{func.__name__}': {e}")
        threading.Thread(target=_run, args=(func, *args), kwargs=kwargs).start()