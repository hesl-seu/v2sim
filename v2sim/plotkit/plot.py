import bisect
from typing import Literal, Optional, Union
import matplotlib
matplotlib.use("agg")
from matplotlib.axes import Axes
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, ScalarFormatter
from .reader import *

PLOT_ALL_CHARGE = Lang.PLOT_STR_ALL
PLOT_FAST_CHARGE = Lang.PLOT_STR_FAST
PLOT_SLOW_CHARGE = Lang.PLOT_STR_SLOW
DEFAULT_FONT = Lang.PLOT_FONT
FONT_SIZE_SMALL = int(Lang.PLOT_FONT_SIZE_SMALL)
FONT_SIZE_NORMAL = int(Lang.PLOT_FONT_SIZE_MEDIUM)
FONT_SIZE_LARGE = int(Lang.PLOT_FONT_SIZE_LARGE)

def split_string_except_quotes(string:str,delim:str,trim_quotes:bool=True) -> list[str]:
    result = []
    current_word = ""
    inside_quotes = False
    for char in string:
        if char in delim and not inside_quotes:
            if current_word:
                result.append(current_word)
                current_word = ""
        elif char == '"':
            inside_quotes = not inside_quotes
            if not trim_quotes:
                current_word += char
        else:
            current_word += char

    if current_word:
        result.append(current_word)

    return result

