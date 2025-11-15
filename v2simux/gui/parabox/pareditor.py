from v2simux.gui.common import *
from ..mainbox.controls import ScrollableTreeView
from .utils import *


class ParamsEditor(Toplevel):
    def __init__(self, data:Dict[str,str]):
        super().__init__()
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("lb", "rb")
        self.tree.column("lb", width=120, stretch=NO)
        self.tree.column("rb", width=120, stretch=NO)
        self.tree.heading("lb", text=_L["PARAM_NAME"])
        self.tree.heading("rb", text=_L["PARAM_VALUE"])
        self.tree.pack(fill="both", expand=True)
        for l,r in data.items():
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("lb", EditMode.combo([
            'b','e','l','no-plg','seed','gen-veh','gen-fcs','gen-scs','plot'
        ]))
        self.tree.setColEditMode("rb", EditMode.entry())
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_add = Button(self.fr, text=_L["ADD"], command=self.add, width=6)
        self.btn_add.grid(row=0,column=0,pady=3,sticky="w")
        self.btn_del = Button(self.fr, text=_L["DELETE"], command=self.delete, width=6)
        self.btn_del.grid(row=0,column=1,pady=3,sticky="w")
        self.btn_moveup = Button(self.fr, text=_L["CLEAR"], command=self.tree.clear, width=6)
        self.btn_moveup.grid(row=0,column=2,pady=3,sticky="w")
        self.btn_save = Button(self.fr, text=_L["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=3,padx=3,pady=3,sticky="e")
    
    def add(self):
        self.tree.insert("", "end", values=("no-plg",""))
    
    def delete(self):
        for i in self.tree.tree.selection():
            self.tree.delete(i)
    
    def save(self):
        self.data = self.getAllData()
        self.destroy()

    def getAllData(self) -> Dict[str,str]:
        res:Dict[str,str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res

__all__ = ["ParamsEditor"]