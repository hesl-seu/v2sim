from v2sim.gui.common import *

from .scrtv import ScrollableTreeView


_L = LangLib.Load(__file__)


class PropertyPanel(Frame):
    def __onclick(self, event):
        if len(self.tree.selection()) == 0:
            self.__desc_var.set(_L["PROP_NODESC"])
            return
        self.selected_item = self.tree.selection()[0]
        selected_row = self.tree.item(self.selected_item, "values")[0]
        self.__desc_var.set(self.__em.get_desc(selected_row))

    def setData(self, data:Dict[str, Any], edit_modes:ConfigItemDict):
        self.tree.tree_item_edit_done(None)
        self.data = data
        self.__em:ConfigItemDict = edit_modes
        if edit_modes is None: edit_modes = {}
        self.tree.clear()
        for l, r in data.items():
            self.tree.insert("", "end", values=(l, r))
            self.tree.setCellEditMode(l, "d", edit_modes.get(l))

    def setDataEmpty(self):
        self.setData({}, ConfigItemDict())
        
    def setData2(self, *val_and_modes:Tuple[Any, ConfigItem]):
        data = {}
        edit_modes = ConfigItemDict()
        for v, m in val_and_modes:
            data[m.name] = v
            edit_modes[m.name] = m
        self.setData(data, edit_modes)
    
    def __init__(self, master, data:Dict[str,str], edit_modes:ConfigItemDict, **kwargs):
        super().__init__(master, **kwargs)
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=YES)
        self.tree.heading("t", text=_L["PROPERTY"])
        self.tree.heading("d", text=_L["VALUE"])
        self.tree.tree.bind("<<TreeviewSelect>>", self.__onclick)
        self.tree.pack(fill="both", expand=True)
        self.__desc_var = StringVar(self, _L["PROP_NODESC"])
        self.__desc = Label(self, textvariable=self.__desc_var)
        self.__desc.pack(fill="x", expand=False)
        self.setData(data, edit_modes)

    def getAllData(self) -> Dict[str, str]:
        res:Dict[str, str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res

class PropertyEditor(Toplevel):
    def __init__(self, data:Dict[str,str], var:StringVar, edit_modes:ConfigItemDict):
        super().__init__()
        self.title(_L["PROPERTY_EDITOR"])
        self.__panel = PropertyPanel(self, data, edit_modes)
        self.__panel.pack(fill="both", expand=True)
        self.__fr = Frame(self)
        self.__fr.pack(fill="x", expand=False)
        self.__btn_save = Button(self.__fr, text=_L["SAVE_AND_CLOSE"], command=self.save)
        self.__btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var
    
    def getAllData(self) -> Dict[str,str]:
        return self.__panel.getAllData()
    
    def save(self):
        d = self.getAllData()
        self.var.set(repr(d))
        self.destroy()

__all__ = ["PropertyPanel", "PropertyEditor"]