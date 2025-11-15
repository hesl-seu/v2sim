from v2sim.gui.common import *


_L = LangLib.Load(__file__)


class LoadingBox(Toplevel):
    def __init__(self, items:List[str], parentQ:EventQueue, **kwargs):
        super().__init__(None, **kwargs)
        self._pQ = parentQ
        self.title("Loading...")
        self.geometry("400x300")
        self.attributes("-topmost", True)
        self.cks:List[Label]=[]
        self.dkt:Dict[str,int]={}
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        for i, t in enumerate(items):
            Label(self, text=t).grid(column=0,row=i)
            self.cks.append(Label(self, text="..."))
            self.cks[-1].grid(column=1,row=i)
            self.dkt[t]=i
            self.rowconfigure(i, weight=1)
        self._closed = False
    
    def setText(self, itm:str, val:str):
        if self._closed: return
        self.cks[self.dkt[itm]].configure(text=val)
        for x in self.cks:
            if x['text'] != _L['DONE']: break
        else:
            self._closed = True
            self._pQ.delegate(self.destroy)