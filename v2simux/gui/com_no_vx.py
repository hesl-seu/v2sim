# Load Path
from pathlib import Path

# Load Event Queue
from .evtq import EventQueue

# Load Language Library
from feasytools import LangLib, LangConfig
LangConfig.SetAppName("v2simux")
 
# High DPI awareness for Windows
import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)

# Load Tk controls
from tkinter import (
    Toplevel, messagebox as MB, BooleanVar, StringVar, IntVar, Canvas, Event, Tk, Menu, filedialog, Text, Listbox, PhotoImage, Widget,
    NO, YES, NORMAL, DISABLED, END, BOTH, X, Y, LEFT, RIGHT, TOP, BOTTOM, W, E
)
from tkinter.ttk import Treeview, Button, LabelFrame, Checkbutton, Combobox, Frame, Label, Entry, Spinbox, Scrollbar, Radiobutton, Notebook, OptionMenu

# Load Type Hints
from typing import Dict, List, Set, Tuple, Any, Union, Optional, Iterable, Callable, Literal

# Set exports
__all__ = [
    "LangLib", "LangConfig", "EventQueue", "Path", "Dict", "List", "Set", "Tuple", "Any", "Union", "Optional", "Iterable", "Callable", "Literal",
    "Toplevel", "MB", "BooleanVar", "StringVar", "IntVar", "Canvas", "Event", "Tk", "Menu", "filedialog", "Text", "Listbox", "PhotoImage", "Widget",
    "NO", "YES", "NORMAL", "DISABLED", "END", "X", "Y", "BOTH", "LEFT", "RIGHT", "TOP", "BOTTOM", "W", "E",
    "Treeview", "Button", "LabelFrame", "Checkbutton", "Combobox", "Frame", "Label", "Entry", "Spinbox", "Scrollbar", "Radiobutton", "Notebook", "OptionMenu",
]