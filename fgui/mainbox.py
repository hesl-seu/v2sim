import os
import queue
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
import time
import traceback
from typing import Any, Optional, Callable, Union, Dict, List, Tuple, Set
from tkinter import filedialog
from tkinter import messagebox as MB
from fpowerkit import Grid as PowerGrid
from feasytools import RangeList, SegFunc, OverrideFunc, ConstFunc, PDUniform
import xml.etree.ElementTree as ET
import v2sim
from v2sim import *
from .langhelper import add_lang_menu
from .view import *
from .controls import ScrollableTreeView, empty_postfunc, EditMode, LogItemPad, PropertyPanel, PDFuncEditor, ALWAYS_ONLINE, parseEditMode, _removeprefix
from .network import NetworkPanel, OAfter

DEFAULT_GRID_NAME = "pdn.grid.xml"
DEFAULT_GRID = '<grid Sb="1MVA" Ub="10.0kV" model="ieee33" fixed-load="false" grid-repeat="1" load-repeat="8" />'

def showerr(msg:str):
    MB.showerror(_L["MB_ERROR"], msg)

_L = CustomLocaleLib.LoadFromFolder("resources/gui_main")

SIM_YES = "YES"
SIM_NO = "NO"
LOAD_CFG = "SUMO Config"
LOAD_FCS = "Fast CS"
LOAD_SCS = "Slow CS"
LOAD_NET = "Network"
LOAD_CSCSV = "CS CSV"
LOAD_PLG = "Plugins"
LOAD_GEN = "Instance"
EXT_COMP = "external_components"

    
class PluginEditor(ScrollableTreeView):
    def __init__(self, master, onEnabledSet:Callable[[Tuple[Any,...], str], None] = empty_postfunc, **kwargs):
        super().__init__(master, True, **kwargs)
        self.sta_pool = StaPool()
        self.plg_pool = PluginPool()
        if Path(EXT_COMP).exists():
            load_external_components(EXT_COMP, self.plg_pool, self.sta_pool)
        self.__onset = onEnabledSet
        self["show"] = 'headings'
        self["columns"] = ("Name", "Interval", "Enabled", "Online", "Extra")
        self.column("Name", width=120, stretch=NO)
        self.column("Interval", width=100, stretch=NO)
        self.column("Enabled", width=100, stretch=NO)
        self.column("Online", width=200, stretch=NO)
        self.column("Extra", width=200, stretch=YES)
        self.heading("Name", text=_L["SIM_PLGNAME"])
        self.heading("Interval", text=_L["SIM_EXEINTV"])
        self.heading("Enabled", text=_L["SIM_ENABLED"])
        self.heading("Online", text=_L["SIM_PLGOL"])
        self.heading("Extra", text=_L["SIM_PLGPROP"])
        self.setColEditMode("Interval", EditMode.SPIN, spin_from=1, spin_to=86400)
        self.setColEditMode("Enabled", EditMode.COMBO, combo_values=[SIM_YES, SIM_NO], post_func=onEnabledSet)
        self.setColEditMode("Online", EditMode.RANGELIST, rangelist_hint = True)
        self.setColEditMode("Extra", EditMode.DISABLED)
    
    def add(self, plg_name:str, interval:Union[int, str], enabled:str, online:Union[RangeList, str], extra:Dict[str, Any]):
        self.insert("", "end", values= (
            plg_name, interval, enabled, online, repr(extra)
        ))
        plg_type = self.plg_pool.GetPluginType(plg_name)
        assert issubclass(plg_type, PluginBase)
        self.setCellEditMode(plg_name, "Extra", EditMode.PROP, 
            prop_edit_modes = plg_type.ElemShouldHave().editor_dict(),
            prop_desc = plg_type.ElemShouldHave().desc_dict(),
            prop_default_mode = EditMode.ENTRY
        )
    
    def is_enabled(self, plg_name:str):
        for i in self.get_children():
            if self.item(i, 'values')[0] == "pdn":
                return self.item(i, 'values')[2] == SIM_YES
        return False       
        

