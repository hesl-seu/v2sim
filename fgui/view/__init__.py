from tkinter import *
from tkinter.ttk import *
import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)