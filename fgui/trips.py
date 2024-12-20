import os
from pathlib import Path
import matplotlib
matplotlib.use("agg")
from matplotlib import pyplot as plt
from queue import Queue
import threading
from tkinter import filedialog, messagebox
from v2sim import CustomLocaleLib, TripsReader, TripLogItem
from .view import *
from .controls import ScrollableTreeView

_loc = CustomLocaleLib(["zh_CN","en"])
_loc.SetLanguageLib("zh_CN",
    GUI_EVANA_TITLE = "EV和行程分析",
    GUI_EVANA_ALL = "(全部)",
    GUI_EVANA_START_TIME = "起始时间",
    GUI_EVANA_END_TIME = "结束时间",
    GUI_EVANA_VEH = "车辆",
    GUI_EVANA_TRIP = "行程",
    GUI_EVANA_FILTER = "过滤",
    GUI_EVANA_SAVE = "保存",
    GUI_EVANA_PARAMSSTA = "统计",
    GUI_EVANA_PARAMSPLOT = "阈值曲线",
    GUI_EVANA_TIME = "时间",
    GUI_EVANA_TYPE = "类型",
    GUI_EVANA_SOC = "SoC",
    GUI_EVANA_SOC_THRE = "SoC阈值",
    GUI_EVANA_MSGBOX_STA_INVALID_THRE = "无效的阈值",
    GUI_EVANA_PARAMS = "参数",
    GUI_EVANA_INFO = "信息",
    GUI_EVANA_MSGBOX_STA_TITLE = "统计参数",
    GUI_EVANA_MSGBOX_STA_MSG = "SoC阈值: {0}，大于阈值的比例: {1}，总数: {2}",
    GUI_EVANA_SAVEAS = "另存为",
    GUI_EVANA_CSV_FILE = "CSV文件",
    GUI_EVANA_SEL_CLOG = "选择cproc.clog",
)

_loc.SetLanguageLib("en",
    GUI_EVANA_TITLE = "EV & Trips Analysis",
    GUI_EVANA_ALL = "(All)",
    GUI_EVANA_START_TIME = "Start Time",
    GUI_EVANA_END_TIME = "End Time",
    GUI_EVANA_VEH = "Vehicle",
    GUI_EVANA_TRIP = "Trip",
    GUI_EVANA_FILTER = "Filter",
    GUI_EVANA_SAVE = "Save",
    GUI_EVANA_PARAMSSTA = "Statistics",
    GUI_EVANA_PARAMSPLOT = "Threshold Curve",
    GUI_EVANA_TIME = "Time",
    GUI_EVANA_TYPE = "Type",
    GUI_EVANA_SOC = "SoC",
    GUI_EVANA_SOC_THRE = "SoC Threshold",
    GUI_EVANA_MSGBOX_STA_INVALID_THRE = "Invalid threshold",
    GUI_EVANA_PARAMS = "Parameters",
    GUI_EVANA_INFO = "Information",
    GUI_EVANA_MSGBOX_STA_TITLE = "Statistics",
    GUI_EVANA_MSGBOX_STA_MSG = "SoC threshold: {0}. Proportion greater than threshold: {1}. Total: {2}",
    GUI_EVANA_SAVEAS = "Save as",
    GUI_EVANA_CSV_FILE = "CSV file",
    GUI_EVANA_SEL_CLOG = "Select cproc.clog",
)


