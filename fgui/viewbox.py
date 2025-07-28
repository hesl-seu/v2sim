from typing import Any, List, Dict, Tuple
from queue import Queue
from .view import *

class ViewBox(Tk): 
    def __init__(self, keys:List[str], title:str="ViewBox", width:int=300, height:int=500):
        super().__init__()
        self.title(title)
        self.geometry(f"{width}x{height}")
        
        columns = ("item", "value")
        tree = Treeview(self, columns=columns, show="headings", selectmode="none")
        tree.heading("item", text="Item")
        tree.heading("value", text="Value")
        tree.column("item", width=100)
        tree.column("value", width=200)
        tree.pack(fill=BOTH, expand=True)

        self._dict:Dict[str, Any] = {k:"" for k in keys}
        self._vals:Dict[str, Any] = {k:"" for k in keys}
        for k in keys:
            self._dict[k] = tree.insert("", "end", values=(k, ""))

        self.tree = tree
        self._Q=Queue()
        self.after(100,self._upd)

    def _upd(self):
        d:Dict[str, Tuple[int, Widget]]={}
        while not self._Q.empty():
            d.update(self._Q.get())
        for key,val in d.items():
            if not key in self._dict:
                self._dict[key] = self.tree.insert("", "end", values=(key, str(val)))
            else:
                item = self._dict[key]
                self.tree.item(item, values=(key, str(val)))
            self._vals[key] = val
        self.after(100,self._upd)
    
    def close(self):
        self.destroy()    
    
    def set_val(self, d:Dict[str, Any]):
        self._Q.put(d)