import gzip
import threading, os
import pickle
from pathlib import Path
from typing import Literal, Optional, Dict, List, Tuple
from fgui import add_lang_menu, EventQueue
from fgui.view import *
from fgui import ScrollableTreeView, TripsFrame, DirSelApp
from v2sim import CustomLocaleLib, AdvancedPlot, ReadOnlyStatistics
from tkinter import filedialog
from tkinter import messagebox as MB
from PIL import Image, ImageTk
from v2sim import CS, CSList, EV, EVDict

_L = CustomLocaleLib.LoadFromFolder("resources/gui_viewer")

AVAILABLE_ITEMS = ["fcs","scs","ev","gen","bus","line","pvw","ess"]
AVAILABLE_ITEMS2 = AVAILABLE_ITEMS + ["fcs_accum","scs_accum","bus_total","gen_total"]
ITEM_ALL = _L["ITEM_ALL"]
ITEM_SUM = _L["ITEM_SUM"]
ITEM_ALL_G = "<All common generators>"
ITEM_ALL_V2G = "<All V2G stations>"
ITEM_LOADING = "Loading..."

class OptionBox(Frame):
    def __init__(self, master, options:Dict[str, Tuple[str, bool]], lcnt:int = -1, **kwargs):
        super().__init__(master, **kwargs)
        self._bools:List[BooleanVar] = []
        self._ctls:List[Checkbutton] = []
        self._mp:Dict[str, BooleanVar] = {}
        self._fr:List[Frame] = []
        if lcnt <= 0: 
            fr = Frame(self)
            fr.pack(side = "top", anchor = "w")
            self._fr.append(fr)
        i = 0
        for id, (text, v) in options.items():
            bv = BooleanVar(self, v)
            self._bools.append(bv)
            self._mp[id] = bv
            if lcnt > 0 and i % lcnt == 0:
                fr = Frame(self)
                fr.pack(side = "top", anchor = "w")
                self._fr.append(fr)
            self._ctls.append(Checkbutton(self._fr[-1],text=text,variable=bv))
            self._ctls[-1].pack(side='left',anchor="w")
            i+=1
    
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
    
    def getValues(self):
        return {k: v.get() for k,v in self._mp.items()}
    
    def getSelected(self):
        return [k for k,v in self._mp.items() if v.get()]

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

