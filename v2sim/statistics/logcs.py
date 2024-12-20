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
        cnt = inst.FCSList.get_veh_count()
        Pc = map(lambda cs:cs.Pc_kW, inst.FCSList)
        pb = map(lambda cs:cs.pbuy(t), inst.FCSList)
        return chain(cnt, Pc, pb)

class StaSCS(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        head = cross_list(tinst.SCSList.get_CS_names(),CS_ATTRIB)
        super().__init__(FILE_SCS,path,head,tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        t = inst.current_time
        v2g = "v2g" in plugins and plugins["v2g"].IsOnline(t)
        cnt = inst.SCSList.get_veh_count()
        Pc = map(lambda cs:cs.Pc_kW, inst.SCSList)
        pb = map(lambda cs:cs.pbuy(t), inst.SCSList)
        if len(inst.SCSList)>0 and inst.SCSList[0].supports_V2G:
            ps = map(lambda cs:cs.psell(t), inst.SCSList)
            Pd = map(lambda cs:cs.Pd_kW, inst.SCSList) if v2g else repeat(0,len(inst.SCSList))
            Pv2g = map(lambda cs:cs.Pv2g_kW, inst.SCSList) if v2g else repeat(0,len(inst.SCSList))
        else:
            ps = repeat(0,len(inst.SCSList))
            Pd = repeat(0,len(inst.SCSList))
            Pv2g = repeat(0,len(inst.SCSList))
        return chain(cnt,Pc,Pd,Pv2g,pb,ps)