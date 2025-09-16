from abc import abstractmethod
from dataclasses import dataclass
import enum
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, Optional, Protocol, TypeVar, runtime_checkable, List, Tuple, Dict
from feasytools import RangeList
from fpowerkit import Grid
from ..traffic import TrafficInst
from ..locale import Lang

Getter = Callable[[Any], str]
Setter = Callable[[str], Any]
Validator = Callable[[str], bool]

class PluginStatus(enum.IntEnum):
    '''Plugin status'''
    EXECUTE = 0     # Current call should execute the plugin
    HOLD = 1        # Current call should retain the result of the last plugin execution
    OFFLINE = 2     # Current call should return the return value when the plugin is offline

PIResult = TypeVar('PIResult',covariant=True)
PIExec = Callable[[int,PluginStatus],Tuple[bool,PIResult]]
PINoRet = Callable[[],None]

@dataclass
class ConfigItem:
    '''Configuration item'''
    name:str
    editor:'EditMode'
    desc:str
    default_value:Optional[Any] = None
    combo_values:Optional[List[str]] = None
    spin_range:Optional[Tuple[int,int]] = None
    rangelist_hint:bool = False
    prop_config:'Optional[ConfigItemDict]' = None

class EditMode(enum.Enum):
    DISABLED = "disabled"
    ENTRY = "entry"
    SPIN = "spin"
    COMBO = "combo"
    CHECKBOX = "checkbox"
    RANGELIST = "rangelist"
    SEGFUNC = "segfunc"
    PROP = "prop"
    PDFUNC = "pdfunc"

    @staticmethod
    def entry(): return ConfigItem("", EditMode.ENTRY, "", "")
    @staticmethod
    def spin(l:int, r:int): return ConfigItem("", EditMode.SPIN, "", spin_range=(l, r))
    @staticmethod
    def combo(values:List[Any]): return ConfigItem("", EditMode.COMBO, "", combo_values=values)
    @staticmethod
    def checkbox(checked:bool = False): return ConfigItem("", EditMode.CHECKBOX, "", default_value=checked)
    @staticmethod
    def rangelist(hint:bool = False): return ConfigItem("", EditMode.RANGELIST, "", rangelist_hint=hint)
    @staticmethod
    def segfunc(): return ConfigItem("", EditMode.SEGFUNC, "")
    @staticmethod
    def prop(prop_cfg:'ConfigItemDict'): return ConfigItem("", EditMode.PROP, "", prop_config=prop_cfg)
    @staticmethod
    def pdfunc(): return ConfigItem("", EditMode.PDFUNC, "")


class ConfigItemDict(Dict[str, ConfigItem]):
    '''Plugin configuration item dictionary'''
    def __init__(self, items: Optional[Iterable[ConfigItem]] = None, default_config_item:Optional[ConfigItem]=None):
        if items is None:
            super().__init__()
        else:
            super().__init__((x.name, x) for x in items)
        self.default_config_item = default_config_item if default_config_item is not None else ConfigItem(
            name="",
            editor=EditMode.ENTRY,
            desc="(No description)",
            default_value="",
        )

    def default_value_dict(self):
        return {k:v.default_value for k, v in self.items()}
    
    def desc_dict(self):
        return {k:v.desc for k, v in self.items()}
    
    def editor_dict(self):
        return {k:v.editor for k, v in self.items()}
    
    def get_editor(self, name:str) -> EditMode:
        return self.get(name).editor
    
    def get_desc(self, name:str) -> str:
        return self.get(name).desc
    
    def get_default_value(self, name:str) -> Any:
        return self.get(name).default_value
    
    def get(self, key: str) -> ConfigItem:
        return super().get(key, self.default_config_item)

PluginConfigItem = ConfigItem
ConfigDict = ConfigItemDict

@runtime_checkable
class IGridPlugin(Protocol):
    @property
    def Grid(self) -> Grid:
        '''Get the grid instance'''
        raise NotImplementedError

