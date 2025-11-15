from v2simux.gui.common import *

import os
import threading
import matplotlib
matplotlib.use("agg")
from collections import defaultdict
from pathlib import Path
from matplotlib import pyplot as plt
from queue import Queue
from v2simux import TripsReader, TripLogItem
from ..mainbox.controls import ScrollableTreeView


_L = LangLib.Load(__file__)


class TripsFrame(Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self._file = None
        self.tree = ScrollableTreeView(self) 
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("time", "type", "veh", "soc", "batt", "trip", "info")
        self.tree.column("time", width=80, stretch=NO)
        self.tree.column("type", width=100, stretch=NO)
        self.tree.column("veh", width=80, stretch=NO)
        self.tree.column("soc", width=80, stretch=NO)
        self.tree.column("batt", width=80, stretch=NO)
        self.tree.column("trip", width=60, stretch=NO)
        self.tree.column("info", width=200, stretch=YES)
        
        self.tree.heading("time", text=_L["GUI_EVANA_TIME"])
        self.tree.heading("type", text=_L["GUI_EVANA_TYPE"])
        self.tree.heading("veh", text=_L["GUI_EVANA_VEH"])
        self.tree.heading("soc", text=_L["GUI_EVANA_SOC"])
        self.tree.heading("batt", text=_L["GUI_EVANA_BATT"])
        self.tree.heading("trip", text=_L["GUI_EVANA_TRIP"])
        self.tree.heading("info", text=_L["GUI_EVANA_INFO"])
        self.tree.pack(fill=BOTH,expand=True)

        self._fr=Frame(self)
        self._fr.pack(fill=BOTH)

        self._type_var = StringVar()
        self.TYPES = [_L["GUI_EVANA_ALL"]]
        self.TYPES.extend(f"{k}:{v}" for k,v in TripLogItem.OP_NAMEs.items())
        self._optionType = OptionMenu(self._fr, self._type_var, self.TYPES[0], *self.TYPES)
        self._optionType.pack(side=LEFT)

        self._lb0 = Label(self._fr,text=_L["GUI_EVANA_START_TIME"])
        self._lb0.pack(side=LEFT)

        self._entryST=Entry(self._fr,width=8)
        self._entryST.pack(side=LEFT)

        self._lb1 = Label(self._fr,text=_L["GUI_EVANA_END_TIME"])
        self._lb1.pack(side=LEFT)

        self._entryED=Entry(self._fr,width=8)
        self._entryED.pack(side=LEFT)

        self._lb1 = Label(self._fr,text=_L["GUI_EVANA_VEH"])
        self._lb1.pack(side=LEFT)

        self._entryVeh=Entry(self._fr,width=8)
        self._entryVeh.pack(side=LEFT)

        self._lb2 = Label(self._fr,text=_L["GUI_EVANA_TRIP"])
        self._lb2.pack(side=LEFT)

        self._entryTrip=Entry(self._fr,width=8)
        self._entryTrip.pack(side=LEFT)

        self._btnFilter=Button(self._fr,text=_L["GUI_EVANA_FILTER"],command=lambda:self._Q.put(('F',None)))
        self._btnFilter.pack(side=LEFT)

        self._btnSave=Button(self._fr,text=_L["GUI_EVANA_SAVE"],command=self.save)
        self._btnSave.pack(side=LEFT)

        self._fr2=Frame(self)
        self._fr2.pack(fill=BOTH)

        self._lb_soc = Label(self._fr2,text=_L["GUI_EVANA_SOC_THRE"])
        self._lb_soc.pack(side=LEFT)

        self._entrysocthre=Entry(self._fr2,width=8)
        self._entrysocthre.pack(side=LEFT)
        self._entrysocthre.insert(0,"0.8")

        self._btnStat=Button(self._fr2,text=_L["GUI_EVANA_PARAMSSTA"],command=self.params_calc)
        self._btnStat.pack(side=LEFT)

        self._btnStatPlot=Button(self._fr2,text=_L["GUI_EVANA_PARAMSPLOT"],command=self.params_plot)
        self._btnStatPlot.pack(side=LEFT)

        self._btnEVStat=Button(self._fr2,text="EV Stats",command=self.veh_stat)
        self._btnEVStat.pack(side=LEFT)

        self._disp:List[TripLogItem] = []
        self._Q = Queue()
        
        self.after(100,self._upd)

    def _upd(self):
        cnt = 0
        while not self._Q.empty() and cnt<50:
            op,val = self._Q.get()
            cnt += 1
            if op=='L':
                assert isinstance(val, TripsReader)
                self._data:TripsReader = val
                self._disp = [m for _,m,_ in self._data.filter()]
                self._Q.put(('S', None))
            elif op=='S':
                for item in self.tree.get_children():
                    self.tree.delete(item)
                for item in self._disp:
                    self.tree.insert("", "end", values=item.to_tuple(conv=True))
            elif op=='F':
                ftype = self._type_var.get()
                if ftype == self.TYPES[0]:
                    factions = None
                else:
                    factions = [ftype.split(":")[0]]
                fveh = self._entryVeh.get()
                if fveh == "":
                    fveh = None
                ftrip = self._entryTrip.get().strip()
                if len(ftrip) == 0: 
                    ftrip_id = None
                else: 
                    ftrip_id = int(ftrip)
                st_time_str = self._entryST.get().strip()
                if len(st_time_str) == 0:
                    st_time = None
                else:
                    st_time = int(st_time_str)
                ed_time_str = self._entryED.get().strip()
                if len(ed_time_str) == 0: 
                    ed_time = None
                else:
                    ed_time = int(ed_time_str)
                if "_data" in self.__dict__:
                    self._disp = [m for _,m,_ in self._data.filter(
                        time=(st_time,ed_time),action=factions,veh=fveh,trip_id=ftrip_id
                    )]
                self._Q.put(('S', None))
        self.after(100,self._upd)
    
    def __stat_trip_length(self):
        # Calculate average trip length
        max_trip:Dict[str, int] = defaultdict(int)
        veh_dist:Dict[str, float] = defaultdict(float)
        tot_dist = 0.0
        for item in self._disp:
            if item.op_raw in ("A", "AC"):
                dist = float(item.additional.get('dist', '0'))
                veh_dist[item.veh] += dist
                tot_dist += dist
            if item.op_raw == "A":
                max_trip[item.veh] = max(max_trip[item.veh], item.trip_id + 1)
        avg_dist = {k: (veh_dist[k] / v) for k,v in max_trip.items()}
        tot_trip_cnt = sum(max_trip.values())
        tot_avg_dist = tot_dist / tot_trip_cnt if tot_trip_cnt > 0 else 0
        return max_trip, avg_dist, tot_avg_dist
    
    def __stat_ev_batt(self):
        evs:Dict[str, List[float]] = defaultdict(list)
        for item in self._disp:
            try:
                elec = float(item.veh_batt.removesuffix("kWh"))
            except ValueError:
                elec = 0.0
            evs[item.veh].append(elec)
        
        ret:Dict[str, Tuple[float, float]] = {}
        tot_charge = 0; tot_discharge = 0
        for vname, battlst in evs.items():
            n = len(battlst)
            charge = 0; discharge = 0
            for i in range(1, n):
                delta = battlst[i] - battlst[i - 1]
                if delta > 0:
                    charge += delta
                else:
                    discharge -= delta
            ret[vname] = (charge, discharge)
            tot_charge += charge; tot_discharge += discharge
        
        return ret, tot_charge, tot_discharge
        
    def veh_stat(self):
        max_trip, avg_dist, tot_avg_dist = self.__stat_trip_length()
        ev_batt, tot_charge, tot_discharge = self.__stat_ev_batt()
        avg_charge = tot_charge / len(ev_batt)
        avg_discharge = tot_discharge / len(ev_batt)

        with open(self.get_save_path() / "vehicle_stat.csv", "w", encoding="utf-8") as fp:
            fp.write("Vehicle,# Trips,Average distance (m),Total charging energy (kWh),Total discharging energy (kWh)\n")
            for vname, dist in avg_dist.items():
                fp.write(f"{vname},{max_trip[vname]+1},{dist:.1f},{ev_batt[vname][0]:.1f},{ev_batt[vname][1]:.1f}\n")
            fp.write(f"Total average distance: {tot_avg_dist:.1f}m\n")
            fp.write(f"Total average charging: {avg_charge:.1f}kWh\n")
            fp.write(f"Total average discharging: {avg_discharge:.1f}kWh\n")
        
        MB.showinfo(f"Vehicle statistics", 
            f"Average distance per trip: {tot_avg_dist:.1f}m\n" + 
            f"Average charging: {avg_charge:.1f}kWh\n" + 
            f"Average discharging: {avg_discharge:.1f}kWh\n" + 
            "File saved to figrues/vehicle_stat.csv"
        )

    def __params_calc(self, tau:float):
        okcnt = 0
        cnt = 0
        for item in self._disp:
            if item.op_raw != "D": continue
            soc = float(item.veh_soc.removesuffix("%")) / 100
            if soc > tau:
                okcnt += 1
            cnt += 1
        return okcnt, cnt
    
    def params_calc(self):
        try:
            tau = float(self._entrysocthre.get())
        except ValueError:
            MB.showerror(_L["GUI_EVANA_MSGBOX_STA_TITLE"], _L["GUI_EVANA_MSGBOX_STA_INVALID_THRE"])
            return
        okcnt, cnt = self.__params_calc(tau)
        if cnt == 0:
            MB.showinfo(_L["GUI_EVANA_MSGBOX_STA_TITLE"], 
                _L["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, "N/A", cnt))
        else:
            MB.showinfo(_L["GUI_EVANA_MSGBOX_STA_TITLE"],
                _L["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, f"{okcnt/cnt*100:.2f}%",cnt))
    
    def get_save_path(self):
        if self._file is not None:
            p = Path(self._file).parent / "figures"
        else:
            p = Path("figures")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def params_plot(self):
        y = []
        for i in range(1, 100 + 1):
            tau = i / 100
            okcnt, cnt = self.__params_calc(tau)
            if cnt == 0: 
                y.append(0)
            else:
                y.append(okcnt / cnt)

        plt.title("SoC Threshold vs. Proportion")
        plt.xlabel("SoC Threshold")
        plt.ylabel("Proportion")
        plt.plot(range(1, 100 + 1), y)
        plt.savefig(str(self.get_save_path() / "thre_curve.png"))
        MB.showinfo("Threshold Curve", "Threshold curve saved to figures/thre_curve.png")

    def save(self):
        filename = filedialog.asksaveasfilename(
            title=_L["GUI_EVANA_SAVEAS"],
            filetypes=[(_L["GUI_EVANA_CSV_FILE"],".csv")],
            initialdir=os.getcwd()
        )
        if filename == "": return
        with open(filename,"w",encoding="utf-8") as fp:
            fp.write(f'{_L["GUI_EVANA_TIME"]},{_L["GUI_EVANA_TYPE"]},{_L["GUI_EVANA_VEH"]},{_L["GUI_EVANA_SOC"]},{_L["GUI_EVANA_TRIP"]},{_L["GUI_EVANA_INFO"]}\n')
            for item in self._disp:
                addinfo = ','.join(f"{k} = {v}".replace(',',' ') for k,v in item.additional.items())
                fp.write(f"{item.simT},{item.op},{item.veh},{item.veh_soc},{item.trip_id},{addinfo}\n")
            
    def load(self,filename:str):
        self._file = filename
        def thload(filename:str):
            fh = TripsReader(filename)
            self._Q.put(('L', fh))
        threading.Thread(target=thload,args=(filename,)).start()

__all__ = ["TripsFrame"]