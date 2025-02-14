from .base import *
from .pdn import PluginPDN
from .v2g import PluginV2G

_internal_plugins = {
    "pdn": (PluginPDN,[]),
    "v2g": (PluginV2G,["pdn"]),
}

class PluginError(Exception):
    pass

class PluginPool:
    '''Plugin pool'''
    def __init__(self,use_internal_plugins:bool = True):
        '''
        Initialize
            use_internal_plugins: Whether to load internal plugins
        '''
        self.__curPlugins:dict[str,tuple[type,list[str]]] = {}
        if use_internal_plugins:
            for k,(p,d) in _internal_plugins.items():
                self._Register(k,p,d)
        
        for key,(_,deps) in self.__curPlugins.items():
            for d in deps:
                if d not in self.__curPlugins:
                    print(self.__curPlugins)
                    raise PluginError(Lang.PLG_DEPS_NOT_REGISTERED.format(key,d))

    def __getitem__(self,name:str)->tuple[type,list[str]]:
        '''Get plugin by name'''
        return self.__curPlugins[name]
    
    def GetPluginType(self,name:str)->type:
        '''Get plugin type by name'''
        return self.__curPlugins[name][0]
    
    def GetPluginDependencies(self,name:str)->list[str]:
        '''Get plugin dependencies by name'''
        return self.__curPlugins[name][1]
    
    def GetAllPlugins(self,)->dict[str,tuple[type,list[str]]]:
        '''Get all plugins'''
        return self.__curPlugins
    
    def __contains__(self,name:str)->bool:
        '''Check if plugin exists'''
        return self.__curPlugins.__contains__(name)
    
    def _Register(self,name:str,plugin:type,deps:list[str]):
        '''Register new plugin to plugin pool without checking dependencies'''
        if name in self.__curPlugins:
            raise PluginError(Lang.PLG_REGISTERED.format(name))
        for d in deps:
            if not isinstance(d,str):
                raise PluginError(Lang.PLG_DEPS_MUST_BE_STRLIST)
        self.__curPlugins[name] = (plugin, deps)
    
    def Register(self,name:str,plugin:type,deps:list[str]):
        '''Register new plugin to plugin pool'''
        if not issubclass(plugin,PluginBase):
            raise PluginError(Lang.PLG_NOT_SUBCLASS.format(plugin))
        for d in deps:
            if d not in self.__curPlugins:
                raise PluginError(Lang.PLG_DEPS_NOT_REGISTERED.format(name,d))
        self._Register(name,plugin,deps)

class PluginMan:
    def __init__(self, plg_xml:Optional[str], res_dir:Path, inst:TrafficInst, no_plg:list[str], plugin_pool:PluginPool):
        '''
        Load plugins from file
            plg_xml: Plugin configuration file path, None means not load
            res_dir: Result directory
            inst: Traffic simulation instance
            no_plg: Plugins not to load
            plugin_pool: Available plugin pool
        '''
        self.__curPlugins:dict[str,PluginBase] = {}
        if plg_xml is None:
            return
        if Path(plg_xml).exists() == False:
            print(Lang.PLG_NOT_EXIST.format(plg_xml))
            return
        root = ET.ElementTree(file=plg_xml).getroot()
        work_dir = Path(plg_xml).parent
        if root is None:
            raise PluginError(Lang.PLG_NOT_EXIST_OR_BAD.format(plg_xml))
        for itm in root:
            if itm.tag in no_plg or itm.attrib.get("enabled") == "NO": continue
            if itm.tag not in plugin_pool: raise PluginError(Lang.PLG_INVALID_PLUGIN.format(itm.tag))
            plugin_type, dependencies = plugin_pool[itm.tag]
            deps:list[PluginBase] = []
            for d in dependencies:
                if d not in self.__curPlugins: raise PluginError(Lang.PLG_DEPS_NOT_LOADED.format(itm.tag,d))
                deps.append(self.__curPlugins[d])
            self.Add(plugin_type(inst,itm,work_dir,res_dir,plg_deps=deps))
    
    def PreSimulationAll(self):
        '''Execute all plugins PreSimulation, return all plugins return value'''
        for p in self.__curPlugins.values():
            p._presim()
    
    def PostSimulationAll(self):
        '''Execute all plugins PostSimulation, return all plugins return value'''
        for p in self.__curPlugins.values():
            p._postsim()

    def PreStepAll(self,_t:int)->dict[str,object]:
        '''Execute all plugins PreStep, return all plugins return value'''
        ret:dict[str,object] = {}
        for k,p in self.__curPlugins.items():
            ret[k] = p._precall(_t)
        return ret
    
    def PostStepAll(self,_t:int)->dict[str,object]:
        '''Execute all plugins PreStep, return all plugins return value'''
        ret:dict[str,object] = {}
        for k,p in self.__curPlugins.items():
            ret[k] = p._postcall(_t)
        return ret
    
    def Add(self,plugin:PluginBase):
        '''Add new plugin to current plugin list'''
        if plugin.Name in self.__curPlugins:
            raise PluginError(Lang.PLG_ALREADY_EXISTS.format(plugin.Name))
        self.__curPlugins[plugin.Name] = plugin

    def GetPluginByName(self,name:str)->PluginBase:
        '''Get plugin by name'''
        return self.__curPlugins[name]
    
    def GetPlugins(self)->dict[str,PluginBase]:
        '''Get all plugins'''
        return self.__curPlugins

    def SaveStates(self) -> dict[str, object]:
        '''Save all plugin states'''
        ret = {}
        for name, p in self.__curPlugins.items():
            ret[name] = p._save_state()
        return ret
    
    def LoadStates(self, states: dict[str, object]):
        '''Load all plugin states'''
        for name, p in self.__curPlugins.items():
            if name in states:
                p._load_state(states[name])