from v2sim.gui.common import *

from v2sim import MsgPack, ClientOptions, AltCommand
import multiprocessing as mp
import sys, time


ITEM_NONE = "none"
_L = LangLib.Load(__file__)


class RedirectStdout:
    def __init__(self, q:mp.Queue, id:int):
        self.q = q
        self.ln = id

    def write(self, text):
        self.q.put((self.ln, text))

    def flush(self):
        pass


def work(root:str, par:Dict[str, Any], alt:Dict[str, str], out:str, recv:RedirectStdout):
    sys.stdout = recv
    from v2sim.app.sim_single import work
    par.update({"d":root, "o":out, "silent":True})
    st_time = time.time()
    alti = {k: int(v) for k, v in alt.items()}
    altc = AltCommand(**alti)
    work(par, ClientOptions(recv.ln, recv.q), altc)
    recv.q.put_nowait(MsgPack(recv.ln, f"done:{time.time()-st_time:.2f}"))


__all__ = ["RedirectStdout", "ITEM_NONE", "mp", "_L", "work"]