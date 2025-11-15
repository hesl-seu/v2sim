from v2simux_gui.common import *

from feasytools import PDFunc, CreatePDFunc
from .scrtv import ScrollableTreeView


_L = LangLib.Load(__file__)


def _removeprefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    return s

class PDFuncEditor(Toplevel):
    def reset_tree(self, pdfunc:PDFunc):
        self.tree.clear()
        for l,r in pdfunc.__dict__.items():
            self.tree.insert("", "end", values=(l, r))
    
    def __init__(self, var: StringVar):
        super().__init__()
        self.title(_L["PDFUNC_EDITOR"])
        pdfunc = eval(var.get())
        assert isinstance(pdfunc, PDFunc)
        self.model = StringVar(self, _removeprefix(pdfunc.__class__.__name__, "PD"))
        self.fr0 = Frame(self)
        self.mlabel = Label(self.fr0, text=_L["PDMODEL"])
        self.mlabel.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.cb = Combobox(self.fr0, textvariable=self.model,
            values=["Normal", "Uniform", "Triangular", 
            "Exponential", "Gamma", "Weibull", 
            "Beta", "LogNormal", "LogLogistic"])
        self.cb.bind('<<ComboboxSelected>>', lambda x: self.reset_tree(CreatePDFunc(self.model.get())))
        self.cb.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.fr0.pack(fill="x", expand=True)
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=YES)
        self.tree.heading("t", text=_L["PROPERTY"])
        self.tree.heading("d", text=_L["VALUE"])
        self.tree.pack(fill="both", expand=True)
        self.reset_tree(pdfunc)
        self.tree.setColEditMode("d", ConfigItem(name="d", editor=EditMode.ENTRY, desc="Value"))
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_save = Button(self.fr, text=_L["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var

    def getAllData(self) -> PDFunc:
        res:Dict[str, float] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = float(x[1])
        return CreatePDFunc(self.model.get(), **res)
    
    def save(self):
        d = self.getAllData()
        self.var.set(repr(d))
        self.destroy()

__all__ = ["PDFuncEditor"]