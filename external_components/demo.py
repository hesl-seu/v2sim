'''
External Plugin Example: 
  Please put the external plugin in the external_plugins folder, 
  and the plugin file name is "plugin_name.py"
'''
from v2sim import CustomLocaleLib
from v2sim.plugins import *

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
    
    def Initialization(self,elem:ET.Element,inst:TrafficInst,work_dir:Path,plugin_dependency:'list[PluginBase]') -> object:
        '''
        Add plugin initialization code here, return:
            Return value when the plugin is offline
        '''
        self.SetPreStep(self.Work)
        return None

    def Work(self,_t:int,/,sta:PluginStatus)->tuple[bool,None]:
        '''The execution function of the plugin at time _t'''
        raise NotImplementedError

'''
Set export variables
  plugin_exports = (Plugin name, Plugin class, Plugin dependency list(can be empty))
  sta_exports = (Statistic item name, Statistic item class)
If you don't export the statistic item, please don't set sta_exports
'''

plugin_exports = ("demo", DemoExternalPlugin, ["pdn"])