class CSEditorGUI(Frame):
    def __init__(self, master, generatorFunc, canV2g:bool, file:str="", **kwargs):
        super().__init__(master, **kwargs)
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

        self.tree.setColEditMode("Edge", EditMode.ENTRY)
        self.tree.setColEditMode("Slots", EditMode.SPIN, spin_from = 0, spin_to = 100)
        self.tree.setColEditMode("Bus", EditMode.ENTRY)
        self.tree.setColEditMode("x", EditMode.ENTRY)
        self.tree.setColEditMode("y", EditMode.ENTRY)
        self.tree.setColEditMode("Online", EditMode.RANGELIST, rangelist_hint=True)
        self.tree.setColEditMode("MaxPc", EditMode.SPIN, spin_from = 0, spin_to = 1000)
        self.tree.setColEditMode("PriceBuy", EditMode.SEGFUNC)
        self.tree.setColEditMode("PcAlloc", EditMode.COMBO, combo_values=["Average", "Prioritized"])
        
        if canV2g:
            self.tree.heading("PriceSell", text=_L["CSE_PRICESELL"])
            self.tree.heading("MaxPd", text=_L["CSE_MAXPD"])
            self.tree.heading("PdAlloc", text=_L["CSE_PDALLOC"])
            self.tree.setColEditMode("PriceSell", EditMode.SEGFUNC)
            self.tree.setColEditMode("MaxPd", EditMode.SPIN, spin_from = 0, spin_to = 1000)
            self.tree.setColEditMode("PdAlloc", EditMode.COMBO, combo_values=["Average"])
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
                        c._node = bus
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
                        c._node = bus
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

    def generate(self):
        try:
            seed = int(self.entry_seed.get())
        except:
            showerr("Invalid seed")
            return
        try:
            slots = int(self.entry_slots.get())
        except:
            showerr("Invalid slots")
            return
        mode = "fcs" if self.csType == FCS else "scs"
        if self.useMode.get() == 0:
            cs = ListSelection.ALL
            csCount = -1
            givenCS = []
        elif self.useMode.get() == 1:
            cs = ListSelection.GIVEN
            csCount = -1
            try:
                givenCS = self.entry_sel.get().split(',')
            except:
                showerr("Invalid given CS")
                return
            if len(givenCS) == 0 or len(givenCS) == 1 and givenCS[0] == "":
                showerr("No given CS")
                return
        else:
            cs = ListSelection.RANDOM
            try:
                csCount = int(self.entry_randN.get())
            except:
                showerr("Invalid random N of CS")
                return
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
            try:
                givenbus = self.entry_bussel.get().split(',')
            except:
                showerr("Invalid given bus")
                return
            if len(givenbus) == 0 or len(givenbus) == 1 and givenbus[0] == "":
                showerr("No given bus")
                return
        else:
            bus = ListSelection.RANDOM
            try:
                busCount = int(self.entry_randN.get())
            except:
                showerr("Invalid random N of bus")
                return
        
        if self.pbuy.get() == 0:
            pbuyM = PricingMethod.RANDOM
            pbuy = 1.0
        else:
            pbuyM = PricingMethod.FIXED
            try:
                pbuy = float(self.entry_pbuy.get())
            except:
                showerr("Invalid price buy")
                return
        if self.csType == FCS:
            if self.psell.get() == 0:
                psellM = PricingMethod.RANDOM
                psell = 0
            else:
                psellM = PricingMethod.FIXED
                try:
                    psell = float(self.entry_psell.get())
                except:
                    showerr("Invalid price sell")
                    return
        else:
            psellM = PricingMethod.FIXED
            psell = 0
        self.btn_regen.config(state=DISABLED)
        self.gf(self, self.use_cscsv.get(), seed = seed, mode = mode, slots = slots,
                bus = bus, busCount = busCount, givenBus = givenbus,
                cs = cs, csCount = csCount, givenCS = givenCS, 
                priceBuyMethod = pbuyM, priceBuy = pbuy, priceSellMethod = psellM, 
                priceSell = psell, hasSell = self.csType == SCS, use_grid = use_grid)

    def __update_gui(self):
        cnt = 0
        LIMIT = 50
        try:
            while cnt < LIMIT:
                cnt += 1
                t, x = self.__q.get_nowait()
                if t == 'v':
                    self.tree.insert("", "end", values=x)
                elif t == 'a':
                    if x: x()
        except queue.Empty:
            pass
        if not self.__q_closed or cnt >= LIMIT:
            self.tree.after(10, self.__update_gui)
    
    def load(self, file:str, async_:bool = False, after:OAfter=None):
        if async_:
            self.__q = Queue()
            self.__q_closed = False
            threading.Thread(target=self.__load, args=(file, True, after), daemon=True).start()
            self.tree.after(10, self.__update_gui)
        else:
            self.__load(file, False, after)
    
    def clear(self):
        self.tree.clear()
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
    
    def __load(self, file:str, async_:bool=False, after:OAfter=None):
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
                if async_:
                    self.__q.put(('v',v))
                else:
                    self.tree.insert("", "end", values=v)
        else:
            for cs in self.cslist:
                assert isinstance(cs, SCS)
                ol = str(cs._offline) if len(cs._offline)>0 else ALWAYS_ONLINE
                v = (cs.name, cs.slots, cs.node, cs._x, cs._y, ol, cs._pc_lim1 * 3600, cs._pd_lim1 * 3600, 
                            cs.pbuy, cs.psell, cs._pc_alloc_str, cs._pd_alloc_str)
                if async_:
                    self.__q.put(('v',v))
                else:
                    self.tree.insert("", "end", values=v)
        if async_:
            self.__q.put(('a', after))
            self.__q_closed = False
        else:
            if after: after()
    
    
class CSCSVEditor(Frame):
    def __init__(self, master, down_worker, file:str="", **kwargs):
        super().__init__(master, **kwargs)
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

        if Path("amap_key.txt").exists():
            with open("amap_key.txt", "r") as f:
                self.entry_amapkey.insert(0, f.read().strip())
        
    def down(self):
        if MB.askyesno(_L["CSCSV_CONFIRM_TITLE"], _L["CSCSV_CONFIRM"]):
            self.down_wk()
    
    def __load(self, file:str, async_:bool=False, after:OAfter=None):
        try:
            with open(file, "r") as f:
                lines = f.readlines()
        except Exception as e:
            showerr(f"Error loading {file}: {e}")
            return
        self.file = file
        self.lb_cnt.config(text=_L["LB_COUNT"].format(len(lines) - 1))
        self.tree.clear()
        for cs in lines[1:]:
            vals = cs.strip().split(',')
            if async_:
                self.__q.put(('v', tuple(vals)))
            else:
                self.tree.insert("", "end", values=tuple(vals))
        if async_:
            self.__q.put(('a', after))
            self.__q_closed = True
        else:
            if after: after()

    def __update_gui(self):
        LIMIT = 50
        try:
            cnt = 0
            while cnt < LIMIT:
                cnt += 1
                t, x = self.__q.get_nowait()
                if t == 'v':
                    self.tree.insert("", "end", values=x)
                elif t == 'a':
                    if x: x()
        except queue.Empty:
            pass
        if not self.__q_closed or cnt >= LIMIT:
            self.tree.after(10, self.__update_gui)

    def load(self, file:str, async_:bool, after:OAfter=None):
        if async_:
            self.__q = Queue()
            self.__q_closed = False
            threading.Thread(target=self.__load, args=(file, True, after), daemon=True).start()
            self.tree.after(10, self.__update_gui)
        else:
            self.__load(file, False, after)
    
    def clear(self):
        self.lb_cnt.config(text=_L["LB_COUNT"].format(0))
        self.tree.clear()


class LoadingBox(Toplevel):
    def __init__(self, items:List[str], **kwargs):
        super().__init__(None, **kwargs)
        self.title("Loading...")
        self.geometry("400x300")
        self.cks:List[Label]=[]
        self.dkt:Dict[str,int]={}
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        for i, t in enumerate(items):
            Label(self, text=t).grid(column=0,row=i)
            self.cks.append(Label(self, text="..."))
            self.cks[-1].grid(column=1,row=i)
            self.dkt[t]=i
            self.rowconfigure(i, weight=1)
    
    def setText(self, itm:str, val:str):
        self.cks[self.dkt[itm]].configure(text=val)
        for x in self.cks:
            if x['text'] != _L['DONE']: break
        else:
            self.destroy()
    

