from v2simux.gui.common import *

from v2simux import StaPool
from .pareditor import ParamsEditor
from ..mainbox.controls import LogItemPad
from .utils import *


class LoadGroupBox(Toplevel):
    def __init__(self, parent, folder:str):
        super().__init__(parent)
        self.params = {}
        self.folder = folder
        self.results:Optional[list[tuple[str,str]]] = None
        self.title(_L("LOAD_GROUP_TITLE"))
        self.geometry('600x300')
        self.lb = Label(self, text=_L("FOLDER_NAME").format(self.folder))
        self.lb.pack(padx=3, pady=3)
        self.fr = Frame(self)
        self.fr.pack(padx=3, pady=3)
        self.lb_p = Label(self.fr, text=_L("OTHER_PARAMS"))
        self.lb_p.grid(row=0, column=0, padx=3, pady=3)
        self.fr2 = Frame(self.fr)
        self.fr2.grid(row=0, column=1, padx=3, pady=3)
        self.lb_pv = Label(self.fr2, text=str(self.params))
        self.lb_pv.pack(padx=3, anchor=W, side=LEFT)
        self.en_p = Button(self.fr2, command=self.edit_params, text="...",width=3)
        self.en_p.pack(padx=3, anchor=W, side=LEFT)
        self.lb_m = Label(self.fr, text=_L("MODE_ITEM"))
        self.lb_m.grid(row=1, column=0, padx=3, pady=3)
        self.cb = Combobox(self.fr)
        self.cb.grid(row=1, column=1, padx=3, pady=3)
        self.cb["values"] = [ITEM_NONE, "scs_slots", "fcs_slots", "start_time", "end_time", "traffic_step"]
        self.cb.current(0)
        self.lb_s = Label(self.fr, text=_L("START_VALUE"))
        self.lb_s.grid(row=2, column=0, padx=3, pady=3)
        self.en_s = Entry(self.fr)
        self.en_s.grid(row=2, column=1, padx=3, pady=3)
        self.lb_e = Label(self.fr, text=_L("END_VALUE"))
        self.lb_e.grid(row=3, column=0, padx=3, pady=3)
        self.en_e = Entry(self.fr)
        self.en_e.grid(row=3, column=1, padx=3, pady=3)
        self.lb_t = Label(self.fr, text=_L("STEP_VALUE"))
        self.lb_t.grid(row=4, column=0, padx=3, pady=3)
        self.en_t = Entry(self.fr)
        self.en_t.grid(row=4, column=1, padx=3, pady=3)
        self.lip = LogItemPad(self, _L["SIM_STAT"], StaPool())
        self.lip["ev"]=False
        self.lip.pack(padx=3, pady=3)
        self.btn = Button(self, text=_L("LGB_WORK"), command=self.work)
        self.btn.pack(padx=3, pady=3)
    
    def edit_params(self):
        pe = ParamsEditor(self.params)
        pe.wait_window()
        self.params = pe.data
        self.lb_pv["text"] = str(self.params)
    
    def work(self):
        self.results = []
        mode = self.cb.get()
        if mode == ITEM_NONE:
            self.results.append(('{}', ''))
        else:
            ms = ''.join(x[0] for x in mode.split('_'))
            try:
                start = int(self.en_s.get())
                end = int(self.en_e.get())
                step = int(self.en_t.get())
            except ValueError:
                MB.showerror(_L("ERROR"), _L("INVALID_VALUE"))
                self.focus()
                return
            for i in range(start, end, step):
                self.results.append(('{'+f"'{mode}':{i}"+'}', f"{ms}_{i}"))
        self.destroy()

__all__ = ["LoadGroupBox"]