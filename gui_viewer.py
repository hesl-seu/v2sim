from pathlib import Path
from queue import Queue
import threading, os
from fgui.view import *
from fgui import ScrollableTreeView, TripsFrame
from v2sim import CustomLocaleLib, AdvancedPlot, ReadOnlyStatistics
from tkinter import filedialog
from tkinter import messagebox as MB

_loc = CustomLocaleLib(["zh_CN","en"])
_loc.SetLanguageLib("zh_CN",
    TITLE = "结果查看器",
    STA_READY = "就绪",
    ITEM_ALL = "<所有>",
    ITEM_SUM = "<总和>",
    MENU_FILE = "文件",
    MENU_OPEN = "打开...",
    MENU_EXIT = "退出",
    TAB_CURVE = "绘图",
    TAB_GRID = "电网",
    TAB_TRIP = "行程",
)

_loc.SetLanguageLib("en",
    TITLE = "Result Viewer",
    STA_READY = "Ready",
    ITEM_ALL = "<All>",
    ITEM_SUM = "<Sum>",
    MENU_FILE = "File",
    MENU_OPEN = "Open...",
    MENU_EXIT = "Exit",
    TAB_CURVE = "Graphs",
    TAB_GRID = "Grid",
    TAB_TRIP = "Trips",
)

ITEM_ALL = _loc["ITEM_ALL"]
ITEM_SUM = _loc["ITEM_SUM"]
ITEM_ALL_G = "<All common generators>"
ITEM_ALL_V2G = "<All V2G stations>"
ITEM_LOADING = "Loading..."


