from v2simux_gui.common import *

from feasytools import SegFunc
from .scrtv import ScrollableTreeView


_L = LangLib.Load(__file__)


class SegFuncEditor(Toplevel):
    def __init__(self, data:SegFunc, var:StringVar):
        super().__init__()
        self.title(_L["SEG_FUNC_EDITOR"])
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=NO)
        self.tree.heading("t", text="Time")
        self.tree.heading("d", text="Data")
        self.tree.pack(fill="both", expand=True)
        for l,r in data:
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("t", ConfigItem(
            name="t", editor=EditMode.ENTRY, desc="Time"))
        self.tree.setColEditMode("d", ConfigItem(
            name="d", editor=EditMode.ENTRY, desc="Data"))
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_add = Button(self.fr, text=_L["ADD"], command=self.add, width=6)
        self.btn_add.grid(row=0,column=0,pady=3,sticky="w")
        self.btn_del = Button(self.fr, text=_L["DELETE"], command=self.delete, width=6)
        self.btn_del.grid(row=0,column=1,pady=3,sticky="w")
        self.btn_moveup = Button(self.fr, text=_L["UP"], command=self.moveup, width=6)
        self.btn_moveup.grid(row=0,column=2,pady=3,sticky="w")
        self.btn_movedown = Button(self.fr, text=_L["DOWN"], command=self.movedown, width=6)
        self.btn_movedown.grid(row=0,column=3,pady=3,sticky="w")
        self.btn_save = Button(self.fr, text=_L["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var
    
    def add(self):
        self.tree.insert("", "end", values=(0, 0))
    
    def delete(self):
        for i in self.tree.tree.selection():
            self.tree.delete(i)
    
    def moveup(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p-1)
    
    def movedown(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p+1)
    
    def save(self):
        try:
            d = self.getAllData()
        except:
            MB.showerror(_L["ERROR"], _L["INVALID_SEG_FUNC"])
            return
        if len(d) == 0:
            self.var.set(str(None))
        else:
            self.var.set(str(d))
        self.destroy()

    def getAllData(self) -> SegFunc:
        res:List[Tuple[int,float]] = []
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res.append((int(x[0]), float(x[1])))
        return SegFunc(res)

__all__ = ["SegFuncEditor"]