class AdvancedPlot:
    def __init__(self,tl:int=0,tr:int=-1,w:int=12,h:int=3,remove_edge:bool=True,double_side:bool=False,
            pic_ext:str="png",dpi:int=128,quick_plot_title:bool = True):
        self.__series:dict[str,ReadOnlyStatistics] = {}
        self.fig = None
        self.dpi = dpi
        self.pic_ext = pic_ext
        self.plot_title = quick_plot_title
        self.new_fig(tl,tr,w,h,remove_edge,double_side)
        self.max_tr = -1

    def new_fig(self,tl:int=0,tr:int=-1,w:int=12,h:int=3,remove_edge:bool=True,double_side:bool=False):
        self.tl = tl
        self.tr = tr
        if self.fig is not None: plt.close(self.fig)
        self.fig, self.ax = plt.subplots(figsize=(w, h), dpi = self.dpi, constrained_layout=True)
        self.ax: Axes
        if remove_edge:
            self.ax.spines["right"].set_visible(False)
            self.ax.spines["top"].set_visible(False)
        if double_side:
            self.ax2 = self.ax.twinx()
        else:
            self.ax2 = None
    
    def check_right(self):
        if self.ax2 is None:
            self.ax2 = self.ax.twinx()

    def calc_expr(self, expr:str):
        i = 0
        obj = ""
        vars_dics = {}
        ret_expr = ""
        rb = -1
        lb = expr.find('{')
        lp = 0
        while lb != -1:
            rb = expr.find('}',lb)
            if rb == -1:
                raise ValueError(f"Unmatched bracket in expression '{expr}'")
            obj = expr[lb+1:rb]
            if obj == "": raise ValueError("Empty variable name")
            val = self.get_series(obj)
            vars_dics[f"v{i}"] = val
            ret_expr += expr[lp:lb] + f"v{i}"
            lp = rb + 1
            lb = expr.find('{',rb)
            i += 1
        if expr.find('}',lp) != -1:
            raise ValueError(f"Exccessive right bracket in expression '{expr}'")
        if lp < len(expr):
            ret_expr += expr[lp:]
        return eval(ret_expr.replace("^","**"),vars_dics)
    
    def get_accum_series(self, series:str) -> tuple[list[int],list[list[Any]],list[str]]:
        s = series.split("|")
        if len(s) == 2:
            path,domain = s
            tl = self.tl
            tr = self.tr
        elif len(s) == 4:
            path,domain,tl,tr = s
            tl = int(tl)
            tr = int(tr)
        else:
            raise ValueError(f"Unsupported series '{series}': Should be 'path:domain:value' or 'path:domain:value:tl:tr'")
        if path not in self.__series:
            try:
                t = ReadOnlyStatistics(path)
                self.__series[path] = t
                self.max_tr = max(self.max_tr, t.LastTime)
            except:
                raise RuntimeError(f"Fail to load results directory '{path}'")
        se = self.__series[path]
        if domain == "fcs_load":
            d = se.FCS_load_all(tl,tr)
        elif domain == "scs_load":
            d = se.SCS_net_load_all(tl,tr)
        else:
            raise ValueError(f"Unsupported domain '{domain}'")
        x,y = TimeSeg.cross_interpolate(d)
        return x,y,se.FCS_head if domain.startswith("fcs") else se.SCS_head

    def load_series(self, path:Union[str, ReadOnlyStatistics]):
        if isinstance(path, str):
            try:
                t = ReadOnlyStatistics(path)
                self.__series[path] = t
                self.max_tr = max(self.max_tr, t.LastTime)
            except:
                raise RuntimeError(f"Fail to load results directory '{path}'")
        else:
            self.__series[path.root] = path
            self.max_tr = max(self.max_tr, path.LastTime)
    
    def get_series(self, series:str) -> TimeSeg:
        s = series.split("|")
        if len(s) == 2:
            path,domain = s
            val = ""
            tl = self.tl
            tr = self.tr
        elif len(s) == 3:
            path,domain,val = s
            tl = self.tl
            tr = self.tr
        elif len(s) == 4:
            path,domain,tl,tr = s
            tl = int(tl)
            tr = int(tr)
            val = ""
        elif len(s) == 5:
            path,domain,val,tl,tr = s
            tl = int(tl)
            tr = int(tr)
        else:
            raise ValueError(f"Unsupported series '{series}': Should be 'path|domain|value' or 'path|domain|value|tl|tr'")
        if path not in self.__series:
            try:
                t = ReadOnlyStatistics(path)
                self.__series[path] = t
                self.max_tr = max(self.max_tr, t.LastTime)
            except:
                raise RuntimeError(f"Fail to load results directory '{path}'")
        se = self.__series[path]
        if domain == "gen_total_active":
            d = se.G_total("totP")
        elif domain == "gen_total_reactive":
            d = se.G_total("totQ")
        elif domain == "gen_total_costp":
            d = se.G_total("totC")
        elif domain == "bus_total_active_load":
            d = se.bus_total("totPd")
        elif domain == "bus_total_reactive_load":
            d = se.bus_total("totQd")
        elif domain == "bus_total_active_gen":
            d = se.bus_total("totPg")
        elif domain == "bus_total_reactive_gen":
            d = se.bus_total("totQg")
        else:
            if val == "": raise ValueError("Value cannot be empty! Orginal series: "+series)
            if domain == "fcs_load":
                d = se.FCS_load_of(val)
            elif domain == "fcs_count":
                d = se.FCS_count_of(val)
            elif domain == "fcs_price_buy":
                d = se.FCS_pricebuy_of(val)
            elif domain == "scs_cload":
                d = se.SCS_charge_load_of(val)
            elif domain == "scs_dload":
                d = se.SCS_v2g_load_of(val)
            elif domain == "scs_load":
                d = se.SCS_net_load_of(val)
            elif domain == "scs_count":
                d = se.SCS_count_of(val)     
            elif domain == "scs_price_buy":
                d = se.SCS_pricebuy_of(val)
            elif domain == "scs_price_sell":
                d = se.SCS_pricesell_of(val)
            elif domain == "scs_vcap":
                d = se.SCS_v2g_cap_of(val)
            elif domain == "ev_soc":
                d = se.EV_attrib_of(val,"soc")
            elif domain == "ev_cost":
                d = se.EV_attrib_of(val,"cost")
            elif domain == "ev_earn":
                d = se.EV_attrib_of(val,"earn")
            elif domain == "ev_cpure":
                d = se.EV_attrib_of(val,"cost") - se.EV_attrib_of(val,"earn")
            elif domain == "ev_status":
                d = se.EV_attrib_of(val,"status")
            elif domain == "gen_active":
                d = se.G_attrib_of(val,"P")
            elif domain == "gen_reactive":
                d = se.G_attrib_of(val,"Q")
            elif domain == "gen_costp":
                d = se.G_attrib_of(val,"costp")
            elif domain == "bus_voltage":
                d = se.bus_attrib_of(val,"V")
            elif domain == "bus_active_load":
                d = se.bus_attrib_of(val,"Pd")
            elif domain == "bus_reactive_load":
                d = se.bus_attrib_of(val,"Qd")
            elif domain == "bus_active_gen":
                d = se.bus_attrib_of(val,"Pg")
            elif domain == "bus_reactive_gen":
                d = se.bus_attrib_of(val,"Qg")
            elif domain == "line_active":
                d = se.line_attrib_of(val,"P")
            elif domain == "line_reactive":
                d = se.line_attrib_of(val,"Q")
            elif domain == "line_current":
                d = se.line_attrib_of(val,"I")
            elif domain == "pvw_p":
                d = se.pvw_attrib_of(val,"P")
            elif domain == "pvw_cr":
                d = se.pvw_attrib_of(val,"curt")
            elif domain == "ess_p":
                d = se.ess_attrib_of(val,"P")
            elif domain == "ess_soc":
                d = se.ess_attrib_of(val,"soc")
            else:
                raise ValueError(f"Unsupported domain '{domain}'")
        return d.slice(tl,self.max_tr).interpolate(tl,self.max_tr)
    
    def add_data(self, 
            expr:str, 
            label:Optional[str]=None, 
            color:Optional[str]=None, 
            linestyle:Optional[str]="-",
            linewidth:Optional[float]=1,
            side:Literal["left","right"]="left"
        ):
        kwargs = {}
        if label is not None:
            kwargs["label"] = label
        if color is not None:
            kwargs["color"] = color
        if linestyle is not None:
            kwargs["linestyle"] = linestyle
        if linewidth is not None:
            kwargs["linewidth"] = linewidth
        data = self.calc_expr(expr)
        assert isinstance(data, TimeSeg)
        if side == "left":
            self.ax.plot(*data(), **kwargs)
        else:
            self.check_right()
            assert isinstance(self.ax2, Axes)
            self.ax2.plot(*data(), **kwargs)
        self.__setticks()
    
    def __setticks(self):
        tl = self.tl
        tr = self.max_tr if self.tr == -1 else self.tr
        if tl % 60 != 0: tl -= tl%60
        if tr % 60 != 0: tr += (60-tr%60)
        k = (tr - tl) // 12
        ava_k = [900, 1800, 3600, 7200, 3*3600, 4*3600,6*3600, 8*3600, 12*3600, 24*3600]
        p = bisect.bisect_right(ava_k, k) - 1
        if p<0: p = 0
        k = ava_k[p]
        def __trans(i:int):
            return f"D{i//86400}-{(i%86400)//3600:02}:{(i%3600)//60:02}"
        self.ax.set_xticks(
            list(range(tl, tr+1, k)),
            map(__trans, range(tl, tr+1, k))
        )
        plt.setp(self.ax.get_xticklabels(), rotation=20, ha="right", rotation_mode="anchor")
    
    def add_accum(self,name:str,plot_max:bool):
        x,y,lbs = self.get_accum_series(name)
        self.ax.stackplot(x,y,labels=lbs)
        if plot_max:
            max_y = max([sum(y[i][j] for i in range(len(y))) for j in range(len(x))])
            print(max_y)
            self.ax.plot([x[0],x[-1]],[max_y,max_y],color="black",linestyle="--",linewidth=1.5)
            self.ax.text(x[0] + (x[-1] - x[0]) * 0.01, max_y * 0.9, f"Max = {max_y:.1f}kW", fontsize = FONT_SIZE_SMALL, color="black")
        self.__setticks()
    
    def y_label(self,label:str,side:Literal["left","right"]="left"):
        if side == "left":
            self.yleft_label(label)
        else:
            self.yright_label(label)
    
    def yleft_label(self,label:str):
        self.ax.set_ylabel(label, fontweight="bold", font=DEFAULT_FONT, fontsize=FONT_SIZE_NORMAL)
    
    def yleft_range(self,low:float,high:float):
        self.ax.set_ylim(low, high)

    def yright_label(self,label:str):
        self.check_right()
        assert isinstance(self.ax2, Axes)
        self.ax2.set_ylabel(label, fontweight="bold", font=DEFAULT_FONT, fontsize=FONT_SIZE_NORMAL)
    
    def yright_range(self,low:float,high:float):
        self.check_right()
        assert isinstance(self.ax2, Axes)
        self.ax2.set_ylim(low,high)
    
    def x_label(self,label:str):
        self.ax.set_xlabel(label, fontweight="bold", font=DEFAULT_FONT, fontsize=FONT_SIZE_NORMAL)
    
    def title(self,title:str):
        self.ax.set_title(title, font=DEFAULT_FONT, fontsize=FONT_SIZE_LARGE)
    
    def yticks(self,ticks,labels:Optional[Iterable[str]] = None):
        self.ax.set_yticks(ticks,labels)

    def legend(self,loc:str="upper right",ncol:int=1):
        assert self.fig is not None
        self.fig.legend(loc=loc, bbox_to_anchor=(1, 1), bbox_transform=self.ax.transAxes,ncol=ncol)

    def hline(self,y:float,color:str="black",linestyle:str="--",linewidth:float=1.5):
        self.ax.axhline(y=y,color=color,linestyle=linestyle,linewidth=linewidth)
    
    def vline(self,x:float,color:str="black",linestyle:str="--",linewidth:float=1.5):
        self.ax.axvline(x=x,color=color,linestyle=linestyle,linewidth=linewidth)
    
    def save(self,save_to:str,mloc:bool=True,zeroxmargin:bool=True):
        if mloc:
            x_major_locator = MultipleLocator(3600)
            self.ax.xaxis.set_major_locator(x_major_locator)
        if zeroxmargin:
            self.ax.margins(x=0)
        y_formatter = ScalarFormatter(useOffset=False)
        self.ax.yaxis.set_major_formatter(y_formatter)
        self.ax.set_xlim(self.tl, self.max_tr if self.tr == -1 else self.tr)
        assert self.fig is not None
        self.fig.savefig(save_to, dpi=self.dpi, bbox_inches="tight")
        plt.close()
    
    def configure(self,commands:Union[str,list[str]]):
        if isinstance(commands,str):
            commands = split_string_except_quotes(commands,";",False)
        else:
            new_cmds = []
            for cmd in commands:
                new_cmds.extend(split_string_except_quotes(cmd,";",False))
            commands = new_cmds
        for cmd in commands:
            cmds = split_string_except_quotes(cmd.strip()," ,")
            if len(cmds) == 0:
                continue
            if cmds[0] == "plot":
                if len(cmds) <= 1:
                    raise ValueError("Series not provided")
                expr = cmds[1] 
                kwargs = {
                    "label": cmds[2] if len(cmds) > 2 else None,
                    "color": cmds[3] if len(cmds) > 3 else None,
                    "linestyle": cmds[4] if len(cmds) > 4 else "-",
                    "linewidth": float(cmds[5]) if len(cmds) > 5 else 1,
                    "side": cmds[6] if len(cmds) > 6 else "left"
                }
                self.add_data(expr,**kwargs)
            elif cmds[0] == "plotaccum":
                if len(cmds) <= 1:
                    raise ValueError("Series not provided")
                plot_max = cmds[2] == "True" if len(cmds) > 2 else False
                self.add_accum(cmds[1], plot_max)
            elif cmds[0] == "new":
                if len(cmds) <= 2:
                    raise ValueError("width and height not provided")
                self.fig, self.ax = plt.subplots(
                    figsize=(int(cmds[1]), int(cmds[2])), 
                    dpi=128, 
                    constrained_layout=True
                )
            elif cmds[0] == "title":
                self.title(cmds[1])
                if len(cmds) <= 1:
                    raise ValueError("Title not provided")
            elif cmds[0] == "xlabel":
                self.x_label(cmds[1])
                if len(cmds) <= 1:
                    raise ValueError("X-axis label not provided")
            elif cmds[0] == "yleftlabel" or cmds[0] == "ylabel":
                self.yleft_label(cmds[1])
                if len(cmds) <= 1:
                    raise ValueError("Y-axis label not provided")
            elif cmds[0] == "yrightlabel":
                self.yright_label(cmds[1])
                if len(cmds) <= 1:
                    raise ValueError("Y-axis label not provided")
            elif cmds[0] == "yticks":
                if len(cmds) <= 1:
                    raise ValueError("Y-axis ticks not provided")
                self.yticks(
                    [float(x) for x in cmds[1].split(",")],
                    cmds[2].split(",") if len(cmds) > 2 else None
                )
            elif cmds[0] == "legend":
                self.legend(
                    cmds[1] if len(cmds) > 1 else "upper right", 
                    int(cmds[2]) if len(cmds) > 2 else 1
                )
            elif cmds[0] == "save":
                self.save(cmds[1])
            elif cmds[0] == "default_trunc":
                assert len(cmds) == 3
                self.tl = int(cmds[1])
                self.tr = int(cmds[2])
                self.max_tr = self.tr
            elif cmds[0] == "hline":
                self.hline(
                    float(cmds[1]),
                    cmds[2] if len(cmds) > 2 else "black",
                    cmds[3] if len(cmds) > 3 else "--",
                    float(cmds[4]) if len(cmds) > 4 else 1.5
                )
            elif cmds[0] == "vline":
                self.vline(
                    float(cmds[1]),
                    cmds[2] if len(cmds) > 2 else "black",
                    cmds[3] if len(cmds) > 3 else "--",
                    float(cmds[4]) if len(cmds) > 4 else 1.5
                )
            elif cmds[0] == "exit":
                return False
            elif cmds[0] == "help":
                print(Lang.ADV_PLOT_HELP)
            elif cmds[0] == "":
                continue
            else:
                raise ValueError(f"Unsupported command '{cmds[0]}'")
        return True
    
    def quick_fcs_accum(self,tl:int,tr:int,plot_max:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        self.add_accum(f"{res_path}|fcs_load", plot_max)
        self.yleft_label(Lang.PLOT_YLABEL_POWERKW)
        if self.plot_title: self.title(Lang.PLOT_FCS_ACC_TITLE)
        self.legend(ncol=2)
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if save_to == "": save_to = str(p / f"fcs_total.{self.pic_ext}")
        self.save(save_to)
    
    def quick_scs_accum(self,tl:int,tr:int,plot_max:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        self.add_accum(f"{res_path}|scs_load", plot_max)
        self.yleft_label(Lang.PLOT_YLABEL_POWERKW)
        if self.plot_title: self.title(Lang.PLOT_SCS_ACC_TITLE)
        self.legend(ncol=2)
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if save_to == "": save_to = str(p / f"scs_total.{self.pic_ext}")
        self.save(save_to)
    
    def quick_fcs(self,tl:int,tr:int,cs_name:str,load:bool,price:bool,wcnt:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if cs_name == "":
            raise ValueError("CS name cannot be empty")
        if load:
            self.add_data("{"+f"{res_path}|fcs_load|{cs_name}"+"}","Load",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERKW)
        if price:
            side = "right" if load else "left"
            self.add_data("{"+f"{res_path}|fcs_price_buy|{cs_name}"+"}","Price",color="red",side=side)
            self.y_label(Lang.PLOT_YLABEL_PRICE, side)
        if wcnt:
            if load and price:
                raise RuntimeError("Cannot plot count with load and price, since there are only 2 sides")
            side = "right" if load or price else "left"
            self.add_data("{"+f"{res_path}|fcs_count|{cs_name}"+"}","Veh. Count",color="green",side=side)
            self.y_label(Lang.PLOT_YLABEL_COUNT,side)
        if self.plot_title: self.title(Lang.PLOT_FCS_TITLE.format(cs_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if cs_name == "<sum>": cs_name = "sum"
        if save_to == "": save_to = str(p / f"fcs_{cs_name}.{self.pic_ext}")
        self.save(save_to)
    
    def quick_scs(self,tl:int,tr:int,cs_name:str,cload:bool,dload:bool,netload:bool,v2gcap:bool,wcnt:bool,pricebuy:bool,pricesell:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        has_load = cload or dload or netload or v2gcap
        if has_load:
            self.yleft_label(Lang.PLOT_YLABEL_POWERKW)
            if cload:
                self.add_data("{"+f"{res_path}|scs_cload|{cs_name}"+"}","Charging Load",color="blue")
            if dload:
                self.add_data("{"+f"{res_path}|scs_dload|{cs_name}"+"}", "Discharging Load",color="red")
            if netload:
                self.add_data("{"+f"{res_path}|scs_load|{cs_name}"+"}", "Net Load",color="green")
            if v2gcap:
                self.add_data("{"+f"{res_path}|scs_vcap|{cs_name}"+"}", "V2G Capacity",color="purple")
        
        has_price = pricebuy or pricesell
        if has_price:
            side = "right" if has_load else "left"
            if pricebuy:
                self.add_data("{"+f"{res_path}|scs_price_buy|{cs_name}"+"}","Price Buy",color="orange",side=side)
            if pricesell:
                self.add_data("{"+f"{res_path}|scs_price_sell|{cs_name}"+"}","Price Sell",color="cyan",side=side)
            self.y_label(Lang.PLOT_YLABEL_PRICE, side)
            
        if wcnt:
            if has_load and has_price:
                raise RuntimeError("Cannot plot count with load and price, since there are only 2 sides")
            side = "right" if has_load or has_price else "left"
            self.add_data("{"+f"{res_path}|scs_count|{cs_name}"+"}","Veh. Count",color="gray",side=side)
            self.y_label(Lang.PLOT_YLABEL_COUNT, side)
        if self.plot_title: self.title(Lang.PLOT_SCS_TITLE.format(cs_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if cs_name == "<sum>": cs_name = "sum"
        if save_to == "": save_to = str(p / f"scs_{cs_name}.{self.pic_ext}")
        self.save(save_to)
    
    def quick_bus(self,tl:int,tr:int,bus_name:str,activel:bool,reactivel:bool,volt:bool,
                  activeg:bool,reactiveg:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if volt:
            self.add_data("{"+f"{res_path}|bus_voltage|{bus_name}"+"}","Voltage",color="green")
            self.yleft_label(Lang.PLOT_YLABEL_VOLTKV)
        if activel:
            side = "right" if volt else "left"
            self.add_data("{"+f"{res_path}|bus_active_load|{bus_name}"+"}","Active Load",color="blue",side=side)
            self.y_label(Lang.PLOT_YLABEL_POWERMW, side)
        if reactivel:
            side = "right" if volt else "left"
            self.add_data("{"+f"{res_path}|bus_reactive_load|{bus_name}"+"}","Reactive Load",color="red",side=side)
            self.y_label(Lang.PLOT_YLABEL_POWERMW, side)
        if activeg:
            side = "right" if volt else "left"
            self.add_data("{"+f"{res_path}|bus_active_gen|{bus_name}"+"}","Active Gen",color="purple",side=side)
            self.y_label(Lang.PLOT_YLABEL_POWERMW, side)
        if reactiveg:
            side = "right" if volt else "left"
            self.add_data("{"+f"{res_path}|bus_reactive_gen|{bus_name}"+"}","Reactive Gen",color="cyan",side=side)
            self.y_label(Lang.PLOT_YLABEL_POWERMW, side)
        if self.plot_title: self.title(Lang.PLOT_BUS.format(bus_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if bus_name == "<sum>": bus_name = "sum"
        if save_to == "": save_to = str(p / f"bus_{bus_name}.{self.pic_ext}")
        self.save(save_to)
        
    def quick_gen(self,tl:int,tr:int,gen_name:str,active:bool,reactive:bool,costp:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if active:
            self.add_data("{"+f"{res_path}|gen_active|{gen_name}"+"}","Active Power",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERMW)
        if reactive:
            self.add_data("{"+f"{res_path}|gen_reactive|{gen_name}"+"}","Reactive Power",color="red")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if costp:
            side = "right" if active or reactive else "left"
            self.add_data("{"+f"{res_path}|gen_costp|{gen_name}"+"}","Cost",color="green",side=side)
            self.y_label(Lang.PLOT_YLABEL_COST, side)
        if self.plot_title: self.title(Lang.PLOT_GEN.format(gen_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if gen_name == "<sum>": gen_name = "sum"
        if save_to == "": save_to = str(p / f"gen_{gen_name}.{self.pic_ext}")
        self.save(save_to)
    
    def quick_ev(self,tl:int,tr:int,ev_name:str,soc:bool,status:bool,cost:bool,earn:bool,cpure:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if soc:
            self.add_data("{"+f"{res_path}|ev_soc|{ev_name}"+"}","SOC",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_SOC)
        if cost:
            side = "right" if soc else "left"
            self.add_data("{"+f"{res_path}|ev_cost|{ev_name}"+"}","Cost",color="green",side=side)
            self.y_label(Lang.PLOT_YLABEL_COST, side)
        if earn:
            side = "right" if soc else "left"
            self.add_data("{"+f"{res_path}|ev_earn|{ev_name}"+"}","Earn",color="purple",side=side)
            self.y_label(Lang.PLOT_YLABEL_COST, side)
        if cpure:
            side = "right" if soc else "left"
            self.add_data("{"+f"{res_path}|ev_cpure|{ev_name}"+"}","Pure cost",color="cyan",side=side)
            self.y_label(Lang.PLOT_YLABEL_COST, side)
        if status:
            if soc and (cost or earn or cpure):
                raise RuntimeError("Cannot plot cost with soc and status, since there are only 2 sides")
            side = "right" if soc or cost or earn or cpure else "left"
            self.add_data("{"+f"{res_path}|ev_status|{ev_name}"+"}","Status",color="red")
            self.y_label(Lang.PLOT_YLABEL_STATUS)
        if cost and earn:
            self.legend(ncol=2)
        else:
            self.legend()
        if self.plot_title: self.title(Lang.PLOT_EV.format(ev_name))
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if save_to == "": save_to = str(p / f"ev_{ev_name}.{self.pic_ext}")
        self.save(save_to)
        
    def quick_gen_tot(self,tl:int,tr:int,active:bool,reactive:bool,costp:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if active:
            self.add_data("{"+f"{res_path}|gen_total_active|<sum>"+"}","Active Power",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERMW)
        if reactive:
            self.add_data("{"+f"{res_path}|gen_total_reactive|<sum>"+"}","Reactive Power",color="red")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if costp:
            side = "right" if active or reactive else "left"
            self.add_data("{"+f"{res_path}|gen_total_costp|<sum>"+"}","Cost",color="green",side=side)
            self.y_label(Lang.PLOT_YLABEL_COST,side)
        if self.plot_title: self.title(Lang.PLOT_GEN_TOTAL)
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if save_to == "": save_to = str(p / f"gen_total.{self.pic_ext}")
        self.save(save_to)
    
    def quick_bus_tot(self,tl:int,tr:int,active:bool,reactive:bool,active_gen:bool,reactive_gen:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if active:
            self.add_data("{"+f"{res_path}|bus_total_active_load"+"}","Active Load",color="blue")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if reactive:
            self.add_data("{"+f"{res_path}|bus_total_reactive_load"+"}","Reactive Load",color="red")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if active_gen:
            self.add_data("{"+f"{res_path}|bus_total_active_gen"+"}","Active Gen",color="green")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if reactive_gen:
            self.add_data("{"+f"{res_path}|bus_total_reactive_gen"+"}","Reactive Gen",color="purple")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if self.plot_title: self.title(Lang.PLOT_BUS_TOTAL)
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if save_to == "": save_to = str(p / f"bus_total.{self.pic_ext}")
        self.save(save_to)
    
    def quick_line(self,tl:int,tr:int,line_name:str,active:bool,reactive:bool,current:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if active:
            self.add_data("{"+f"{res_path}|line_active|{line_name}"+"}","Active Power",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERMW)
        if reactive:
            self.add_data("{"+f"{res_path}|line_reactive|{line_name}"+"}","Reactive Power",color="red")
            self.y_label(Lang.PLOT_YLABEL_POWERMW)
        if current:
            side = "right" if active or reactive else "left"
            self.add_data("{"+f"{res_path}|line_current|{line_name}"+"}","Current",color="green",side=side)
            self.y_label(Lang.PLOT_YLABEL_CURRENT, side)
        if self.plot_title: self.title(Lang.PLOT_LINE.format(line_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if line_name == "<sum>": line_name = "sum"
        if save_to == "": save_to = str(p / f"line_{line_name}.{self.pic_ext}")
        self.save(save_to)
    
    def quick_pvw(self,tl:int,tr:int,pvw_name:str,P:bool,cr:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if P:
            self.add_data("{"+f"{res_path}|pvw_p|{pvw_name}"+"}","Active Power",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERMW)
        if cr:
            side = "right" if P else "left"
            self.add_data("{"+f"{res_path}|pvw_cr|{pvw_name}"+"}","Curtailment Rate",color="red")
            self.y_label(Lang.PLOT_YLABEL_CURTAIL, side=side)
        if self.plot_title: self.title(Lang.PLOT_PVW.format(pvw_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if pvw_name == "<sum>": pvw_name = "sum"
        if save_to == "": save_to = str(p / f"pvw_{pvw_name}.{self.pic_ext}")
        self.save(save_to)
    
    def quick_ess(self,tl:int,tr:int,ess_name:str,P:bool,soc:bool,save_to:str="",res_path:str="results"):
        self.new_fig(tl,tr)
        if P:
            self.add_data("{"+f"{res_path}|ess_p|{ess_name}"+"}","Active Power",color="blue")
            self.yleft_label(Lang.PLOT_YLABEL_POWERMW)
        if soc:
            side = "right" if P else "left"
            self.add_data("{"+f"{res_path}|ess_soc|{ess_name}"+"}","SoC",color="red")
            self.y_label(Lang.PLOT_YLABEL_SOC, side=side)
        if self.plot_title: self.title(Lang.PLOT_ESS.format(ess_name))
        self.legend()
        self.x_label(Lang.PLOT_XLABEL_TIME)
        p = Path(res_path) / "figures"
        p.mkdir(parents=True,exist_ok=True)
        if ess_name == "<sum>": ess_name = "sum"
        if save_to == "": save_to = str(p / f"ess_{ess_name}.{self.pic_ext}")
        self.save(save_to)