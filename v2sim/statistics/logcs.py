from itertools import chain, repeat
from .base import *

FILE_FCS = "fcs"
FILE_SCS = "scs"
CS_ATTRIB = ["cnt","c","d","v2g","pb","ps"]

class StaFCS(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        head = cross_list(tinst.FCSList.get_CS_names(),["cnt","c","pb"])
        super().__init__(FILE_FCS,path,head,tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        t = inst.current_time
        IL = inst.FCSList
        cnt = (cs.__len__() for cs in IL)
        Pc = (cs._cload * 3600 for cs in IL)
        pb = (cs.pbuy(t) for cs in IL)
        return chain(cnt, Pc, pb)

class StaSCS(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        head = cross_list(tinst.SCSList.get_CS_names(),CS_ATTRIB)
        super().__init__(FILE_SCS,path,head,tinst,plugins)
        self.L = len(tinst.SCSList)
        self.supv2g = self.L > 0 and tinst.SCSList[0].supports_V2G
        self.hasv2g = "v2g" in plugins

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        L = self.L
        IL = inst.SCSList
        t = inst.current_time
        cnt = (cs.__len__() for cs in IL)
        Pc = (cs._cload * 3600 for cs in IL) # Performance problem: do not call property
        pb = (cs._pbuy(t) for cs in IL)
        if self.supv2g:
            v2g = self.hasv2g and plugins["v2g"].IsOnline(t)
            ps = (cs._psell(t) for cs in IL) # type: ignore
            Pd = (cs._dload * 3600 for cs in IL) if v2g else repeat(0, L)
            Pv2g = (cs._cur_v2g_cap * 3600 for cs in IL) if v2g else repeat(0, L)
        else:
            ps = repeat(0,L)
            Pd = repeat(0,L)
            Pv2g = repeat(0,L)
        return chain(cnt,Pc,Pd,Pv2g,pb,ps)