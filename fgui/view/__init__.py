from tkinter import *
from tkinter.ttk import *
import platform
from tkinter import messagebox, filedialog
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)