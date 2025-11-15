from v2simux.gui.common import *

from .optbox import OptionBox
from .plotpad import PlotPad


_L = LangLib.Load(__file__)
AVAILABLE_ITEMS = ["fcs","scs","ev","gen","bus","line","pvw","ess"]
AVAILABLE_ITEMS2 = AVAILABLE_ITEMS + ["fcs_accum","scs_accum","bus_total","gen_total"]


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