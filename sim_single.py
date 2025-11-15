from pathlib import Path
from typing import Dict, Optional
from v2simux import (
    Lang, PluginPool, StaPool,
    load_external_components,
    simulate_single,
    get_sim_params,
)
import threading, sys, logging, platform
from feasytools import ArgChecker, KeyNotSpecifiedError, FEasyTimer


def error_exit(err=None, print_help: bool = False):
    if err:
        if isinstance(err, KeyNotSpecifiedError):
            print(Lang.ERROR_CMD_NOT_SPECIFIED.format(err.key))
        elif isinstance(err, Exception):
            print(Lang.ERROR_GENERAL.format(f"{type(err).__name__} {str(err)}"))
        else:
            print(Lang.ERROR_GENERAL.format(err))
    print()
    if print_help:
        print(Lang.MAIN_HELP_STR.format(sys.argv[0]))
    sys.exit()

#@FEasyTimer
def work(pars:Optional[dict] = None, clntID:int = -1, q=None, alt:Optional[Dict[str,str]] = None):
    if pars is not None:
        args = ArgChecker(pars=pars, force_parametric=["gen-veh", "gen-scs", "gen-fcs", "plot"])
    else:
        try:
            args = ArgChecker(force_parametric=["gen-veh", "gen-scs", "gen-fcs", "plot"])
        except Exception as e:
            error_exit(e, True)
    if args.pop_bool("h") or args.pop_bool("help"):
        error_exit(None, True)

    sta_pool = StaPool()
    plg_pool = PluginPool()
    if Path("external_components").exists():
        load_external_components("external_components", plg_pool, sta_pool)

    if args.pop_bool("ls-com"):
        print(Lang.MAIN_LS_TITLE_PLG)
        for key, (_, deps) in plg_pool.GetAllPlugins().items():
            if len(deps) > 0:
                print(f"{key}: {','.join(deps)}")
            else:
                print(key)
        print(Lang.MAIN_LS_TITLE_STA)
        print(",".join(sta_pool.GetAllLogItem()))
        sys.exit()

    from_file = args.pop_str("file", "")
    if from_file != "":  # Read parameters from file
        try:
            with open(from_file, "r") as f:
                command = f.read().strip()
        except Exception as e:
            error_exit(Lang.ERROR_FAIL_TO_OPEN.format(from_file, e))
        try:
            kwargs = get_sim_params(command, plg_pool, sta_pool)
        except Exception as e:
            error_exit(str(e), True)
        visible = False
    else:  # Read parameters from command line
        if platform.system() == "Windows":
            if "show" in args.keys():
                print(Lang.WARN_MAIN_SHOW_MEANINGLESS)
                args.pop_bool("show")
            visible = False
        else:
            visible = args.pop_bool("show")

        no_deamon = args.pop_bool("no-daemon")
        debug_mode = args.pop_bool("debug")
        if debug_mode and not visible:
            print(Lang.WARN_MAIN_DEBUG_MEANINGLESS)
            debug_mode = False

        # Get simulation parameters
        try:
            kwargs = get_sim_params(args, plg_pool, sta_pool)
        except Exception as e:
            error_exit(e, True)

    if visible:
        try:
            from v2simux_gui.progbox import ProgBox
        except:
            print(Lang.WARN_MAIN_GUI_NOT_FOUND)
            visible = False

    kwargs.update({
        "clntID": clntID,
        "mpQ": q,
        "alt_command": alt,
    })
    
    if visible:
        vb = ProgBox(
            ["Driving", "Pending", "Charging", "Parking", "Depleted"],
            "Simulator Dashboard",
        )

        def work():
            try:
                simulate_single(vb=vb, **kwargs)
            except Exception as e:
                if debug_mode:
                    raise e
                logging.exception(e)
            vb.close()

        th = threading.Thread(target=work, daemon=not no_deamon).start()
        vb.mainloop()
    else:
        if clntID == -1: print(Lang.MAIN_SIM_START)
        simulate_single(**kwargs)

if __name__ == "__main__":
    from version_checker import check_requirements
    check_requirements()
    work()