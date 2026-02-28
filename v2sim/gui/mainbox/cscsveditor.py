from v2sim.gui.common import *
from v2sim.gen import AMAP_KEY_FILE
from .utils import *
from .controls import ScrollableTreeView


_L = LangLib.Load(__file__)


class CSCSVEditor(Frame):
    def __init__(self, master, downcs_worker, downgs_worker, files:Optional[List[str]] = None, **kwargs):
        super().__init__(master, **kwargs)

        self._Q = EventQueue(self)
        self._Q.register("loaded", lambda: None)

        if files:
            self.files = files
        else:
            self.files = []
        
        self.downcs_wk = downcs_worker
        self.downgs_wk = downgs_worker
        self.tree = ScrollableTreeView(self) 
        self.tree.setheadings(
            ("ID", 120, _L["CSCSV_ID"], ),
            ("Address", 180, _L["CSCSV_ADDR"], None, True),
            ("X", 100, _L["CSCSV_X"], ),
            ("Y", 100, _L["CSCSV_Y"], ),
        )
        self.tree.pack(fill="both", expand=True)

        self.lb_cnt = Label(self, text=_L["LB_COUNT"].format(0))
        self.lb_cnt.pack(fill="x", expand=False)

        self.panel = Frame(self)
        self.panel.pack(fill="x", expand=False)
        self.btn_downcs = Button(self.panel, text=_L["CSCSV_DOWNLOAD_CS"], command=self.downcs)
        self.btn_downcs.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.btn_downgs = Button(self.panel, text=_L["CSCSV_DOWNLOAD_GS"], command=self.downgs)
        self.btn_downgs.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.lb_amapkey = Label(self.panel, text=_L["CSCSV_KEY"])
        self.lb_amapkey.grid(row=0, column=2, padx=3, pady=3, sticky="w")
        self.entry_amapkey = Entry(self.panel, width=50)
        self.entry_amapkey.grid(row=0, column=3, columnspan=2, padx=3, pady=3, sticky="w")

        if Path(AMAP_KEY_FILE).exists():
            with open(AMAP_KEY_FILE, "r") as f:
                self.entry_amapkey.insert(0, f.read().strip())
        
    def downcs(self):
        if MB.askyesno(_L["CSCSV_CONFIRM_TITLE"], _L["CSCSV_CONFIRM_CS"]):
            with open(AMAP_KEY_FILE, "w") as f:
                f.write(self.entry_amapkey.get().strip())
            self.downcs_wk()
    
    def downgs(self):
        if MB.askyesno(_L["CSCSV_CONFIRM_TITLE"], _L["CSCSV_CONFIRM_GS"]):
            with open(AMAP_KEY_FILE, "w") as f:
                f.write(self.entry_amapkey.get().strip())
            self.downgs_wk()
    
    def __readfile(self, file:str, encoding:str):
        try:
            with open(file, "r", encoding=encoding) as f:
                f.readline()
                lines = f.readlines()
            return lines
        except UnicodeDecodeError:
            return None

    def __load(self, files:List[str]):
        encodings = ['utf-8', 'gbk']
        all_lines = []
        for file in files:
            lines = None
            for enc in encodings:
                try:
                    lines = self.__readfile(file, enc)
                except Exception as e:
                    continue
                if lines is not None:
                    all_lines.extend(lines)
                    break
            else:
                showerr(_L["ERROR_LOADING"].format(file, _L["UKN_ENCODING"]))
                return
            
        self.files = files
        self.lb_cnt.config(text=_L["LB_COUNT"].format(len(all_lines) - 1))
        self.tree.clear()
        for i, cs in enumerate(all_lines, start=2):
            vals = cs.strip().split(',')
            if len(vals) != 4:
                print(_L["INVALID_LINE_IN_CSCSV"].format(i, cs))
            self._Q.delegate(self.tree.insert, "", "end", values=tuple(vals))

    def load(self, files:List[str]):
        self._Q.submit("loaded", self.__load, files)
    
    def clear(self):
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
        self.tree.clear()