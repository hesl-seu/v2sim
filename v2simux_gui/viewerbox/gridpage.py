from v2simux_gui.common import *

from typing import Protocol, runtime_checkable
from ..mainbox.controls import ScrollableTreeView
from v2simux import ReadOnlyStatistics


_L = LangLib.Load(__file__)


@runtime_checkable
class ISupportSetStatus(Protocol):
    def set_status(self, msg:str): ...


class GridFrame(Frame):
    def __init__(self, parent, to_set, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        self._sta = None
        assert isinstance(to_set, ISupportSetStatus)
        self._master = to_set

        self.panel_time2 = Frame(self)
        self.panel_time2.pack(side='top',fill='x',padx=3,pady=5)
        self.lb_time2 = Label(self.panel_time2, text=_L["TIME_POINT"])
        self.lb_time2.grid(row=0,column=0)
        self.entry_time2 = Entry(self.panel_time2)
        self.entry_time2.insert(0,"86400")
        self.entry_time2.grid(row=0,column=1,sticky='ew')
        self.btn_time2 = Button(self.panel_time2, text=_L["GRID_COLLECT"], takefocus=False, command=self.collectgrid)
        self.btn_time2.grid(row=0,column=2)

        self.grbus = ScrollableTreeView(self)
        self.grbus.pack(side='top',fill='both',padx=3,pady=5)
        self.grbus["show"]="headings"
        self.grbus["columns"]=("bus","v","pd","qd","pg","qg")
        self.grbus.heading("bus",text="Bus")
        self.grbus.heading("v",text="Voltage/kV")
        self.grbus.heading("pd",text="Active load/MW")
        self.grbus.heading("qd",text="Reactive load/Mvar")
        self.grbus.heading("pg",text="Active gen/MW")
        self.grbus.heading("qg",text="Reactive gen/Mvar")
        self.grbus.column("bus",width=50)
        self.grbus.column("v",width=90)
        self.grbus.column("pd",width=100)
        self.grbus.column("qd",width=100)
        self.grbus.column("pg",width=100)
        self.grbus.column("qg",width=100)
        
        self.grline = ScrollableTreeView(self)
        self.grline.pack(side='top',fill='both',padx=3,pady=5)
        self.grline["show"]="headings"
        self.grline["columns"]=("line","p","q","i")
        self.grline.heading("line",text="Line")
        self.grline.heading("p",text="Active pwr/MW")
        self.grline.heading("q",text="Reactive pwr/Mvar")
        self.grline.heading("i",text="Current/kA")
        self.grline.column("line",width=50)
        self.grline.column("p",width=100)
        self.grline.column("q",width=100)
        self.grline.column("i",width=100)

    def setSta(self, sta:ReadOnlyStatistics):
        self._sta = sta
    
    def collectgrid(self):
        self.grbus.clear()
        try:
            t = int(self.entry_time2.get())
        except:
            self._master.set_status("Invalid time point!")
            return
        if self._sta is None:
            self._master.set_status("Statistics not loaded!")
            return
        for b in self._sta.bus_head:
            v = self._sta.bus_attrib_of(b, "V").value_at(t)
            pd = self._sta.bus_attrib_of(b, "Pd").value_at(t)
            qd = self._sta.bus_attrib_of(b, "Qd").value_at(t)
            pg = self._sta.bus_attrib_of(b, "Pg").value_at(t)
            qg = self._sta.bus_attrib_of(b, "Qg").value_at(t)
            self.grbus.insert("",'end',values=(b,v,pd,qd,pg,qg))
        for l in self._sta.line_head:
            p = self._sta.line_attrib_of(l, "P").value_at(t)
            q = self._sta.line_attrib_of(l, "Q").value_at(t)
            i = self._sta.line_attrib_of(l, "I").value_at(t)
            self.grline.insert("",'end',values=(l,p,q,i))
        self._master.set_status(_L["STA_READY"])