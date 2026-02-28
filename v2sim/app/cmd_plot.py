import shutil
from pathlib import Path
from feasytools import ArgChecker
from v2sim import *


def clear_all(p: str):
    if not (Path(p) / "cproc.clog").exists():
        return False

    print(Lang.PLOT_TOOL_CLEARING.format(p))
    p0 = Path(p) / "figures"
    if p0.exists() and p0.is_dir():
        shutil.rmtree(str(p0))
    return True


def plot_all(config: dict, p: str, q: bool, npl: AdvancedPlot):
    if not (Path(p) / "cproc.clog").exists():
        return False

    print(Lang.PLOT_TOOL_PLOTTING.format(p))

    sta = ReadOnlyStatistics(p)
    npl.load_series(sta)
    tl, tr = npl.tl, npl.tr
    plot_max = config["plotmax"]
    ploted = False

    if sta.has_BUS() and any(config["bus"].values()):
        print("\r  Plotting Bus...            ", end="")
        npl.quick_bus_tot(tl, tr, True, True, True, True, res_path=p)
        if not q:
            n = len(sta.bus_head)
            for i, b in enumerate(sta.bus_head):
                print(f"\r  Plotting Bus ({i}/{n})...            ", end="")
                npl.quick_bus(tl, tr, b, res_path=p, **config["bus"])
        ploted = True

    if sta.has_ESS() and not q and any(config["ess"].values()):
        print("\r  Plotting ESS...            ", end="")
        n = len(sta.ess_head)
        for i, e in enumerate(sta.ess_head):
            print(f"\r  Plotting ESS ({i}/{n})...            ", end="")
            npl.quick_ess(tl, tr, e, res_path=p, **config["ess"])
        ploted = True

    if sta.has_GEN() and any(config["gen"].values()):
        print("\r  Plotting Gen...            ", end="")
        npl.quick_gen_tot(tl, tr, True, True, True, res_path=p)
        if not q:
            n = len(sta.gen_head)
            for i, g in enumerate(sta.gen_head):
                print(f"\r  Plotting Gen ({i}/{n})...            ", end="")
                npl.quick_gen(tl, tr, g, res_path=p, **config["gen"])
        ploted = True

    if sta.has_LINE() and not q and any(config["line"].values()):
        print("\r  Plotting Line...           ", end="")
        n = len(sta.line_head)
        for i, l in enumerate(sta.line_head):
            print(f"\r  Plotting Line ({i}/{n})...           ", end="")
            npl.quick_line(tl, tr, l, res_path=p, **config["line"])
        ploted = True

    if sta.has_PVW() and not q and any(config["pvw"].values()):
        print("\r  Plotting PVW...            ", end="")
        n = len(sta.pvw_head)
        for i, p in enumerate(sta.pvw_head):
            print(f"\r  Plotting PVW ({i}/{n})...            ", end="")
            npl.quick_pvw(tl, tr, p, res_path=p, **config["pvw"])
        ploted = True

    if sta.has_FCS() and any(config["fcs"].values()):
        print("\r  Plotting FCS...            ", end="")
        npl.quick_fcs(tl, tr, "<sum>", res_path=p, **config["fcs"])
        npl.quick_fcs_accum(tl, tr, plot_max, res_path=p)
        if not q:
            n = len(sta.FCS_head)
            for i, f in enumerate(sta.FCS_head):
                print(f"\r  Plotting FCS ({i}/{n})...            ", end="")
                npl.quick_fcs(tl, tr, f, res_path=p, **config["fcs"])
        ploted = True

    if sta.has_SCS() and any(config["scs"].values()):
        print("\r  Plotting SCS...            ", end="")
        npl.quick_scs(tl, tr, "<sum>", res_path=p, **config["scs"])
        npl.quick_scs_accum(tl, tr, plot_max, res_path=p)
        if not q:
            n = len(sta.SCS_head)
            for i, s in enumerate(sta.SCS_head):
                print(f"\r  Plotting SCS ({i}/{n})...            ", end="")
                npl.quick_scs(tl, tr, s, res_path=p, **config["scs"])
        ploted = True

    if ploted:
        print()
    else:
        print("  " + Lang.PLOT_TOOL_EMPTY)
    return True


def recusrive_clear_all(p: str):
    if clear_all(p):
        return
    for i in Path(p).iterdir():
        if i.is_dir():
            recusrive_clear_all(str(i))


def recursive_plot_all(config: dict, p: str, q: bool, npl: AdvancedPlot):
    if plot_all(config, p, q, npl):
        return True
    res = False
    for i in Path(p).iterdir():
        if i.is_dir():
            if recursive_plot_all(config, str(i), q, npl):
                res = True
    return res


def main():
    args = ArgChecker()
    input_dir = args.pop_str("d")
    config = {
        "btime": args.pop_int("b", 0),
        "etime": args.pop_int("e", -1),
        "plotmax": args.pop_bool("plotmax"),
        "fcs": {
            "wcnt": args.pop_bool("fcs-wcnt"),
            "load": args.pop_bool("fcs-load"),
            "price": args.pop_bool("fcs-price"),
        },
        "scs": {
            "wcnt": args.pop_bool("scs-wcnt"),
            "cload": args.pop_bool("scs-cload"),
            "dload": args.pop_bool("scs-dload"),
            "netload": args.pop_bool("scs-netload"),
            "v2gcap": args.pop_bool("scs-v2gcap"),
            "pricebuy": args.pop_bool("scs-pbuy"),
            "pricesell": args.pop_bool("scs-psell"),
        },
        "ev": None,
        "bus": {
            "activel": args.pop_bool("bus-activel"),
            "reactivel": args.pop_bool("bus-reactivel"),
            "volt": args.pop_bool("bus-volt"),
            "activeg": args.pop_bool("bus-activeg"),
            "reactiveg": args.pop_bool("bus-reactiveg"),
        },
        "gen": {
            "active": args.pop_bool("gen-active"),
            "reactive": args.pop_bool("gen-reactive"),
            "costp": args.pop_bool("gen-costp"),
        },
        "line": {
            "active": args.pop_bool("line-active"),
            "reactive": args.pop_bool("line-reactive"),
            "current": args.pop_bool("line-current"),
        },
        "pvw": {
            "P": args.pop_bool("pvw-P"),
            "cr": args.pop_bool("pvw-cr"),
        },
        "ess": {
            "P": args.pop_bool("ess-P"),
            "soc": args.pop_bool("ess-soc"),
        },
    }
    if not Path(input_dir).exists():
        print(Lang.PLOT_TOOL_INDIR_NOT_FOUND.format(input_dir))
        exit(1)
    
    recur = args.pop_bool("r")
    clear = args.pop_bool("c")
    q = args.pop_bool("q")
    if not args.empty():
        for k in args.keys():
            print(Lang.PLOT_TOOL_UNKNOWN_ARG.format(k))
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
            if not plot_all(config, input_dir, q, npl):
                print(Lang.PLOT_TOOL_NO_RESULTS.format(input_dir))
        else:
            if not recursive_plot_all(config, input_dir, q, npl):
                print(Lang.PLOT_TOOL_NO_RESULTS_RECURSIVE.format(input_dir))


if __name__ == "__main__":
    main()
