from itertools import chain
from typing import Optional
from feasytools import TimeFunc, LangLib

from ..sim.pdncore import IntegratedPDN
from .base import *

FILE_GEN = "gen"
FILE_BUS = "bus"
FILE_LINE = "line"
FILE_PVW = "pvw"
FILE_ESS = "ess"

GEN_ATTRIB = ["P","Q","costp"]
GEN_TOT_ATTRIB = ["totP","totQ","totC"]
BUS_ATTRIB = ["Pd","Qd","Pg","Qg","V","sp"]
BUS_TOT_ATTRIB = ["totPd","totQd","totPg","totQg"]
LINE_ATTRIB = ["P","Q","I"]
PVW_ATTRIB = ["P","curt"]
ESS_ATTRIB = ["P","soc"]

_L = LangLib(["en", "zh_CN"])
_L.SetLangLib("en",
    GEN = "Generator",
    BUS = "Bus",
    LINE = "Line",
    PVW = "PV/Wind",
    ESS = "ESS",
)

_L.SetLangLib("zh_CN",
    GEN = "发电机",
    BUS = "母线",
    LINE = "线路",
    PVW = "光伏/风电",
    ESS = "储能",
)

def _chk(x:Optional[float])->float:
    if x is None: return 0
    return x

def _find_grid_source(tinst: TrafficInst) -> IntegratedPDN:
    core_pdn = getattr(tinst, "_integrated_pdn", None)
    if core_pdn is None:
        raise ValueError("Integrated PDN core is not initialized.")
    return core_pdn

class StaGen(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        self.__plg = _find_grid_source(tinst)
        # Physical generator columns are fixed at startup. Dynamic internal V2G
        # price-group generators are represented by exactly one logical column
        # set per V2G-capable charging station.
        self.__physical_gen_names = [
            g.ID for g in self.__plg.Grid.Gens
            if not getattr(g, "IsV2GBidGroup", False)
        ]
        self.__v2g_gen_names = list(getattr(self.__plg, "V2GLogGenNames", []))
        gen_names = self.__physical_gen_names + self.__v2g_gen_names
        super().__init__(FILE_GEN, path, cross_list2(gen_names, GEN_ATTRIB) + GEN_TOT_ATTRIB, tinst, plugins)
    
    @staticmethod
    def GetLocalizedName() -> str:
        return _L("GEN")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        return []

    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        mpdn = self.__plg
        sb_MVA = mpdn.Grid.Sb_MVA
        _t = inst.current_time
        p = []; q = []; cp = []

        # Preserve the startup physical-generator order even when dynamic V2G
        # market segments are added/deleted from Grid.Gens.
        for name in self.__physical_gen_names:
            g = mpdn.Grid.Gen(name)
            costthis = g.Cost(_t)
            if costthis is None:
                costthis = 0
            gp = g.P(_t) if isinstance(g.P, TimeFunc) else g.P
            gq = g.Q(_t) if isinstance(g.Q, TimeFunc) else g.Q
            p.append(0.0 if gp is None else float(gp) * sb_MVA)
            q.append(0.0 if gq is None else float(gq) * sb_MVA)
            cp.append(float(costthis))

        # One aggregated logical V2G generator per station, regardless of how
        # many exact price groups currently exist inside the OPF.
        v2g = mpdn.get_v2g_generator_log_data(_t)
        for name in self.__v2g_gen_names:
            vp, vq, vc = v2g.get(name, (0.0, 0.0, 0.0))
            p.append(vp); q.append(vq); cp.append(vc)

        return chain(p, q, cp, [sum(p), sum(q), sum(cp)])

class StaBus(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        self.__plg = _find_grid_source(tinst)
        bus_names = self.__plg.Grid.BusNames
        physical_gen_buses = [b.ID for b in self.__plg.Grid.Buses if len(self.__plg.Grid.GensAtBus(b.ID)) > 0]
        v2g_buses = list(getattr(self.__plg, "V2GBuses", []))
        self.__bus_with_gens = list(dict.fromkeys(physical_gen_buses + v2g_buses))
        super().__init__(FILE_BUS, path, cross_list2(bus_names, ["Pd", "Qd", "V", "sp"]) 
            + cross_list2(self.__bus_with_gens, ["Pg", "Qg"]) + BUS_TOT_ATTRIB, tinst, plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("BUS")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst: TrafficInst, plugins: Dict[str, PluginBase]) -> Iterable[Any]:
        '''Get Data'''
        mpdn = self.__plg.Grid
        sb_MVA = mpdn.Sb
        _t = inst.current_time
        bs = mpdn.Buses
        Pd = [b.Pd(_t)*sb_MVA for b in bs]
        Qd = [b.Qd(_t)*sb_MVA for b in bs]
        V = (b.V * mpdn.Ub if b.V else 0 for b in bs)
        p = (b.ShadowPrice for b in bs)
        Pg = []; Qg = []
        for bn in self.__bus_with_gens:
            pg = 0; qg = 0
            for g in mpdn.GensAtBus(bn):
                if isinstance(g.P, float): pg += g.P
                elif isinstance(g.P, TimeFunc): pg += g.P(_t)
                if isinstance(g.Q, float): qg += g.Q
                elif isinstance(g.Q, TimeFunc): qg += g.Q(_t)
            Pg.append(pg*sb_MVA); Qg.append(qg*sb_MVA)
        return chain(Pd, Qd, V, p, Pg, Qg, [sum(Pd), sum(Qd), sum(Pg), sum(Qg)]) # Unit = MVA

class StaLine(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        self.__plg = _find_grid_source(tinst)
        super().__init__(FILE_LINE, path, cross_list2(self.__plg.Grid._lines.keys(), LINE_ATTRIB), tinst, plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("LINE")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str,PluginBase]) -> Iterable[Any]:
        mpdn = self.__plg.Grid
        P = (_chk(b.P)*mpdn.Sb for b in mpdn.Lines)
        Q = (_chk(b.Q)*mpdn.Sb for b in mpdn.Lines)
        I = (_chk(b.I)*mpdn.Ib for b in mpdn.Lines)
        return chain(P, Q, I) # Unit = MVA or kA

class StaPVWind(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        self.__plg = _find_grid_source(tinst)
        super().__init__(FILE_PVW, path, cross_list2(self.__plg.Grid._pvws.keys(), PVW_ATTRIB),tinst,plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("PVW")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str,PluginBase]) -> Iterable[Any]:
        mpdn = self.__plg.Grid
        P = (b.P(inst.current_time)*mpdn.Sb for b in mpdn.PVWinds)
        curt = (_chk(b._cr) for b in mpdn.PVWinds)
        return chain(P, curt) # Unit = MVA or %

class StaESS(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        self.__plg = _find_grid_source(tinst)
        super().__init__(FILE_ESS, path, cross_list2(self.__plg.Grid._esss.keys(), ESS_ATTRIB),tinst,plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("ESS")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str,PluginBase])->Iterable[Any]:
        mpdn = self.__plg.Grid
        P = (_chk(b.P) * mpdn.Sb for b in mpdn.ESSs)
        soc = (b.SOC for b in mpdn.ESSs)
        return chain(P, soc) # Unit = MVA or %