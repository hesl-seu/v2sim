import threading, sys, logging, platform
from typing import Optional, Union
from v2sim import Lang, get_sim_params
from feasytools import ArgChecker, KeyNotSpecifiedError
from v2sim.core import ClientOptions
from v2sim.wrapper import AltCommand, create_pools, simulate_single


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


FORCE_PARAM = ["gen-veh", "gen-scs", "gen-fcs", "plot"]


def work(
    pars:Union[ArgChecker, dict], 
    client_options:Optional[ClientOptions] = None,
    alt:Optional[AltCommand] = None
):
    args = ArgChecker(pars=pars, force_parametric=FORCE_PARAM) if isinstance(pars, dict) else pars
    
    try:
        kwargs = get_sim_params(args)
    except Exception as e:
        error_exit(e, True)
    
    kwargs.update({
        "client_options": client_options,
        "alt_cmds": alt,
    })
    
    if (client_options or ClientOptions()).clientID == -1:
        print(Lang.MAIN_SIM_START)
    else:
        kwargs["silent"] = True
    simulate_single(**kwargs)


def work_gui(pars:Union[ArgChecker, dict], no_daemon:bool, debug_mode:bool):
    from v2sim.gui.progbox import ProgBox
    vb = ProgBox(["Driving", "Pending", "Charging", "Parking", "Depleted"], "Simulator Dashboard")

    args = ArgChecker(pars=pars, force_parametric=FORCE_PARAM) if isinstance(pars, dict) else pars

    try:
        kwargs = get_sim_params(args)
    except Exception as e:
        error_exit(e, True)

    def _work():
        try:
            simulate_single(vb=vb, **kwargs)
        except Exception as e:
            if debug_mode:
                raise e
            logging.exception(e)
        vb.close()
    
    threading.Thread(target=_work, daemon=not no_daemon).start()
    vb.mainloop()


def main():
    try:
        args = ArgChecker(force_parametric=FORCE_PARAM)
    except Exception as e:
        error_exit(e, True)
    
    # Help message
    if args.pop_bool("h") or args.pop_bool("help"):
        print(Lang.MAIN_HELP_STR)
        return
    
    # List available plugins and statistics
    if args.pop_bool("ls-com"):
        plg_pool, sta_pool = create_pools()
        print(Lang.MAIN_LS_TITLE_PLG)
        for key, (_, deps) in plg_pool.GetAllPlugins().items():
            if len(deps) > 0:
                print(f"{key}: {','.join(deps)}")
            else:
                print(key)
        print(Lang.MAIN_LS_TITLE_STA)
        print(",".join(sta_pool.GetAllLogItem()))
        return
    
    # Read parameters from file if specified
    from_file = args.pop_str("file", "")
    if from_file != "":
        try:
            with open(from_file, "r") as f:
                command = f.read().strip()
        except Exception as e:
            error_exit(Lang.ERROR_FAIL_TO_OPEN.format(from_file, e))
        try:
            # Use the parameters from file as default, override with command line
            new_args = ArgChecker(pars = command).to_dict()
            new_args.update(args.to_dict())
            args = ArgChecker(pars = new_args, force_parametric=FORCE_PARAM)
        except Exception as e:
            error_exit(str(e), True)

    # Determine visibility level
    if platform.system() == "Windows":
        if "show" in args.keys():
            print(Lang.WARN_MAIN_SHOW_MEANINGLESS)
            args.pop_bool("show")
        from v2sim.sim.win_vis import WINDOWS_VISUALIZE
        visible = WINDOWS_VISUALIZE
    else:
        visible = args.pop_bool("show")

    no_deamon = args.pop_bool("no-daemon")
    debug_mode = args.pop_bool("debug")
    if not visible:
        if no_deamon:
            print(Lang.WARN_MAIN_NO_DAEMON_MEANINGLESS)
            no_deamon = False
        if debug_mode:
            print(Lang.WARN_MAIN_DEBUG_MEANINGLESS)
            debug_mode = False
        work(args)
    else:
        work_gui(args, no_deamon, debug_mode)


if __name__ == "__main__":
    main()