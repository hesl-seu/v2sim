from v2sim.gui.common import *
from v2sim import AMAP_KEY_FILE
from .utils import *
from .controls import ScrollableTreeView


_L = LangLib.Load(__file__)


class CSCSVEditor(Frame):
    def __init__(self, master, down_worker, file:str="", **kwargs):
        super().__init__(master, **kwargs)

        self._Q = EventQueue(self)
        self._Q.register("loaded", lambda: None)

        if file:
            self.file = file
        else:
            self.file = ""
        self.down_wk = down_worker
        self.tree = ScrollableTreeView(self) 
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("ID", "Address", "X", "Y")
        self.tree.column("ID", width=120, stretch=NO)
        self.tree.column("X", width=100, stretch=NO)
        self.tree.column("Y", width=100, stretch=NO)
        self.tree.column("Address", width=180, stretch=YES)
        
        self.tree.heading("ID", text=_L["CSCSV_ID"])
        self.tree.heading("X", text=_L["CSCSV_X"])
        self.tree.heading("Y", text=_L["CSCSV_Y"])
        self.tree.heading("Address", text=_L["CSCSV_ADDR"])
        self.tree.pack(fill="both", expand=True)

        self.lb_cnt = Label(self, text=_L["LB_COUNT"].format(0))
        self.lb_cnt.pack(fill="x", expand=False)

        self.panel = Frame(self)
        self.panel.pack(fill="x", expand=False)
        self.btn_down = Button(self.panel, text=_L["CSCSV_DOWNLOAD"], command=self.down)
        self.btn_down.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.lb_amapkey = Label(self.panel, text=_L["CSCSV_KEY"])
        self.lb_amapkey.grid(row=0, column=1, padx=3, pady=3, sticky="w")
        self.entry_amapkey = Entry(self.panel, width=50)
        self.entry_amapkey.grid(row=0, column=2, columnspan=2, padx=3, pady=3, sticky="w")

        if Path(AMAP_KEY_FILE).exists():
            with open(AMAP_KEY_FILE, "r") as f:
                self.entry_amapkey.insert(0, f.read().strip())
        
    def down(self):
        if MB.askyesno(_L["CSCSV_CONFIRM_TITLE"], _L["CSCSV_CONFIRM"]):
            with open(AMAP_KEY_FILE, "w") as f:
                f.write(self.entry_amapkey.get().strip())
            self.down_wk()
    
    def __load(self, file:str):
        try:
            with open(file, "r") as f:
                f.readline()
                lines = f.readlines()
        except Exception as e:
            showerr(f"Error loading {file}: {e}")
            return
        self.file = file
        self.lb_cnt.config(text=_L["LB_COUNT"].format(len(lines) - 1))
        self.tree.clear()
        for i, cs in enumerate(lines, start=2):
            vals = cs.strip().split(',')
            if len(vals) != 4:
                print(f"Invalid line {i} in CS CSV:", cs)
            self._Q.delegate(self.tree.insert, "", "end", values=tuple(vals))

    def load(self, file:str):
        self._Q.submit("loaded", self.__load, file)
    
    def clear(self):
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
        self.tree.clear()