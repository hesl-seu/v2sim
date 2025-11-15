from v2sim.gui.common import *

from feasytools import RangeList
from .scrtv import ScrollableTreeView, ALWAYS_ONLINE


_L = LangLib.Load(__file__)


class RangeListEditor(Toplevel):
    def __init__(self, data:RangeList, var:StringVar, hint_hms:bool=False):
        super().__init__()
        self.title(_L["RANGE_LIST_EDITOR"])
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("lb", "rb")
        self.tree.column("lb", width=120, stretch=NO)
        self.tree.column("rb", width=120, stretch=NO)
        self.tree.heading("lb", text=_L["LEFT_BOUND"])
        self.tree.heading("rb", text=_L["RIGHT_BOUND"])
        self.tree.pack(fill="both", expand=True)
        for l,r in data:
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("lb", ConfigItem(
            name="lb", editor=EditMode.ENTRY, desc="Left Bound", default_value=0))
        self.tree.setColEditMode("rb", ConfigItem(
            name="rb", editor=EditMode.ENTRY, desc="Right Bound", default_value=0))
        if hint_hms:
            self.lb_hint = Label(self, text=_L["TIME_FORMAT"])
            self.lb_hint.pack(fill="x", expand=False)
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
            MB.showerror(_L["ERROR"], _L["INVALID_TIME_FORMAT"])
            return
        if len(d) == 0:
            self.var.set(ALWAYS_ONLINE)
        else:
            self.var.set(str(d))
        self.destroy()

    def getAllData(self) -> RangeList:
        res:List[Tuple[int,int]] = []
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res.append((RangeList.parse_time(x[0]), RangeList.parse_time(x[1])))
        return RangeList(res)

__all__ = ["RangeListEditor"]