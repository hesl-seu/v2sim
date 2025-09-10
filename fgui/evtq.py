from collections import deque
from queue import Queue
import threading
import time
import traceback
from typing import Callable, Dict, Tuple

class EventQueue:
    def __init__(self, parent, maxsize:int = 0, interval_ms:int = 100, max_proc_ms:int = 90):
        self._Q = Queue(maxsize)
        self._parent = parent
        self._evt:Dict[str, Callable] = {}
        self._interval_ms = interval_ms
        self._max_proc_ns = max_proc_ms * 1e6  # Convert to nanoseconds
        self._delegates:deque[Tuple[Callable, Tuple, Dict]] = deque()
        self.do()  # Start processing events immediately
    
    def do(self):
        """Process all events in the queue."""
        prod_next = True
        st = time.time_ns()

        cnt = 0
        while self._delegates:
            func, args, kwargs = self._delegates.popleft()
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"Error in delegate function '{func.__name__}': {e}")
        
        cnt = 0
        while not self._Q.empty() and (time.time_ns() - st < self._max_proc_ns) and cnt < 100:
            name, args, kwargs = self._Q.get()
            if name == "__quit__":
                self._Q.task_done()
                prod_next = False
                break
            if name in self._evt and self._evt[name] is not None:
                try:
                    self._evt[name](*args, **kwargs)
                except Exception as e:
                    traceback.print_exc()
                    print(f"Error processing event '{name}': {e}")
            else:
                print(f"Event '{name}' is not registered.")
            self._Q.task_done()
            self._parent.update()  # Ensure the GUI updates after processing each event
            cnt += 1
        if prod_next:
            intv = self._interval_ms
            if cnt >= 100:
                intv = max(intv // 10, 1)
            self._parent.after(intv, self.do)

    def register(self, name:str, callback:Callable):
        """Register an event handler for a specific event name."""
        if name in self._evt:
            raise ValueError(f"Event '{name}' is already registered.")
        self._evt[name] = callback
    
    def setcallback(self, name:str, callback:Callable):
        """Set or update the callback for an event."""
        if name not in self._evt:
            raise ValueError(f"Event '{name}' is not registered.")
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
                if result is None:
                    result = ()
                elif not isinstance(result, tuple):
                    result = (result,)
                self.trigger(name, *result)
            except Exception as e:
                print(f"Error in submitting function '{func.__name__}' for event '{name}': {e}")
        threading.Thread(target=_run_and_trigger, args=(name, func, *args), kwargs=kwargs).start()
    
    def asyncrun(self, func:Callable, *args, **kwargs):
        """Run a no-return function asynchronously"""
        def _run(func, *args, **kwargs):
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"Error in delegating function '{func.__name__}': {e}")
        threading.Thread(target=_run, args=(func, *args), kwargs=kwargs).start()

    def delegate(self, func:Callable, *args, **kwargs):
        """Run a no-return function on the main thread."""
        self._delegates.append((func, args, kwargs))