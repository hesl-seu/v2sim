'''
External Plugin Example: 
  Please put the external plugin in the external_plugins folder, 
  and the plugin file name is "plugin_name.py"
'''
from v2sim import CustomLocaleLib
from v2sim.plugins import *
from v2sim.statistics import *

_locale = CustomLocaleLib(["zh_CN","en"])
_locale.SetLanguageLib("zh_CN",
    DESCRIPTION = "插件描述",
    # More language information
)
_locale.SetLanguageLib("en",
    DESCRIPTION = "Plugin description",
    # More language information
)

class DemoExternalPlugin(PluginBase):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    def Init(self,elem:ET.Element,inst:TrafficInst,work_dir:Path,plg_deps:'list[PluginBase]') -> object:
        '''
        Add plugin initialization code here, return:
            Return value when the plugin is offline
        '''
        self.SetPreStep(self.Work)
        return None

    def Work(self,_t:int,/,sta:PluginStatus)->tuple[bool,None]:
        '''The execution function of the plugin at time _t'''
        raise NotImplementedError

class DemoStatisticItem(StaBase):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    def __init__(self, name:str, path:str, items:list[str], tinst:TrafficInst, 
            plugins:dict[str,PluginBase], precision:dict[str, int]={}, compress:bool=True):
        super().__init__(name, path, items, tinst, plugins, precision, compress)
        raise NotImplementedError

    def GetData(self, inst:TrafficInst, plugins:dict[str,PluginBase]) -> Iterable[Any]: 
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