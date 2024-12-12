from queue import Queue
from .view import *

class ViewBox(Tk):
    def __make(self,key:str,i:int):
        lb1=Label(self._fr, text=key, border=0)
        lb1.grid(row=i,column=0,padx=3,pady=3)
        lb2=Label(self._fr, text="0", border=0)
        lb2.grid(row=i,column=1,padx=3,pady=3)
        self._dict[key]=[0,lb2]
    
    def __init__(self,keys:list[str],title="ViewBox",size:str="300x500"):
        super().__init__()
        self.title(title)
        self.geometry(size)
        self._dict:dict[str,list]={}
        self._cnt=len(keys)
        self._fr=Frame(self)
        self._fr.pack(side='top',anchor='center',expand=1)
        self._gcf={"padx":3, "pady":3}
        for i,key in enumerate(keys):
            self.__make(key,i)
        self._Q=Queue()
        self.after(100,self._upd)

    def _upd(self):
        d:dict[str,tuple[int,Widget]]={}
        while not self._Q.empty():
            d.update(self._Q.get())
        for key,val in d.items():
            if not key in self._dict:
                self.__make(key,self._cnt)
                self._cnt+=1
            self._dict[key][0]=val
            self._dict[key][1].configure(text=str(val))
        self.after(100,self._upd)
    
    def close(self):
        self.destroy()    
    
    def set_val(self,d:dict):
        self._Q.put(d)