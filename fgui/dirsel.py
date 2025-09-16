from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
from v2sim import CustomLocaleLib
import datetime
from .view import *

_L = CustomLocaleLib.LoadFromFolder(Path(__file__).parent.parent / "resources/controls")

def get_clog_mtime(folder:Path):
    clog_path = folder / "cproc.clog"
    if clog_path.is_file():
        return clog_path.stat().st_mtime
    return None

def format_time(ts):
    if ts is None:
        return _L("NOT_FOUND")
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

class SelectItemDialog(Toplevel):
    def __init__(self, items:List[List[Any]], title:str, columns:List[Union[str, Tuple[str, str]]]):
        super().__init__()
        self.title(title)
        self.geometry("500x300")
        self.__dkt:Dict[str, Any] = {}
        self.selected_item = None

        col_id = []
        col_name = []
        for col in columns:
            if isinstance(col, str):
                col_id.append(col)
                col_name.append(col.capitalize())
            else:
                col_id.append(col[0])
                col_name.append(col[1])
        tree = Treeview(self, columns=col_id, show="headings", selectmode="browse")
        for i, n in zip(col_id, col_name):
            tree.heading(i, text=n)

        for item in items:
            idx = tree.insert("", "end", values=item)
            self.__dkt[idx] = item
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree = tree

        btn = Button(self, text=_L("CONFIRM"), command=self.confirm_selection)
        btn.pack(pady=5)

    def on_select(self, event):
        selected = self.tree.selection()
        if selected:
            self.selected_item = self.__dkt[selected[0]]

    def confirm_selection(self):
        if self.selected_item is not None:
            self.destroy()
        else:
            messagebox.showwarning(_L("WARNING"), _L("HINT_SELECT_ITEM"))

class SelectResultsDialog(SelectItemDialog):
    def __init__(self, items:List[Path]):
        new_items = []
        self.__folders:Dict[str, Path] = {}
        for item in items:
            mtime = get_clog_mtime(item)
            new_items.append([item.name, format_time(mtime)])
            self.__folders[item.name] = item.absolute()
        super().__init__(new_items, title=_L("SELECT_RESULTS"), 
                         columns=[("folder",_L("FOLDER")), ("mtime",_L("MODIFIED_TIME"))])
        self.tree.column("folder", width=300)
        self.tree.column("mtime", width=180)
    
    @property
    def folder(self) -> Union[Path, None]:
        if self.selected_item is None:
            return None
        return self.__folders[self.selected_item[0]]