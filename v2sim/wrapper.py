from dataclasses import dataclass
from feasytools import ArgChecker
from .sim import TimeConfig
from .plugins import *
from .stats import *
from .sim import *
from .locale import Lang
from .utils import *
from .core import *


def get_internal_components():
    """
    Get internal components
    Returns:
        A tuple containing two lists:
            - The first list contains plugins
            - The second list contains statistical items
    """
    return GetInternalPlugins(), GetInternalStatistics()


@dataclass
class GenerationCommand:
    fcs: str = ""
    scs: str = ""
    gs: str = ""
    veh: str = ""

    def all_empty(self):
        return all(x == "" for x in [self.fcs, self.scs, self.gs, self.veh])
    
    def generate(self, proj_dir:str, silent:bool = False):
        if self.all_empty(): return None

        from .gen import TrafficGenerator
        traff_gen = TrafficGenerator(proj_dir, silent)

        vehicles = None

        if self.fcs != "":
            traff_gen.FCSFromArgs(self.fcs)
            if not silent: print(Lang.INFO_REGEN_FCS)

        if self.scs != "":
            traff_gen.SCSFromArgs(self.scs)
            if not silent: print(Lang.INFO_REGEN_SCS)
        
        if self.gs != "":
            traff_gen.GSFromArgs(self.gs)
            if not silent: print(Lang.INFO_REGEN_GS)

        if self.veh != "":
            vehicles = traff_gen.VTripsFromArgs(self.veh)
            if not silent: print(Lang.INFO_REGEN_VEH)

        return vehicles


class PlotCommand:
    def __init__(self, command: List[str]):
        self.command = command
    
    @staticmethod
    def from_file(fname:str):
        with open(fname, "r", encoding="utf-8") as f:
            lines = f.readlines()
        commands = [line.strip() for line in lines if line.strip() != "" and not line.strip().startswith("#")]
        return PlotCommand(commands)
    
    def execute(self):
        from .plot import AdvancedPlot
        plotter = AdvancedPlot()
        for cmd in self.command:
            plotter.configure(cmd)


@dataclass
class AltCommand:
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    traffic_step: Optional[int] = None
    scs_slots: Optional[int] = None
    fcs_slots: Optional[int] = None
    gs_slots: Optional[int] = None

    def apply(self, sim_inst: V2SimInstance):
        if self.start_time is not None:
            sim_inst.core._st = self.start_time
        if self.end_time is not None:
            sim_inst.core._et = self.end_time
        if self.traffic_step is not None:
            sim_inst.core._step = self.traffic_step
        if self.scs_slots is not None:
            for s in sim_inst.core.scs:
                s._slots = self.scs_slots
        if self.fcs_slots is not None:
            for f in sim_inst.core.fcs:
                f._slots = self.fcs_slots
        if self.gs_slots is not None:
            for g in sim_inst.core.gs:
                g._slots = self.gs_slots


