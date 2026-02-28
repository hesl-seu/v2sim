from typing import Sequence
from v2sim.gui.common import *
from enum import Enum
from v2sim import BaseStation, CS, GS, ConstPriceGetter, ToUPriceGetter, LoadCSList, LoadGSList
from v2sim.gen import ListSelection, PricingMethod
from feasytools import SegFunc, RangeList
from .utils import *
from .controls import ScrollableTreeView, ALWAYS_ONLINE

_L = LangLib.Load(__file__)

class StationEditorMode(Enum):
    SCS = "scs"
    FCS = "fcs"
    GS = "gs"

class StationEditor(Frame):
    def __init__(self, master, generatorFunc, mode: StationEditorMode, file:str="", **kwargs):
        super().__init__(master, **kwargs)

        self._Q = EventQueue(self)
        self._Q.register("loaded", lambda: None)
        self.__mode = mode
        
        self.gf = generatorFunc
        self.file = file if file else ""
        
        self.tree = ScrollableTreeView(self, allowSave=True) 
        EM = EditMode
        headings = [
            ("Name", 120, _L["CSE_NAME"], EM.entry()),
            ("Bind", 120, _L["CSE_BIND"], EM.entry()),
            ("Slots", 120, _L["CSE_SLOTS_GS"] if mode == StationEditorMode.GS else _L["CSE_SLOTS_CS"], EM.spin(0, 100)),
            ("x", 60, _L["CSE_X"], EM.entry()),
            ("y", 60, _L["CSE_Y"], EM.entry()),
            ("Offline", 100, _L["CSE_OFFLINE"], EM.rangelist(hint=True)),
            ("PriceBuy", 120, _L["CSE_PRICEBUY"], EM.segfunc(), True),
        ]
        if mode != StationEditorMode.GS:
            headings.extend([
                ("PriceSell", 120, _L["CSE_PRICESELL"], EM.segfunc(), True),
                ("Bus", 120, _L["CSE_BUS"], EM.entry()),
                ("MaxPc", 130, _L["CSE_MAXPC"], EM.spin(0, 1000)),
                ("MaxPd", 130, _L["CSE_MAXPD"], EM.spin(0, 1000)),
                ("PcAlloc", 80, _L["CSE_PCALLOC"], EM.combo(values=["Average", "Prioritized"])),
                ("PdAlloc", 80, _L["CSE_PDALLOC"], EM.combo(values=["Average"])),
            ])
        
        self.tree.setheadings(*headings)
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
        self.entry_sel = Entry(self.group_use, state=DISABLED)
        self.entry_sel.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.rb_useRandN = Radiobutton(self.group_use, text=_L["CS_RANDOM"], value=2, variable=self.useMode, command=self._useModeChanged)
        self.rb_useRandN.grid(row=0,column=3,padx=3,pady=3,sticky="w")
        self.entry_randN = Entry(self.group_use, state=DISABLED)
        self.entry_randN.grid(row=0,column=4,padx=3,pady=3,sticky="w")
        self.group_use.grid(row=2,column=0,padx=3,pady=3,sticky="nesw")

        self.use_cscsv = IntVar(self, 0)
        self.group_src = LabelFrame(self.gens, text=_L["CS_SRC"])
        self.rb_rnet = Radiobutton(self.group_src, text=_L["CS_USENODES"], value=0, variable=self.use_cscsv)
        self.rb_rnet.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_cscsv = Radiobutton(self.group_src, text=_L["CS_USECSV"], value=1, variable=self.use_cscsv, state=DISABLED)
        self.rb_cscsv.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.rb_poly = Radiobutton(self.group_src, text=_L["CS_USEPOLY"], value=2, variable=self.use_cscsv, state=DISABLED)
        self.rb_poly.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.group_src.grid(row=1,column=0,padx=3,pady=3,sticky="nesw")

        self.fr = Frame(self.gens)
        self.lb_slots = Label(self.fr, text=_L["CS_SLOTS"])
        self.lb_slots.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.entry_slots = Entry(self.fr)
        self.entry_slots.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_slots.insert(0, "6" if mode == StationEditorMode.GS else "10")
        self.lb_seed = Label(self.fr, text=_L["CS_SEED"])
        self.lb_seed.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.entry_seed = Entry(self.fr)
        self.entry_seed.grid(row=0,column=3,padx=3,pady=3,sticky="w")
        self.entry_seed.insert(0, "0")
        self.allow_queue = BooleanVar(self, mode != StationEditorMode.SCS)
        self.cb_queue = Checkbutton(self.fr, text=_L["CS_ALLOWQUEUE"], variable=self.allow_queue)
        self.cb_queue.grid(row=0,column=4,padx=3,pady=3,sticky="w")
        self.fr.grid(row=0,column=0,padx=3,pady=3,sticky="nesw")
        
        self.pbuy = IntVar(self, 1)
        self.group_pbuy = LabelFrame(self.gens, text=_L["CS_PRICEBUY"])
        self.rb_pbuy0 = Radiobutton(self.group_pbuy, text=_L["CS_PB5SEGS"], value=0, variable=self.pbuy, command=self._pBuyChanged)
        self.rb_pbuy0.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.rb_pbuy1 = Radiobutton(self.group_pbuy, text=_L["CS_PBFIXED"], value=1, variable=self.pbuy, command=self._pBuyChanged)
        self.rb_pbuy1.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.entry_pbuy = Entry(self.group_pbuy)
        self.entry_pbuy.insert(0, "7.0" if mode == StationEditorMode.GS else "1.0")
        self.entry_pbuy.grid(row=0,column=2,padx=3,pady=3,sticky="w")
        self.group_pbuy.grid(row=3,column=0,padx=3,pady=3,sticky="nesw")

        if mode != StationEditorMode.GS:
            self.psell = IntVar(self, 0 if mode == StationEditorMode.FCS else 2)
            self.group_psell = LabelFrame(self.gens, text=_L["CS_PRICESELL"])
            self.rb_psellN = Radiobutton(self.group_psell, text=_L["CS_PBNONE"], value=0, variable=self.psell, command=self._pSellChanged)
            self.rb_psellN.grid(row=0,column=0,padx=3,pady=3,sticky="w")
            self.rb_psell0 = Radiobutton(self.group_psell, text=_L["CS_PB5SEGS"], value=1, variable=self.psell, command=self._pSellChanged)
            self.rb_psell0.grid(row=0,column=1,padx=3,pady=3,sticky="w")
            self.rb_psell1 = Radiobutton(self.group_psell, text=_L["CS_PBFIXED"], value=2, variable=self.psell, command=self._pSellChanged)
            self.rb_psell1.grid(row=0,column=2,padx=3,pady=3,sticky="w")
            self.entry_psell = Entry(self.group_psell)
            self.entry_psell.insert(0, "1.5")
            self.entry_psell.grid(row=0,column=3,padx=3,pady=3,sticky="w")
            self.group_psell.grid(row=4,column=0,padx=3,pady=3,sticky="nesw")
            self._pSellChanged()

            self.busMode = IntVar(self, 0)
            self.group_bus = LabelFrame(self.gens, text=_L["CS_BUSMODE"])
            self.rb_busGrid = Radiobutton(self.group_bus, text=_L["CS_BUSBYPOS"], value=0, variable=self.busMode, command=self._busModeChanged)
            self.rb_busGrid.grid(row=0,column=0,padx=3,pady=3,sticky="w")
            self.rb_busAll = Radiobutton(self.group_bus, text=_L["CS_BUSUSEALL"], value=1, variable=self.busMode, command=self._busModeChanged)
            self.rb_busAll.grid(row=0,column=1,padx=3,pady=3,sticky="w")
            self.rb_busSel = Radiobutton(self.group_bus, text=_L["CS_BUSSELECTED"], value=2, variable=self.busMode, command=self._busModeChanged)
            self.rb_busSel.grid(row=0,column=2,padx=3,pady=3,sticky="w")
            self.entry_bussel = Entry(self.group_bus, state=DISABLED)
            self.entry_bussel.grid(row=0,column=3,padx=3,pady=3,sticky="w")
            self.rb_busRandN = Radiobutton(self.group_bus, text=_L["CS_BUSRANDOM"], value=3, variable=self.busMode, command=self._busModeChanged)
            self.rb_busRandN.grid(row=0,column=4,padx=3,pady=3,sticky="w")
            self.entry_busrandN = Entry(self.group_bus, state=DISABLED)
            self.entry_busrandN.grid(row=0,column=5,padx=3,pady=3,sticky="w")
            self.group_bus.grid(row=5,column=0,padx=3,pady=3,sticky="nesw")
            self._busModeChanged()

        self.btn_regen = Button(self.gens, text=_L["CS_BTN_GEN"], command=self.generate)
        self.btn_regen.grid(row=6,column=0,padx=3,pady=3,sticky="w")
        self.tree.setOnSave(self.save())

        self.cslist:Sequence[BaseStation] = []
    
    @property
    def mode(self):
        return self.__mode
    
    @property
    def saved(self):
        return self.tree.saved
    
    def save(self):
        def mkFunc(s:str):
            try:
                return ConstPriceGetter(float(s))
            except:
                return ToUPriceGetter(SegFunc(eval(s)))
            
        def _save(data:List[tuple]):
            if not self.file: return False
            assert len(self.cslist) == len(data)
            from xml.etree.ElementTree import Element, ElementTree
            root = Element("root")
            for i, d in enumerate(data):
                if self.__mode == StationEditorMode.GS:
                    assert len(d) == 7
                    name, bind, slots, x, y, ol, pbuy = d
                    c = self.cslist[i]
                    assert isinstance(c, GS)
                else:
                    assert len(d) == 13
                    name, bind, slots, x, y, ol, pbuy, psell, bus, maxpc, maxpd, pcalloc, pdalloc = d
                    c = self.cslist[i]
                    assert isinstance(c, CS)
                    c._bus = bus
                    c._pc_lim1 = float(maxpc) / 3600
                    c._pd_lim1 = float(maxpd) / 3600
                    c._psell = mkFunc(psell)
                    c._pc_alloc_str = pcalloc
                    c._pd_alloc_str = pdalloc
                c._name = name
                c._bind = bind
                c._slots = slots
                c._x = float(x)
                c._y = float(y)
                if ol == ALWAYS_ONLINE: ol = "[]"
                c._offline = RangeList(eval(ol))
                c._pbuy = mkFunc(pbuy)
                root.append(c.to_xml())

            ElementTree(root).write(self.file, encoding="utf-8", xml_declaration=True)
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
            self.rb_poly.configure(state=DISABLED)
            if self.use_cscsv.get() == 2:
                self.use_cscsv.set(0)
        else:
            self.rb_poly.configure(state=NORMAL)
    
    def setCSCSV(self, val:bool):
        if not val:
            self.rb_cscsv.configure(state=DISABLED)
            if self.use_cscsv.get() == 1:
                self.use_cscsv.set(0)
        else:
            self.rb_cscsv.configure(state=NORMAL)

    def _pBuyChanged(self):
        v = self.pbuy.get()
        if v == 0:
            self.entry_pbuy.config(state=DISABLED)
        else:
            self.entry_pbuy.config(state=NORMAL)
    
    def _pSellChanged(self):
        v = self.psell.get()
        if v != 2:
            self.entry_psell.config(state=DISABLED)
        else:
            self.entry_psell.config(state=NORMAL)
    
    def _useModeChanged(self):
        v = self.useMode.get()
        if v == 0:
            self.entry_sel.config(state=DISABLED)
            self.entry_randN.config(state=DISABLED)
        elif v == 1:
            self.entry_sel.config(state=NORMAL)
            self.entry_randN.config(state=DISABLED)
        else:
            self.entry_sel.config(state=DISABLED)
            self.entry_randN.config(state=NORMAL)
    
    def _busModeChanged(self):
        v = self.busMode.get()
        if v == 0 or v == 1:
            self.entry_bussel.config(state=DISABLED)
            self.entry_busrandN.config(state=DISABLED)
        elif v == 2:
            self.entry_bussel.config(state=NORMAL)
            self.entry_busrandN.config(state=DISABLED)
        else:
            self.entry_bussel.config(state=DISABLED)
            self.entry_busrandN.config(state=NORMAL)

    @errwrapper
    def generate(self):
        seed = try_int(self.entry_seed.get(), _L["CSGUI_GEN_SEED"])
        slots = try_int(self.entry_slots.get(), _L["CSGUI_GEN_SLOTS"])
        que = self.allow_queue.get()

        if self.useMode.get() == 0:
            cs = ListSelection.ALL
            csCount = -1
            givenCS = []
        elif self.useMode.get() == 1:
            cs = ListSelection.GIVEN
            csCount = -1
            givenCS = try_split(self.entry_sel.get(), _L["CSGUI_GEN_GIVENCS"])
            assert not (len(givenCS) == 0 or len(givenCS) == 1 and givenCS[0] == ""), "No given CS"
        else:
            cs = ListSelection.RANDOM
            csCount = try_int(self.entry_randN.get(), _L["CSGUI_GEN_RANDOMNCS"])
            givenCS = []

        if self.__mode != StationEditorMode.GS:
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
                givenbus = try_split(self.entry_bussel.get(), _L["CSGUI_GEN_GIVENBUS"])
                assert not (len(givenbus) == 0 or len(givenbus) == 1 and givenbus[0] == ""), "No given bus"
            else:
                bus = ListSelection.RANDOM
                busCount = try_int(self.entry_randN.get(), _L["CSGUI_GEN_RANDOMNBUS"])
        
        if self.pbuy.get() == 0:
            pbuyM = PricingMethod.RANDOM
            pbuy = 1.0
        else:
            pbuyM = PricingMethod.FIXED
            pbuy = try_float(self.entry_pbuy.get(), _L["CSGUI_GEN_PRICEBUY"])
        
        if self.__mode != StationEditorMode.GS:
            if self.psell.get() == 0:
                hasSell = False
            elif self.psell.get() == 1:
                psellM = PricingMethod.RANDOM
                psell = 0
                hasSell = True
            else:
                psellM = PricingMethod.FIXED
                psell = try_float(self.entry_psell.get(), _L["CSGUI_GEN_PRICESELL"])
                hasSell = True
        
        self.btn_regen.config(state=DISABLED)
        if self.__mode != StationEditorMode.GS:
            if hasSell:
                self.gf(self, self.use_cscsv.get(), seed = seed, mode = self.__mode.value, slots = slots,
                        bus = bus, busCount = busCount, givenBus = givenbus, allowQueue=que,
                        station = cs, stationCount = csCount, givenStations = givenCS, 
                        priceBuyMethod = pbuyM, priceBuy = pbuy, priceSellMethod = psellM, 
                        priceSell = psell, hasSell = True, use_grid = use_grid)
            else:
                self.gf(self, self.use_cscsv.get(), seed = seed, mode = self.__mode.value, slots = slots,
                        bus = bus, busCount = busCount, givenBus = givenbus, allowQueue=que,
                        station = cs, stationCount = csCount, givenStations = givenCS, 
                        priceBuyMethod = pbuyM, priceBuy = pbuy, hasSell = False, use_grid = use_grid)
        else:
            self.gf(self, self.use_cscsv.get(), seed = seed, mode = self.__mode.value, slots = slots,
                    station = cs, stationCount = csCount, givenStations = givenCS, allowQueue=que,
                    priceBuyMethod = pbuyM, priceBuy = pbuy, hasSell = False, use_grid = False)
    
    def load(self, file:str):
        self._Q.submit("loaded", self.__load, file)
            
    def clear(self):
        self.tree.clear()
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
    
    def __load(self, file:str):
        try:
            if self.__mode != StationEditorMode.GS:
                self.cslist = LoadCSList(file)
            else:
                self.cslist = LoadGSList(file)
        except Exception as e:
            showerr(_L["ERROR_LOADING"].format(file, e))
            return
        self.file = file
        self.tree.clear()
        self.lb_cnt.config(text=_L["LB_COUNT"].format(len(self.cslist)))

        for cs in self.cslist:
            ol = str(cs._offline) if len(cs._offline)>0 else ALWAYS_ONLINE
            if self.__mode == StationEditorMode.GS:
                v = (cs._name, cs._bind, cs._slots, cs._x, cs._y, ol, cs._pbuy)
            else:
                assert isinstance(cs, CS)
                v = (cs._name, cs._bind, cs._slots, cs._x, cs._y, ol, cs._pbuy, cs._psell, 
                    cs.bus, cs._pc_lim1 * 3600, cs._pd_lim1 * 3600, cs._pc_alloc_str, cs._pd_alloc_str)
            self._Q.delegate(self.tree.insert, "", "end", values=v)