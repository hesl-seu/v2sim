from ..plugins import *
from ..statistics import *
from typing import Any
from feasytools import SegFunc
import math
    
class StatisticsNotSupportedError(Exception): pass

def _parse_val(x:str)->list[Any]:
    v = []
    v0 = 0
    for c in x:
        if c.isdigit():
            v0 = v0*10 + int(c)
        else:
            if v0>0:
                v.append(v0)
                v0 = 0
            v.append(ord(c))
    if v0>0: v.append(v0)
    return v

TO_BE_LOADED = True

class ReadOnlyStatistics(StaReader):
    def has_FCS(self)->bool: return self.__fcs_head is not None
    def has_SCS(self)->bool: return self.__scs_head is not None
    def has_EV(self)->bool: return FILE_EV in self
    def has_GEN(self)->bool: return FILE_GEN in self
    def has_BUS(self)->bool: return FILE_BUS in self
    def has_LINE(self)->bool: return FILE_LINE in self
    def has_PVW(self)->bool: return FILE_PVW in self
    def has_ESS(self)->bool: return FILE_ESS in self
    
    def __loadhead(self, name:str) -> list[str]:
        def __trans(x:str):
            p = x.rfind("#")
            if p>=0: return x[:p]
            return x
        return list(set(__trans(x) for x in self.GetTable(name).keys()))
    
    def __init__(self, path:str):
        super().__init__(path)
        self.root = path
        self.__fcs_head = None if FILE_FCS not in self else TO_BE_LOADED
        self.__scs_head = None if FILE_SCS not in self else TO_BE_LOADED
        self.__ev_head  = None if FILE_EV  not in self else TO_BE_LOADED
        self.__gen_head = None if FILE_GEN not in self else TO_BE_LOADED
        self.__bus_head = None if FILE_BUS not in self else TO_BE_LOADED
        self.__line_head = None if FILE_LINE not in self else TO_BE_LOADED
        self.__pvw_head = None if FILE_PVW not in self else TO_BE_LOADED
        self.__ess_head = None if FILE_ESS not in self else TO_BE_LOADED
        
    @property
    def FCS_head(self)->list[str]: 
        assert self.__fcs_head is not None, "CS properties not supported"
        if not isinstance(self.__fcs_head, list):
            self.__fcs_head = self.__loadhead(FILE_FCS)
            self.__fcs_head.sort(key=_parse_val)
        return self.__fcs_head

    @property
    def SCS_head(self)->list[str]: 
        assert self.__scs_head is not None, "CS properties not supported"
        if not isinstance(self.__scs_head, list):
            self.__scs_head = self.__loadhead(FILE_SCS)
            self.__scs_head.sort(key=_parse_val)
        return self.__scs_head
    
    @property
    def veh_head(self)->list[str]:
        assert self.__ev_head is not None, "Vehicle properties not supported"
        if not isinstance(self.__ev_head, list):
            self.__ev_head = self.__loadhead(FILE_EV)
            self.__ev_head.sort(key=_parse_val)
        return self.__ev_head
    
    @property
    def gen_head(self)->list[str]:
        assert self.__gen_head is not None, "Generator properties not supported"
        if not isinstance(self.__gen_head, list):
            self.__gen_head = self.__loadhead(FILE_GEN)
            for itm in GEN_TOT_ATTRIB:
                if itm in self.__gen_head:
                    self.__gen_head.remove(itm)
            self.__gen_head.sort(key=_parse_val)
        return self.__gen_head
    
    @property
    def bus_head(self)->list[str]:
        assert self.__bus_head is not None, "Bus properties not supported"
        if not isinstance(self.__bus_head, list):
            self.__bus_head = self.__loadhead(FILE_BUS)
            for itm in BUS_TOT_ATTRIB:
                if itm in self.__bus_head:
                    self.__bus_head.remove(itm)
            self.__bus_head.sort(key=_parse_val)
        return self.__bus_head
    
    @property
    def line_head(self)->list[str]:
        assert self.__line_head is not None, "Line properties not supported"
        if not isinstance(self.__line_head, list):
            self.__line_head = self.__loadhead(FILE_LINE)
            for itm in LINE_ATTRIB:
                if itm in self.__line_head:
                    self.__line_head.remove(itm)
            self.__line_head.sort(key=_parse_val)
        return self.__line_head
    
    @property
    def pvw_head(self)->list[str]:
        assert self.__pvw_head is not None, "PV & Wind properties not supported"
        if not isinstance(self.__pvw_head, list):
            self.__pvw_head = self.__loadhead(FILE_PVW)
            for itm in PVW_ATTRIB:
                if itm in self.__pvw_head:
                    self.__pvw_head.remove(itm)
            self.__pvw_head.sort(key=_parse_val)
        return self.__pvw_head

    @property
    def ess_head(self)->list[str]:
        assert self.__ess_head is not None, "ESS properties not supported"
        if not isinstance(self.__ess_head, list):
            self.__ess_head = self.__loadhead(FILE_ESS)
            for itm in ESS_ATTRIB:
                if itm in self.__ess_head:
                    self.__ess_head.remove(itm)
            self.__ess_head.sort(key=_parse_val)
        return self.__ess_head

    def FCS_attrib_of(self,cs:str, attrib:str)->SegFunc: 
        '''Charging station information'''
        assert attrib in CS_ATTRIB, f"Invalid CS property: {attrib}"
        if cs == "<sum>":
            d = [self.GetColumn(FILE_FCS,c+"#"+attrib) for c in self.FCS_head]
            return SegFunc.qs(d)
        return self.GetColumn(FILE_FCS,cs+"#"+attrib)
    
    def SCS_attrib_of(self,cs:str,attrib:str)->SegFunc: 
        '''Charging station information'''
        assert attrib in CS_ATTRIB, f"Invalid CS property: {attrib}"
        if cs == "<sum>":
            d = [self.GetColumn(FILE_SCS,c+"#"+attrib) for c in self.SCS_head]
            return SegFunc.qs(d)
        return self.GetColumn(FILE_SCS,cs+"#"+attrib)
    
    def FCS_load_of(self,cs:str)->SegFunc:
        '''Charging power'''
        return self.FCS_attrib_of(cs,"c")
    
    def FCS_load_all(self,tl=-math.inf,tr=math.inf)->list[SegFunc]:
        '''Charging power of all CS'''
        return [self.FCS_load_of(cs).slice(tl,tr) for cs in self.FCS_head]
    
    def FCS_count_of(self,cs:str)->SegFunc:
        '''Number of vehicles in the CS'''
        return self.FCS_attrib_of(cs,"cnt")
    
    def FCS_pricebuy_of(self,cs:str)->SegFunc:
        '''Buy price'''
        return self.FCS_attrib_of(cs,"pb")
    
    def SCS_charge_load_of(self,cs:str)->SegFunc:
        '''Charging power'''
        return self.SCS_attrib_of(cs,"c")
    
    def SCS_charge_load_all(self,tl=-math.inf,tr=math.inf)->list[SegFunc]:
        '''Charging power of all CS'''
        return [self.SCS_charge_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_v2g_load_of(self,cs:str)->SegFunc:
        '''Discharging power (V2G)'''
        return self.SCS_attrib_of(cs,"d")
    
    def SCS_v2g_load_all(self,tl=-math.inf,tr=math.inf)->list[SegFunc]:
        '''Discharging power (V2G) of all CS'''
        return [self.SCS_v2g_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_v2g_cap_of(self,cs:str)->SegFunc:
        '''V2G capacity'''
        return self.SCS_attrib_of(cs,"v2g")
    
    def SCS_v2g_cap_all(self,tl=-math.inf,tr=math.inf)->list[SegFunc]:
        '''V2G capacity of all CS'''
        return [self.SCS_v2g_cap_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_net_load_of(self,cs:str)->SegFunc:
        '''Net charging power'''
        return self.SCS_charge_load_of(cs) - self.SCS_v2g_load_of(cs)
    
    def SCS_net_load_all(self,tl=-math.inf,tr=math.inf)->list[SegFunc]:
        '''Net charging power of all CS'''
        return [self.SCS_net_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_count_of(self,cs:str)->SegFunc:
        '''Number of vehicles in the CS'''
        return self.SCS_attrib_of(cs,"cnt")
    
    def SCS_pricebuy_of(self,cs:str)->SegFunc:
        '''Buy price'''
        return self.SCS_attrib_of(cs,"pb")
    
    def SCS_pricesell_of(self,cs:str)->SegFunc:
        '''Sell price'''
        return self.SCS_attrib_of(cs,"ps")
    
    def EV_attrib_of(self,veh:str,attrib:str)->SegFunc: 
        '''EV information'''
        assert attrib in EV_ATTRIB, f"Invalid EV property: {attrib}"
        return self.GetColumn(FILE_EV,veh+"#"+attrib)
    
    def EV_net_cost_of(self,veh:str)->SegFunc: 
        '''EV net cost'''
        return self.GetColumn(FILE_EV,veh+"#cost")-self.GetColumn(FILE_EV,veh+"#earn")
    
    def G_attrib_of(self,g:str,attrib:str)->SegFunc: 
        '''Generator information'''
        assert attrib in GEN_ATTRIB
        return self.GetColumn(FILE_GEN,g+"#"+attrib)
    
    def G_total(self,attrib:str)->SegFunc:
        '''Total generation data'''
        assert attrib in GEN_TOT_ATTRIB
        return self.GetColumn(FILE_GEN,attrib)
    
    def bus_attrib_of(self,b:str,attrib:str)->SegFunc: 
        '''Bus information'''
        assert attrib in BUS_ATTRIB
        return self.GetColumn(FILE_BUS,b+"#"+attrib)
    
    def bus_total(self,attrib:str)->SegFunc:
        '''Total bus data'''
        assert attrib in BUS_TOT_ATTRIB
        return self.GetColumn(FILE_BUS,attrib)
    
    def line_attrib_of(self,l:str,attrib:str)->SegFunc: 
        '''Line information'''
        assert attrib in LINE_ATTRIB
        return self.GetColumn(FILE_LINE,l+"#"+attrib)
    
    def pvw_attrib_of(self,p:str,attrib:str)->SegFunc:
        '''PV and wind information'''
        assert attrib in PVW_ATTRIB
        return self.GetColumn(FILE_PVW,p+"#"+attrib)
    
    def ess_attrib_of(self,e:str,attrib:str)->SegFunc:
        '''ESS information'''
        assert attrib in ESS_ATTRIB
        return self.GetColumn(FILE_ESS,e+"#"+attrib)