def get_sim_params(args:Union[str, ArgChecker], check_illegal:bool = True) -> Dict[str, Any]:
    '''
    Get simulation parameters used by the simulate function
        args: Command line parameters or ArgChecker instance
        check_illegal: Whether to check illegal parameters, default is True
    '''
    if isinstance(args, str):
        args = ArgChecker(args, force_parametric=["plot", "gen-veh", "gen-fcs", "gen-scs"])
    
    # Generation commands
    gen_cmd = GenerationCommand(
        fcs = args.pop_str("gen-fcs", ""),
        scs = args.pop_str("gen-scs", ""),
        gs = args.pop_str("gen-gs", ""),
        veh = args.pop_str("gen-veh", ""),
    )
    if gen_cmd.all_empty():
        gen_cmd = None

    # Plot commands
    plot_script = args.pop_str("plot-script", "")
    if plot_script != "":
        plot_cmd = PlotCommand.from_file(plot_script)
    else:
        plot_cmd = None
    
    # Time
    start_time = args.pop_int("b", 0)
    step_len = args.pop_int("l", 10)
    end_time = args.pop_int("e", 172800)
    time_conf = TimeConfig(start_time, step_len, end_time)
    break_at = args.pop_int("break-at", -1)
    if break_at < 0: break_at = end_time
    assert start_time >= 0 and step_len > 0 and end_time >= start_time and \
        break_at >= start_time, "Time options: 0 <= start < break_at <= end, step > 0"
    
    # Load state options
    state_opt = LoadStateOption.Skip
    initial_state = args.pop_str("initial-state", "")
    if initial_state == "":
        initial_state = None
    else:
        state_opt = LoadStateOption.FromGiven
    if args.pop_bool("load-last-state"):
        assert state_opt == LoadStateOption.Skip, "Cannot use load-case-state with other state loading options."
        state_opt = LoadStateOption.FromLastResult
    if args.pop_bool("load-case-state"):
        assert state_opt == LoadStateOption.Skip, "Cannot use load-case-state with other state loading options."
        state_opt = LoadStateOption.FromCase
    
    # Save state options
    save_opt = 0
    if args.pop_bool("save-on-abort"):
        save_opt |= SaveStateOptions.OnAbort.value
    if args.pop_bool("save-on-finish"):
        save_opt |= SaveStateOptions.OnFinish.value
    save_opt = SaveStateOptions(save_opt)

    # Directories
    proj_dir = args.pop_str("d", "") or args.pop_str("dir", "") or args.pop_str("proj-dir")
    out_dir = args.pop_str("o", "") or args.pop_str("out", "") or args.pop_str("out-dir", "")
    if out_dir == "": out_dir = None

    # Plugins
    no_plgs = (args.pop_str("no-plg", "") or args.pop_str("disable-plugins", "")).split(",")
    if len(no_plgs) == 1 and no_plgs[0] == "": no_plgs = None

    # Logging items
    logs = (args.pop_str("log", "") or args.pop_str("logging-items", "")).split(",")
    if len(logs) == 1 and logs[0] == "": logs = None

    # Common config
    ralgo = args.pop_str("route-algo", "astar")
    gasoline_price = args.pop_float("gasoline-price", 5.0)
    vscfg = CommonConfig(
        routing_algorithm = ralgo,
        gasoline_price = ConstFunc(gasoline_price),
    )

    # SUMO or UXsim Config
    config = None
    uxsim_show = args.pop_bool("uxsim-show-info")
    uxsim_rand = args.pop_bool("uxsim-randomize")
    uxsim_nopara = args.pop_bool("uxsim-no-parallel")
    sumo_ignd = args.pop_bool("sumo-ignore-driving")
    sumo_raise = args.pop_bool("sumo-raise-routing-error")

    if uxsim_show or uxsim_nopara or uxsim_rand:
        from .sim import UXsimConfig
        config = UXsimConfig(uxsim_show, uxsim_rand, uxsim_nopara)
    
    if sumo_ignd or sumo_raise:
        assert config is None, "Cannot use both SUMO and UXsim configurations."
        from .sim import SUMOConfig
        config = SUMOConfig(sumo_ignd, not sumo_raise)
    

    if isinstance(args, ArgChecker):
        kwargs = {
            "proj_dir":             proj_dir,
            "time":                 time_conf,
            "out_dir":              out_dir,
            "seed":                 args.pop_int("seed", 0),
            "silent":               args.pop_bool("silent"),
            "vscfg":                vscfg,
            "config":               config,
            "disabled_plugins":     no_plgs,
            "logging_items":        logs,
            "state_option":         state_opt,
            "state_dir":            initial_state,
            "save_option":          save_opt,
            "gen_cmds":             gen_cmd,
            "plot_cmd":             plot_cmd,
            "copy_proj_to_out":     args.pop_bool("copy-proj-to-out"),
            "copy_state_to_proj":   args.pop_bool("copy-state-to-proj"),
        }
    if check_illegal and len(args) > 0:
        for key in args.keys(): raise ValueError(Lang.ERROR_ILLEGAL_CMD.format(key))
    return kwargs


def simulate_single(
    proj_dir:str, time:TimeConfig, break_at:Optional[int] = None, out_dir: Optional[str] = None, seed = 0, silent:bool = False, 
    vb = None, vscfg:Optional[CommonConfig] = None, config: Union[None, SUMOConfig, UXsimConfig] = None, 
    disabled_plugins:Optional[List[str]] = None, logging_items:Optional[List[str]] = None,
    state_option: LoadStateOption = LoadStateOption.Skip, state_dir:Optional[str] = None, 
    save_option: SaveStateOptions = SaveStateOptions.Skip, client_options: Optional[ClientOptions] = None, 
    gen_cmds:Optional[GenerationCommand] = None, plot_cmd:Optional[PlotCommand] = None,
    copy_proj_to_out:bool = False, copy_state_to_proj:bool = False, alt_cmds:Optional[AltCommand] = None,
):
    # Generate traffic components if needed
    if gen_cmds is not None:
        gen_cmds.generate(proj_dir, silent)
    
    # Run simulation
    inst = V2SimInstance.from_project(
        proj_dir, time, break_at, out_dir, seed, silent, vb, vscfg, config, 
        disabled_plugins, logging_items, state_option, state_dir, save_option, client_options
    )

    # Set alternative commands if provided
    if alt_cmds is not None:
        assert state_option == LoadStateOption.Skip, Lang.ALT_COMMAND_NOT_SUPPORTED
        alt_cmds.apply(inst)

    ok = inst.simulate()[0]
    out_dir = inst.result_dir  # Get the actual output directory used
    
    if not ok:
        # Simulation failed, do not proceed further
        return False
    
    # Plot results if needed
    if plot_cmd: plot_cmd.execute()
    
    # Copy project files to results directory if needed
    if copy_proj_to_out:
        proj_p = Path(proj_dir).resolve()
        out_p = Path(out_dir).resolve()

        # Avoid copying if the output directory is inside the project directory
        if not (proj_p == out_p or proj_p in out_p.parents):
            import shutil
            shutil.copytree(proj_p, out_p / proj_p.name, dirs_exist_ok=True)
            if not silent: print(Lang.CASE_FILE_COPIED)
        else:
            if not silent: print(Lang.WARN_COPY_SKIPPED)
    
    # Copy saved state back to project directory if needed
    if copy_state_to_proj:
        pres_p = Path(out_dir) / SAVED_STATE_FOLDER
        proj_p = Path(proj_dir).resolve()

        if pres_p.exists() and pres_p.is_dir():
            import shutil
            shutil.copytree(pres_p, proj_p / SAVED_STATE_FOLDER, dirs_exist_ok=True)
            if not silent: print(Lang.SAVED_STATE_COPIED)
    
    return True

__all__ = ["get_internal_components", "get_sim_params", "simulate_single", "GenerationCommand", "PlotCommand", "AltCommand"]