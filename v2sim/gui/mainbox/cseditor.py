from v2sim.gui.common import *

from v2sim import CS, SCS, FCS, ListSelection, PricingMethod, LoadCSList
from feasytools import SegFunc, ConstFunc, OverrideFunc, RangeList
from .utils import *
from .controls import ScrollableTreeView, ALWAYS_ONLINE


_L = LangLib.Load(__file__)


class CSEditorGUI(Frame):
    def __init__(self, master, generatorFunc, canV2g:bool, file:str="", **kwargs):
        super().__init__(master, **kwargs)

        self._Q = EventQueue(self)
        self._Q.register("loaded", lambda: None)
        
        self.gf = generatorFunc
        if file:
            self.file = file
        else:
            self.file = ""
        
        self.tree = ScrollableTreeView(self, allowSave=True) 
        self.tree['show'] = 'headings'
        if canV2g:
            self.csType = SCS
            self.tree["columns"] = ("Edge", "Slots", "Bus", "x", "y", "Online", "MaxPc", "MaxPd", "PriceBuy", "PriceSell", "PcAlloc", "PdAlloc")
        else:
            self.csType = FCS
            self.tree["columns"] = ("Edge", "Slots", "Bus", "x", "y", "Online", "MaxPc", "PriceBuy", "PcAlloc")
        self.tree.column("Edge", width=120, stretch=NO)
        self.tree.column("Slots", width=90, stretch=NO)
        self.tree.column("Bus", width=80, stretch=NO)
        self.tree.column("x", width=60, stretch=NO)
        self.tree.column("y", width=60, stretch=NO)
        self.tree.column("Online", width=100, stretch=NO)
        self.tree.column("MaxPc", width=130, stretch=NO)
        self.tree.column("PriceBuy", width=120, stretch=YES)
        if canV2g:
            self.tree.column("MaxPd", width=130, stretch=NO)
            self.tree.column("PriceSell", width=120, stretch=YES)
            self.tree.column("PcAlloc", width=80, stretch=NO)
            self.tree.column("PdAlloc", width=80, stretch=NO)
        
        self.tree.heading("Edge", text=_L["CSE_EDGE"])
        self.tree.heading("Slots", text=_L["CSE_SLOTS"])
        self.tree.heading("Bus", text=_L["CSE_BUS"])
        self.tree.heading("x", text=_L["CSE_X"])
        self.tree.heading("y", text=_L["CSE_Y"])
        self.tree.heading("Online", text=_L["CSE_OFFLINE"])
        self.tree.heading("MaxPc", text=_L["CSE_MAXPC"])
        self.tree.heading("PriceBuy", text=_L["CSE_PRICEBUY"])
        self.tree.heading("PcAlloc", text=_L["CSE_PCALLOC"])

        self.tree.setColEditMode("Edge", EditMode.entry())
        self.tree.setColEditMode("Slots", EditMode.spin(0, 100))
        self.tree.setColEditMode("Bus", EditMode.entry())
        self.tree.setColEditMode("x", EditMode.entry())
        self.tree.setColEditMode("y", EditMode.entry())
        self.tree.setColEditMode("Online", EditMode.rangelist(hint=True))
        self.tree.setColEditMode("MaxPc", EditMode.spin(0, 1000))
        self.tree.setColEditMode("PriceBuy", EditMode.segfunc())
        self.tree.setColEditMode("PcAlloc", EditMode.combo(values=["Average", "Prioritized"]))

        if canV2g:
            self.tree.heading("PriceSell", text=_L["CSE_PRICESELL"])
            self.tree.heading("MaxPd", text=_L["CSE_MAXPD"])
            self.tree.heading("PdAlloc", text=_L["CSE_PDALLOC"])
            self.tree.setColEditMode("PriceSell", EditMode.segfunc())
            self.tree.setColEditMode("MaxPd", EditMode.spin(0, 1000))
            self.tree.setColEditMode("PdAlloc", EditMode.combo(values=["Average"]))
        self.tree.pack(fill="both", expand=True)

        self.panel2 = Frame(self)
        self.btn_find = Button(self.panel2, text=_L["BTN_FIND"], command=self._on_btn_find_click)
        self.btn_find.pack(fill="x", side='right', anchor='e', expand=False)
        self.entry_find = Entry(self.panel2)
        self.entry_find.pack(fill="x", side='right', anchor='e',expand=False)
        self.lb_cnt = Label(self.panel2, text=_L["LB_COUNT"].format(0))
        self.lb_cnt.pack(fill="x", side='left', anchor='w', expand=False)
        self.panel2.pack(fill="x")

        self.gens = LabelFrame(self, text=_L["CS_GEN"])
        self.gens.pack(fill="x", expand=False)

        self.useMode = IntVar(self, 0)
        self.group_use = LabelFrame(self.gens, text=_L["CS_MODE"])
        self.rb_useAll = Radiobutton(self.group_use, text=_L["CS_USEALL"], value=0, variable=self.useMode, command=self._useModeChanged)
        self.rb_useAll.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_useSel = Radiobutton(self.group_use, text=_L["CS_SELECTED"], value=1, variable=self.useMode, command=self._useModeChanged)
        self.rb_useSel.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_sel = Entry(self.group_use, state="disabled")
        self.entry_sel.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.rb_useRandN = Radiobutton(self.group_use, text=_L["CS_RANDOM"], value=2, variable=self.useMode, command=self._useModeChanged)
        self.rb_useRandN.grid(row=0,column=3,padx=3,pady=3,sticky="w")
        self.entry_randN = Entry(self.group_use, state="disabled")
        self.entry_randN.grid(row=0,column=4,padx=3,pady=3,sticky="w")
        self.group_use.grid(row=2,column=0,padx=3,pady=3,sticky="nesw")

        self.use_cscsv = IntVar(self, 0)
        self.group_src = LabelFrame(self.gens, text=_L["CS_SRC"])
        self.rb_rnet = Radiobutton(self.group_src, text=_L["CS_USEEDGES"], value=0, variable=self.use_cscsv)
        self.rb_rnet.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_cscsv = Radiobutton(self.group_src, text=_L["CS_USECSV"], value=1, variable=self.use_cscsv, state="disabled")
        self.rb_cscsv.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.rb_poly = Radiobutton(self.group_src, text=_L["CS_USEPOLY"], value=2, variable=self.use_cscsv,state="disabled")
        self.rb_poly.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.group_src.grid(row=1,column=0,padx=3,pady=3,sticky="nesw")

        self.fr = Frame(self.gens)
        self.lb_slots = Label(self.fr, text=_L["CS_SLOTS"])
        self.lb_slots.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.entry_slots = Entry(self.fr)
        self.entry_slots.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_slots.insert(0, "10")
        self.lb_seed = Label(self.fr, text=_L["CS_SEED"])
        self.lb_seed.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.entry_seed = Entry(self.fr)
        self.entry_seed.grid(row=0,column=3,padx=3,pady=3,sticky="w")
        self.entry_seed.insert(0, "0")
        self.fr.grid(row=0,column=0,padx=3,pady=3,sticky="nesw")
        
        self.pbuy = IntVar(self, 1)
        self.group_pbuy = LabelFrame(self.gens, text=_L["CS_PRICEBUY"])
        self.rb_pbuy0 = Radiobutton(self.group_pbuy, text=_L["CS_PB5SEGS"], value=0, variable=self.pbuy, command=self._pBuyChanged)
        self.rb_pbuy0.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_pbuy1 = Radiobutton(self.group_pbuy, text=_L["CS_PBFIXED"], value=1, variable=self.pbuy, command=self._pBuyChanged)
        self.rb_pbuy1.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_pbuy = Entry(self.group_pbuy)
        self.entry_pbuy.insert(0, "1.0")
        self.entry_pbuy.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.group_pbuy.grid(row=3,column=0,padx=3,pady=3,sticky="nesw")

        self.psell = IntVar(self, 1)
        self.group_psell = LabelFrame(self.gens, text=_L["CS_PRICESELL"])
        self.rb_psell0 = Radiobutton(self.group_psell, text=_L["CS_PB5SEGS"], value=0, variable=self.psell, command=self._pSellChanged)
        self.rb_psell0.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_psell1 = Radiobutton(self.group_psell, text=_L["CS_PBFIXED"], value=1, variable=self.psell, command=self._pSellChanged)
        self.rb_psell1.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_psell = Entry(self.group_psell)
        self.entry_psell.insert(0, "1.5")
        self.entry_psell.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.group_psell.grid(row=4,column=0,padx=3,pady=3,sticky="nesw")

        self.busMode = IntVar(self, 0)
        self.group_bus = LabelFrame(self.gens, text=_L["CS_BUSMODE"])
        self.rb_busGrid = Radiobutton(self.group_bus, text=_L["CS_BUSBYPOS"], value=0, variable=self.busMode, command=self._busModeChanged)
        self.rb_busGrid.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_busAll = Radiobutton(self.group_bus, text=_L["CS_BUSUSEALL"], value=1, variable=self.busMode, command=self._busModeChanged)
        self.rb_busAll.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.rb_busSel = Radiobutton(self.group_bus, text=_L["CS_BUSSELECTED"], value=2, variable=self.busMode, command=self._busModeChanged)
        self.rb_busSel.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.entry_bussel = Entry(self.group_bus, state="disabled")
        self.entry_bussel.grid(row=0,column=3,padx=3,pady=3,sticky="w")
        self.rb_busRandN = Radiobutton(self.group_bus, text=_L["CS_BUSRANDOM"], value=3, variable=self.busMode, command=self._busModeChanged)
        self.rb_busRandN.grid(row=0,column=4,padx=3,pady=3,sticky="w")
        self.entry_busrandN = Entry(self.group_bus, state="disabled")
        self.entry_busrandN.grid(row=0,column=5,padx=3,pady=3,sticky="w")
        self.group_bus.grid(row=5,column=0,padx=3,pady=3,sticky="nesw")

        self.btn_regen = Button(self.gens, text=_L["CS_BTN_GEN"], command=self.generate)
        self.btn_regen.grid(row=6,column=0,padx=3,pady=3,sticky="w")
        self.tree.setOnSave(self.save())

        self.cslist:List[CS] = []
    
    @property
    def saved(self):
        return self.tree.saved
    
    def save(self):
        def mkFunc(s:str):
            try:
                return ConstFunc(float(s))
            except:
                return SegFunc(eval(s))
            
        def _save(data:List[tuple]):
            if not self.file: return False
            assert len(self.cslist) == len(data)
            with open(self.file, "w") as f:
                f.write(f"<?xml version='1.0' encoding='utf-8'?>\n<root>\n")
                if self.csType == FCS:
                    for i, d in enumerate(data):
                        assert len(d) == 9
                        name, slots, bus, x, y, ol, maxpc, pbuy, pcalloc = d
                        c = self.cslist[i]
                        c._name = name
                        c._slots = slots
                        c._bus = bus
                        c._x = float(x)
                        c._y = float(y)
                        c._pc_lim1 = float(maxpc) / 3600
                        if ol == ALWAYS_ONLINE: ol = "[]"
                        c._offline = RangeList(eval(ol))
                        c._pbuy = OverrideFunc(mkFunc(pbuy))
                        f.write(c.to_xml())
                        f.write("\n")
                else:
                    for i, d in enumerate(data):
                        assert len(d) == 12
                        name, slots, bus, x, y, ol, maxpc, maxpd, pbuy, psell, pcalloc, pdalloc = d
                        c = self.cslist[i]
                        c._name = name
                        c._slots = slots
                        c._bus = bus
                        c._x = float(x)
                        c._y = float(y)
                        c._pc_lim1 = float(maxpc) / 3600
                        c._pd_lim1 = float(maxpd) / 3600
                        if ol == ALWAYS_ONLINE: ol = "[]"
                        c._offline = RangeList(eval(ol))
                        c._pbuy = OverrideFunc(mkFunc(pbuy))
                        c._psell = OverrideFunc(mkFunc(psell))
                        c._pc_alloc_str = pcalloc
                        c._pd_alloc_str = pdalloc
                        f.write(c.to_xml())
                        f.write("\n")
                f.write("</root>")
            return True
        return _save

    def FindCS(self, edge:str):
        for item in self.tree.get_children():
            if self.tree.item(item, 'values')[0] == edge:
                self.tree.tree.selection_set(item)
                self.tree.tree.focus(item)
                self.tree.tree.see(item)
                break
    
    def _on_btn_find_click(self):
        self.FindCS(self.entry_find.get())
    
    def setPoly(self, val:bool):
        if not val:
            self.rb_poly.configure(state="disabled")
            if self.use_cscsv.get() == 2:
                self.use_cscsv.set(0)
        else:
            self.rb_poly.configure(state="normal")
    
    def setCSCSV(self, val:bool):
        if not val:
            self.rb_cscsv.configure(state="disabled")
            if self.use_cscsv.get() == 1:
                self.use_cscsv.set(0)
        else:
            self.rb_cscsv.configure(state="normal")

    def _pBuyChanged(self):
        v = self.pbuy.get()
        if v == 0:
            self.entry_pbuy.config(state="disabled")
        else:
            self.entry_pbuy.config(state="normal")
    
    def _pSellChanged(self):
        v = self.psell.get()
        if v == 0:
            self.entry_psell.config(state="disabled")
        else:
            self.entry_psell.config(state="normal")
    
    def _useModeChanged(self):
        v = self.useMode.get()
        if v == 0:
            self.entry_sel.config(state="disabled")
            self.entry_randN.config(state="disabled")
        elif v == 1:
            self.entry_sel.config(state="normal")
            self.entry_randN.config(state="disabled")
        else:
            self.entry_sel.config(state="disabled")
            self.entry_randN.config(state="normal")
    
    def _busModeChanged(self):
        v = self.busMode.get()
        if v == 0 or v == 1:
            self.entry_bussel.config(state="disabled")
            self.entry_busrandN.config(state="disabled")
        elif v == 2:
            self.entry_bussel.config(state="normal")
            self.entry_busrandN.config(state="disabled")
        else:
            self.entry_bussel.config(state="disabled")
            self.entry_busrandN.config(state="normal")
    
    @errwrapper
    def generate(self):
        seed = try_int(self.entry_seed.get(), "seed")
        slots = try_int(self.entry_slots.get(), "slots")
        mode = "fcs" if self.csType == FCS else "scs"

        if self.useMode.get() == 0:
            cs = ListSelection.ALL
            csCount = -1
            givenCS = []
        elif self.useMode.get() == 1:
            cs = ListSelection.GIVEN
            csCount = -1
            givenCS = try_split(self.entry_sel.get(), "given CS")
            assert not (len(givenCS) == 0 or len(givenCS) == 1 and givenCS[0] == ""), "No given CS"
        else:
            cs = ListSelection.RANDOM
            csCount = try_int(self.entry_randN.get(), "random N of CS")
            givenCS = []
        use_grid = False
        busCount = -1
        givenbus = []
        if self.busMode.get() == 0:
            use_grid = True
            bus = ListSelection.ALL
        elif self.busMode.get() == 1:
            bus = ListSelection.ALL
        elif self.busMode.get() == 2:
            bus = ListSelection.GIVEN
            givenbus = try_split(self.entry_bussel.get(), "given bus")
            assert not (len(givenbus) == 0 or len(givenbus) == 1 and givenbus[0] == ""), "No given bus"
        else:
            bus = ListSelection.RANDOM
            busCount = try_int(self.entry_randN.get(), "random N of bus")
        
        if self.pbuy.get() == 0:
            pbuyM = PricingMethod.RANDOM
            pbuy = 1.0
        else:
            pbuyM = PricingMethod.FIXED
            pbuy = try_float(self.entry_pbuy.get(), "price buy")
        if self.csType == FCS:
            if self.psell.get() == 0:
                psellM = PricingMethod.RANDOM
                psell = 0
            else:
                psellM = PricingMethod.FIXED
                psell = try_float(self.entry_psell.get(), "price sell")
        else:
            psellM = PricingMethod.FIXED
            psell = 0
        self.btn_regen.config(state=DISABLED)
        self.gf(self, self.use_cscsv.get(), seed = seed, mode = mode, slots = slots,
                bus = bus, busCount = busCount, givenBus = givenbus,
                cs = cs, csCount = csCount, givenCS = givenCS, 
                priceBuyMethod = pbuyM, priceBuy = pbuy, priceSellMethod = psellM, 
                priceSell = psell, hasSell = self.csType == SCS, use_grid = use_grid)
    
    def load(self, file:str):
        self._Q.submit("loaded", self.__load, file)
            
    def clear(self):
        self.tree.clear()
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
    
    def __load(self, file:str):
        try:
            self.cslist = LoadCSList(file, self.csType)
        except Exception as e:
            showerr(f"Error loading {file}: {e}")
            return
        self.file = file
        self.tree.clear()
        self.lb_cnt.config(text=_L["LB_COUNT"].format(len(self.cslist)))
        if self.csType == FCS:
            for cs in self.cslist:
                ol = str(cs._offline) if len(cs._offline)>0 else ALWAYS_ONLINE
                v = (cs.name, cs.slots, cs.node, cs._x, cs._y, ol, cs._pc_lim1 * 3600, cs.pbuy, cs._pc_alloc_str)
                self._Q.delegate(self.tree.insert, "", "end", values=v)
        else:
            for cs in self.cslist:
                assert isinstance(cs, SCS)
                ol = str(cs._offline) if len(cs._offline)>0 else ALWAYS_ONLINE
                v = (cs.name, cs.slots, cs.node, cs._x, cs._y, ol, cs._pc_lim1 * 3600, cs._pd_lim1 * 3600, 
                            cs.pbuy, cs.psell, cs._pc_alloc_str, cs._pd_alloc_str)
                self._Q.delegate(self.tree.insert, "", "end", values=v)