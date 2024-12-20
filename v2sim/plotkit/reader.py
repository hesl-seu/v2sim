from ..plugins import *
from ..statistics import *
    
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

class ReadOnlyStatistics(StaReader):
    def has_FCS(self)->bool: return self.__fcs_head is not None
    def has_SCS(self)->bool: return self.__scs_head is not None
    def has_EV(self)->bool: return FILE_EV in self
    def has_GEN(self)->bool: return FILE_GEN in self
    def has_BUS(self)->bool: return FILE_BUS in self
    def has_LINE(self)->bool: return FILE_LINE in self
    
    def __init__(self,path:str):
        super().__init__(path)
        self.root = path
        def __trans(x:str):
            p = x.rfind("#")
            if p>=0: return x[:p]
            return x
            
        if FILE_FCS not in self:
            self.__fcs_head = None
        else:
            self.__fcs_head = list(set(__trans(x) for x in self.GetTable(FILE_FCS).keys()))
            self.__fcs_head.sort(key=_parse_val)
        if FILE_SCS not in self:
            self.__scs_head = None
        else:
            self.__scs_head = list(set(__trans(x) for x in self.GetTable(FILE_SCS).keys()))
            self.__scs_head.sort(key=_parse_val)
        if FILE_EV not in self:
            self.__ev_head = None
        else:
            self.__ev_head = list(set(__trans(x) for x in self.GetTable(FILE_EV).keys()))
            self.__ev_head.sort(key=_parse_val)
        if FILE_GEN not in self:
            self.__gen_head = None
        else:
            self.__gen_head = list(set(__trans(x) for x in self.GetTable(FILE_GEN).keys()))
            for itm in GEN_TOT_ATTRIB:
                if itm in self.__gen_head:
                    self.__gen_head.remove(itm)
            self.__gen_head.sort(key=_parse_val)
        if FILE_BUS not in self:
            self.__bus_head = None
        else:
            self.__bus_head = list(set(__trans(x) for x in self.GetTable(FILE_BUS).keys()))
            for itm in BUS_TOT_ATTRIB:
                if itm in self.__bus_head:
                    self.__bus_head.remove(itm)
            self.__bus_head.sort(key=_parse_val)
        if FILE_LINE not in self:
            self.__line_head = None
        else:
            self.__line_head = list(set(__trans(x) for x in self.GetTable(FILE_LINE).keys()))
            for itm in LINE_ATTRIB:
                if itm in self.__line_head:
                    self.__line_head.remove(itm)
            self.__line_head.sort(key=_parse_val)
        
    @property
    def FCS_head(self)->list[str]: 
        assert self.__fcs_head is not None, "CS properties not supported"
        return self.__fcs_head

    @property
    def SCS_head(self)->list[str]: 
        assert self.__scs_head is not None, "CS properties not supported"
        return self.__scs_head
    
    @property
    def veh_head(self)->list[str]:
        assert self.__ev_head is not None, "Vehicle properties not supported"
        return self.__ev_head
    
    @property
    def gen_head(self)->list[str]:
        assert self.__gen_head is not None, "Generator properties not supported"
        return self.__gen_head
    
    @property
    def bus_head(self)->list[str]:
        assert self.__bus_head is not None, "Bus properties not supported"
        return self.__bus_head
    
    @property
    def line_head(self)->list[str]:
        assert self.__line_head is not None, "Line properties not supported"
        return self.__line_head

    def FCS_attrib_of(self,cs:str,attrib:str)->TimeSeg: 
        '''Charging station information'''
        assert attrib in CS_ATTRIB, f"Invalid CS property: {attrib}"
        if cs == "<sum>":
            d = [self.GetColumn(FILE_FCS,c+"#"+attrib) for c in self.FCS_head]
            return TimeSeg.quicksum(*d)
        return self.GetColumn(FILE_FCS,cs+"#"+attrib)
    
    def SCS_attrib_of(self,cs:str,attrib:str)->TimeSeg: 
        '''Charging station information'''
        assert attrib in CS_ATTRIB, f"Invalid CS property: {attrib}"
        if cs == "<sum>":
            d = [self.GetColumn(FILE_SCS,c+"#"+attrib) for c in self.SCS_head]
            return TimeSeg.quicksum(*d)
        return self.GetColumn(FILE_SCS,cs+"#"+attrib)
    
    def FCS_load_of(self,cs:str)->TimeSeg:
        '''Charging power'''
        return self.FCS_attrib_of(cs,"c")
    
    def FCS_load_all(self,tl=-math.inf,tr=math.inf)->list[TimeSeg]:
        '''Charging power of all CS'''
        return [self.FCS_load_of(cs).slice(tl,tr) for cs in self.FCS_head]
    
    def FCS_count_of(self,cs:str)->TimeSeg:
        '''Number of vehicles in the CS'''
        return self.FCS_attrib_of(cs,"cnt")
    
    def FCS_pricebuy_of(self,cs:str)->TimeSeg:
        '''Buy price'''
        return self.FCS_attrib_of(cs,"pb")
    
    def SCS_charge_load_of(self,cs:str)->TimeSeg:
        '''Charging power'''
        return self.SCS_attrib_of(cs,"c")
    
    def SCS_charge_load_all(self,tl=-math.inf,tr=math.inf)->list[TimeSeg]:
        '''Charging power of all CS'''
        return [self.SCS_charge_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_v2g_load_of(self,cs:str)->TimeSeg:
        '''Discharging power (V2G)'''
        return self.SCS_attrib_of(cs,"d")
    
    def SCS_v2g_load_all(self,tl=-math.inf,tr=math.inf)->list[TimeSeg]:
        '''Discharging power (V2G) of all CS'''
        return [self.SCS_v2g_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_v2g_cap_of(self,cs:str)->TimeSeg:
        '''V2G capacity'''
        return self.SCS_attrib_of(cs,"v2g")
    
    def SCS_v2g_cap_all(self,tl=-math.inf,tr=math.inf)->list[TimeSeg]:
        '''V2G capacity of all CS'''
        return [self.SCS_v2g_cap_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_net_load_of(self,cs:str)->TimeSeg:
        '''Net charging power'''
        return self.SCS_charge_load_of(cs) - self.SCS_v2g_load_of(cs)
    
    def SCS_net_load_all(self,tl=-math.inf,tr=math.inf)->list[TimeSeg]:
        '''Net charging power of all CS'''
        return [self.SCS_net_load_of(cs).slice(tl,tr) for cs in self.SCS_head]
    
    def SCS_count_of(self,cs:str)->TimeSeg:
        '''Number of vehicles in the CS'''
        return self.SCS_attrib_of(cs,"cnt")
    
    def SCS_pricebuy_of(self,cs:str)->TimeSeg:
        '''Buy price'''
        return self.SCS_attrib_of(cs,"pb")
    
    def SCS_pricesell_of(self,cs:str)->TimeSeg:
        '''Sell price'''
        return self.SCS_attrib_of(cs,"ps")
    
    def EV_attrib_of(self,veh:str,attrib:str)->TimeSeg: 
        '''EV information'''
        assert attrib in EV_ATTRIB, f"Invalid EV property: {attrib}"
        return self.GetColumn(FILE_EV,veh+"#"+attrib)
    
    def EV_net_cost_of(self,veh:str)->TimeSeg: 
        '''EV net cost'''
        return self.GetColumn(FILE_EV,veh+"#cost")-self.GetColumn(FILE_EV,veh+"#earn")
    
    def G_attrib_of(self,g:str,attrib:str)->TimeSeg: 
        '''Generator information'''
        assert attrib in GEN_ATTRIB
        return self.GetColumn(FILE_GEN,g+"#"+attrib)
    
    def G_total(self,attrib:str)->TimeSeg:
        '''Total generation data'''
        assert attrib in GEN_TOT_ATTRIB
        return self.GetColumn(FILE_GEN,attrib)
    
    def bus_attrib_of(self,b:str,attrib:str)->TimeSeg: 
        '''Bus information'''
        assert attrib in BUS_ATTRIB
        return self.GetColumn(FILE_BUS,b+"#"+attrib)
    
    def bus_total(self,attrib:str)->TimeSeg:
        '''Total bus data'''
        assert attrib in BUS_TOT_ATTRIB
        return self.GetColumn(FILE_BUS,attrib)
    
    def line_attrib_of(self,l:str,attrib:str)->TimeSeg: 
        '''Line information'''
        assert attrib in LINE_ATTRIB
        return self.GetColumn(FILE_LINE,l+"#"+attrib)