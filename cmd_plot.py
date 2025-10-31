from pathlib import Path
import shutil
from feasytools import ArgChecker
from v2simux import *

def clear_all(p:str):
    if not (Path(p)/"cproc.clog").exists(): return False
    print(f"Clearing {p}...")
    p0 = Path(p) / "figures"
    if p0.exists() and p0.is_dir():
        shutil.rmtree(str(p0))
    return True

def plot_all(config:dict, p:str, q:bool, npl:AdvancedPlot):
    if not (Path(p)/"cproc.clog").exists(): return False
    print(f"Plotting {p}...")
    sta = ReadOnlyStatistics(p)
    npl.load_series(sta)
    tl, tr = npl.tl, npl.tr
    plot_max = config["plotmax"]        
    if sta.has_BUS():
        print("\r  Plotting Bus...            ",end="")
        npl.quick_bus_tot(tl,tr,True,True,True,True,res_path=p)
        if not q:
            n = len(sta.bus_head)
            for i, b in enumerate(sta.bus_head):
                print(f"\r  Plotting Bus ({i}/{n})...            ",end="")
                npl.quick_bus(tl,tr,b,res_path=p,**config["bus"])
    if sta.has_ESS() and not q:
        print("\r  Plotting ESS...            ",end="")
        n = len(sta.ess_head)
        for i, e in enumerate(sta.ess_head):
            print(f"\r  Plotting ESS ({i}/{n})...            ",end="")
            npl.quick_ess(tl,tr,e,res_path=p,**config["ess"])
    if sta.has_GEN():
        print("\r  Plotting Gen...            ",end="")
        npl.quick_gen_tot(tl,tr,True,True,True,res_path=p)
        if not q:
            n = len(sta.gen_head)
            for i, g in enumerate(sta.gen_head):
                print(f"\r  Plotting Gen ({i}/{n})...            ",end="")
                npl.quick_gen(tl,tr,g,res_path=p,**config["gen"])
    if sta.has_LINE() and not q:
        print("\r  Plotting Line...           ",end="")
        n = len(sta.line_head)
        for i, l in enumerate(sta.line_head):
            print(f"\r  Plotting Line ({i}/{n})...           ",end="")
            npl.quick_line(tl,tr,l,res_path=p,**config["line"])
    if sta.has_PVW() and not q:
        print("\r  Plotting PVW...            ",end="")
        n = len(sta.pvw_head)
        for i, p in enumerate(sta.pvw_head):
            print(f"\r  Plotting PVW ({i}/{n})...            ",end="")
            npl.quick_pvw(tl,tr,p,res_path=p,**config["pvw"])
    if sta.has_FCS():
        print("\r  Plotting FCS...            ",end="")
        npl.quick_fcs(tl,tr,"<sum>",res_path=p,**config["fcs"])
        npl.quick_fcs_accum(tl,tr,plot_max,res_path=p)
        if not q:
            n = len(sta.FCS_head)
            for i, f in enumerate(sta.FCS_head):
                print(f"\r  Plotting FCS ({i}/{n})...            ",end="")
                npl.quick_fcs(tl,tr,f,res_path=p,**config["fcs"])
    if sta.has_SCS():
        print("\r  Plotting SCS...            ",end="")
        npl.quick_scs(tl,tr,"<sum>",res_path=p,**config["scs"])
        npl.quick_scs_accum(tl,tr,plot_max,res_path=p)
        if not q:
            n = len(sta.SCS_head)
            for i, s in enumerate(sta.SCS_head):
                print(f"\r  Plotting SCS ({i}/{n})...            ",end="")
                npl.quick_scs(tl,tr,s,res_path=p,**config["scs"])
    print()
    return True

def recusrive_clear_all(p:str):
    if clear_all(p): return
    for i in Path(p).iterdir():
        if i.is_dir():
            recusrive_clear_all(str(i))
    
def recursive_plot_all(config:dict, p:str, q:bool, npl:AdvancedPlot):
    if plot_all(config, p, q, npl): return
    for i in Path(p).iterdir():
        if i.is_dir():
            recursive_plot_all(config, str(i), q, npl)

if __name__ == "__main__":
    from version_checker import check_requirements
    check_requirements()
    
    args = ArgChecker()
    input_dir = args.pop_str("d")
    config = {
        "btime":args.pop_int("b",0),
        "etime":args.pop_int("e",-1),
        "plotmax":args.pop_bool("plotmax"),
        "fcs":{
            "wcnt": args.pop_bool("fcs_wcnt"),
            "load": args.pop_bool("fcs_load"),
            "price": args.pop_bool("fcs_price"),
        },
        "scs":{
            "wcnt": args.pop_bool("scs_wcnt"),
            "cload": args.pop_bool("scs_cload"),
            "dload": args.pop_bool("scs_dload"),
            "netload": args.pop_bool("scs_netload"),
            "v2gcap": args.pop_bool("scs_v2gcap"),
            "pricebuy": args.pop_bool("scs_pbuy"),
            "pricesell": args.pop_bool("scs_psell"),
        },
        "ev":None,
        "bus":{
            "activel": args.pop_bool("bus_activel"),
            "reactivel": args.pop_bool("bus_reactivel"),
            "volt": args.pop_bool("bus_volt"),
            "activeg": args.pop_bool("bus_activeg"),
            "reactiveg": args.pop_bool("bus_reactiveg"),
        },
        "gen":{
            "active": args.pop_bool("gen_active"),
            "reactive": args.pop_bool("gen_reactive"),
            "costp": args.pop_bool("gen_costp"),
        },
        "line":{
            "active": args.pop_bool("line_active"),
            "reactive": args.pop_bool("line_reactive"),
            "current": args.pop_bool("line_current"),
        },
        "pvw":{
            "P": args.pop_bool("pvw_P"),
            "cr": args.pop_bool("pvw_cr"),
        },
        "ess":{
            "P": args.pop_bool("ess_P"),
            "soc": args.pop_bool("ess_soc"),
        }
    }
    if not Path(input_dir).exists():
        print("Input directory does not exist")
        exit(1)
    recur = args.pop_bool("r")
    clear = args.pop_bool("c")
    q = args.pop_bool("q")
    if not args.empty():
        print("Unknown arguments!",)
        exit(1)
    if clear:
        if not recur:
            clear_all(input_dir)
        else:
            recusrive_clear_all(input_dir)
    else:
        tl, tr = config["btime"], config["etime"]
        npl = AdvancedPlot(tl, tr)
        if not recur:
            plot_all(config, input_dir, q, npl)
        else:
            recursive_plot_all(config, input_dir, q, npl)