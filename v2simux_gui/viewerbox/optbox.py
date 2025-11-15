from v2simux_gui.common import *


class OptionBox(Frame):
    def __init__(self, master, options:Dict[str, Tuple[str, bool]], lcnt:int = -1, **kwargs):
        super().__init__(master, **kwargs)
        self._bools:List[BooleanVar] = []
        self._ctls:List[Checkbutton] = []
        self._mp:Dict[str, BooleanVar] = {}
        self._fr:List[Frame] = []
        if lcnt <= 0: 
            fr = Frame(self)
            fr.pack(side = "top", anchor = "w")
            self._fr.append(fr)
        i = 0
        for id, (text, v) in options.items():
            bv = BooleanVar(self, v)
            self._bools.append(bv)
            self._mp[id] = bv
            if lcnt > 0 and i % lcnt == 0:
                fr = Frame(self)
                fr.pack(side = "top", anchor = "w")
                self._fr.append(fr)
            self._ctls.append(Checkbutton(self._fr[-1],text=text,variable=bv))
            self._ctls[-1].pack(side='left',anchor="w")
            i+=1
    
    def disable(self):
        for c in self._ctls:
            c['state']=DISABLED
        
    def enable(self):
        for c in self._ctls:
            c['state']=NORMAL

    def __setitem__(self, key:str, value:bool):
        self._mp[key].set(value)
    
    def __getitem__(self, key:str)->bool:
        return self._mp[key].get()
    
    def getValues(self):
        return {k: v.get() for k,v in self._mp.items()}
    
    def getSelected(self):
        return [k for k,v in self._mp.items() if v.get()]