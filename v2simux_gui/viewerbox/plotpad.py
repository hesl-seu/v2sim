from v2simux_gui.common import *


_L = LangLib.Load(__file__)


class PlotPad(Frame):
    def __init__(self, master, show_accum:bool=False, useEntry:bool=False, useTotalText:bool=False, **kwargs):
        super().__init__(master, **kwargs)
        if useEntry:
            self.cb = Entry(self)
        else:
            self.cb = Combobox(self)
            self.cb['values'] = []
        self.cb.pack(side='left',padx=3,pady=5)
        self.accum = BooleanVar(self, False)
        if show_accum:
            self.accum.set(True)
            self.cb_accum = Checkbutton(self, text=_L["BTN_TOTAL"] if useTotalText else _L["BTN_ACCUM"], variable=self.accum)
            self.cb_accum.pack(side='left',padx=3,pady=5)
        else:
            self.cb_accum = None
    
    def setValues(self, values:List[str]):
        if isinstance(self.cb, Combobox):
            self.cb['values'] = values
            self.cb.current(0)
    
    def set(self, item:str):
        if isinstance(self.cb, Combobox):
            self.cb.set(item)
        else:
            self.cb.delete(0,END)
            self.cb.insert(0,item)
    
    def get(self):
        return self.cb.get()
    
    def disable(self):
        self.cb['state']=DISABLED
        if self.cb_accum: self.cb_accum['state']=DISABLED
        
    def enable(self):
        self.cb['state']=NORMAL
        if self.cb_accum: self.cb_accum['state']=NORMAL