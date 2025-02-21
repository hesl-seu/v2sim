import gzip
from pathlib import Path
import pickle
from queue import Queue
import threading, os
from typing import Literal
from fgui.view import *
from fgui import ScrollableTreeView, TripsFrame
from v2sim import CustomLocaleLib, AdvancedPlot, ReadOnlyStatistics
from tkinter import filedialog
from tkinter import messagebox as MB

from v2sim.traffic.cs import CS
from v2sim.traffic.cslist import CSList
from v2sim.traffic.ev import EV
from v2sim.traffic.evdict import EVDict

_L = CustomLocaleLib.LoadFromFolder("resources/gui_viewer")

ITEM_ALL = _L["ITEM_ALL"]
ITEM_SUM = _L["ITEM_SUM"]
ITEM_ALL_G = "<All common generators>"
ITEM_ALL_V2G = "<All V2G stations>"
ITEM_LOADING = "Loading..."

class OptionBox(Frame):
    def __init__(self, master, options:dict[str, str], **kwargs):
        super().__init__(master, **kwargs)
        self._bools:list[BooleanVar] = []
        self._ctls:list[Checkbutton] = []
        self._mp:dict[str, BooleanVar] = {}
        for id, text in options.items():
            bv = BooleanVar(self,True,id)
            self._bools.append(bv)
            self._mp[id] = bv
            self._ctls.append(Checkbutton(self,text=text,variable=bv))
            self._ctls[-1].pack(side='left',anchor="w")
    
    def disable(self):
        for c in self._ctls:
            c['state']=DISABLED
        
    def enable(self):
        for c in self._ctls:
            c['state']=NORMAL

    def __setitem__(self, key:str, value:bool):
        self._mp[key].set(value)
    
    def __getitem__(self, key:str)->bool:
        return self._mp[key].get()

class PlotPad(Frame):
    def __init__(self, master, plot_cmd, show_accum:bool=False, accum_cmd=None, useEntry:bool=False, useTotalText:bool=False, **kwargs):
        super().__init__(master, **kwargs)
        self.btn_plot = Button(self, text=_L["BTN_PLOT"], takefocus=False, command=plot_cmd)
        self.btn_plot.pack(side='left',padx=3,pady=5)
        if useEntry:
            self.cb = Entry(self)
        else:
            self.cb = Combobox(self)
            self.cb['values'] = []
        self.cb.pack(side='left',padx=3,pady=5)
        if show_accum and accum_cmd is not None:
            self.btn_accum = Button(self, text=_L["BTN_TOTAL"] if useTotalText else _L["BTN_ACCUM"], takefocus=False, command=accum_cmd)
            self.btn_accum.pack(side='left',padx=3,pady=5)
        else:
            self.btn_accum = None
    
    def setValues(self, values:list[str]):
        if isinstance(self.cb, Combobox):
            self.cb['values'] = values
    
    def set(self, item:str):
        if isinstance(self.cb, Combobox):
            self.cb.set(item)
        else:
            self.cb.delete(0,END)
            self.cb.insert(0,item)
    
    def get(self):
        return self.cb.get()
    
    def disable(self):
        self.btn_plot['state']=DISABLED
        self.cb['state']=DISABLED
        if self.btn_accum: self.btn_accum['state']=DISABLED
        
    def enable(self):
        self.btn_plot['state']=NORMAL
        self.cb['state']=NORMAL
        if self.btn_accum: self.btn_accum['state']=NORMAL

