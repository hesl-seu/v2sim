from collections import defaultdict
from itertools import chain
from feasytools import LangLib
from fpowerkit import IslandResult, DistFlowSolver, Estimator
from ..traffic.cs import CS
from .pdn import PluginPDN
from .base import *

_locale = LangLib(["zh_CN","en"])
_locale.SetLangLib("zh_CN",
    DESCRIPTION = "过流保护",
    ERROR_NO_PDN = "过流保护依赖于PDN插件",
    ERROR_SMART_CHARGE = "启用有序充电时过流保护不可用",
)
_locale.SetLangLib("en",
    DESCRIPTION = "Over-current protection",
    ERROR_NO_PDN = "Over-current protection depends on PDN plugin",
    ERROR_SMART_CHARGE = "Over-current protection is not available when smart charging is enabled",
)

class PluginOvercurrent(PluginBase[None]):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    def _save_state(self) -> object:
        '''Save the plugin state'''
        return None
    
    def _load_state(self,state:object) -> None:
        '''Load the plugin state'''

    @staticmethod
    def ElemShouldHave() -> ConfigDict:
        '''Get the plugin configuration item list'''
        return ConfigDict()
    
    def Init(self, elem:ET.Element, inst:TrafficInst, work_dir:Path, res_dir:Path, plg_deps:'List[PluginBase]')->None:
        self.__file = open(str(res_dir / "current_protect.log"), "w")
        self.SetPreStep(self._work)
        self.SetPostSimulation(self.__file.close)
        assert len(plg_deps) == 1 and isinstance(plg_deps[0], PluginPDN), _locale["ERROR_NO_PDN"]
        self.__pdn = plg_deps[0]
        if self.__pdn.isSmartChargeEnabled():
            raise RuntimeError(_locale["ERROR_SMART_CHARGE"])
        if self.__pdn.Solver.est != Estimator.DistFlow:
            raise RuntimeError("Over-current protection only works with DistFlowSolver")
        self.__csatb:Dict[str, List[CS]] = defaultdict(list)
        for cs in chain(inst.SCSList, inst.FCSList):
            self.__csatb[cs._bus].append(cs)
        self.__csatb_closed:Dict[str, bool] = {
            b:False for b in self.__csatb
        }
    
    def _close(self, b:str):
        '''
        Force shutdown all charging stations at bus b
        '''
        if self.__csatb_closed[b]: return
        for cs in self.__csatb[b]:
            cs.force_shutdown()
        print(f"CS {','.join(map(lambda x:x.name, self.__csatb[b]))} forced shutdown at bus {b}.", file=self.__file)

    def _work(self,_t:int,/,sta:PluginStatus)->Tuple[bool, None]:
        '''
        Get the V2G demand power of all bus with slow charging stations at time _t, unit kWh/s, 3.6MW=3600kW=1kWh/s
        '''
        if sta == PluginStatus.EXECUTE:
            p = self.__pdn
            if p.LastPreStepSucceed:
                svr = p.Solver
                assert isinstance(svr.est, DistFlowSolver), "Over-current protection only works with DistFlowSolver"
                if len(svr.est.OverflowLines) > 0:
                    print(f"[{_t}] Overcurrent protection triggered: ", svr.est.OverflowLines, file=self.__file)
                    for l in svr.est.OverflowLines:
                        ln = p.Grid.Line(l)
                        ln.P = 0.
                        ln.Q = 0.
                        ln.I = 0.
                    svr.est.UpdateGrid(p.Grid, cut_overflow_lines=True)
                    self.__island_closed = [False] * len(svr.est.Islands)
                    svr.solve(_t)
                for i, il in enumerate(svr.est.Islands):
                    if il.result == IslandResult.Failed and not self.__island_closed[i]:
                        self.__island_closed[i] = True
                        for b in il.Buses: self._close(b)
                ret = True, None
            else:
                ret = False, None
        elif sta == PluginStatus.OFFLINE:
            ret = True, None
        elif sta == PluginStatus.HOLD:
            ret = True, self.LastPreStepResult
        return ret