class PlotPage(Frame):
    @property
    def AccumPlotMax(self)->bool:
        return self.accum_plotmax.get()
    
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.columnconfigure(index=0,weight=1)
        self.columnconfigure(index=1,weight=1)
        self.lfra_head = LabelFrame(self, text=_L["TIME"])
        self.lfra_head.grid(row=0,column=0,padx=3,pady=5, columnspan=2, sticky="nsew")
        self.panel_time = Frame(self.lfra_head)
        self.panel_time.pack(side="top",fill="x",anchor='w',pady=2,) 
        self.lb_time = Label(self.panel_time, text=_L["START_TIME"])
        self.lb_time.pack(side="left")
        self.entry_time = Entry(self.panel_time,width=10)
        self.entry_time.insert(0,"86400")
        self.entry_time.pack(side="left")
        self.lb_end_time = Label(self.panel_time, text=_L["END_TIME"])
        self.lb_end_time.pack(side="left")
        self.entry_end_time = Entry(self.panel_time,width=10)
        self.entry_end_time.insert(0,"-1")
        self.entry_end_time.pack(side="left")
        self.accum_plotmax = BooleanVar(self.panel_time,False)
        self.cb_accum_plotmax = Checkbutton(self.panel_time,text=_L["PLOT_MAX"],variable=self.accum_plotmax)
        self.cb_accum_plotmax.pack(side="left")
        self.panel_conf = Frame(self.lfra_head)
        self.panel_conf.pack(side="top",fill="x",anchor='w',pady=2,)
        self.lb_conf = Label(self.panel_conf, text=_L["FILE_EXT"])
        self.lb_conf.pack(side="left")
        self.cb_ext = Combobox(self.panel_conf,width=5, state="readonly")
        self.cb_ext['values'] = ["png","jpg","pdf","eps","svg","tiff"]
        self.cb_ext.current(0)
        self.cb_ext.pack(side="left")
        self.lb_dpi = Label(self.panel_conf, text=_L["IMAGE_DPI"])
        self.lb_dpi.pack(side="left")
        self.entry_dpi = Combobox(self.panel_conf,width=5)
        self.entry_dpi['values'] = ['128', '192', '256', '300', '400', '600', '1200']
        self.entry_dpi.current(3)
        self.entry_dpi.pack(side="left")
        self.plot_title = BooleanVar(self.panel_conf,True)
        self.cb_accum_plotmax = Checkbutton(self.panel_conf,text=_L["PLOT_TITLE"],variable=self.plot_title)
        self.cb_accum_plotmax.pack(side="left")

        self.plot_fcs = BooleanVar(self, False)
        self.cb_fcs = Checkbutton(self, text=_L["FCS_TITLE"], variable=self.plot_fcs)
        self.cb_fcs.grid(row=1,column=0,padx=3,pady=5,sticky='w')
        self.panel_fcs = Frame(self, border=1, relief='groove')
        self.panel_fcs.grid(row=2,column=0,sticky="nsew",padx=(5,3),pady=(0,5))
        self.fcs_opts = OptionBox(self.panel_fcs, {
            "wcnt": (_L["FCS_NVEH"], True),
            "load": (_L["FCS_PC"], True),
            "price": (_L["FCS_PRICE"], False),
        })
        self.fcs_opts.pack(side='top',fill='x',padx=3)
        self.fcs_pad = PlotPad(self.panel_fcs, True)
        self.fcs_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_scs = BooleanVar(self, False)
        self.cb_scs = Checkbutton(self, text=_L["SCS_TITLE"], variable=self.plot_scs)
        self.cb_scs.grid(row=3,column=0,padx=3,pady=5,sticky='w')
        self.panel_scs = Frame(self, border=1, relief='groove')
        self.panel_scs.grid(row=4,column=0,sticky="nsew",padx=(5,3),pady=(0,5))
        self.scs_opts = OptionBox(self.panel_scs, {
            "wcnt": (_L["SCS_NVEH"], True), 
            "cload": (_L["SCS_PC"], True), 
            "dload": (_L["SCS_PD"], True), 
            "netload": (_L["SCS_PPURE"], True), 
            "v2gcap": (_L["SCS_PV2G"], True), 
            "pricebuy": (_L["SCS_PBUY"], False), 
            "pricesell": (_L["SCS_PSELL"], False), 
        }, lcnt = 4)
        self.scs_opts.pack(side='top',fill='x',padx=3)
        self.scs_pad = PlotPad(self.panel_scs, True)
        self.scs_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_ev = BooleanVar(self, False)
        self.cb_ev = Checkbutton(self, text=_L["EV_TITLE"], variable=self.plot_ev)
        self.cb_ev.grid(row=1,column=1,padx=3,pady=5,sticky='w')
        self.panel_ev = Frame(self, border=1, relief='groove')
        self.panel_ev.grid(row=2,column=1,sticky="nsew",padx=(5,3),pady=(0,5))
        self.ev_opts = OptionBox(self.panel_ev, {
            "soc": (_L["SOC"], True),
            "status": (_L["EV_STA"], False),
            "cost": (_L["EV_COST"], True),
            "earn": (_L["EV_EARN"], True),
            "cpure": (_L["EV_NETCOST"], True),
        })
        self.ev_opts.pack(side='top',fill='x',padx=3)
        self.ev_pad = PlotPad(self.panel_ev, useEntry=True)
        self.ev_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_bus = BooleanVar(self, False)
        self.cb_bus = Checkbutton(self, text=_L["BUS_TITLE"], variable=self.plot_bus)
        self.cb_bus.grid(row=3,column=1,padx=3,pady=5,sticky='w')
        self.panel_bus = Frame(self, border=1, relief='groove')
        self.panel_bus.grid(row=4,column=1,sticky="nsew",padx=(5,3),pady=(0,5))
        self.bus_opts = OptionBox(self.panel_bus, {
            "activel": (_L["BUS_PD"], True),
            "reactivel": (_L["BUS_QD"], True),
            "volt": (_L["BUS_V"], True),
            "activeg": (_L["BUS_PG"], True),
            "reactiveg": (_L["BUS_QG"], True),
        },lcnt=3)
        self.bus_opts.pack(side='top',fill='x',padx=3)
        self.bus_pad = PlotPad(self.panel_bus, True, False, True)
        self.bus_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_gen = BooleanVar(self, False)
        self.cb_gen = Checkbutton(self, text=_L["GEN_TITLE"], variable=self.plot_gen)
        self.cb_gen.grid(row=5,column=0,padx=3,pady=5,sticky='w')
        self.panel_gen = Frame(self, border=1, relief='groove')
        self.panel_gen.grid(row=6,column=0,sticky="nsew",padx=(5,3),pady=(0,5))
        self.gen_opts = OptionBox(self.panel_gen, {
            "active": (_L["ACTIVE_POWER"], True),
            "reactive": (_L["REACTIVE_POWER"], True),
            "costp": (_L["GEN_COST"], True),
        })
        self.gen_opts.pack(side='top',fill='x',padx=3)
        self.gen_pad = PlotPad(self.panel_gen, True, False, True)
        self.gen_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_line = BooleanVar(self, False)
        self.cb_line = Checkbutton(self, text=_L["LINE_TITLE"], variable=self.plot_line)
        self.cb_line.grid(row=5,column=1,padx=3,pady=5,sticky='w')
        self.panel_line = Frame(self, border=1, relief='groove')
        self.panel_line.grid(row=6,column=1,sticky="nsew",padx=(5,3),pady=(0,5))
        self.line_opts = OptionBox(self.panel_line, {
            "active": (_L["ACTIVE_POWER"], True),
            "reactive": (_L["REACTIVE_POWER"], True),
            "current": (_L["LINE_CURRENT"], True),
        })
        self.line_opts.pack(side='top',fill='x',padx=3)
        self.line_pad = PlotPad(self.panel_line)
        self.line_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_pvw = BooleanVar(self, False)
        self.cb_pvw = Checkbutton(self, text=_L["PVW_TITLE"], variable=self.plot_pvw)
        self.cb_pvw.grid(row=7,column=0,padx=3,pady=5,sticky='w')
        self.panel_pvw = Frame(self, border=1, relief='groove')
        self.panel_pvw.grid(row=8,column=0,sticky="nsew",padx=(5,3),pady=(0,5))
        self.pvw_opts = OptionBox(self.panel_pvw, {
            "P": (_L["ACTIVE_POWER"], True),
            "cr": (_L["PVW_CR"], True),
        })
        self.pvw_opts.pack(side='top',fill='x',padx=3)
        self.pvw_pad = PlotPad(self.panel_pvw)
        self.pvw_pad.pack(side='top',fill='x',padx=3,pady=(0,3))

        self.plot_ess = BooleanVar(self, False)
        self.cb_ess = Checkbutton(self, text=_L["ESS_TITLE"], variable=self.plot_ess)
        self.cb_ess.grid(row=7,column=1,padx=3,pady=5,sticky='w')
        self.panel_ess = Frame(self, border=1, relief='groove')
        self.panel_ess.grid(row=8,column=1,sticky="nsew",padx=(5,3),pady=(0,5))
        self.ess_opts = OptionBox(self.panel_ess, {
            "P": (_L["ACTIVE_POWER"], True),
            "soc": (_L["SOC"], True),
        })
        self.ess_opts.pack(side='top',fill='x',padx=3)
        self.ess_pad = PlotPad(self.panel_ess)
        self.ess_pad.pack(side='top',fill='x',padx=3,pady=(0,3))
    
    def getConfig(self):
        return {
            "btime": int(self.entry_time.get()),
            "etime": int(self.entry_end_time.get()),
            "plotmax": self.accum_plotmax.get(),
            "fcs_accum": self.fcs_pad.accum.get() and self.plot_fcs.get(),
            "scs_accum": self.scs_pad.accum.get() and self.plot_scs.get(),
            "bus_total": self.bus_pad.accum.get() and self.plot_bus.get(),
            "gen_total": self.gen_pad.accum.get() and self.plot_gen.get(),
            "fcs": self.fcs_opts.getValues() if self.plot_fcs.get() else None,
            "scs": self.scs_opts.getValues() if self.plot_scs.get() else None,
            "ev": self.ev_opts.getValues() if self.plot_ev.get() else None,
            "gen": self.gen_opts.getValues() if self.plot_gen.get() else None,
            "bus": self.bus_opts.getValues() if self.plot_bus.get() else None,
            "line": self.line_opts.getValues() if self.plot_line.get() else None,
            "pvw": self.pvw_opts.getValues() if self.plot_pvw.get() else None,
            "ess": self.ess_opts.getValues() if self.plot_ess.get() else None,
        }

    def getTime(self):
        return int(self.entry_time.get()), int(self.entry_end_time.get())
    
    def pars(self, key:str):
        ret = self.getConfig()[key]
        assert isinstance(ret, dict), f"{key} is not a dict: {ret}"
        ret.update({
            "tl": int(self.entry_time.get()),
            "tr": int(self.entry_end_time.get())
        })
        return ret

    def enable(self, items:Optional[List[str]]=None):
        if items is None:
            items = AVAILABLE_ITEMS
        else:
            for i in items:
                assert i in AVAILABLE_ITEMS
        for i in items:
            getattr(self, f"cb_{i}")['state']=NORMAL
            getattr(self, f"{i}_opts").enable()
            getattr(self, f"{i}_pad").enable()
    
    def disable(self, items:List[str]=[]):
        if len(items)==0:
            items = AVAILABLE_ITEMS
        else:
            for i in items:
                assert i in AVAILABLE_ITEMS
        for i in items:
            getattr(self, f"cb_{i}")['state']=DISABLED
            getattr(self, f"{i}_opts").disable()
            getattr(self, f"{i}_pad").disable()


