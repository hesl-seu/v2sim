from tkinter import *
from tkinter.ttk import *
from tkinter import messagebox, filedialog
import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)