class PlotBox(Tk):
    _sta:ReadOnlyStatistics
    _npl:AdvancedPlot

    def __init__(self):
        super().__init__()
        self._win()
        
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_loc["MENU_FILE"], menu=self.filemenu)
        self.filemenu.add_command(label=_loc["MENU_OPEN"], command=self.force_reload)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_loc["MENU_EXIT"], command=self.destroy)

        self.tab = Notebook(self)
        self.tab.pack(expand=True,fill='both',padx=20,pady=3)
        self.tab_curve = Frame(self.tab)
        self.tab.add(self.tab_curve,text=_loc["TAB_CURVE"])
        self.tab_grid = Frame(self.tab)
        self.tab.add(self.tab_grid,text=_loc["TAB_GRID"])
        self.tab_trip = TripsFrame(self.tab)
        self.tab.add(self.tab_trip,text=_loc["TAB_TRIP"],sticky='nsew')

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

        self.panel_fcs = LabelFrame(self.tab_curve, text="Fast Charging Stations")
        self.panel_fcs.pack(side='top',fill='x',padx=3,pady=5)
        self._fcs_wcnt = BooleanVar(self.panel_fcs,True,"fcs_wcnt")
        self.cb_fcs1 = Checkbutton(self.panel_fcs,text="#Veh.",variable=self._fcs_wcnt)
        self.cb_fcs1.grid(row=0,column=0)
        self._fcs_pc = BooleanVar(self.panel_fcs,True,"fcs_pc")
        self.cb_fcs2 = Checkbutton(self.panel_fcs,text="Charging pwr.",variable=self._fcs_pc)
        self.cb_fcs2.grid(row=0,column=1)
        self._fcs_price = BooleanVar(self.panel_fcs,False,"fcs_price")
        self.cb_fcs3 = Checkbutton(self.panel_fcs,text="Charging price",variable=self._fcs_price)
        self.cb_fcs3.grid(row=0,column=2)
        self.btn_fcs = Button(self.panel_fcs, text="Plot", takefocus=False)
        self.btn_fcs.grid(row=1,column=0)
        self.fcs_entry = Combobox(self.panel_fcs)
        self.fcs_entry['values'] = []
        self.fcs_entry.grid(row=1,column=1,columnspan=3,sticky='ew')
        self.btn_fcs_accum = Button(self.panel_fcs, text="Plot accum. graph", takefocus=False,)
        self.btn_fcs_accum.grid(row=1,column=4)

        self.panel_scs = LabelFrame(self.tab_curve, text="Slow Charging Stations")
        self.panel_scs.pack(side='top',fill='x',padx=3,pady=5)
        self._scs_wcnt = BooleanVar(self.panel_scs,True,"scs_wcnt")
        self.cb_scs1 = Checkbutton(self.panel_scs,text="#Veh.",variable=self._scs_wcnt)
        self.cb_scs1.grid(row=0,column=0)
        self._scs_pc = BooleanVar(self.panel_scs,True,"scs_pc")
        self.cb_scs2 = Checkbutton(self.panel_scs,text="Charging pwr.",variable=self._scs_pc)
        self.cb_scs2.grid(row=0,column=1)
        self._scs_pd = BooleanVar(self.panel_scs,True,"scs_pd")
        self.cb_scs3 = Checkbutton(self.panel_scs,text="Discharging pwr.",variable=self._scs_pd)
        self.cb_scs3.grid(row=0,column=2)
        self._scs_ppure = BooleanVar(self.panel_scs,True,"scs_ppure")
        self.cb_scs4 = Checkbutton(self.panel_scs,text="Net pwr.",variable=self._scs_ppure)
        self.cb_scs4.grid(row=0,column=3)
        self._scs_pv2g = BooleanVar(self.panel_scs,True,"scs_pv2g")
        self.cb_scs5 = Checkbutton(self.panel_scs,text="V2G cap.",variable=self._scs_pv2g)
        self.cb_scs5.grid(row=1,column=0)
        self._scs_pricebuy = BooleanVar(self.panel_scs,False,"scs_pricebuy")
        self.cb_scs6 = Checkbutton(self.panel_scs,text="Charging price",variable=self._scs_pricebuy)
        self.cb_scs6.grid(row=1,column=1)
        self._scs_pricesell = BooleanVar(self.panel_scs,False,"scs_pricesell")
        self.cb_scs7 = Checkbutton(self.panel_scs,text="Discharging price",variable=self._scs_pricesell)
        self.cb_scs7.grid(row=1,column=2)
        self.btn_scs = Button(self.panel_scs, text="Plot", takefocus=False)
        self.btn_scs.grid(row=2,column=0)
        self.scs_entry = Combobox(self.panel_scs)
        self.scs_entry['values'] = []
        self.scs_entry.grid(row=2,column=1,columnspan=2,sticky='ew')
        self.btn_scs_accum = Button(self.panel_scs, text="Plot accum. graph", takefocus=False,)
        self.btn_scs_accum.grid(row=2,column=3)

        self.panel_ev = self._panel_ev(self.tab_curve)
        self.btn_ev = self._btn_ev(self.panel_ev) 
        self.cb_ev1 = self._cb_ev1(self.panel_ev)
        self.cb_ev2 = self._cb_ev2(self.panel_ev) 
        self.cb_ev3 = self._cb_ev3(self.panel_ev) 
        self.cb_ev4 = self._cb_ev4(self.panel_ev) 
        self.cb_ev5 = self._cb_ev5(self.panel_ev) 
        self.ev_entry = self._ev_entry(self.panel_ev)

        self.panel_gen = self._panel_gen(self.tab_curve)
        self.btn_gen = self._btn_gen(self.panel_gen) 
        self.cb_gen1 = self._cb_gen1(self.panel_gen)
        self.cb_gen2 = self._cb_gen2(self.panel_gen) 
        self.cb_gen3 = self._cb_gen3(self.panel_gen) 
        self.gen_entry = self._gen_entry(self.panel_gen) 
        self.btn_Gtotal = self._btn_Gtotal(self.panel_gen)

        self.panel_bus = self._panel_bus(self.tab_curve)
        self.btn_bus = self._btn_bus(self.panel_bus) 
        self.cb_bus1 = self._cb_bus1(self.panel_bus) 
        self.cb_bus2 = self._cb_bus2(self.panel_bus) 
        self.cb_bus3 = self._cb_bus3(self.panel_bus)
        self.cb_bus4 = self._cb_bus4(self.panel_bus) 
        self.cb_bus5 = self._cb_bus5(self.panel_bus)
        self.bus_entry = self._bus_entry(self.panel_bus)
        self.btn_Bustotal = self._btn_Bustotal(self.panel_bus)

        self.panel_line = self._panel_line(self.tab_curve)
        self.btn_line = self._btn_line(self.panel_line)
        self.cb_line1 = self._cb_line1(self.panel_line)
        self.cb_line2 = self._cb_line2(self.panel_line)
        self.cb_line3 = self._cb_line3(self.panel_line)
        self.line_entry = self._line_entry(self.panel_line)
        
        self.panel_time2 = Frame(self.tab_grid)
        self.panel_time2.pack(side='top',fill='x',padx=3,pady=5)
        self.lb_time2 = Label(self.panel_time2, text="Time point:")
        self.lb_time2.grid(row=0,column=0)
        self.entry_time2 = Entry(self.panel_time2)
        self.entry_time2.insert(0,"86400")
        self.entry_time2.grid(row=0,column=1,sticky='ew')
        self.btn_time2 = Button(self.panel_time2, text="Collect", takefocus=False)
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

        self.btn_scs.configure(command=self.plotSCSCurve)
        self.btn_scs_accum.configure(command=self.plotSCSAccum)
        self.btn_fcs.configure(command=self.plotFCSCurve)
        self.btn_fcs_accum.configure(command=self.plotFCSAccum)
        self.btn_ev.configure(command=self.plotEVCurve)
        self.btn_gen.configure(command=self.plotGCurve)
        self.btn_Gtotal.configure(command=self.plotGTotal)
        self.btn_bus.configure(command=self.plotBusCurve)
        self.btn_Bustotal.configure(command=self.plotBTotal)
        self.btn_line.configure(command=self.plotLineCurve)
        self.btn_time2.configure(command=self.collectgrid)

        self._ava ={
            "fcs": [False, self.panel_fcs],
            "scs": [False, self.panel_scs],
            "ev": [False, self.panel_ev],
            "gen": [False, self.panel_gen],
            "bus": [False, self.panel_bus],
            "line": [False, self.panel_line],
        }
        self._Q = Queue()
        self.disable_all()
        threading.Thread(target=self.reload,daemon=True,args=("results",)).start()

        self.after(100,self._upd)
    
    def _win(self):
        self.title(_loc["TITLE"])
        width = 1024
        height = 768
        screenwidth = self.winfo_screenwidth()
        screenheight = self.winfo_screenheight()
        geometry = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
        self.geometry(geometry)
        #self.resizable(width=False, height=False)

    def _panel_ev(self,parent):
        frame = LabelFrame(parent,text="Electric Vehicles",)
        frame.pack(side='top',fill='x',padx=3,pady=5)
        return frame
    def _cb_ev1(self,parent):
        self._ev_soc = BooleanVar(parent,True,"ev_soc")
        cb = Checkbutton(parent,text="SoC",variable=self._ev_soc)
        cb.grid(row=0,column=0)
        return cb
    def _btn_ev(self,parent):
        btn = Button(parent, text="Plot", takefocus=False,)
        btn.grid(row=1,column=0)
        return btn
    def _cb_ev2(self,parent):
        self._ev_sta = BooleanVar(parent,False,"ev_sta")
        cb = Checkbutton(parent,text="Status",variable=self._ev_sta)
        cb.grid(row=0,column=1)
        return cb
    def _cb_ev3(self,parent):
        self._ev_cost = BooleanVar(parent,True,"ev_cost")
        cb = Checkbutton(parent,text="Charging cost",variable=self._ev_cost)
        cb.grid(row=0,column=2)
        return cb
    def _cb_ev4(self,parent):
        self._ev_earn = BooleanVar(parent,True,"ev_earn")
        cb = Checkbutton(parent,text="V2G earn",variable=self._ev_earn)
        cb.grid(row=0,column=3)
        return cb
    def _cb_ev5(self,parent):
        self._ev_cpure = BooleanVar(parent,True,"ev_cpure")
        cb = Checkbutton(parent,text="Net cost",variable=self._ev_cpure)
        cb.grid(row=0,column=4)
        return cb
    def _ev_entry(self,parent):
        ipt = Entry(parent)
        ipt.grid(row=1,column=1,columnspan=4,sticky='ew')
        return ipt
    def _panel_gen(self,parent):
        frame = LabelFrame(parent,text="Generators",)
        frame.pack(side='top',fill='x',padx=3,pady=5)
        return frame
    def _cb_gen1(self,parent):
        self._g_p = BooleanVar(parent,True,"g_p")
        cb = Checkbutton(parent,text="Active pwr.",variable=self._g_p)
        cb.grid(row=0,column=0)
        return cb
    def _cb_gen2(self,parent):
        self._g_q = BooleanVar(parent,True,"g_q")
        cb = Checkbutton(parent,text="Reactive pwr.",variable=self._g_q)
        cb.grid(row=0,column=1)
        return cb
    def _cb_gen3(self,parent):
        self._g_cost = BooleanVar(parent,True,"g_cost")
        cb = Checkbutton(parent,text="Avg. gen. cost",variable=self._g_cost)
        cb.grid(row=0,column=2)
        return cb
    def _btn_gen(self,parent):
        btn = Button(parent, text="Plot", takefocus=False,)
        btn.grid(row=1,column=0)
        return btn
    def _btn_Gtotal(self,parent):
        btn = Button(parent, text="Plot total", takefocus=False,)
        btn.grid(row=1,column=4)
        return btn
    def _gen_entry(self,parent):
        cb = Combobox(parent,)
        cb['values'] = []
        cb.grid(row=1,column=1,columnspan=3,sticky='ew')
        return cb
    def _panel_bus(self,parent):
        frame = LabelFrame(parent,text="Buses",)
        frame.pack(side='top',fill='x',padx=3,pady=5)
        return frame
    def _btn_bus(self,parent):
        btn = Button(parent, text="Plot", takefocus=False,)
        btn.grid(row=1,column=0)
        return btn
    def _cb_bus1(self,parent):
        self._bus_pd = BooleanVar(parent,True,"bus_pd")
        cb = Checkbutton(parent,text="Active load",variable=self._bus_pd)
        cb.grid(row=0,column=0)
        return cb
    def _cb_bus2(self,parent):
        self._bus_qd = BooleanVar(parent,True,"bus_qd")
        cb = Checkbutton(parent,text="Reactive load",variable=self._bus_qd)
        cb.grid(row=0,column=1)
        return cb
    def _cb_bus3(self,parent):
        self._bus_v = BooleanVar(parent,True,"bus_v")
        cb = Checkbutton(parent,text="Voltage",variable=self._bus_v)
        cb.grid(row=0,column=2)
        return cb
    def _cb_bus4(self,parent):
        self._bus_pg = BooleanVar(parent,True,"bus_pg")
        cb = Checkbutton(parent,text="Active gen.",variable=self._bus_pg)
        cb.grid(row=0,column=3)
        return cb
    def _cb_bus5(self,parent):
        self._bus_qg = BooleanVar(parent,True,"bus_qg")
        cb = Checkbutton(parent,text="Reactive gen.",variable=self._bus_qg)
        cb.grid(row=0,column=4)
        return cb
    def _bus_entry(self,parent):
        cb = Combobox(parent,)
        cb['values'] = []
        cb.grid(row=1,column=1,columnspan=3,sticky='ew')
        return cb
    def _btn_Bustotal(self,parent):
        btn = Button(parent, text="Plot total", takefocus=False,)
        btn.grid(row=1,column=4)
        return btn
    def _panel_line(self,parent):
        frame = LabelFrame(parent,text="Lines",)
        frame.pack(side='top',fill='x',padx=3,pady=5)
        return frame
    def _btn_line(self,parent):
        btn = Button(parent, text="Plot", takefocus=False,)
        btn.grid(row=1,column=0)
        return btn
    def _cb_line1(self,parent):
        self._line_p = BooleanVar(parent,True,"line_p")
        cb = Checkbutton(parent,text="Active pwr.",variable=self._line_p)
        cb.grid(row=0,column=0)
        return cb
    def _cb_line2(self,parent):
        self._line_q = BooleanVar(parent,True,"line_q")
        cb = Checkbutton(parent,text="Reactive pwr.",variable=self._line_q)
        cb.grid(row=0,column=1)
        return cb
    def _cb_line3(self,parent):
        self._line_cur = BooleanVar(parent,True,"line_cur")
        cb = Checkbutton(parent,text="Current",variable=self._line_cur)
        cb.grid(row=0,column=2)
        return cb
    def _line_entry(self,parent):
        cb = Combobox(parent,)
        cb['values'] = []
        cb.grid(row=1,column=1,columnspan=2,sticky='ew')
        return cb

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
        self.set_status(_loc["STA_READY"])
    
    def disable_all(self):
        for ok, panel in self._ava.values():
            for child in panel.children.values():
                child['state']=DISABLED

    def enable_all(self):
        for ok, panel in self._ava.values():
            if not ok: continue
            for child in panel.children.values():
                child['state']=NORMAL
    
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
                    self.fcs_entry['values'] = [ITEM_SUM, ITEM_ALL] + self._sta.FCS_head
                    self.fcs_entry.set(ITEM_SUM)
                if self._sta.has_SCS():
                    self._ava["scs"][0] = True
                    self.scs_entry['values'] = [ITEM_SUM, ITEM_ALL] + self._sta.SCS_head
                    self.scs_entry.set(ITEM_SUM)
                self._ava["ev"][0] = self._sta.has_EV()
                if self._sta.has_GEN():
                    self._ava["gen"][0] = True
                    self.gen_entry['values'] = [ITEM_ALL_G,ITEM_ALL_V2G,ITEM_ALL] + self._sta.gen_head
                    self.gen_entry.set(ITEM_ALL_G)
                if self._sta.has_BUS():
                    self._ava["bus"][0] = True
                    self.bus_entry['values'] = [ITEM_ALL] + self._sta.bus_head
                    self.bus_entry.set(ITEM_ALL)
                if self._sta.has_LINE():
                    self._ava["line"][0] = True
                    self.line_entry['values'] = [ITEM_ALL] + self._sta.line_head
                    self.line_entry.set(ITEM_ALL)
                self.set_status(_loc["STA_READY"])
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
                self.set_status(_loc["STA_READY"])
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
                    if not first: MB.showerror("Error loading","Folder not found!")
                first = False
                res_path = self.askdir()
                if res_path=="":
                    self._Q.put(('Q',None))
                    return
            self.title(f'{_loc["TITLE"]} - {res_path.absolute()}')
            self.disable_all()
            sta = ReadOnlyStatistics(str(res_path))
            nplt = AdvancedPlot()
            self._Q.put(('L',sta,nplt))
            cproc = res_path / "cproc.clog"
            if cproc.exists():
                self.tab_trip.load(str(cproc))
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
            t=self.fcs_entry.get()
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
                        self._fcs_pc.get(), self._fcs_price.get(), self._fcs_wcnt.get(),res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting FCS: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
    def plotSCSCurve(self):
        self.disable_all()
        self.set_status("Plotting SCS graph...")
        def work():
            t=self.scs_entry.get()
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
                        self._scs_pc.get(),
                        self._scs_pd.get(),
                        self._scs_ppure.get(),
                        self._scs_pv2g.get(),
                        self._scs_wcnt.get(),
                        self._scs_pricebuy.get(),
                        self._scs_pricesell.get(),
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
            t=self.ev_entry.get()
            evs=None if t.strip()=="" else [x.strip() for x in t.split(',')]
            if evs is None:
                self._Q.put(('E','ID of EV cannot be empty'))
                return
            for ev in evs:
                try:
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_ev(tl, tr, ev,
                        self._ev_soc.get(), 
                        self._ev_sta.get(),
                        self._ev_cost.get(),
                        self._ev_earn.get(),
                        self._ev_cpure.get(),
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
            t=self.gen_entry.get()
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
                        self._g_p.get(),self._g_q.get(),self._g_cost.get(),
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
            t=self.bus_entry.get()
            if t.strip()=="" or t==ITEM_ALL:
                bus=self._sta.bus_head
            else: bus=[x.strip() for x in t.split(',')]
            for i,g in enumerate(bus,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(bus)})Plotting buses...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_bus(tl,tr,g,
                        self._bus_pd.get(),self._bus_qd.get(),
                        self._bus_v.get(),self._bus_pg.get(),self._bus_qg.get(),
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
            t=self.line_entry.get()
            if t.strip()=="" or t==ITEM_ALL:
                line=self._sta.line_head
            else: line=[x.strip() for x in t.split(',')]
            for i,g in enumerate(line,start=1):
                try:
                    self._Q.put(('I',f'({i}/{len(line)})Plotting lines...'))
                    tl = int(self.entry_time.get())
                    tr = int(self.entry_end_time.get())
                    self._npl.quick_line(tl,tr,g,
                        self._line_p.get(),self._line_q.get(),self._line_cur.get(),
                        res_path=self._sta.root)
                except Exception as e:
                    self._Q.put(('E',f'Error plotting lines: {e}'))
                    return
            self._Q.put(('D',None))
        threading.Thread(target=work,daemon=True).start()
    
if __name__ == "__main__":
    win = PlotBox()
    win.mainloop()