from v2simux_gui.common import *

import datetime
from ..mainbox.controls import SelectItemDialog

_L = LangLib.Load(__file__)

def get_clog_mtime(folder:Path):
    clog_path = folder / "cproc.clog"
    if clog_path.is_file():
        return clog_path.stat().st_mtime
    return None


def format_time(ts):
    if ts is None:
        return _L("NOT_FOUND")
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class SelectResultsDialog(SelectItemDialog):
    def __init__(self, items:List[Path]):
        new_items = []
        self.__folders:Dict[str, Path] = {}
        for item in items:
            mtime = get_clog_mtime(item)
            new_items.append([item.name, format_time(mtime)])
            self.__folders[item.name] = item.absolute()
        super().__init__(new_items, title=_L("SELECT_RESULTS"), 
                         columns=[("folder",_L("FOLDER")), ("mtime",_L("MODIFIED_TIME"))])
        self.tree.column("folder", width=300)
        self.tree.column("mtime", width=180)
    
    @property
    def folder(self) -> Union[Path, None]:
        if self.selected_item is None:
            return None
        return self.__folders[self.selected_item[0]]
__all__ = ["SelectResultsDialog", "get_clog_mtime", "format_time"]