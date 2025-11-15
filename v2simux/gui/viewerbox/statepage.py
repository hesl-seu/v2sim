from v2simux.gui.common import *

from v2simux import CS, CSList, EV, EVDict, TrafficInst


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
        self.entry_ev_query = Entry(self.query_fr)
        self.entry_ev_query.grid(row=2,column=0,sticky='ew',padx=3,pady=5)
        self.btn_ev_query = Button(self.query_fr, text="Query EV", takefocus=False, command=self.queryEV)
        self.btn_ev_query.grid(row=2,column=1,sticky='ew',padx=3,pady=5)
        self.query_fr.pack(side='top',fill='x',padx=3,pady=5)
        self.text_qres = Text(self)
        self.text_qres.pack(side='top',fill='both',padx=3,pady=5)
    
    def setStateInst(self, inst:Optional[TrafficInst]):
        self.__inst = inst
        if inst is None:
            self.cb_fcs_query['values'] = []
            self.cb_scs_query['values'] = []
            return
        fcslist = inst._fcs
        scslist = inst._scs
        assert isinstance(fcslist, CSList)
        assert isinstance(scslist, CSList)
        self.cb_fcs_query['values'] = [cs.name for cs in fcslist]
        self.cb_scs_query['values'] = [cs.name for cs in scslist]
    
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
        cslist = self.__inst._fcs if cstype=="fcs" else self.__inst._scs
        assert isinstance(cslist, CSList)
        try:
            cs = cslist[q]
            assert isinstance(cs, CS)
        except:
            res = "CS Not found: "+q
        else:
            if cs.supports_V2G:
                res = (
                    f"ID: {cs.name} (V2G)\nBus: {cs.bus}\n  Pc_kW:{cs.Pc_kW}\n  Pd_kW: {cs.Pd_kW}\n  Pv2g_kW: {cs.Pv2g_kW}\n" +
                    f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n"+
                    f"Price:\n  Buy: {cs.pbuy}\n  Sell: {cs.psell}\n"
                )
            else:
                res = (
                    f"ID: {cs.name}\nBus: {cs.bus}\n  Pc_kW:{cs.Pc_kW}\n" +
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
        vehs = self.__inst._VEHs
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