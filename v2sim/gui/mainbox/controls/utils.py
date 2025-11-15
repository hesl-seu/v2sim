from v2sim.gui.common import *

from v2sim.trafficgen.misc import *

class EditDesc:
    def __init__(self, typename:type):
        self._t = typename.__name__
        self._desc:Dict[str, str] = {}
        self._text:Dict[str, str] = {}
        self._dtype:Dict[str, type] = {}
        self._em:Dict[str, EditMode] = {}
        self._em_kwargs:Dict[str, Dict[str, Any]] = {}
        self._onchanged:Dict[str, Optional[Callable[[Any, Any], None]]] = {}
    
    def add(self, key:str, show:str, dtype:type, desc:str, 
            edit_mode:EditMode, onchanged = None, **kwargs):
        self._desc[key] = desc
        self._text[key] = show
        self._dtype[key] = dtype
        self._em[key] = edit_mode
        self._em_kwargs[key] = kwargs
        self._onchanged[key] = onchanged
        return self
    
    @staticmethod
    def create(typename:type, default_edit_mode:EditMode):
        return EditDesc(typename)


class EditDescGroup:
    def __init__(self, EditDescs:Iterable[EditDesc]):
        self._eds = {ed._t:ed for ed in EditDescs}
    
    def get(self, inst:Any) -> EditDesc:
        typename = type(inst).__name__
        if typename not in self._eds:
            raise KeyError(f"Type {typename} not found in EditDescGroup")
        return self._eds[typename]
    
__all__ = ["EditDesc", "EditDescGroup"]