class PlotBox(Tk):
    _sta:ReadOnlyStatistics
    _npl:AdvancedPlot

    def __init__(self):
        super().__init__()
        self.title(_L["TITLE"])
        self.geometry("1024x840")
        self.original_image = None
        
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_L["MENU_FILE"], menu=self.filemenu)
        self.filemenu.add_command(label=_L["MENU_OPEN"], command=self.force_reload)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_L["MENU_EXIT"], command=self.destroy)
        add_lang_menu(self.menu)

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

        self.fr_pic = Frame(self.tab_curve)
        self.fr_pic.pack(side="top",fill=BOTH, expand=False)
        self.lb_pic = Label(self.fr_pic,text=_L["NO_IMAGE"])
        self.lb_pic.pack(side="left",fill=BOTH, expand=True,anchor='w')
        self.pic_list = Listbox(self.fr_pic)
        self.pic_list.pack(side="right",fill=Y,anchor='e')
        self.pic_list.bind("<<ListboxSelect>>", self.on_file_select)

        self.fr_draw = Frame(self.tab_curve)
        self.fr_draw.pack(side="bottom",fill=BOTH, expand=True)
        self._ppc = Canvas(self.fr_draw)
        self._ppc.pack(side="left", fill="both", expand=True)
        self.scrollbar = Scrollbar(self.fr_draw, orient="vertical", command=self._ppc.yview)
        self.scrollbar.pack(side="right", fill="y")
        self._pp = PlotPage(self._ppc)
        self._pp.bind("<Configure>", lambda e: self._ppc.configure(scrollregion=self._ppc.bbox("all")))
        self.btn_draw = Button(self._pp.panel_time, text=_L["BTN_PLOT"], command=self.plotSelected)
        self.btn_draw.pack(side='right')
        self._ppc.create_window((0, 0), window=self._pp, anchor="nw")
        self._ppc.configure(yscrollcommand=self.scrollbar.set)
        
        
        self.panel_time2 = Frame(self.tab_grid)
        self.panel_time2.pack(side='top',fill='x',padx=3,pady=5)
        self.lb_time2 = Label(self.panel_time2, text=_L["TIME_POINT"])
        self.lb_time2.grid(row=0,column=0)
        self.entry_time2 = Entry(self.panel_time2)
        self.entry_time2.insert(0,"86400")
        self.entry_time2.grid(row=0,column=1,sticky='ew')
        self.btn_time2 = Button(self.panel_time2, text=_L["GRID_COLLECT"], takefocus=False, command=self.collectgrid)
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

        self._sbar=Label(self,text=_L["STA_READY"])
        self._sbar.pack(side='bottom',anchor='w',padx=3,pady=3)

        self.__inst = None
        self.query_fr = LabelFrame(self.tab_state, text=_L["TAB_QUERIES"])
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
            "fcs": False,
            "scs": False, 
            "ev": False, 
            "gen": False, 
            "bus": False, 
            "line": False, 
            "pvw": False, 
            "ess": False,
        }
        self._Q = EventQueue(self)
        self._Q.register("exit", self.quit)
        self._Q.register("loaded", self.on_loaded)
        self._Q.register("state_loaded", self.on_state_loaded)
        self._Q.register("plot_done", self.on_plot_done)
        self._Q.do()

        self.disable_all()
        self.bind("<Configure>", self.on_resize)
        self.resize_timer = None
    
    def display_images(self, file_name:str):
        if self.folder is None: return
        img1_path = os.path.join(self.folder, file_name)
        
        try:
            if os.path.exists(img1_path):
                self.original_image = Image.open(img1_path)
            else:
                self.original_image = None
        except Exception as e:
            messagebox.showerror(_L["ERROR"], _L["LOAD_FAILED"].format(str(e)))
        
        self.resize()
    
    def resize(self):
        sz = (self.winfo_width() - 200, self.winfo_height() // 2 - 20)
        if self.original_image is not None:
            resized_image = self.original_image.copy()
            resized_image.thumbnail(sz)
            image = ImageTk.PhotoImage(resized_image)

            self.lb_pic.config(image=image,text="")
            self.image = image
        else:
            self.lb_pic.config(image='',text=_L["NO_IMAGE"])
            self.image = None


    def on_resize(self, event):
        if self.resize_timer is not None:
            self.after_cancel(self.resize_timer)
        self.resize_timer = self.after(100, self.resize_end)
    
    def resize_end(self):
        self.resize()
    
    def on_file_select(self, event):
        selected_index = self.pic_list.curselection()
        if selected_index:
            file_name = self.pic_list.get(selected_index)
            self.display_images(file_name)

    def set_qres(self,text:str):
        self.text_qres.delete(0.0,END)
        self.text_qres.insert(END,text)
    
    def __queryCS(self,cstype:Literal["fcs","scs"], q:str):
        if self.__inst is None: 
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        if q.strip()=="":
            self.set_qres(_L["EMPTY_QUERY"])
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
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        q = self.entry_ev_query.get()
        if q.strip()=="":
            self.set_qres(_L["EMPTY_QUERY"])
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
        self._pp.disable()
        self.btn_draw['state']=DISABLED

    def enable_all(self):
        self._pp.enable([p for p, ok in self._ava.items() if ok])
        self.btn_draw['state']=NORMAL
    
    def set_status(self,text:str):
        self._sbar.configure(text=text)

    def update_file_list(self):
        self.pic_list.delete(0, END)
        self.original_image = None
        self.lb_pic.config(image='',text=_L["NO_IMAGE"])
        self.image = None
        if self.folder and os.path.exists(self.folder):
            files = set(os.listdir(self.folder))
            for file in sorted(files):
                if file.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):  # 只列出图片文件
                    self.pic_list.insert(END, file)

    def on_state_loaded(self, par):
        self.__inst = par
    
    def on_loaded(self, sta:ReadOnlyStatistics, npl:AdvancedPlot):
        assert isinstance(sta, ReadOnlyStatistics)
        assert isinstance(npl, AdvancedPlot)
        self._sta = sta
        self._npl = npl
        for x in AVAILABLE_ITEMS:
            self._ava[x] = getattr(self._sta, f"has_{x.upper()}")()
        if self._sta.has_FCS():
            self._pp.fcs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.FCS_head)
            self.cb_fcs_query['values'] = self._sta.FCS_head
            if self._sta.FCS_head:
                self.cb_fcs_query.set(self._sta.FCS_head[0])
        if self._sta.has_SCS():
            self._pp.scs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.SCS_head)
            self.cb_scs_query['values'] = self._sta.SCS_head
            if self._sta.SCS_head:
                self.cb_scs_query.set(self._sta.SCS_head[0])
        if self._sta.has_GEN():
            self._pp.gen_pad.setValues([ITEM_ALL_G,ITEM_ALL_V2G,ITEM_ALL] + self._sta.gen_head)
        if self._sta.has_BUS():
            self._pp.bus_pad.setValues([ITEM_ALL] + self._sta.bus_head)
        if self._sta.has_LINE():
            self._pp.line_pad.setValues([ITEM_ALL] + self._sta.line_head)
        if self._sta.has_PVW():
            self._pp.pvw_pad.setValues([ITEM_ALL] + self._sta.pvw_head)
        if self._sta.has_ESS():
            self._pp.ess_pad.setValues([ITEM_ALL] + self._sta.ess_head)
        self.update_file_list()
        self.set_status(_L["STA_READY"])
        self.enable_all()
        
    def on_error(self, par):
        MB.showerror(_L["ERROR"], par[0])
        self.set_status(par[0])
        self.enable_all()
    
    def on_plot_done(self, ex:Optional[Exception] = None):
        if ex is None:
            self.update_file_list()
            self.set_status(_L["STA_READY"])
            self.enable_all()
        else:
            self.on_error(str(ex))
    
    def askdir(self):
        p = Path(os.getcwd()) / "cases"
        p.mkdir(parents=True,exist_ok=True)
        return filedialog.askdirectory(
            title=_L["TITLE_SEL_FOLDER"],
            initialdir=str(p),
            mustexist=True,
        )
    
    def force_reload(self):
        res_path = self.askdir()
        if res_path == "": return

        # Check folder existence
        first = True
        while True:
            res_path = Path(res_path)
            if res_path.exists():
                break
            else: 
                if not first: MB.showerror(_L["ERROR"], "Folder not found!")
            first = False
            res_path = self.askdir()
            if res_path == "":
                self._Q.trigger("exit")
                return
        
        # Check cproc.clog existence
        cproc = res_path / "cproc.clog"
        if cproc.exists():
            self.tab_trip.load(str(cproc))
        else:
            res_path_list = []
            for dir_ in res_path.iterdir():
                if dir_.is_dir() and dir_.name.lower().startswith("results") and (dir_ / "cproc.clog").exists():
                    res_path_list.append(dir_)
            if len(res_path_list) == 0:
                MB.showerror(_L["ERROR"], _L["NO_CPROC"])
                return
            elif len(res_path_list) == 1:
                res_path = res_path_list[0]
            else:
                self.disable_all()
                dsa = DirSelApp(res_path_list)
                self.wait_window(dsa)
                if dsa.folder is None:
                    self._Q.trigger("exit")
                    return
                res_path = Path(dsa.folder)
            cproc = res_path / "cproc.clog"
            self.tab_trip.load(str(cproc))
        
        # Load the results
        self.set_status(_L["LOADING"])
        self.folder = str(res_path.absolute() / "figures")
        self.title(f'{_L["TITLE"]} - {res_path.name}')
        self.disable_all()

        def load_async(res_path):
            sta = ReadOnlyStatistics(res_path)
            npl = AdvancedPlot()
            npl.load_series(sta)
            return (sta, npl)
        
        self._Q.submit("loaded", load_async, res_path)

        state_path = res_path / "saved_state" / "inst.gz"

        def load_state_async(state_path):
            try:
                with gzip.open(state_path, 'rb') as f:
                    inst = pickle.load(f) # type: ignore
            except:
                MB.showerror(_L["ERROR"], _L["SAVED_STATE_LOAD_FAILED"])
                inst = None
            return inst

        if state_path.exists():
            self._Q.submit("state_loaded", load_state_async, state_path)

    def plotSelected(self):
        cfg = self._pp.getConfig()
        self.disable_all()
        self.set_status("Plotting all...")
        self._npl.pic_ext = self._pp.cb_ext.get()
        self._npl.plot_title = self._pp.plot_title.get()
        try:
            self._npl.dpi = int(self._pp.entry_dpi.get())
        except:
            MB.showerror(_L["ERROR"], _L["INVALID_DPI"])
            self.enable_all()
            return
        for a in AVAILABLE_ITEMS2:
            if cfg[a]: break
        else:
            MB.showerror(_L["ERROR"], _L["NOTHING_PLOT"])
            self.enable_all()
        
        def work(cfg):
            def todo(plotpage, opt_name):
                getattr(plotpage, "plot_" + opt_name).set("False")

            try:
                for a in AVAILABLE_ITEMS2:
                    if cfg[a]:
                        getattr(self, "_plot_"+a)()
                        if "_" in a: continue
                        self._Q.delegate(todo, self._pp, a)
            except Exception as e:
                return e
            return None

        self._Q.submit("plot_done", work, cfg)

    def _plot_scs_accum(self):
        tl,tr = self._pp.getTime()
        self._npl.quick_scs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)
    
    def _plot_fcs_accum(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_fcs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)

    def _plot_fcs(self):
        t = self._pp.fcs_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            cs = self._sta.FCS_head
        elif t==ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i,c in enumerate(cs,start=1):
            self._Q.delegate(self.set_status, f'({i} of {len(cs)})Plotting FCS graph...')
            self._npl.quick_fcs(
                cs_name=c, res_path=self._sta.root, 
                **self._pp.pars("fcs")
            )

    def _plot_scs(self):
        t = self._pp.scs_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            cs = self._sta.SCS_head
        elif t==ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i,c in enumerate(cs,start=1):
            self._Q.delegate(self.set_status, f'({i} of {len(cs)})Plotting SCS graph...')
            self._npl.quick_scs(
                cs_name=c, res_path=self._sta.root,
                **self._pp.pars("scs")
            )

    def _plot_ev(self):
        self._npl.tl = int(self._pp.entry_time.get())
        t = self._pp.ev_pad.get()
        evs=None if t.strip()=="" else [x.strip() for x in t.split(',')]
        if evs is None:
            self._Q.trigger("error", 'ID of EV cannot be empty')
            return
        for ev in evs:
            self._npl.quick_ev(ev_name = ev,
                res_path=self._sta.root,
                **self._pp.pars("ev")
            )
    
    def _plot_gen(self):
        t = self._pp.gen_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            gen = self._sta.gen_head
        elif t==ITEM_ALL_G:
            gen = [x for x in self._sta.gen_head if not x.startswith("V2G")]
        elif t==ITEM_ALL_V2G:
            gen = [x for x in self._sta.gen_head if x.startswith("V2G")]
        else: gen = [x.strip() for x in t.split(',')]
        for i, g in enumerate(gen, start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(gen)})Plotting generators...')
            self._npl.quick_gen(
                gen_name=g,res_path=self._sta.root,
                **self._pp.pars("gen")
            )

    def _plot_bus(self):
        t=self._pp.bus_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            bus=self._sta.bus_head
        else: bus=[x.strip() for x in t.split(',')]
        for i,g in enumerate(bus,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(bus)})Plotting buses...')
            self._npl.quick_bus(
                bus_name = g, res_path=self._sta.root,
                **self._pp.pars("bus")
            )
    
    def _plot_gen_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_gen_tot(tl,tr,True,True,True,res_path=self._sta.root)
    
    def _plot_bus_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_bus_tot(tl,tr,True,True,True,True,res_path=self._sta.root)
    
    def _plot_line(self):
        t=self._pp.line_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            line=self._sta.line_head
        else: line=[x.strip() for x in t.split(',')]
        for i,g in enumerate(line,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(line)})Plotting lines...')
            self._npl.quick_line(
                line_name = g, res_path=self._sta.root,
                **self._pp.pars("line")
            )

    def _plot_pvw(self):
        t = self._pp.pvw_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            pvw = self._sta.pvw_head
        else: pvw = [x.strip() for x in t.split(',')]
        for i, g in enumerate(pvw,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(pvw)})Plotting PV & Wind...')
            self._npl.quick_pvw(
                pvw_name = g, res_path=self._sta.root,
                **self._pp.pars("pvw")
            )

    def _plot_ess(self):
        t = self._pp.ess_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            ess = self._sta.ess_head
        else: ess = [x.strip() for x in t.split(',')]
        for i,g in enumerate(ess,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(ess)})Plotting ESS...')
            self._npl.quick_ess(
                ess_name = g, res_path = self._sta.root,
                **self._pp.pars("ess")
            )
    
if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()
    win = PlotBox()
    win.mainloop()