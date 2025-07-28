import os
from pathlib import Path
from typing import Dict, List
from .view import *
import datetime

def get_clog_mtime(folder:Path):
    clog_path = folder / "cproc.clog"
    if clog_path.is_file():
        return clog_path.stat().st_mtime
    return None

def format_time(ts):
    if ts is None:
        return "Not Found"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

class DirSelApp(Toplevel):
    def __init__(self, folders:List[Path]):
        super().__init__()
        self.title("Select Result Folder")
        self.geometry("500x300")
        self.__sel_folder = StringVar()
        self.__dkt:Dict[str, Path] = {}
        self.create_widgets(folders)
        self.folder = None

    def create_widgets(self, folders:List[Path]):
        columns = ("folder", "mtime")
        tree = Treeview(self, columns=columns, show="headings", selectmode="browse")
        tree.heading("folder", text="Result Folder")
        tree.heading("mtime", text="Modified Time")
        tree.column("folder", width=300)
        tree.column("mtime", width=180)
        for folder in folders:
            mtime = get_clog_mtime(folder)
            idx = tree.insert("", "end", values=(folder.name, format_time(mtime)))
            self.__dkt[idx] = folder
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree = tree

        btn = Button(self, text="Confirm", command=self.confirm_selection)
        btn.pack(pady=5)

    def on_select(self, event):
        selected = self.tree.selection()
        if selected:
            self.__sel_folder.set(self.__dkt[selected[0]].as_posix())

    def confirm_selection(self):
        self.folder = self.__sel_folder.get()
        if self.folder:
            self.destroy()
        else:
            messagebox.showwarning("Warning", "Please select a folder first")