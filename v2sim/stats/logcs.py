from itertools import chain, repeat
from feasytools import LangLib
from .base import *

FILE_FCS = "fcs"
FILE_SCS = "scs"
FILE_GS = "gs"
CS_ATTRIB = ["cnt", "c", "d", "v2g", "v2gpay", "v2guser"]
GS_ATTRIB = ["cnt"]

_L = LangLib(["en", "zh_CN"])
_L.SetLangLib("en",
    FCS = "FCS",
    SCS = "SCS",
    GS = "Gas station",
)
_L.SetLangLib("zh_CN",
    FCS = "快充站",
    SCS = "慢充站",
    GS = "加油站",
)

class StaFCS(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        head = cross_list2(tinst.fcs.get_names(), ["cnt", "c"])
        super().__init__(FILE_FCS, path, head, tinst, plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("FCS")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        IL = inst._hubs.fcs
        cnt = (cs.__len__() for cs in IL)
        Pc = (cs._cload * 3600 for cs in IL)
        return chain(cnt, Pc)

class StaSCS(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        head = cross_list2(tinst.scs.get_names(), CS_ATTRIB)
        super().__init__(FILE_SCS, path, head, tinst, plugins)
        self.L = len(tinst._hubs.scs)
        self.pdn_core = getattr(tinst, "_integrated_pdn", None)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("SCS")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        L = self.L
        IL = inst._hubs.scs
        t = inst._ct
        cnt = (cs.__len__() for cs in IL)
        Pc = (cs._cload * 3600 for cs in IL)
        if self.pdn_core is not None and self.pdn_core.v2g_online(t):
            Pd = (cs._dload * 3600 for cs in IL)
            Pv2g = (cs._cur_v2g_cap * 3600 for cs in IL)
            # Exact actual V2G settlement rates for the just-completed physical
            # step. Units are $/h so integrating rate * dt/3600 gives dollars.
            Ppay = (getattr(cs, "_v2g_actual_system_payment_rate_per_hour", 0.0) for cs in IL)
            Puser = (getattr(cs, "_v2g_actual_user_revenue_rate_per_hour", 0.0) for cs in IL)
        else:
            Pd = repeat(0, L)
            Pv2g = repeat(0, L)
            Ppay = repeat(0, L)
            Puser = repeat(0, L)
        return chain(cnt, Pc, Pd, Pv2g, Ppay, Puser)
    

class StaGS(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        head = cross_list2(tinst.gs.get_names(), GS_ATTRIB)
        super().__init__(FILE_GS, path, head, tinst, plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("GS")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        return (cs.__len__() for cs in inst._hubs.gs)