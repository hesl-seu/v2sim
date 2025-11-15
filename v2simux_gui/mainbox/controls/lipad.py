from v2simux_gui.common import *

from v2simux import StaPool, StaBase


class LogItemPad(LabelFrame):
    def __init__(self, master, title:str, stapool:StaPool, **kwargs):
        super().__init__(master, text=title, **kwargs)
        self._bvs:Dict[str, BooleanVar] = {}
        self._cbs:Dict[str, Checkbutton] = {}
        self.__stapool = stapool
        for id, val in zip(stapool.GetAllLogItem(), stapool.GetAllLogItemLocalizedName()):
            bv = BooleanVar(self, True)
            self._bvs[id] = bv
            cb = Checkbutton(self, text=val, variable=bv)
            cb.pack(anchor='w', side='left')
            self._cbs[id] = cb
            
    def __getitem__(self, key:str):
        return self._bvs[key].get()
    
    def __setitem__(self, key:str, val:bool):
        self._bvs[key].set(val)
    
    def enable(self, key:str):
        return self._cbs[key].configure(state="enabled")

    def disable(self, key:str):
        return self._cbs[key].configure(state="disabled")
    
    def setEnabled(self, key:str, v:bool):
        if v:
            return self._cbs[key].configure(state="enabled")
        else:
            return self._cbs[key].configure(state="disabled")
    
    def getSelected(self):
        return [k for k, v in self._bvs.items() if v.get()]
    
    def check_by_enabled_plugins(self, enabled_plugins:Iterable[str]):
        p = set(enabled_plugins)
        for k in self._bvs.keys():
            sta_type = self.__stapool.Get(k)
            assert issubclass(sta_type, StaBase)
            deps = sta_type.GetPluginDependency()
            for d in deps:
                if d not in p:
                    self.disable(k)
                    self._bvs[k].set(False)
                    break
            else:
                self.enable(k)
    
    def __contains__(self, key:str):
        return key in self._bvs

__all__ = ["LogItemPad"]