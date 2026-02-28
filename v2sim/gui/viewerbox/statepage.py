from v2sim.gui.common import *

from v2sim import CS, EV, EVDict, TrafficInst
from v2sim.hub.s import GS


_L = LangLib.Load(__file__)


class StateFrame(Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.__inst = None
        self.query_fr = LabelFrame(self, text=_L["TAB_QUERIES"])
        self.cb_fcs_query = Combobox(self.query_fr)
        self.cb_fcs_query.grid(row=0,column=0,sticky='ew',padx=3,pady=5)
        self.btn_fcs_query = Button(self.query_fr, text="Query FCS", takefocus=False, command=self.queryFCS)
        self.btn_fcs_query.grid(row=0,column=1,sticky='ew',padx=3,pady=5)
        self.cb_scs_query = Combobox(self.query_fr)
        self.cb_scs_query.grid(row=1,column=0,sticky='ew',padx=3,pady=5)
        self.btn_scs_query = Button(self.query_fr, text="Query SCS", takefocus=False, command=self.querySCS)
        self.btn_scs_query.grid(row=1,column=1,sticky='ew',padx=3,pady=5)
        self.cb_gs_query = Combobox(self.query_fr)
        self.cb_gs_query.grid(row=2,column=0,sticky='ew',padx=3,pady=5)
        self.btn_gs_query = Button(self.query_fr, text="Query GS", takefocus=False, command=self.queryGS)
        self.btn_gs_query.grid(row=2,column=1,sticky='ew',padx=3,pady=5)
        self.entry_ev_query = Entry(self.query_fr)
        self.entry_ev_query.grid(row=3,column=0,sticky='ew',padx=3,pady=5)
        self.btn_ev_query = Button(self.query_fr, text="Query Vehicle", takefocus=False, command=self.queryEV)
        self.btn_ev_query.grid(row=3,column=1,sticky='ew',padx=3,pady=5)
        self.query_fr.pack(side='top',fill='x',padx=3,pady=5)
        self.text_qres = Text(self)
        self.text_qres.pack(side='top',fill='both',padx=3,pady=5)
    
    def setStateInst(self, inst, mode:str):
        self.__inst = inst
        self.cb_fcs_query['values'] = []
        self.cb_scs_query['values'] = []
        self.cb_gs_query['values'] = []

        from v2sim.sim.ux import TrafficUX
        if mode == 'ux' and isinstance(inst, TrafficUX):
            self.cb_fcs_query['values'] = [cs._name for cs in inst.fcs]
            self.cb_scs_query['values'] = [cs._name for cs in inst.scs]
            self.cb_gs_query['values'] = [cs._name for cs in inst.gs]
            self.__fcs_query = inst.fcs
            self.__scs_query = inst.scs
            self.__gs_query = inst.gs
            self.__vehs_query = inst._vehs
        elif mode == 'sumo' and isinstance(inst, dict):
            self.cb_fcs_query['values'] = [cs._name for cs in inst["hubs"].fcs]
            self.cb_scs_query['values'] = [cs._name for cs in inst["hubs"].scs]
            self.cb_gs_query['values'] = [cs._name for cs in inst["hubs"].gs]
            self.__fcs_query = inst["hubs"].fcs
            self.__scs_query = inst["hubs"].scs
            self.__gs_query = inst["hubs"].gs
            self.__vehs_query = inst["VEHs"]
        else:
            print("Unknown mode or instance type for StateFrame:", mode, type(inst))
    
    def set_qres(self,text:str):
        self.text_qres.delete(0.0,END)
        self.text_qres.insert(END,text)
    
    def __queryCS(self,cstype:Literal["fcs","scs","gs"], q:str):
        if self.__inst is None: 
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        if q.strip()=="":
            self.set_qres(_L["EMPTY_QUERY"])
            return
        if cstype == "fcs": cslist = self.__fcs_query
        elif cstype == "scs": cslist = self.__scs_query
        else: cslist = self.__gs_query
        try:
            cs = cslist[q]
        except:
            res = "Station Not found: "+q
        else:
            if isinstance(cs, CS):
                if cs.supports_V2G:
                    res = (
                        f"ID: {cs.name} (V2G)\nBus: {cs.bus}\n  Pc_kW:{cs.Pc_kW}\n  Pd_kW: {cs.Pd_kW}\n  Pv2g_kW: {cs.Pv2g_kW}\n" +
                        f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n"+
                        f"Price:\n  Buy: {cs._pbuy}\n  Sell: {cs._psell}\n"
                    )
                else:
                    res = (
                        f"ID: {cs.name}\nBus: {cs.bus}\n  Pc_kW:{cs.Pc_kW}\n" +
                        f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n"+
                        f"Price:\n  Buy: {cs._pbuy}\n"
                    )
            elif isinstance(cs, GS):
                res = (
                    f"ID: {cs.name}\nSlots: {cs.slots}\n  Count: {len(cs)} total\n"+
                    f"Price:\n  Buy: {cs._pbuy}\n"
                )
        self.set_qres(res)
    
    def queryFCS(self):
        self.__queryCS("fcs",self.cb_fcs_query.get())
        
    def querySCS(self):
        self.__queryCS("scs",self.cb_scs_query.get())
    
    def queryGS(self):
        self.__queryCS("gs",self.cb_gs_query.get())

    def queryEV(self):
        if self.__inst is None: 
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        q = self.entry_ev_query.get()
        if q.strip() == "":
            self.set_qres(_L["EMPTY_QUERY"])
            return
        vehs = self.__vehs_query
        try:
            veh = vehs[q]
            assert isinstance(veh, EV)
        except:
            res = "EV Not found: "+q
        else:
            res = (
                f"ID: {veh._name}\n  SoC: {veh.soc*100:.4f}%\n  Status: {veh.status}\n  Distance(m): {veh.odometer}\n" + 
                f"Params:\n  Omega: {veh.omega}\n  KRel: {veh._kr}\n  Kfc: {veh._kf}  Ksc: {veh._ks}  Kv2g: {veh.kv2g}\n" +
                f"Consump(Wh/m): {veh._epm * 1000}\n" +
                f"Money:\n  Charging cost: {veh._cost}\n  V2G earn: {veh._earn}\n  Net cost: {veh._cost-veh._earn}\n"
            )
        self.set_qres(res)