class TripsFrame(Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self._file = None
        self.tree = ScrollableTreeView(self) 
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("time", "type", "veh", "soc", "trip", "params", "info")
        self.tree.column("time", width=80, stretch=NO)
        self.tree.column("type", width=100, stretch=NO)
        self.tree.column("veh", width=80, stretch=NO)
        self.tree.column("soc", width=80, stretch=NO)
        self.tree.column("trip", width=60, stretch=NO)
        self.tree.column("params", width=200, stretch=NO)
        self.tree.column("info", width=200, stretch=YES)
        
        self.tree.heading("time", text=_loc["GUI_EVANA_TIME"])
        self.tree.heading("type", text=_loc["GUI_EVANA_TYPE"])
        self.tree.heading("veh", text=_loc["GUI_EVANA_VEH"])
        self.tree.heading("soc", text=_loc["GUI_EVANA_SOC"])
        self.tree.heading("trip", text=_loc["GUI_EVANA_TRIP"])
        self.tree.heading("params", text=_loc["GUI_EVANA_PARAMS"])
        self.tree.heading("info", text=_loc["GUI_EVANA_INFO"])
        self.tree.pack(fill=BOTH,expand=True)

        self._fr=Frame(self)
        self._fr.pack(fill=BOTH)

        self._type_var = StringVar()
        self.TYPES = [_loc["GUI_EVANA_ALL"]]
        self.TYPES.extend(f"{k}:{v}" for k,v in TripLogItem.OP_NAMEs.items())
        self._optionType = OptionMenu(self._fr, self._type_var, self.TYPES[0], *self.TYPES)
        self._optionType.pack(side=LEFT)

        self._lb0 = Label(self._fr,text=_loc["GUI_EVANA_START_TIME"])
        self._lb0.pack(side=LEFT)

        self._entryST=Entry(self._fr,width=8)
        self._entryST.pack(side=LEFT)

        self._lb1 = Label(self._fr,text=_loc["GUI_EVANA_END_TIME"])
        self._lb1.pack(side=LEFT)

        self._entryED=Entry(self._fr,width=8)
        self._entryED.pack(side=LEFT)

        self._lb1 = Label(self._fr,text=_loc["GUI_EVANA_VEH"])
        self._lb1.pack(side=LEFT)

        self._entryVeh=Entry(self._fr,width=8)
        self._entryVeh.pack(side=LEFT)

        self._lb2 = Label(self._fr,text=_loc["GUI_EVANA_TRIP"])
        self._lb2.pack(side=LEFT)

        self._entryTrip=Entry(self._fr,width=8)
        self._entryTrip.pack(side=LEFT)

        self._btnFilter=Button(self._fr,text=_loc["GUI_EVANA_FILTER"],command=lambda:self._Q.put(('F',None)))
        self._btnFilter.pack(side=LEFT)

        self._btnSave=Button(self._fr,text=_loc["GUI_EVANA_SAVE"],command=self.save)
        self._btnSave.pack(side=LEFT)

        self._fr2=Frame(self)
        self._fr2.pack(fill=BOTH)

        self._lb_soc = Label(self._fr2,text=_loc["GUI_EVANA_SOC_THRE"])
        self._lb_soc.pack(side=LEFT)

        self._entrysocthre=Entry(self._fr2,width=8)
        self._entrysocthre.pack(side=LEFT)
        self._entrysocthre.insert(0,"0.8")

        self._btnStat=Button(self._fr2,text=_loc["GUI_EVANA_PARAMSSTA"],command=self.params_calc)
        self._btnStat.pack(side=LEFT)

        self._btnStatPlot=Button(self._fr2,text=_loc["GUI_EVANA_PARAMSPLOT"],command=self.params_plot)
        self._btnStatPlot.pack(side=LEFT)

        self._disp:list[TripLogItem] = []
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
            messagebox.showerror(_loc["GUI_EVANA_MSGBOX_STA_TITLE"], _loc["GUI_EVANA_MSGBOX_STA_INVALID_THRE"])
            return
        okcnt, cnt = self.__params_calc(tau)
        if cnt == 0:
            messagebox.showinfo(_loc["GUI_EVANA_MSGBOX_STA_TITLE"], 
                _loc["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, "N/A", cnt))
        else:
            messagebox.showinfo(_loc["GUI_EVANA_MSGBOX_STA_TITLE"],
                _loc["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, f"{okcnt/cnt*100:.2f}%",cnt))
    
    def params_plot(self):
        y = []
        for i in range(1, 100 + 1):
            tau = i / 100
            okcnt, cnt = self.__params_calc(tau)
            if cnt == 0: 
                y.append(0)
            else:
                y.append(okcnt / cnt)
        print(y)
        plt.title("SoC Threshold vs. Proportion")
        plt.xlabel("SoC Threshold")
        plt.ylabel("Proportion")
        plt.plot(range(1, 100 + 1), y)
        if self._file is not None:
            p = Path(self._file).parent / "figures"
        else:
            p = Path("figures")
        p.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(p / "thre_curve.png"))
        messagebox.showinfo("Threshold Curve", "Threshold curve saved to figures/thre_curve.png")

    def save(self):
        filename = filedialog.asksaveasfilename(
            title=_loc["GUI_EVANA_SAVEAS"],
            filetypes=[(_loc["GUI_EVANA_CSV_FILE"],".csv")],
            initialdir=os.getcwd()
        )
        if filename == "": return
        with open(filename,"w",encoding="utf-8") as fp:
            fp.write(f'{_loc["GUI_EVANA_TIME"]},{_loc["GUI_EVANA_TYPE"]},{_loc["GUI_EVANA_VEH"]},{_loc["GUI_EVANA_SOC"]},{_loc["GUI_EVANA_TRIP"]},{_loc["GUI_EVANA_INFO"]}\n')
            for item in self._disp:
                addinfo = ','.join(f"{k} = {v}".replace(',',' ') for k,v in item.additional.items())
                fp.write(f"{item.simT},{item.op},{item.veh},{item.veh_soc},{item.trip_id},{addinfo}\n")
            
    def load(self,filename:str):
        self._file = filename
        def thload(filename:str):
            fh = TripsReader(filename)
            self._Q.put(('L', fh))
        threading.Thread(target=thload,args=(filename,)).start()
