from v2simux.gui.common import *

import functools

_L = LangLib.Load(__file__)

V2SIM_UX_DIR = Path(__file__).parent.parent.parent
SIM_YES = "YES"
SIM_NO = "NO"

def showerr(msg:str):
    MB.showerror(_L["MB_ERROR"], msg)

def showwarn(msg:str):
    MB.showwarning(_L["MB_INFO"], msg)

def try_int(s:str, name:str) -> int:
    try: return int(s)
    except: raise ValueError(f"Invalid {name}. Must be an integer.")

def try_float(s:str, name:str) -> float:
    try: return float(s)
    except: raise ValueError(f"Invalid {name}. Must be a float.")

def try_split(s:str, name:str, sep:str=',') -> List[str]:
    try:
        parts = s.split(sep)
        parts = [p.strip() for p in parts if p.strip()]
        return parts
    except:
        raise ValueError(f"Invalid {name}. Must be a list of strings separated by '{sep}'.")

def errwrapper(func):
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            showerr(str(e))
    return wrapped

__all__ = ["showerr", "showwarn", "try_int", "try_float", "try_split", "errwrapper", "SIM_YES", "SIM_NO", "V2SIM_UX_DIR"]