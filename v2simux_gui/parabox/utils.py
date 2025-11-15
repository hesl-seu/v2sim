from v2simux_gui.common import *
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


def work(root:str, par:Dict[str,str], alt:Dict[str,str], out:str, recv:RedirectStdout):
    sys.stdout = recv
    import sim_single
    par.update({"d":root, "od":out})
    st_time = time.time()
    sim_single.work(par, recv.ln, recv.q, alt)
    print(f"done:{time.time()-st_time:.2f}")


__all__ = ["RedirectStdout", "ITEM_NONE", "mp", "_L", "work"]