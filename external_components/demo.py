'''
External Plugin Example: 
  Please put the external plugin in the external_plugins folder, 
  and the plugin file name is "plugin_name.py"
'''
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Any, Tuple, List, Dict
from v2sim import CustomLocaleLib, TrafficInst
from v2sim.plugins import *
from v2sim.statistics import *

_L = CustomLocaleLib(["zh_CN","en"])
_L.SetLanguageLib("zh_CN",
    DESCRIPTION = "插件描述",
    STA_NAME = "示例统计项",
    # More language information
)
_L.SetLanguageLib("en",
    DESCRIPTION = "Plugin description",
    STA_NAME = "Demo",
    # More language information
)

class DemoExternalPlugin(PluginBase):
    @property
    def Description(self)->str:
        return _L["DESCRIPTION"]
    
    def Init(self,elem:ET.Element,inst:TrafficInst,work_dir:Path,plg_deps:'List[PluginBase]') -> object:
        '''
        Add plugin initialization code here, return:
            Return value when the plugin is offline
        '''
        self.SetPreStep(self.Work) # Indicate that the Work function should be called in PreStep (i.e. before SUMO simulation step)
        return None

    def Work(self,_t:int,/,sta:PluginStatus)->Tuple[bool,None]:
        '''The execution function of the plugin at time _t'''
        raise NotImplementedError

class DemoStatisticItem(StaBase):
    @property
    def Description(self)->str:
        return _L["DESCRIPTION"]
    
    def __init__(self, name:str, path:str, items:List[str], tinst:TrafficInst, 
            plugins:Dict[str,PluginBase], precision:Dict[str, int]={}, compress:bool=True):
        super().__init__(name, path, items, tinst, plugins, precision, compress)
        raise NotImplementedError

    @staticmethod
    def GetLocalizedName() -> str:
        '''Get Localized Name'''
        return _L["STA_NAME"]
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return ["demo"] # Example: This statistic item depends on the "demo" plugin
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str,PluginBase]) -> Iterable[Any]: 
        '''Get Data'''
        raise NotImplementedError

'''
Set export variables
  plugin_exports = (Plugin name, Plugin class, Plugin dependency list(can be empty))
  sta_exports = (Statistic item name, Statistic item class)
If you don't export the statistic item, please don't set sta_exports
'''

plugin_exports = ("demo", DemoExternalPlugin, ["pdn"])
sta_exports = ("demo", DemoStatisticItem)