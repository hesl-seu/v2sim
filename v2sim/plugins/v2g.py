from itertools import chain
from fpowerkit import Generator
from feasytools import ComFunc, LangLib
from ..hub import ConstPriceGetter, ToUPriceGetter
from .pdn import PluginPDN
from .base import *

V2GRes = List[float]

_locale = LangLib(["zh_CN","en"])
_locale.SetLangLib("zh_CN",
    DESCRIPTION = "V2G调度系统",
    ERROR_NO_PDN = "V2G调度依赖于PDN插件",
    ERROR_SMART_CHARGE = "启用有序充电时V2G调度插件不可用",
)
_locale.SetLangLib("en",
    DESCRIPTION = "V2G scheduling system",
    ERROR_NO_PDN = "V2G scheduling depends on PDN plugin",
    ERROR_SMART_CHARGE = "V2G scheduling plugin is not available when smart charging is enabled",
)

class PluginV2G(PluginBase[V2GRes]):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    def _save_state(self) -> object:
        '''Save the plugin state'''
        return None
    
    def _load_state(self, state:object) -> None:
        '''Load the plugin state'''

    @staticmethod
    def ElemShouldHave() -> ConfigDict:
        '''Get the plugin configuration item list'''
        return ConfigDict()
    
    def Init(self, elem:Element, inst:TrafficInst, work_dir:Path, res_dir:Path, plg_deps:'List[PluginBase]') -> V2GRes:
        self.__inst = inst
        self.__step_len = inst.step_len
        self.SetPreStep(self._work)
        self.SetPostStep(self._work_post)

        assert len(plg_deps) == 1 and isinstance(plg_deps[0], IGridPlugin), _locale["ERROR_NO_PDN"]
        self.__pdn = plg_deps[0]
        if isinstance(self.__pdn, PluginPDN) and self.__pdn.isSmartChargeEnabled():
            raise RuntimeError(_locale["ERROR_SMART_CHARGE"])
        self.__inst = inst
        self._cap:List[float] = [0.] * (len(inst.fcs) + len(inst.scs))

        for i, cs in enumerate(chain(inst.fcs, inst.scs)):
            if cs._psell is None: continue
            if isinstance(cs._psell, ConstPriceGetter):
                psell_func = cs._psell._price
            elif isinstance(cs._psell, ToUPriceGetter):
                psell_func = cs._psell._price_func
            else:
                raise RuntimeError("V2G only supports constant price or time-of-use price for selling electricity.")
            self.__pdn.Grid.AddGen(
                Generator(
                    "V2G_" + cs._name, cs._bus, 
                    0., psell_func * (self.__pdn.Grid.Sb * 1000), 0.,
                    -1.0, -1.0, None,
                    0., ComFunc(self.__get_cap(i)), 0., 0.,
                )
            )
        if isinstance(self.__pdn, PluginPDN):
            self.__pdn.Solver.est.UpdateGrid(self.__pdn.Grid)
        return []
    
    def __get_cap(self,i:int):
        def func(t: int) -> float:
            if not self.IsOnline(t): return 0.
            return self._cap[i]
        return func
    
    def _work_post(self, _t:int, /, sta:PluginStatus) -> Tuple[bool, List[float]]:
        if sta == PluginStatus.EXECUTE or (sta == PluginStatus.OFFLINE and self.IsOnline(_t + self.__step_len)):
            self._cap = [x * 3.6 / self.__pdn.Grid.Sb for x in chain(self.__inst.fcs.get_V2G_cap(_t), self.__inst.scs.get_V2G_cap(_t))]
            ret = True, self._cap
        elif sta == PluginStatus.OFFLINE:
            ret = True, []
        elif sta == PluginStatus.HOLD:
            ret = True, self.LastPreStepResult
        return ret
    
    def _work(self, _t:int, /, sta:PluginStatus) -> Tuple[bool, List[float]]:
        '''
        Get the V2G demand power of all bus with slow charging stations at time _t, unit kWh/s, 3.6MW=3600kW=1kWh/s
        '''
        if sta == PluginStatus.EXECUTE:
            if self.__pdn.LastPreStepSucceed:
                f = lambda x: (0.0 if x is None else x) * self.__pdn.Grid.Sb / 3.6
                ret1 = [
                    f(self.__pdn.Grid.Gen("V2G_" + cs._name).P) if cs._psell is not None 
                    else 0.0 for cs in self.__inst.fcs
                ]
                if sum(ret1) > 1e-8: 
                    ret2 = [
                        f(self.__pdn.Grid.Gen("V2G_" + cs._name).P) if cs._psell is not None 
                        else 0.0 for cs in self.__inst.scs
                    ]
                    ret = True, ret1 + ret2
                    self.__inst.fcs.set_V2G_demand(ret1)
                    self.__inst.scs.set_V2G_demand(ret2)
                else: 
                    ret = False, []
                    self.__inst.fcs.clear_V2G_demand()
                    self.__inst.scs.clear_V2G_demand()
            else:
                ret = False, []
                self.__inst.fcs.clear_V2G_demand()
                self.__inst.scs.clear_V2G_demand()
        elif sta == PluginStatus.OFFLINE:
            self.__inst.fcs.clear_V2G_demand()
            self.__inst.scs.clear_V2G_demand()
            ret = True, []
        elif sta == PluginStatus.HOLD:
            ret = True, self.LastPreStepResult
        return ret