class MainBox(Tk):
    def _OnPDNEnabledSet(self):
        def _setSimStat(itm:Tuple[Any,...], v:str):
            if itm[0] != "pdn": return
            t = v == SIM_YES
            for x in ("gen","bus","line","pvw","ess"):
                self.sim_statistic[x] = t
                self.sim_statistic.setEnabled(x, t)
        return _setSimStat
    
    def __init__(self, to_open:str = ""):
        super().__init__()
        self._Q = Queue()
        self.folder:str = to_open
        self.state:Optional[FileDetectResult] = None
        self.tg:Optional[TrafficGenerator] = None
        self._win()

        self.menu = Menu(self)
        self.menuFile = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_L["MENU_PROJ"], menu=self.menuFile)
        self.menuFile.add_command(label=_L["MENU_OPEN"], command=self.openFolder, accelerator='Ctrl+O')
        self.bind("<Control-o>", lambda e: self.openFolder())
        self.menuFile.add_command(label=_L["MENU_SAVEALL"], command=self.save, accelerator="Ctrl+S")
        self.bind("<Control-s>", lambda e: self.save())
        self.menuFile.add_separator()
        self.menuFile.add_command(label=_L["MENU_EXIT"], command=self.onDestroy, accelerator='Ctrl+Q')
        self.bind("<Control-q>", lambda e: self.onDestroy())
        add_lang_menu(self.menu)
        self.config(menu=self.menu)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.panel_info = Frame(self, borderwidth=1, relief="solid")
        self.panel_info.grid(row=0, column=0, padx=3, pady=3, sticky="nsew")

        self.lb_infotitle = Label(self.panel_info, text = _L["BAR_PROJINFO"], background="white")
        self.lb_infotitle.grid(row=0, column=0, columnspan=2, padx=3, pady=3, sticky="nsew")

        self.lb_fcs_indicatif = Label(self.panel_info, text = _L["BAR_FCS"])
        self.lb_fcs_indicatif.grid(row=1, column=0, padx=3, pady=3)
        self.lb_fcs = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_fcs.grid(row=1, column=1, padx=3, pady=3)

        self.lb_scs_indicatif = Label(self.panel_info, text = _L["BAR_SCS"])
        self.lb_scs_indicatif.grid(row=2, column=0, padx=3, pady=3)
        self.lb_scs = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_scs.grid(row=2, column=1, padx=3, pady=3)

        self.lb_grid_indicatif = Label(self.panel_info, text = _L["BAR_GRID"])
        self.lb_grid_indicatif.grid(row=3, column=0, padx=3, pady=3)
        self.lb_grid = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_grid.grid(row=3, column=1, padx=3, pady=3)

        self.lb_net_indicatif = Label(self.panel_info, text = _L["BAR_RNET"])
        self.lb_net_indicatif.grid(row=4, column=0, padx=3, pady=3)
        self.lb_net = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_net.grid(row=4, column=1, padx=3, pady=3)

        self.lb_veh_indicatif = Label(self.panel_info, text = _L["BAR_VEH"])
        self.lb_veh_indicatif.grid(row=5, column=0, padx=3, pady=3)
        self.lb_veh = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_veh.grid(row=5, column=1, padx=3, pady=3)

        self.lb_plg_indicatif = Label(self.panel_info, text = _L["BAR_PLG"])
        self.lb_plg_indicatif.grid(row=6, column=0, padx=3, pady=3)
        self.lb_plg = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_plg.grid(row=6, column=1, padx=3, pady=3)

        self.lb_cfg_indicatif = Label(self.panel_info, text = _L["BAR_SUMO"])
        self.lb_cfg_indicatif.grid(row=7, column=0, padx=3, pady=3)
        self.lb_cfg = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_cfg.grid(row=7, column=1, padx=3, pady=3)

        self.lb_taz_indicatif = Label(self.panel_info, text = _L["BAR_TAZ"])
        self.lb_taz_indicatif.grid(row=8, column=0, padx=3, pady=3)
        self.lb_taz = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_taz.grid(row=8, column=1, padx=3, pady=3)

        self.lb_py_indicatif = Label(self.panel_info, text = _L["BAR_ADDON"])
        self.lb_py_indicatif.grid(row=9, column=0, padx=3, pady=3)
        self.lb_py = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_py.grid(row=9, column=1, padx=3, pady=3)

        self.lb_taz_type_indicatif = Label(self.panel_info, text = _L["BAR_TAZTYPE"])
        self.lb_taz_type_indicatif.grid(row=10, column=0, padx=3, pady=3)
        self.lb_taz_type = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_taz_type.grid(row=10, column=1, padx=3, pady=3)

        self.lb_osm_indicatif = Label(self.panel_info, text = _L["BAR_OSM"])
        self.lb_osm_indicatif.grid(row=11, column=0, padx=3, pady=3)
        self.lb_osm = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_osm.grid(row=11, column=1, padx=3, pady=3)

        self.lb_poly_indicatif = Label(self.panel_info, text = _L["BAR_POLY"])
        self.lb_poly_indicatif.grid(row=12, column=0, padx=3, pady=3)
        self.lb_poly = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_poly.grid(row=12, column=1, padx=3, pady=3)

        self.lb_cscsv_indicatif = Label(self.panel_info, text = _L["BAR_CSCSV"])
        self.lb_cscsv_indicatif.grid(row=13, column=0, padx=3, pady=3)
        self.lb_cscsv = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_cscsv.grid(row=13, column=1, padx=3, pady=3)

        self.tabs = Notebook(self)
        self.tabs.grid(row=0, column=1, padx=3, pady=3, sticky="nsew")

        self.tab_sim = Frame(self.tabs)
        self.sim_time = LabelFrame(self.tab_sim, text=_L["SIM_BASIC"])
        self.sim_time.pack(fill="x", expand=False)
        self.lb_start = Label(self.sim_time, text=_L["SIM_BEGT"])
        self.lb_start.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.entry_start = Entry(self.sim_time)
        self.entry_start.insert(0, "0")
        self.entry_start.grid(row=0, column=1, padx=3, pady=3, sticky="w")
        self.lb_end = Label(self.sim_time, text=_L["SIM_ENDT"])
        self.lb_end.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.entry_end = Entry(self.sim_time)
        self.entry_end.insert(0, "172800")
        self.entry_end.grid(row=1, column=1, padx=3, pady=3, sticky="w")
        self.lb_step = Label(self.sim_time, text=_L["SIM_STEP"])
        self.lb_step.grid(row=2, column=0, padx=3, pady=3, sticky="w")
        self.entry_step = Entry(self.sim_time)
        self.entry_step.insert(0, "10")
        self.entry_step.grid(row=2, column=1, padx=3, pady=3, sticky="w")
        self.lb_seed = Label(self.sim_time, text=_L["SIM_SEED"])
        self.lb_seed.grid(row=3, column=0, padx=3, pady=3, sticky="w")
        self.entry_seed = Entry(self.sim_time)
        self.entry_seed.insert(0, "0")
        self.entry_seed.grid(row=3, column=1, padx=3, pady=3, sticky="w")
        self.ralgo = StringVar(self, "CH")
        self.lb_route_algo = Label(self.sim_time, text=_L["SIM_ROUTE_ALGO"])
        self.lb_route_algo.grid(row=4, column=0, padx=3, pady=3, sticky="w")
        self.combo_ralgo = Combobox(self.sim_time, textvariable=self.ralgo, values=["dijkstra", "astar", "CH", "CHWrapper"])
        self.combo_ralgo.grid(row=4, column=1, padx=3, pady=3, sticky="w")

        self.sim_load_last_state = BooleanVar(self, False)
        self.sim_cb_load_last_state = Checkbutton(self.sim_time, text=_L["SIM_LOAD_LAST_STATE"], variable=self.sim_load_last_state)
        self.sim_cb_load_last_state.grid(row=0, column=2, padx=3, pady=3, sticky="w")
        self.sim_save_on_abort = BooleanVar(self, False)
        self.sim_cb_save_on_abort = Checkbutton(self.sim_time, text=_L["SIM_SAVE_ON_ABORT"], variable=self.sim_save_on_abort)
        self.sim_cb_save_on_abort.grid(row=1, column=2, padx=3, pady=3, sticky="w")
        self.sim_save_on_finish = BooleanVar(self, False)
        self.sim_cb_save_on_finish = Checkbutton(self.sim_time, text=_L["SIM_SAVE_ON_FINISH"], variable=self.sim_save_on_finish)
        self.sim_cb_save_on_finish.grid(row=2, column=2, padx=3, pady=3, sticky="w")
        self.sim_copy_state = BooleanVar(self, False)
        self.sim_cb_copy_state = Checkbutton(self.sim_time, text=_L["SIM_COPY_STATE"], variable=self.sim_copy_state)
        self.sim_cb_copy_state.grid(row=3, column=2, padx=3, pady=3, sticky="w")
        self.sim_static_route = BooleanVar(self, False)
        self.sim_cb_static_route = Checkbutton(self.sim_time, text=_L["SIM_STATIC_ROUTE"], variable=self.sim_static_route)
        self.sim_cb_static_route.grid(row=4, column=2, padx=3, pady=3, sticky="w")
        self.sim_visualize = BooleanVar(self, False)
        self.sim_cb_visualize = Checkbutton(self.sim_time, text=_L["SIM_VISUALIZE"], variable=self.sim_visualize)
        self.sim_cb_visualize.grid(row=5, column=2, padx=3, pady=3, sticky="w")

        self.sim_plugins = LabelFrame(self.tab_sim, text=_L["SIM_PLUGIN"])
        self.sim_plglist = PluginEditor(self.sim_plugins, self._OnPDNEnabledSet())
        self.sim_plglist.pack(fill="both", expand=True)
        self.sim_plugins.pack(fill="x", expand=False)
        self.sim_plglist.setOnSave(self.savePlugins())

        self.sim_statistic = LogItemPad(self.tab_sim, _L["SIM_STAT"],{
            "fcs":_L["SIM_FCS"],
            "scs":_L["SIM_SCS"],
            "ev":_L["SIM_VEH"],
            "gen":_L["SIM_GEN"],
            "bus":_L["SIM_BUS"],
            "line":_L["SIM_LINE"],
            "pvw":_L["SIM_PVW"],
            "ess":_L["SIM_ESS"],
        })
        self.sim_statistic["ev"] = False
        self.sim_statistic.pack(fill="x", expand=False)

        self.sim_btn = Button(self.tab_sim, text=_L["SIM_START"], command=self.simulate)
        self.sim_btn.pack(anchor="w", padx=3, pady=3)
        self.tabs.add(self.tab_sim, text=_L["TAB_SIM"])

        self.tab_CsCsv = Frame(self.tabs)
        self.CsCsv_editor = CSCSVEditor(self.tab_CsCsv, self.CSCSVDownloadWorker)
        self.CsCsv_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_CsCsv, text=_L["TAB_CSCSV"])

        self.tab_FCS = Frame(self.tabs)
        self.FCS_editor = CSEditorGUI(self.tab_FCS, self.generateCS, False)
        self.FCS_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_FCS, text=_L["TAB_FCS"])

        self.tab_SCS = Frame(self.tabs)
        self.SCS_editor = CSEditorGUI(self.tab_SCS, self.generateCS, True)
        self.SCS_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_SCS, text=_L["TAB_SCS"])

        self.tab_Net = Frame(self.tabs)
        self.cv_net = NetworkPanel(self.tab_Net)
        self.cv_net.pack(fill=BOTH, expand=True)
        self.panel_net = LabelFrame(self.tab_Net, text=_L["RNET_TITLE"])
        self.lb_gridsave = Label(self.panel_net, text=_L["NOT_OPEN"])
        self.lb_gridsave.pack(side='left',padx=3,pady=3, anchor='w')
        def on_saved_changed(saved:bool):
            if saved:
                self.lb_gridsave.config(text=_L["SAVED"],foreground="green")
            else:
                self.lb_gridsave.config(text=_L["UNSAVED"],foreground="red")
        self.cv_net.save_callback = on_saved_changed
        self.btn_savegrid = Button(self.panel_net, text=_L["SAVE_GRID"], command=self.saveGrid)
        self.btn_savegrid.pack(side='left',padx=3,pady=3, anchor='w')
        self.lb_puvalues = Label(self.panel_net, text=_L["PU_VALS"].format('Null','Null'))
        self.lb_puvalues.pack(side='left',padx=3,pady=3, anchor='w')
        self.btn_savenetfig = Button(self.panel_net, text=_L["RNET_SAVE"], command=self.netsave)
        self.btn_savenetfig.pack(side="right", padx=3, pady=3, anchor="e")
        self.btn_draw = Button(self.panel_net, text=_L["RNET_DRAW"], command=self.draw)
        self.btn_draw.pack(side="right", padx=3, pady=3, anchor="e")
        self.entry_Ledges = Entry(self.panel_net)
        self.entry_Ledges.pack(side="right", padx=3, pady=3, anchor="e")
        self.lb_Ledges = Label(self.panel_net, text=_L["RNET_EDGES"])
        self.lb_Ledges.pack(side="right", padx=3, pady=3, anchor="e")
        
        self.panel_net.pack(fill="x", expand=False, anchor="s")
        self.tabs.add(self.tab_Net, text=_L["TAB_RNET"])

        self.tab_Veh = Frame(self.tabs)
        self.fr_veh_basic = LabelFrame(self.tab_Veh,text=_L["VEH_BASIC"])
        self.fr_veh_basic.pack(fill="x", expand=False)
        self.lb_carcnt = Label(self.fr_veh_basic, text=_L["VEH_COUNT"])
        self.lb_carcnt.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.entry_carcnt = Entry(self.fr_veh_basic)
        self.entry_carcnt.insert(0, "10000")
        self.entry_carcnt.grid(row=0, column=1, padx=3, pady=3, sticky="w")
        self.lb_daycnt = Label(self.fr_veh_basic, text=_L["VEH_DAY_COUNT"])
        self.lb_daycnt.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.entry_daycnt = Entry(self.fr_veh_basic)
        self.entry_daycnt.insert(0, "7")
        self.entry_daycnt.grid(row=1, column=1, padx=3, pady=3, sticky="w")
        self.lb_v2gprop = Label(self.fr_veh_basic, text=_L["VEH_V2GPROP"])
        self.lb_v2gprop.grid(row=2, column=0, padx=3, pady=3, sticky="w")
        self.entry_v2gprop = Entry(self.fr_veh_basic)
        self.entry_v2gprop.insert(0, "1.00")
        self.entry_v2gprop.grid(row=2, column=1, padx=3, pady=3, sticky="w")
        self.lb_v2gprop_info = Label(self.fr_veh_basic, text=_L["VEH_V2GPROP_INFO"])
        self.lb_v2gprop_info.grid(row=2, column=2, padx=3, pady=3, sticky="w")
        self.lb_carseed = Label(self.fr_veh_basic, text=_L["VEH_SEED"])
        self.lb_carseed.grid(row=3, column=0, padx=3, pady=3, sticky="w")
        self.entry_carseed = Entry(self.fr_veh_basic)
        self.entry_carseed.insert(0, "0")
        self.entry_carseed.grid(row=3, column=1, padx=3, pady=3, sticky="w")

        self.veh_pars = PropertyPanel(self.tab_Veh, {
            "Omega":repr(PDUniform(5.0, 10.0)),
            "KRel":repr(PDUniform(1.0, 1.2)),
            "KSC":repr(PDUniform(0.4, 0.6)),
            "KFC":repr(PDUniform(0.2, 0.25)),
            "KV2G":repr(PDUniform(0.65, 0.75)),
        }, default_edit_mode=EditMode.PDFUNC, desc = {
            "Omega": _L["VEH_OMEGA_DESC"],
            "KRel": _L["VEH_KREL_DESC"],
            "KSC": _L["VEH_KSC_DESC"],
            "KFC": _L["VEH_KFC_DESC"],
            "KV2G": _L["VEH_KV2G_DESC"],
        })
        self.veh_pars.pack(fill="x", expand=False, pady=10)

        self.veh_gen_src = IntVar(self, 0)
        self.fr_veh_src = LabelFrame(self.tab_Veh,text=_L["VEH_ODSRC"])
        self.fr_veh_src.pack(fill="x", expand=False)
        self.rb_veh_src0 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODAUTO"], value=0, variable=self.veh_gen_src)
        self.rb_veh_src0.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_src1 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODTAZ"], value=1, variable=self.veh_gen_src)
        self.rb_veh_src1.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_src2 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODPOLY"], value=2, variable=self.veh_gen_src)
        self.rb_veh_src2.grid(row=2, column=0, padx=3, pady=3, sticky="w")

        self.veh_route_cache = IntVar(self, 0)
        self.fr_veh_route_cache = LabelFrame(self.tab_Veh,text=_L["VEH_ROUTE_CACHE"])
        self.fr_veh_route_cache.pack(fill="x", expand=False)
        self.rb_veh_route_cache0 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_NO_CACHE"], value=0, variable=self.veh_route_cache)
        self.rb_veh_route_cache0.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_route_cache1 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_RUNTIME_CACHE"], value=1, variable=self.veh_route_cache)
        self.rb_veh_route_cache1.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_route_cache2 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_STATIC_CACHE"], value=2, variable=self.veh_route_cache)
        self.rb_veh_route_cache2.grid(row=2, column=0, padx=3, pady=3, sticky="w")

        self.btn_genveh = Button(self.tab_Veh, text=_L["VEH_GEN"], command=self.generateVeh)
        self.btn_genveh.pack(anchor="w")
        self.tabs.add(self.tab_Veh, text=_L["TAB_VEH"])

        self.sbar = Label(self, text=_L["STA_READY"], anchor="w")
        self.sbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.onDestroy)
        self.after(100, self._loop)

        if self.folder != "":
            self.after(200, self._load)
    
    def netsave(self):
        ret = filedialog.asksaveasfilename(
            defaultextension=".eps",
            filetypes=[
                (_L["EXT_EPS"],".eps"),             
            ]
        )
        if ret == "": return
        try:
            self.cv_net.savefig(ret)
        except RuntimeError:
            showerr(_L["RNET_SAVE_ERR"])
            return
        self.setStatus("Figure saved")

    def veh_par_edit(self, var:StringVar):
        def _f():
            e = PDFuncEditor(var)
            e.wait_window()
        return _f

    @property
    def saved(self):
        return self.sim_plglist.saved and self.FCS_editor.saved and self.SCS_editor.saved and self.cv_net.saved
    
    def save(self):
        if not self.sim_plglist.saved: self.sim_plglist.save()
        if not self.FCS_editor.saved: self.FCS_editor.save()
        if not self.SCS_editor.saved: self.SCS_editor.save()
        if not self.cv_net.saved: self.saveGrid()
    
    def saveGrid(self):
        defpath = self.folder+"/"+DEFAULT_GRID_NAME
        assert self.state is not None
        if self.state.grid:
            path = self.state.grid
            os.remove(path)
            if not path.lower().endswith(".xml"): path = defpath
        else:
            path = defpath
        self.cv_net.saveGrid(path)
        
    def onDestroy(self):
        if not self.saved:
            ret = MB.askyesnocancel(_L["MB_INFO"], _L["MB_EXIT_SAVE"])
            if ret is None: return
            if ret: self.save()
        self.destroy()

    def simulate(self):
        if not self.__checkFolderOpened():
            return
        try:
            start = int(self.entry_start.get())
            end = int(self.entry_end.get())
            step = int(self.entry_step.get())
            seed = int(self.entry_seed.get())
        except:
            showerr("Invalid time")
            return
        if not self.state:
            showerr("No project loaded")
            return
        if "scs" not in self.state:
            showerr("No SCS loaded")
            return
        if "fcs" not in self.state:
            showerr("No FCS loaded")
            return
        if "veh" not in self.state:
            showerr("No vehicles loaded")
            return
        logs = []
        for x in ("fcs","scs","ev","gen","bus","line","pvw","ess"):
            if self.sim_statistic[x]:
                logs.append(x)
        if not logs:
            showerr(_L["NO_STA"])
            return
        if not self.saved:
            if not MB.askyesno(_L["MB_INFO"],_L["MB_SAVE_AND_SIM"]): return
            self.save()

        #Check SUMOCFG
        if not self.state.cfg:
            showerr(_L["NO_SUMO_CFG"])
            return
        
        cflag, tr, route_file_name = FixSUMOConfig(self.state.cfg, start, end)
        if cflag:
            if MB.askyesno(_L["MB_INFO"],_L["MB_CFG_MODIFY"]):
                tr.write(self.state.cfg)
                route_path = Path(self.state.cfg).absolute().parent / route_file_name
                if route_file_name.strip() != "" and route_path.exists():
                    route_path.unlink()
            else:
                return
        
        # If PDN is enabled, check if cvxpy and ecos are installed
        if self.sim_plglist.is_enabled("pdn"):
            try:
                import cvxpy # type: ignore
                import ecos # type: ignore
            except ImportError as e:
                if MB.askyesno(_L["MB_INFO"], _L["MB_PDN_REQUIRED"]):
                    os.system(f"{sys.executable} -m pip install cvxpy ecos")
                else:
                    return
        
        # Save preference
        vcfg = V2SimConfig()
        vcfg.start_time = start
        vcfg.end_time = end
        vcfg.traffic_step = step
        vcfg.seed = seed
        vcfg.visualize = self.sim_visualize.get()
        vcfg.load_state = self.sim_load_last_state.get()
        vcfg.save_state_on_abort = self.sim_save_on_abort.get()
        vcfg.save_state_on_finish = self.sim_save_on_finish.get()
        vcfg.copy_state = self.sim_copy_state.get()
        vcfg.force_caching = self.sim_static_route.get()
        vcfg.routing_method = self.ralgo.get()
        vcfg.stats = logs
        vcfg.save(self.folder + "/preference.v2simcfg")
            
        commands = [sys.executable, "sim_single.py",
                    "-d", '"'+self.folder+'"', 
                    "-b", str(start), 
                    "-e", str(end), 
                    "-l", str(step), 
                    "-log", ','.join(logs),
                    "-seed", str(seed),
                    "--load-last-state" if self.sim_load_last_state.get() else "",
                    "--save-on-abort" if self.sim_save_on_abort.get() else "",
                    "--save-on-finish" if self.sim_save_on_finish.get() else "",
                    "--route-algo", self.ralgo.get(),
                    "--static-routing" if self.sim_static_route.get() else "",
                ]
        
        visualize = self.sim_visualize.get()
        if platform.system() == "Windows":
            with open(v2sim.traffic.win_vis.__file__,"w") as f:
                f.write(f"WINDOWS_VISUALIZE = {visualize}")
        else:
            if visualize: commands.append("--show")
        self.destroy()
        try:
            os.system(" ".join(commands))
        except KeyboardInterrupt:
            pass
        

    def savePlugins(self):
        def _save(data:List[tuple]):
            if not self.__checkFolderOpened():
                return False
            self.setStatus(_L["SAVE_PLG"])
            if self.state and "plg" in self.state:
                filename = self.state["plg"]
            else:
                filename = self.folder + "/plugins.plg.xml"
            try:
                rt = ET.Element("root")
                with open(filename, "w") as f:
                    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    for d in data:
                        attr = {"interval":str(d[1]), "enabled":str(d[2])}
                        attr.update(eval(d[4]))
                        for k,v in attr.items():
                            if not isinstance(v, str):
                                attr[k] = str(v)
                        e = ET.Element(d[0], attr)
                        if d[3] != ALWAYS_ONLINE:
                            ol = ET.Element("online")
                            lst = eval(d[3])
                            for r in lst:
                                ol.append(ET.Element("item", {"btime":str(r[0]), "etime":str(r[1])}))
                            e.append(ol)
                        rt.append(e)
                    f.write(ET.tostring(rt, "unicode", ).replace("><", ">\n<"))
                pass
            except Exception as e:
                self.setStatus(f"Error: {e}")
                traceback.print_exc()
                showerr(f"Error saving plugins: {e}")
                return False
            self.setStatus("Plugins saved")
            return True
        return _save
    
    def __checkFolderOpened(self):
        if not self.folder:
            showerr(_L["PROJ_NO_OPEN"])
            return False
        return True
    
    def _loop(self):
        neww = -1
        newh = -1
        while not self._Q.empty():
            try:
                t, d = self._Q.get_nowait()
            except Empty:
                self.after(100, self._loop)
                return
            if t == "DoneOK":
                self.setStatus(_L["STA_READY"])
            elif t == "DoneErr":
                self.setStatus(f"Error: {d}")
                showerr(f"Error: {d}")
            elif t == "Resized":
                neww, newh = d
                neww = neww - 10
                newh = newh - 80
        self.after(100, self._loop)
    
    def _load_tg(self, after:OAfter=None):
        try:
            self.tg = TrafficGenerator(self.folder)
        except Exception as e:
            traceback.print_exc()
            showerr(f"Error loading traffic generator: {e}")
            self.tg = None
        else:
            if after: after()
    
    def _load(self,loads:Optional[List[str]]=None, async_:bool = True):
        if not self.folder:
            showerr("No project folder selected")
            return
        if loads is None: loads = [
            LOAD_GEN, LOAD_CFG, LOAD_FCS, LOAD_SCS, LOAD_CSCSV, LOAD_NET, LOAD_PLG
        ]
        frm = LoadingBox(loads)
        self.after(100, self.__load_part2, set(loads), async_, frm)
    
    def __load_part2(self, loads:Set[str], async_:bool, frm:LoadingBox):
        self.state = res = DetectFiles(self.folder)
        self.title(f"{_L['TITLE']} - {Path(self.folder).name}")
        # Check if grid exists
        if not res.grid: 
            with open(self.folder+"/"+DEFAULT_GRID_NAME,"w") as f:
                f.write(DEFAULT_GRID)
            self.state = res = DetectFiles(self.folder)
        
        # Load traffic generator
        if LOAD_GEN in loads:
            threading.Thread(target = self._load_tg, args=(
                lambda:frm.setText(LOAD_GEN, _L['DONE']),
            ), daemon = True).start()

        # Load SUMO config
        if LOAD_CFG in loads:
            if res.cfg:
                st,et,x = GetTimeAndNetwork(res.cfg)
                if st == -1: st = 0
                if et == -1: et = 172800
                self.entry_start.delete(0, END)
                self.entry_start.insert(0, str(st))
                self.entry_end.delete(0, END)
                self.entry_end.insert(0, str(et))
            frm.setText(LOAD_CFG, _L['DONE'])
        
        # Load FCS
        if LOAD_FCS in loads:
            self._load_fcs(async_, 
                lambda: frm.setText(LOAD_FCS, _L['DONE']))

        # Load SCS
        if LOAD_SCS in loads:
            self._load_scs(async_, 
                lambda: frm.setText(LOAD_SCS, _L['DONE']))
        
        # Load CSCSV
        if LOAD_CSCSV in loads:
            self._load_cscsv(async_, 
                lambda: frm.setText(LOAD_CSCSV, _L['DONE']))
        
        # Load plugins
        if LOAD_PLG in loads:
            self._load_plugins()
            frm.setText(LOAD_PLG,_L['DONE'])
        
        self.rb_veh_src2.configure(state="normal" if "poly" in res else "disabled")
        self.rb_veh_src1.configure(state="normal" if "taz" in res else "disabled")
        
        self.state = res = DetectFiles(self.folder)

        if LOAD_NET in loads:
            self.cv_net.clear()
            self._load_network(self.tabs.select(), async_, 
                lambda: frm.setText(LOAD_NET, _L['DONE']))
        
        def setText(lb:Label, itm:str, must:bool = False):
            if itm in res:
                lb.config(text=Path(res[itm]).name, foreground="black")
            else:
                lb.config(text="None", foreground="red" if must else "black")
        
        setText(self.lb_fcs, "fcs", True)
        setText(self.lb_scs, "scs", True)
        setText(self.lb_grid, "grid")
        setText(self.lb_net, "net", True)
        setText(self.lb_veh, "veh", True)
        setText(self.lb_plg, "plg")
        setText(self.lb_cfg, "cfg")
        setText(self.lb_taz, "taz")
        setText(self.lb_py, "py")
        setText(self.lb_taz_type, "taz_type")
        setText(self.lb_osm, "osm")
        setText(self.lb_poly, "poly")
        setText(self.lb_cscsv, "cscsv")

        if self.state.pref:
            vcfg = V2SimConfig.load(self.state.pref)
            self.entry_start.delete(0, END)
            self.entry_start.insert(0, str(vcfg.start_time))
            self.entry_end.delete(0, END)
            self.entry_end.insert(0, str(vcfg.end_time))
            self.entry_step.delete(0, END)
            self.entry_step.insert(0, str(vcfg.traffic_step))
            self.entry_seed.delete(0, END)
            self.entry_seed.insert(0, str(vcfg.seed))
            self.ralgo.set(vcfg.routing_method)
            self.sim_save_on_finish.set(vcfg.save_state_on_finish)
            self.sim_save_on_abort.set(vcfg.save_state_on_abort)
            self.sim_load_last_state.set(vcfg.load_state)
            self.sim_visualize.set(vcfg.visualize)
            self.sim_static_route.set(vcfg.force_caching)
            if vcfg.stats:
                for x in vcfg.stats:
                    if x in self.sim_statistic:
                        self.sim_statistic[x] = True
                    else:
                        showerr(f"Unknown statistic: {x}")

        self.setStatus(_L["STA_READY"])
        if len(loads) == 0: frm.destroy()
    
    def _load_plugins(self):
        
        plg_set:Set[str] = set()
        plg_enabled_set:Set[str] = set()

        self.sim_plglist.clear()
        assert self.state is not None
        if self.state.plg:
            et = ReadXML(self.state.plg)
            if et is None:
                showerr("Error loading plugins")
                return
            rt = et.getroot()
            if rt is None:
                showerr("Error loading plugins")
                return
            for p in rt:
                try:
                    plg_type = self.sim_plglist.plg_pool.GetPluginType(p.tag.lower())
                except KeyError:
                    showerr(f"Unknown plugin type: {p.tag}")
                    continue
                assert issubclass(plg_type, PluginBase), "Plugin type is not a subclass of PluginBase"

                attr = plg_type.ElemShouldHave().default_value_dict()
                plg_set.add(p.tag.lower())

                # Check online attribute
                olelem = p.find("online")
                if olelem is not None: ol_str = RangeList(olelem)
                else: ol_str = ALWAYS_ONLINE

                # Check enabled attribute
                enabled = p.attrib.pop("enabled", SIM_YES)
                if enabled.upper() != SIM_NO:
                    enabled = SIM_YES
                    plg_enabled_set.add(p.tag.lower())
                
                # Check interval attribute
                intv = p.attrib.pop("interval")
                attr.update(p.attrib)
                self.sim_plglist.add(p.tag, intv, enabled, ol_str, attr)

        # Check if PDN exists
        if "pdn" not in plg_set:
            pdn_attr_default = PluginPDN.ElemShouldHave().default_value_dict()
            self.sim_plglist.add("pdn", 300, SIM_YES, ALWAYS_ONLINE, pdn_attr_default)
            plg_set.add("pdn")
            plg_enabled_set.add("pdn")
        
        t = "pdn" in plg_set and "pdn" in plg_enabled_set

        for x in ("gen","bus","line","pvw","ess"):
            self.sim_statistic[x] = t
            self.sim_statistic.setEnabled(x, t)
        
        # Check if V2G exists
        if "v2g" not in plg_set:
            self.sim_plglist.add("v2g", 300, SIM_YES, ALWAYS_ONLINE, {})
        if not self.state.plg:
            self.sim_plglist.save()
        
    def _load_fcs(self, async_:bool = False, afterx:OAfter=None):
        assert self.state is not None
        def after():
            assert self.state is not None
            v = "fcs" in self.state
            self.sim_statistic["fcs"]=v
            self.sim_statistic.setEnabled("fcs", v)
            self.FCS_editor.setPoly("poly" in self.state)
            self.FCS_editor.setCSCSV("cscsv" in self.state)
            if afterx: afterx()
        if self.state.fcs:
            self.FCS_editor.load(self.state.fcs, async_, after)
        else:
            self.FCS_editor.clear()
            after()
        
    def _load_scs(self, async_:bool = False, afterx:OAfter=None):
        assert self.state is not None
        def after():
            assert self.state is not None
            v = "scs" in self.state
            self.sim_statistic["scs"]=v
            self.sim_statistic.setEnabled("scs", v)
            self.SCS_editor.setPoly("poly" in self.state)
            self.SCS_editor.setCSCSV("cscsv" in self.state)
            if afterx: afterx()
        if self.state.scs:
            self.SCS_editor.load(self.state.scs, async_, after)
        else:
            self.SCS_editor.clear()
            after()

    def _load_cscsv(self, async_:bool = False, after:OAfter=None):
        assert self.state is not None
        if self.state.cscsv:
            self.CsCsv_editor.load(self.state.cscsv, async_, after)
        else:
            self.CsCsv_editor.clear()
            if after: after()
    
    def _load_network(self, tab_ret, async_:bool = False, after:OAfter=None):
        if self.state and self.state.net:
            self.tabs.select(self.tab_Net)
            time.sleep(0.01)
            self.tabs.select(tab_ret)
            self.lb_gridsave.config(text=_L["SAVED"],foreground="green")
            def work():
                assert self.state is not None and self.state.net is not None
                if self.state.grid:
                    self.cv_net.setGrid(PowerGrid.fromFile(self.state.grid))
                assert self.cv_net.Grid is not None
                self.lb_puvalues.configure(text=_L["PU_VALS"].format(self.cv_net.Grid.Ub,self.cv_net.Grid.Sb_MVA))
                self.cv_net.setRoadNet(RoadNetConnectivityChecker(self.state.net,
                    self.state.fcs if self.state.fcs else "",
                    self.state.scs if self.state.scs else "",
                ), async_ = async_, after=after)
            if async_:
                threading.Thread(target=work,daemon=True).start()
            else:
                work()

    def openFolder(self):
        init_dir = Path("./cases")
        if not init_dir.exists(): init_dir.mkdir(parents=True, exist_ok=True)
        folder = filedialog.askdirectory(initialdir=str(init_dir),mustexist=True,title="Select project folder")
        if folder:
            self.folder = str(Path(folder))
            self._load()
    
    def generateCS(self, ctl:CSEditorGUI, cscsv_mode:int, **kwargs):
        if not self.tg:
            showerr("No traffic generator loaded")
            return
        self.setStatus("Generating CS...")
        if cscsv_mode == 0:
            cs_file = ""
            poly_file = ""
        elif cscsv_mode == 1:
            cs_file = self.state.cscsv if self.state else ""
            poly_file = ""
        else:
            cs_file = ""
            poly_file = self.state.poly if self.state else ""
        use_grid = kwargs.pop("use_grid", False)
        assert self.state is not None
        if use_grid:
            if self.state.grid is None:
                showerr("No grid loaded")
                return
            kwargs["grid_file"] = self.state.grid
        kwargs["cs_file"] = cs_file
        kwargs["poly_file"] = poly_file

        def work():
            try:
                if not self.tg: return
                self.tg._CS(**kwargs)
                if kwargs["mode"] == "fcs":
                    self._load([LOAD_FCS, LOAD_GEN])
                else:
                    self._load([LOAD_SCS, LOAD_GEN])
                self._Q.put(("DoneOK", None))
            except Exception as e:
                print(f"\nError generating CS: {e}")
                traceback.print_exc()
                self._Q.put(("DoneErr", e))
            ctl.btn_regen.config(state=NORMAL)
        threading.Thread(target=work,daemon=True).start()    
    
    def generateVeh(self):
        if not self.tg:
            showerr(_L["MSG_NO_TRAFFIC_GEN"])
            return
        if not self.__checkFolderOpened(): return
        self.setStatus(_L["STA_GEN_VEH"])
        try:
            carcnt = int(self.entry_carcnt.get())
        except:
            showerr(_L["MSG_INVALID_VEH_CNT"])
            return
        try:
            carseed = int(self.entry_carseed.get())
        except:
            showerr(_L["MSG_INVALID_VEH_SEED"])
            return
        try:
            day_count = int(self.entry_daycnt.get())
        except:
            showerr(_L["MSG_INVALID_VEH_DAY_CNT"])
            return
        try:
            pars = self.veh_pars.getAllData()
            new_pars = {
                "v2g_prop":float(self.entry_v2gprop.get()),
                "omega":eval(pars["Omega"]),
                "krel":eval(pars["KRel"]),
                "ksc":eval(pars["KSC"]),
                "kfc":eval(pars["KFC"]),
                "kv2g":eval(pars["KV2G"]),
            }
        except:
            showerr("Invalid Vehicle parameters")
            return
        if self.veh_gen_src.get() == 0:
            mode = TripsGenMode.AUTO
        elif self.veh_gen_src.get() == 1:
            mode = TripsGenMode.TAZ
        else:
            mode = TripsGenMode.POLY
        route_cache = RoutingCacheMode(self.veh_route_cache.get())
        self.btn_genveh.config(state = DISABLED)
        def work():
            try:
                assert self.tg
                self.tg.EVTrips(carcnt, carseed, day_count, mode = mode, route_cache = route_cache, **new_pars)
                self._load([])
                self._Q.put(("DoneOK", None))
            except Exception as e:
                self._Q.put(("DoneErr", e))
            self.btn_genveh.config(state = NORMAL)
        threading.Thread(target=work,daemon=True).start()

    def draw(self):
        if not self.__checkFolderOpened(): return
        self.cv_net.UnlocateAllEdges()
        s = set(x.strip() for x in self.entry_Ledges.get().split(','))
        self.cv_net.LocateEdges(s)

    def CSCSVDownloadWorker(self):
        if not self.__checkFolderOpened(): return
        self.setStatus("Downloading CS CSV...")
        key = self.CsCsv_editor.entry_amapkey.get()
        def work():
            try:
                csQuery(self.folder,"",key,True)
                self._load([LOAD_CSCSV])
            except Exception as e:
                self._Q.put(('DoneErr', f"Error downloading CS CSV: {e}"))
                return
            self._Q.put(('DoneOK',None))
        threading.Thread(target=work,daemon=True).start()
        
    def setStatus(self, text:str):
        self.sbar.config(text=text)

    def _win(self):
        self.title(_L["TITLE"])

if __name__ == "__main__":
    win = MainBox()
    win.mainloop()