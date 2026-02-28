from feasytools import LangLib
from .base import *

_locale = LangLib(["zh_CN","en"])
_locale.SetLangLib("zh_CN",
    DESCRIPTION = "动态行程",
)
_locale.SetLangLib("en",
    DESCRIPTION = "Dynamic Trip",
)

class PluginDynamicTrip(PluginBase[None]):
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
    
    def Init(self, elem:Element, inst:TrafficInst, work_dir:Path, res_dir:Path, plg_deps:'List[PluginBase]')->None:
        self.__file = open(str(res_dir / "dynamic_trips.csv"), "w")
        self.__file.write("scheduled_time,ev_id,origin,destination\n")
        self.SetPreStep(self._work)
        self.SetPostSimulation(self._close)

        # To be done ...
        
    def _close(self):
        self.__file.close()

    def _work(self, _t:int, /, sta:PluginStatus) -> Tuple[bool, None]:
        '''
        Get the V2G demand power of all bus with slow charging stations at time _t, unit kWh/s, 3.6MW=3600kW=1kWh/s
        '''
        if sta == PluginStatus.EXECUTE:
            # To be done ...
            ret = True, None
        elif sta == PluginStatus.OFFLINE:
            ret = True, None
        elif sta == PluginStatus.HOLD:
            ret = True, self.LastPreStepResult
        return ret