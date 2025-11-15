from v2sim.gui.common import *
from feasytools import RangeList
from v2sim import PluginPool, PluginBase, StaPool, load_external_components
from .controls import ScrollableTreeView, SelectItemDialog, ALWAYS_ONLINE, empty_postfunc
from .utils import *


_L = LangLib.Load(__file__)


class PluginEditor(ScrollableTreeView):
    def __addgetter(self):
        # 获取第1列所有值
        plgs_exist = set(self.item(i, 'values')[0] for i in self.get_children())
        plgs = [[x] for x in self.plg_pool.GetAllPlugins() if x not in plgs_exist]
        f = SelectItemDialog(plgs, _L["SIM_SELECTPLG"], [("Name", _L["PLG_NAME"])])
        f.wait_window()
        if f.selected_item is None:
            return None
        plgname = f.selected_item[0]
        plgtype = self.plg_pool.GetPluginType(plgname)
        assert issubclass(plgtype, PluginBase)
        self.setCellEditMode(plgname, "Extra", ConfigItem("Extra", EditMode.PROP, "Extra properties", prop_config=plgtype.ElemShouldHave()))
        return [plgname, 300, SIM_YES, ALWAYS_ONLINE, plgtype.ElemShouldHave().default_value_dict()]
    
    def GetEnabledPlugins(self):
        enabled_plg = []
        for i in self.get_children():
            if self.item(i, 'values')[2] == SIM_YES:
                enabled_plg.append(self.item(i, 'values')[0])
        return enabled_plg
            
    def __init__(self, master, onEnabledSet:Callable[[Tuple[Any,...], str], None] = empty_postfunc, **kwargs):
        super().__init__(master, True, True, True, True, self.__addgetter, **kwargs)
        self.sta_pool = StaPool()
        self.plg_pool = PluginPool()
        if Path(EXT_COMP).exists():
            load_external_components(EXT_COMP, self.plg_pool, self.sta_pool)
        else:
            print(f"Warning: external components folder '{EXT_COMP}' not found.")
        self["show"] = 'headings'
        self["columns"] = ("Name", "Interval", "Enabled", "Online", "Extra")
        self.column("Name", width=120, stretch=NO)
        self.column("Interval", width=100, stretch=NO)
        self.column("Enabled", width=100, stretch=NO)
        self.column("Online", width=200, stretch=NO)
        self.column("Extra", width=200, stretch=YES)
        self.heading("Name", text=_L["SIM_PLGNAME"])
        self.heading("Interval", text=_L["SIM_EXEINTV"])
        self.heading("Enabled", text=_L["SIM_ENABLED"])
        self.heading("Online", text=_L["SIM_PLGOL"])
        self.heading("Extra", text=_L["SIM_PLGPROP"])
        self.setColEditMode("Interval", ConfigItem("Interval", EditMode.SPIN, "Time interval", spin_range=(1, 86400)))
        self.setColEditMode("Enabled", ConfigItem("Enabled", EditMode.COMBO, "Enabled or not", combo_values=[SIM_YES, SIM_NO]), post_func=onEnabledSet)
        self.setColEditMode("Online", ConfigItem("Online", EditMode.RANGELIST, "Online time ranges", rangelist_hint=True))
        self.setColEditMode("Extra", ConfigItem("Extra", EditMode.DISABLED, "Extra properties"))
        self.__onEnabledSet = onEnabledSet
    
    def add(self, plg_name:str, interval:Union[int, str], enabled:str, online:Union[RangeList, str], extra:Dict[str, Any]):
        new_line = (plg_name, interval, enabled, online, str(extra))
        self.insert("", "end", values=new_line)
        plg_type = self.plg_pool.GetPluginType(plg_name)
        assert issubclass(plg_type, PluginBase)
        self.setCellEditMode(plg_name, "Extra", ConfigItem("Extra", EditMode.PROP, "Extra properties", prop_config=plg_type.ElemShouldHave()))
        self.__onEnabledSet(new_line, plg_name)
    
    def is_enabled(self, plg_name:str):
        for i in self.get_children():
            if self.item(i, 'values')[0] == plg_name:
                return self.item(i, 'values')[2] == SIM_YES
        return False