class PluginBase(Generic[PIResult]):
    __PreSimulation: Optional[PINoRet]
    __PreStep: Optional[PIExec]
    __PostSimulation: Optional[PINoRet]
    __PostStep: Optional[PIExec]
    def SetPreSimulation(self,func:PINoRet) -> None:
        '''Pre-simulation plugin processing, run after other parameters are loaded'''
        self.__PreSimulation = func
    def SetPreStep(self,func:PIExec) -> None:
        '''Plugin work before simulation step'''
        self.__PreStep = func
    def SetPostStep(self,func:PIExec) -> None:
        '''Plugin work after simulation step'''
        self.__PostStep = func
    def SetPostSimulation(self,func:PINoRet) -> None:
        '''Post-simulation plugin processing'''
        self.__PostSimulation = func

    @abstractmethod
    def _save_state(self) -> object:
        '''Save the plugin state'''
        
    @abstractmethod
    def _load_state(self,state:object) -> None:
        '''Load the plugin state'''

    @staticmethod
    @abstractmethod
    def ElemShouldHave() -> ConfigDict:
        '''Get the plugin configuration item list'''
        return ConfigDict()

    def __init__(self, inst:TrafficInst, elem:ET.Element, work_dir:Path, res_dir:Path, enable_time:Optional[RangeList]=None,
            interval:int=0, plg_deps:'Optional[List[PluginBase]]' = None):
        '''
        Initialize the plugin
            inst: Traffic network simulation instance
            elem: Plugin configuration XML element
            enable_time: Enable time of the plugin, if not specified, check the online subnode in xml, 
                if the online subnode does not exist, it means always enable
            interval: Plugin running interval, unit = second, 
                if not specified, the invterval attribute must be specified in xml
            plugin_dependency: Plugin dependency list
        '''
        self.__PreStep = None
        self.__PostStep = None
        self.__PreSimulation = None
        self.__PostSimulation = None
        self.__lastTpre = self.__lastTpost = -1
        self.__lastOkpre = False
        self.__lastOkpost = False
        self.__name = elem.tag
        self.__interval = interval if interval > 0 else int(elem.attrib.pop("interval",0))
        if self.__interval <= 0: 
            raise ValueError(Lang.ERROR_PLUGIN_INTERVAL)
        self.__on = enable_time
        if self.__on is None:
            online_elem = elem.find("online")
            if online_elem is None: self.__on = None
            else: self.__on = RangeList(online_elem)
        if plg_deps is None: plg_deps = []

        self.__respre = self.__respost = self.Init(elem, inst, work_dir, res_dir, plg_deps)
    
    @property
    @abstractmethod
    def Description(self)->str:
        '''Get the plugin description'''
        raise NotImplementedError
    
    @property
    def Name(self)->str:
        '''Get the plugin name'''
        return self.__name
    
    @property
    def Interval(self)->int:
        '''Get the plugin running interval, unit = second'''
        return self.__interval
    
    @property
    def OnlineTime(self)->Optional[RangeList]:
        '''Get the plugin enable time'''
        return self.__on
    
    @property
    def LastTime(self)->int:
        '''
        Get the time when the last plugin was in PluginStatus.EXECUTE state
        '''
        return self.__lastTpre
    
    @property
    def LastPreStepSucceed(self)->bool:
        '''
        Get whether PreStep was successful when the last plugin was in PluginStatus.EXECUTE state
        '''
        return self.__lastOkpre
    
    @property
    def LastPostStepSucceed(self)->bool:
        '''
        Get whether PostStep was successful when the last plugin was in PluginStatus.EXECUTE state
        '''
        return self.__lastOkpost

    @property
    def LastPreStepResult(self)->PIResult:
        '''
        Get the result of PreStep when the last plugin was in PluginStatus.EXECUTE state
        '''
        return self.__respre
    
    @property
    def LastPostStepResult(self)->PIResult:
        '''
        Get the result of PostStep when the last plugin was in PluginStatus.EXECUTE state
        '''
        return self.__respost
    
    @abstractmethod
    def Init(self, elem:ET.Element, inst:TrafficInst, work_dir:Path, 
             res_dir:Path, plg_deps:'List[PluginBase]') -> PIResult:
        '''
        Initialize the plugin from the XML element, TrafficInst, work path, result path, and plugin dependency.
        Return the result of offline.
        '''
    
    def IsOnline(self, t:int):
        '''Determine if the plugin is online'''
        return self.__on is None or t in self.__on
    
    def _presim(self)->None:
        '''Run the plugin PreSimulation'''
        if self.__PreSimulation is not None:
            self.__PreSimulation()
    
    def _postsim(self)->None:
        '''Run the plugin PostSimulation'''
        if self.__PostSimulation is not None:
            self.__PostSimulation()
    
    def _precall(self, _t:int)->None:
        '''Run the plugin PreStep'''
        if self.__PreStep is None: return
        if self.__on != None and _t not in self.__on:
            self.__PreStep(_t,PluginStatus.OFFLINE)
        elif self.__lastTpre + self.__interval <= _t or self.__lastTpre < 0:
            self.__lastOkpre, self.__respre = self.__PreStep(_t,PluginStatus.EXECUTE)
            self.__lastTpre = _t
        else:
            self.__PreStep(_t,PluginStatus.HOLD)
    
    def _postcall(self, _t:int, /)->None:
        '''Run the plugin PostStep'''
        if self.__PostStep is None: return
        if self.__on != None and _t not in self.__on:
            self.__PostStep(_t,PluginStatus.OFFLINE)
        elif self.__lastTpost + self.__interval <= _t or self.__lastTpost < 0:
            self.__lastOkpost, self.__respost = self.__PostStep(_t,PluginStatus.EXECUTE)
            self.__lastTpost = _t
        else:
            self.__PostStep(_t,PluginStatus.HOLD)