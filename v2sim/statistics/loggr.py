from itertools import chain
from typing import Protocol, runtime_checkable
from fpowerkit import Grid
from .base import *

FILE_GEN = "gen"
FILE_BUS = "bus"
FILE_LINE = "line"
GEN_ATTRIB = ["P","Q","costp"]
GEN_TOT_ATTRIB = ["totP","totQ","totC"]
BUS_ATTRIB = ["Pd","Qd","Pg","Qg","V"]
BUS_TOT_ATTRIB = ["totPd","totQd","totPg","totQg"]
LINE_ATTRIB = ["P","Q","I"]

def _chk(x:Optional[float])->float:
    if x is None: return 0
    return x

def _find_grid_plugin(plugins:dict[str,PluginBase])->IGridPlugin:
    for plg in plugins.values():
        if isinstance(plg, IGridPlugin):
            return plg
    raise ValueError("未找到可以导出电网数据的插件")

class StaGen(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        self.__plg = _find_grid_plugin(plugins)
        gen_names = self.__plg.Grid.GenNames
        super().__init__(FILE_GEN,path,cross_list(gen_names,GEN_ATTRIB)+GEN_TOT_ATTRIB,tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:list[PluginBase])->Iterable[Any]:
        mpdn = self.__plg
        sb_MVA = mpdn.Grid.Sb_MVA
        _t = inst.current_time
        p = []; q = []; cp = []
        for g in mpdn.Grid.Gens:
            costthis = g.Cost(_t)
            if costthis is None:
                costthis = 0
            if g.P is None or g.Q is None:
                p.append(0); q.append(0)
                cp.append(costthis)
            else:
                p.append(g.P*sb_MVA); q.append(g.Q*sb_MVA)
                cp.append(costthis)
        return chain(p,q,cp,[sum(p), sum(q), sum(cp)])

class StaBus(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        self.__plg = _find_grid_plugin(plugins)
        bus_names = self.__plg.Grid.BusNames
        self.__bus_with_gens = [b.ID for b in self.__plg.Grid.Buses if len(self.__plg.Grid.GensAtBus(b.ID))>0]
        super().__init__(FILE_BUS,path,cross_list(bus_names,["Pd","Qd","V"]) 
            + cross_list(self.__bus_with_gens,["Pg","Qg"]) + BUS_TOT_ATTRIB,tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        mpdn = self.__plg.Grid
        sb_MVA = mpdn.Sb
        _t = inst.current_time
        Pd = [b.Pd(_t)*sb_MVA for b in mpdn.Buses]
        Qd = [b.Qd(_t)*sb_MVA for b in mpdn.Buses]
        V = [b.V*mpdn.Ub if b.V else 0 for b in mpdn.Buses]
        Pg = []; Qg = []
        for bn in self.__bus_with_gens:
            pg = 0; qg = 0
            for g in mpdn.GensAtBus(bn):
                if g.P is not None: pg += g.P
                if g.Q is not None: qg += g.Q
            Pg.append(pg*sb_MVA); Qg.append(qg*sb_MVA)
        return chain(Pd,Qd,V,Pg,Qg,[sum(Pd), sum(Qd), sum(Pg), sum(Qg)]) # Unit = MVA

class StaLine(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        self.__plg = _find_grid_plugin(plugins)
        super().__init__(FILE_LINE,path,cross_list(self.__plg.Grid._lines.keys(),["P","Q","I"]),tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        mpdn = self.__plg.Grid
        Ib_kA = mpdn.Ib
        sb_MVA = mpdn.Sb
        P = [_chk(b.P)*sb_MVA for b in mpdn.Lines]
        Q = [_chk(b.Q)*sb_MVA for b in mpdn.Lines]
        I = [_chk(b.I)*Ib_kA for b in mpdn.Lines]
        return chain(P,Q,I) # Unit = MVA or kA