class PlotBox(Tk):
    _sta:ReadOnlyStatistics
    _npl:AdvancedPlot

    def __init__(self):
        super().__init__()
        self._win()
        
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_L["MENU_FILE"], menu=self.filemenu)
        self.filemenu.add_command(label=_L["MENU_OPEN"], command=self.force_reload)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_L["MENU_EXIT"], command=self.destroy)

        self.tab = Notebook(self)
        self.tab.pack(expand=True,fill='both',padx=20,pady=3)
        self.tab_curve = Frame(self.tab)
        self.tab.add(self.tab_curve,text=_L["TAB_CURVE"])
        self.tab_grid = Frame(self.tab)
        self.tab.add(self.tab_grid,text=_L["TAB_GRID"])
        self.tab_trip = TripsFrame(self.tab)
        self.tab.add(self.tab_trip,text=_L["TAB_TRIP"], sticky='nsew')
        self.tab_state = Frame(self.tab)
        self.tab.add(self.tab_state,text=_L["TAB_STATE"], sticky='nsew')

        self.panel_time = LabelFrame(self.tab_curve, text="Time")
        self.panel_time.pack(side='top',fill='x',padx=3,pady=5)
        self.lb_time = Label(self.panel_time, text="Start time:")
        self.lb_time.grid(row=0,column=0)
        self.entry_time = Entry(self.panel_time)
        self.entry_time.insert(0,"86400")
        self.entry_time.grid(row=0,column=1,sticky='ew')
        self.lb_end_time = Label(self.panel_time, text="End time:")
        self.lb_end_time.grid(row=0,column=2)
        self.entry_end_time = Entry(self.panel_time)
        self.entry_end_time.insert(0,"-1")
        self.entry_end_time.grid(row=0,column=3,sticky='ew')
        self.accum_plotmax = BooleanVar(self.panel_time,False,"accum_plotmax")
        self.cb_accum_plotmax = Checkbutton(self.panel_time,text="Plot max",variable=self.accum_plotmax)
        self.cb_accum_plotmax.grid(row=0,column=4)

        self.panel_fcs = LabelFrame(self.tab_curve, text=_L["FCS_TITLE"])
        self.panel_fcs.pack(side='top',fill='x',padx=3,pady=5)
        self.fcs_opts = OptionBox(self.panel_fcs, {
            "wcnt": _L["FCS_NVEH"],
            "pc": _L["FCS_PC"],
            "price": _L["FCS_PRICE"]
        })
        self.fcs_opts.pack(side='top',fill='x',padx=3)
        self.fcs_pad = PlotPad(self.panel_fcs, self.plotFCSCurve, True, self.plotFCSAccum)
        self.fcs_pad.pack(side='top',fill='x',padx=3)

        self.panel_scs = LabelFrame(self.tab_curve, text=_L["SCS_TITLE"])
        self.panel_scs.pack(side='top',fill='x',padx=3,pady=5)
        self.scs_opts = OptionBox(self.panel_scs, {
            "wcnt": _L["SCS_NVEH"],
            "pc": _L["SCS_PC"],
            "pd": _L["SCS_PD"],
            "ppure": _L["SCS_PPURE"],
            "pv2g": _L["SCS_PV2G"],
            "pricebuy": _L["SCS_PBUY"],
            "pricesell": _L["SCS_PSELL"]
        })
        self.scs_opts.pack(side='top',fill='x',padx=3)
        self.scs_pad = PlotPad(self.panel_scs, self.plotSCSCurve, True, self.plotSCSAccum)
        self.scs_pad.pack(side='top',fill='x',padx=3)

        self.panel_ev = LabelFrame(self.tab_curve,text=_L["EV_TITLE"],)
        self.panel_ev.pack(side='top',fill='x',padx=3,pady=5)
        self.ev_opts = OptionBox(self.panel_ev, {
            "soc": "SoC",
            "sta": "Status",
            "cost": "Charging cost",
            "earn": "V2G earn",
            "cpure": "Net cost"
        })
        self.ev_opts.pack(side='top',fill='x',padx=3)
        self.ev_pad = PlotPad(self.panel_ev, self.plotEVCurve, useEntry=True)
        self.ev_pad.pack(side='top',fill='x',padx=3)

        self.panel_bus = LabelFrame(self.tab_curve,text=_L["BUS_TITLE"],)
        self.panel_bus.pack(side='top',fill='x',padx=3,pady=5)
        self.bus_opts = OptionBox(self.panel_bus, {
            "pd": "Active load",
            "qd": "Reactive load",
            "v": "Voltage",
            "pg": "Active gen.",
            "qg": "Reactive gen."
        })
        self.bus_opts.pack(side='top',fill='x',padx=3)
        self.bus_pad = PlotPad(self.panel_bus, self.plotBusCurve, True, self.plotBTotal, False, True)
        self.bus_pad.pack(side='top',fill='x',padx=3)

        self.frA = Frame(self.tab_curve)
        self.frA.pack(side='top',fill='x')
        self.panel_gen = LabelFrame(self.frA,text=_L["GEN_TITLE"],)
        self.panel_gen.grid(column=0,row=0,padx=3,pady=5,sticky="nsew")
        self.gen_opts = OptionBox(self.panel_gen, {
            "p": "Active power",
            "q": "Reactive power",
            "cost": "Avg. cost"
        })
        self.gen_opts.pack(side='top',fill='x',padx=3)
        self.gen_pad = PlotPad(self.panel_gen, self.plotGCurve, True, self.plotGTotal, False, True)
        self.gen_pad.pack(side='top',fill='x',padx=3)

        self.panel_line = LabelFrame(self.frA, text=_L["LINE_TITLE"],)
        self.panel_line.grid(column=1,row=0,padx=3,pady=5,sticky="nsew")
        self.line_opts = OptionBox(self.panel_line, {
            "p": "Active power",
            "q": "Reactive power",
            "cur": "Current"
        })
        self.line_opts.pack(side='top',fill='x',padx=3)
        self.line_pad = PlotPad(self.panel_line, self.plotLineCurve)
        self.line_pad.pack(side='top',fill='x',padx=3)

        self.panel_pvw = LabelFrame(self.frA, text=_L["PVW_TITLE"],)
        self.panel_pvw.grid(column=0,row=1,padx=3,pady=5,sticky="nsew")
        self.pvw_opts = OptionBox(self.panel_pvw, {
            "p": "Active power",
            "cr": "Curtailed rate",
        })
        self.pvw_opts.pack(side='top',fill='x',padx=3)
        self.pvw_pad = PlotPad(self.panel_pvw, self.plotPVWCurve)
        self.pvw_pad.pack(side='top',fill='x',padx=3)

        self.panel_ess = LabelFrame(self.frA, text=_L["ESS_TITLE"],)
        self.panel_ess.grid(column=1,row=1,padx=3,pady=5,sticky="nsew")
        self.ess_opts = OptionBox(self.panel_ess, {
            "p": "Active power",
            "soc": "SoC",
        })
        self.ess_opts.pack(side='top',fill='x',padx=3)
        self.ess_pad = PlotPad(self.panel_ess, self.plotESSCurve)
        self.ess_pad.pack(side='top',fill='x',padx=3)
        
        self.panel_time2 = Frame(self.tab_grid)
        self.panel_time2.pack(side='top',fill='x',padx=3,pady=5)
        self.lb_time2 = Label(self.panel_time2, text="Time point:")
        self.lb_time2.grid(row=0,column=0)
        self.entry_time2 = Entry(self.panel_time2)
        self.entry_time2.insert(0,"86400")
        self.entry_time2.grid(row=0,column=1,sticky='ew')
        self.btn_time2 = Button(self.panel_time2, text="Collect", takefocus=False, command=self.collectgrid)
        self.btn_time2.grid(row=0,column=2)

        self.grbus = ScrollableTreeView(self.tab_grid)
        self.grbus.pack(side='top',fill='both',padx=3,pady=5)
        self.grbus["show"]="headings"
        self.grbus["columns"]=("bus","v","pd","qd","pg","qg")
        self.grbus.heading("bus",text="Bus")
        self.grbus.heading("v",text="Voltage/kV")
        self.grbus.heading("pd",text="Active load/MW")
        self.grbus.heading("qd",text="Reactive load/Mvar")
        self.grbus.heading("pg",text="Active gen/MW")
        self.grbus.heading("qg",text="Reactive gen/Mvar")
        self.grbus.column("bus",width=50)
        self.grbus.column("v",width=90)
        self.grbus.column("pd",width=100)
        self.grbus.column("qd",width=100)
        self.grbus.column("pg",width=100)
        self.grbus.column("qg",width=100)
        
        self.grline = ScrollableTreeView(self.tab_grid)
        self.grline.pack(side='top',fill='both',padx=3,pady=5)
        self.grline["show"]="headings"
        self.grline["columns"]=("line","p","q","i")
        self.grline.heading("line",text="Line")
        self.grline.heading("p",text="Active pwr/MW")
        self.grline.heading("q",text="Reactive pwr/Mvar")
        self.grline.heading("i",text="Current/kA")
        self.grline.column("line",width=50)
        self.grline.column("p",width=100)
        self.grline.column("q",width=100)
        self.grline.column("i",width=100)

        self._sbar=Label(self,text=ITEM_LOADING)
        self._sbar.pack(side='bottom',anchor='w',padx=3,pady=3)

        self.plt = AdvancedPlot()

        self.__inst = None
        self.query_fr = LabelFrame(self.tab_state, text="Queries")
        self.cb_fcs_query = Combobox(self.query_fr)
        self.cb_fcs_query.grid(row=0,column=0,sticky='ew',padx=3,pady=5)
        self.btn_fcs_query = Button(self.query_fr, text="Query FCS", takefocus=False, command=self.queryFCS)
        self.btn_fcs_query.grid(row=0,column=1,sticky='ew',padx=3,pady=5)
        self.cb_scs_query = Combobox(self.query_fr)
        self.cb_scs_query.grid(row=1,column=0,sticky='ew',padx=3,pady=5)
        self.btn_scs_query = Button(self.query_fr, text="Query SCS", takefocus=False, command=self.querySCS)
        self.btn_scs_query.grid(row=1,column=1,sticky='ew',padx=3,pady=5)
        self.entry_ev_query = Entry(self.query_fr)
        self.entry_ev_query.grid(row=2,column=0,sticky='ew',padx=3,pady=5)
        self.btn_ev_query = Button(self.query_fr, text="Query EV", takefocus=False, command=self.queryEV)
        self.btn_ev_query.grid(row=2,column=1,sticky='ew',padx=3,pady=5)
        self.query_fr.pack(side='top',fill='x',padx=3,pady=5)
        self.text_qres = Text(self.tab_state)
        self.text_qres.pack(side='top',fill='both',padx=3,pady=5)
        
        self._ava ={
            "fcs": [False, self.panel_fcs],
            "scs": [False, self.panel_scs],
            "ev": [False, self.panel_ev],
            "gen": [False, self.panel_gen],
            "bus": [False, self.panel_bus],
            "line": [False, self.panel_line],
            "pvw": [False, self.panel_pvw],
            "ess": [False, self.panel_ess],
        }
        self._Q = Queue()
        self.disable_all()
        threading.Thread(target=self.reload,daemon=True,args=("results",)).start()

        self.after(100,self._upd)
    
    def set_qres(self,text:str):
        self.text_qres.delete(0.0,END)
        self.text_qres.insert(END,text)
    
    def __queryCS(self,cstype:Literal["fcs","scs"], q:str):
        if self.__inst is None: 
            self.set_qres("No instance loaded!")
            return
        if q.strip()=="":
            self.set_qres("Query cannot be empty!")
            return
        cslist = self.__inst[cstype]
        assert isinstance(cslist, CSList)
        try:
            cs = cslist[q]
            assert isinstance(cs, CS)
        except:
            res = "CS Not found: "+q
        else:
            if cs.supports_V2G:
                res = (
                    f"ID: {cs.name} (V2G)\nBus: {cs.node}\n  Pc_kW:{cs.Pc_kW}\n  Pd_kW: {cs.Pd_kW}\n  Pv2g_kW: {cs.Pv2g_kW}\n" +
                    f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n"+
                    f"Price:\n  Buy: {cs.pbuy}\n  Sell: {cs.psell}\n"
                )
            else:
                res = (
                    f"ID: {cs.name}\nBus: {cs.node}\n  Pc_kW:{cs.Pc_kW}\n" +
                    f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n"+
                    f"Price:\n  Buy: {cs.pbuy}\n"
                )
        self.set_qres(res)
    
    def queryFCS(self):
        self.__queryCS("fcs",self.cb_fcs_query.get())
        
    def querySCS(self):
        self.__queryCS("scs",self.cb_scs_query.get())
    
    def queryEV(self):
        if self.__inst is None: 
            self.set_qres("No instance loaded!")
            return
        q = self.entry_ev_query.get()
        if q.strip()=="":
            self.set_qres("Query cannot be empty!")
            return
        vehs = self.__inst["VEHs"]
        assert isinstance(vehs, EVDict)
        try:
            veh = vehs[q]
            assert isinstance(veh, EV)
        except:
            res = "EV Not found: "+q
        else:
            res = (
                f"ID: {veh.ID}\n  SoC: {veh.SOC*100:.4f}%\n  Status: {veh.status}\n  Distance(m): {veh.odometer}\n" + 
                f"Params:\n  Omega: {veh.omega}\n  KRel: {veh.krel}\n  Kfc: {veh.kfc}  Ksc: {veh.ksc}  Kv2g: {veh.kv2g}\n" +
                f"Consump(Wh/m): {veh.consumption*1000}\n" +
                f"Money:\n  Charging cost: {veh._cost}\n  V2G earn: {veh._earn}\n  Net cost: {veh._cost-veh._earn}\n"
            )
        self.set_qres(res)
    
    def _win(self):
        self.title(_L["TITLE"])
        width = 1024
        height = 768
        screenwidth = self.winfo_screenwidth()
        screenheight = self.winfo_screenheight()
        geometry = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
        self.geometry(geometry)
        #self.resizable(width=False, height=False)

    def collectgrid(self):
        self.grbus.clear()
        try:
            t = int(self.entry_time2.get())
        except:
            self.set_status("Invalid time point!")
            return
        for b in self._sta.bus_head:
            v = self._sta.bus_attrib_of(b, "V").value_at(t)
            pd = self._sta.bus_attrib_of(b, "Pd").value_at(t)
            qd = self._sta.bus_attrib_of(b, "Qd").value_at(t)
            pg = self._sta.bus_attrib_of(b, "Pg").value_at(t)
            qg = self._sta.bus_attrib_of(b, "Qg").value_at(t)
            self.grbus.insert("",'end',values=(b,v,pd,qd,pg,qg))
        for l in self._sta.line_head:
            p = self._sta.line_attrib_of(l, "P").value_at(t)
            q = self._sta.line_attrib_of(l, "Q").value_at(t)
            i = self._sta.line_attrib_of(l, "I").value_at(t)
            self.grline.insert("",'end',values=(l,p,q,i))
        self.set_status(_L["STA_READY"])
    
    def disable_all(self):
        for ok, panel in self._ava.values():
            for child in panel.children.values():
                if isinstance(child, (Button, Combobox, Checkbutton, Entry)):
                    child['state']=DISABLED
                elif isinstance(child, (OptionBox, PlotPad)):
                    child.disable()

    def enable_all(self):
        for ok, panel in self._ava.values():
            if not ok: continue
            for child in panel.children.values():
                if isinstance(child, (Button, Combobox, Checkbutton, Entry)):
                    child['state']=NORMAL
                elif isinstance(child, (OptionBox, PlotPad)):
                    child.enable()
    
    def set_status(self,text:str):
        self._sbar.configure(text=text)

    def _upd(self):
        while not self._Q.empty():
            op,*par=self._Q.get()
            if op=='L':
                self._sta,self._npl=par
                assert isinstance(self._sta,ReadOnlyStatistics)
                if self._sta.has_FCS():
                    self._ava["fcs"][0] = True
                    self.fcs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.FCS_head)
                    self.cb_fcs_query['values'] = self._sta.FCS_head
                    self.fcs_pad.set(ITEM_SUM)
                    if self._sta.FCS_head:
                        self.cb_fcs_query.set(self._sta.FCS_head[0])
                if self._sta.has_SCS():
                    self._ava["scs"][0] = True
                    self.scs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.SCS_head)
                    self.cb_scs_query['values'] = self._sta.SCS_head
                    self.scs_pad.set(ITEM_SUM)
                    if self._sta.SCS_head:
                        self.cb_scs_query.set(self._sta.SCS_head[0])
                self._ava["ev"][0] = self._sta.has_EV()
                if self._sta.has_GEN():
                    self._ava["gen"][0] = True
                    self.gen_pad.setValues([ITEM_ALL_G,ITEM_ALL_V2G,ITEM_ALL] + self._sta.gen_head)
                    self.gen_pad.set(ITEM_ALL_G)
                if self._sta.has_BUS():
                    self._ava["bus"][0] = True
                    self.bus_pad.setValues([ITEM_ALL] + self._sta.bus_head)
                    self.bus_pad.set(ITEM_ALL)
                if self._sta.has_LINE():
                    self._ava["line"][0] = True
                    self.line_pad.setValues([ITEM_ALL] + self._sta.line_head)
                    self.line_pad.set(ITEM_ALL)
                if self._sta.has_PVW():
                    self._ava["pvw"][0] = True
                    self.pvw_pad.setValues([ITEM_ALL] + self._sta.pvw_head)
                    self.pvw_pad.set(ITEM_ALL)
                if self._sta.has_ESS():
                    self._ava["ess"][0] = True
                    self.ess_pad.setValues([ITEM_ALL] + self._sta.ess_head)
                    self.ess_pad.set(ITEM_ALL)
                self.set_status(_L["STA_READY"])
                self.enable_all()
            elif op=='I':
                self.set_status(par[0])
            elif op=='E':
                self.set_status(par[0])
                self.enable_all()
            elif op=='LE':
                self.set_status(par[0])
                break
            elif op=='D':
                self.set_status(_L["STA_READY"])
                self.enable_all()
            elif op=='Q':
                self.destroy()
            else:
                self.set_status("Internal Error!")
                break
        self.after(100,self._upd)
    
    def askdir(self):
        p = Path(os.getcwd()) / "results"
        p.mkdir(parents=True,exist_ok=True)
        return filedialog.askdirectory(
            title="Please select the result folder",
            initialdir=str(p)
        )
    def force_reload(self):
        res_path = self.askdir()
        if res_path=="": return
        self.reload(res_path)

    def reload(self,res_path):
        try:
            first = True
            while True:
                res_path = Path(res_path)
                if res_path.exists():
                    break
                else: 
                    if not first: MB.showerror("Error loading", "Folder not found!")
                first = False
                res_path = self.askdir()
                if res_path=="":
                    self._Q.put(('Q',None))
                    return
            self.title(f'{_L["TITLE"]} - {res_path.absolute()}')
            self.disable_all()
            sta = ReadOnlyStatistics(str(res_path))
            nplt = AdvancedPlot()
            self._Q.put(('L',sta,nplt))
            cproc = res_path / "cproc.clog"
            if cproc.exists():
                self.tab_trip.load(str(cproc))
            state_path = res_path / "saved_state" / "inst.gz"
            if state_path.exists():
                try:
                    with gzip.open(state_path,'rb') as f:
                        self.__inst = pickle.load(f)
                except:
                    MB.showerror("Error loading", "Failed to load saved state!")
                    self.__inst = None
        except Exception as e:
            self._Q.put(('LE',e))

    def plotSCSAccum(self):
        self.disable_all()
        self.set_status("Plotting SCS load accumulation graph...")
        def work():
            try:
                tl = int(self.entry_time.get())
                tr = int(self.entry_end_time.get())
                self._npl.quick_scs_accum(tl, tr, self.accum_plotmax.get(), res_path=self._sta.root)
            except Exception as e:
                self._Q.put(('E',f'Error plotting SCS load accum. graph: {e}'))
                return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotFCSAccum(self):
        self.disable_all()
        self.set_status("Plotting FCS load accumulation graph...")
        def work():
            try:
                tl = int(self.entry_time.get())
                tr = int(self.entry_end_time.get())
                self._npl.quick_fcs_accum(tl, tr, self.accum_plotmax.get(), res_path=self._sta.root)
            except Exception as e:
                self._Q.put(('E',f'Error plotting SCS load accum. graph: {e}'))
                return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()

    def plotFCSCurve(self):
        self.disable_all()
        self.set_status("Plotting FCS graph...")
        def work():
            t=self.fcs_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                cs = self._sta.FCS_head
            elif t==ITEM_SUM:
                cs = ["<sum>"]
            else:
                cs = [x.strip() for x in t.split(',')]
            for i,c in enumerate(cs,start=1):
                try:
                    self._Q.put(('I',f'({i} of {len(cs)})Plotting FCS graph...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self.plt.quick_fcs(tl, tr, c,
                        self.fcs_opts["pc"], self.fcs_opts["price"], self.fcs_opts["wcnt"],res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting FCS: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotSCSCurve(self):
        self.disable_all()
        self.set_status("Plotting SCS graph...")
        def work():
            t=self.scs_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                cs = self._sta.SCS_head
            elif t==ITEM_SUM:
                cs = ["<sum>"]
            else:
                cs = [x.strip() for x in t.split(',')]
            for i,c in enumerate(cs,start=1):
                try:
                    self._Q.put(('I',f'({i} of {len(cs)})Plotting SCS graph...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self.plt.quick_scs(tl,tr,c, 
                        self.scs_opts["pc"],
                        self.scs_opts["pd"],
                        self.scs_opts["ppure"],
                        self.scs_opts["pv2g"],
                        self.scs_opts["wcnt"],
                        self.scs_opts["pricebuy"],
                        self.scs_opts["pricesell"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting SCS: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotEVCurve(self):
        self.disable_all()
        self.set_status("Plotting EV params...")
        def work():
            self._npl.tl = int(self.entry_time.get())
            t=self.ev_pad.get()
            evs=None if t.strip()=="" else [x.strip() for x in t.split(',')]
            if evs is None:
                self._Q.put(('E','ID of EV cannot be empty'))
                return
            for ev in evs:
                try:
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_ev(tl, tr, ev,
                        self.ev_opts["soc"], 
                        self.ev_opts["sta"],
                        self.ev_opts["cost"],
                        self.ev_opts["earn"],
                        self.ev_opts["cpure"],
                        res_path=self._sta.root
                    )
                except Exception as e:
                    self._Q.put(('E',f'Error plotting params. of {ev}: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()

    def plotGCurve(self):
        self.disable_all()
        self.set_status("Plotting generator curves...")
        def work():
            t=self.gen_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                gen=self._sta.gen_head
            elif t==ITEM_ALL_G:
                gen = [x for x in self._sta.gen_head if not x.startswith("V2G")]
            elif t==ITEM_ALL_V2G:
                gen = [x for x in self._sta.gen_head if x.startswith("V2G")]
            else: gen=[x.strip() for x in t.split(',')]
            for i,g in enumerate(gen,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(gen)})Plotting generators...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self.plt.quick_gen(tl,tr,g,
                        self.gen_opts["p"],self.gen_opts["q"],self.gen_opts["cost"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting generators: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()

    def plotBusCurve(self):
        self.disable_all()
        self.set_status("Plotting bus curves...")
        def work():
            t=self.bus_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                bus=self._sta.bus_head
            else: bus=[x.strip() for x in t.split(',')]
            for i,g in enumerate(bus,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(bus)})Plotting buses...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_bus(tl,tr,g,
                        self.bus_opts["pd"],self.bus_opts["qd"],
                        self.bus_opts["v"],self.bus_opts["pg"],self.bus_opts["qg"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting buses: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotGTotal(self):
        self.disable_all()
        self.set_status("Plotting total generator curve...")
        def work():
            try:
                tl = int(self.entry_time.get())
                tr = int(self.entry_end_time.get())
                self._npl.quick_gen_tot(tl,tr,True,True,True,res_path=self._sta.root)
            except Exception as e:
                self._Q.put(('E',f'Error plotting total generator curve: {e}'))
                return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotBTotal(self):
        self.disable_all()
        self.set_status("Plotting total generator curve...")
        def work():
            try:
                tl = int(self.entry_time.get())
                tr = int(self.entry_end_time.get())
                self._npl.quick_bus_tot(tl,tr,True,True,True,True,res_path=self._sta.root)
            except Exception as e:
                self._Q.put(('E',f'Error plotting total generator curve: {e}'))
                return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotLineCurve(self):
        self.disable_all()
        self.set_status("Plotting line curves...")
        def work():
            t=self.line_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                line=self._sta.line_head
            else: line=[x.strip() for x in t.split(',')]
            for i,g in enumerate(line,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(line)})Plotting lines...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_line(tl,tr,g,
                        self.line_opts["p"],self.line_opts["q"],self.line_opts["cur"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting lines: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotPVWCurve(self):
        self.disable_all()
        self.set_status("Plotting PV & Wind curves...")
        def work():
            t=self.pvw_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                pvw=self._sta.pvw_head
            else: pvw=[x.strip() for x in t.split(',')]
            for i,g in enumerate(pvw,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(pvw)})Plotting PV & Wind...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_pvw(tl,tr,g,
                        self.pvw_opts["p"],self.pvw_opts["cr"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting PV & Wind: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()

    def plotESSCurve(self):
        self.disable_all()
        self.set_status("Plotting ESS curves...")
        def work():
            t=self.ess_pad.get()
            if t.strip()=="" or t==ITEM_ALL:
                ess=self._sta.ess_head
            else: ess=[x.strip() for x in t.split(',')]
            for i,g in enumerate(ess,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(ess)})Plotting ESS...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_ess(tl,tr,g,
                        self.ess_opts["p"],self.ess_opts["soc"],
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting ESS: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
if __name__ == "__main__":
    win = PlotBox()
    win.mainloop()