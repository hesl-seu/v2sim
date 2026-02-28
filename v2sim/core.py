import dill as pickle
import time, sys, gzip, os, threading
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
from feasytools import time2str
from pathlib import Path
from multiprocessing import Queue
from .sim import CaseData, CaseType, TimeConfig
from .plugins import *
from .stats import *
from .sim import *
from .locale import Lang
from .utils import *


PLUGINS_FILE = "plugins.gz"
RESULTS_FOLDER = "results"
TRIP_EVENT_LOG = "cproc.clog"
SIM_INFO_LOG = "cproc.log"
PLUGINS_DIR = CONFIG_DIR / "plugins"


def load_external_components(
    external_plugin_dir: Union[str, Path, None] = None,
    plugin_pool: Optional[PluginPool] = None, sta_pool: Optional[StaPool] = None
):
    """
    Load external components from the specified directory into the plugin and statistical item pools.
        external_plugin_dir: Directory containing external components. If None, use the default plugins directory.
        plugin_pool: Plugin pool to register loaded plugins.
        sta_pool: Statistical item pool to register loaded statistical items.
    Returns:
        A tuple containing two dictionaries:
            - The first dictionary maps module names to their loaded plugin exports.
            - The second dictionary maps module names to their loaded statistical item exports.
    """
    plg_ret:Dict[str, PluginExports] = {}
    sta_ret:Dict[str, StaExports] = {}
    if external_plugin_dir is None:
        exp = PLUGINS_DIR
        if not exp.exists():
            exp.mkdir(parents=True, exist_ok=True)
    elif isinstance(external_plugin_dir, str):
        exp = Path(external_plugin_dir).absolute()
    else:
        exp = external_plugin_dir.absolute()
    if not (exp.exists() and exp.is_dir()):
        return plg_ret, sta_ret
    sys.path.append(str(exp))
    for module_file in exp.iterdir():
        if (not module_file.is_file() or module_file.name.startswith("_")): continue
        if module_file.suffix == ".link":
            # Read the actual module path from the .link file
            with open(module_file, "r", encoding="utf-8") as f:
                linked_path = f.read().strip()
            module_file = Path(linked_path)
            if (not module_file.is_file()
                or module_file.name.startswith("_") 
                or module_file.suffix != ".py"): continue
            sys.path.append(str(module_file.parent))
        elif module_file.suffix != ".py":
            continue
        module_name = module_file.stem
        import importlib
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(Lang.WARN_EXT_LOAD_FAILED.format(module_name, e))
            module = None
        if hasattr(module, "plugin_exports"):
            try:
                plg_exports = getattr(module, "plugin_exports")
                if plugin_pool is not None: plugin_pool._Register(*plg_exports)
                plg_ret[module_name] = plg_exports
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_PLUGIN.format(module_name, e))
        if hasattr(module, "sta_exports"):
            try:
                sta_exports = getattr(module, "sta_exports")
                if sta_pool is not None: sta_pool.Register(*sta_exports)
                sta_ret[module_name] = sta_exports
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_STA.format(module_name, e))
    return plg_ret, sta_ret


def create_pools():
    from v2sim.plugins import PluginPool
    from v2sim.stats import StaPool
    plg_pool = PluginPool()
    sta_pool = StaPool()
    load_external_components(None, plg_pool, sta_pool)
    return plg_pool, sta_pool


def find_latest_results_folder(parent_folder:str):
    parent_path = Path(parent_folder)
    
    if not parent_path.exists() or not parent_path.is_dir():
        return None
    
    results_folders = [
        child for child in parent_path.iterdir()
        if (child.is_dir() and 
            RESULTS_FOLDER in child.name.lower() and 
            (child / TRIP_EVENT_LOG).exists())
    ]
    
    if not results_folders:
        return None
    
    return str(max(results_folders, key=lambda x: x.stat().st_mtime))


def check_output(proj_dir:Path, out_dir:Optional[str] = None):
    # Determine result folder
    pout = proj_dir / RESULTS_FOLDER if out_dir is None else Path(out_dir)
    pout = pout.resolve()

    # If there is an existing saved state, change the result folder  
    if pout.is_dir() and (pout / TRIP_EVENT_LOG).exists():
        j = 0
        while True:
            j += 1; new_path = f"{str(pout)}_{j}"
            if not os.path.exists(new_path): break
        pout = Path(new_path)
    pout.mkdir(parents=True, exist_ok=True)
    return pout


def create_output_directory(
    proj_dir: Path, out_dir: Optional[str] = None,
):
    # Check output directory
    pout = check_output(proj_dir, out_dir)

    # Create TripLogger
    tlog = TripLogger(pout / TRIP_EVENT_LOG)

    return pout, tlog


def _create_plg_and_stats(plgfile:Optional[str], state_dir:Optional[str], pout:Path, inst:TrafficInst, logging_items:Optional[List[str]], disabled_plugins:Optional[List[str]]):
        plg_pool, sta_pool = create_pools()

        # Enable plugins
        if state_dir is not None:
            plugin_state_file = Path(state_dir) / PLUGINS_FILE
            with gzip.open(plugin_state_file, "rb") as f:
                d = pickle.load(f)
            assert isinstance(d, dict) and "obj" in d and "version" in d and "pickler" in d, Lang.INVALID_PLUGIN_STATES.format(plugin_state_file)
            plugin_state = d["obj"]
            assert isinstance(plugin_state, dict), Lang.INVALID_PLUGIN_STATES.format(plugin_state_file)
            assert CheckPyVersion(d["version"]), Lang.PY_VERSION_MISMATCH_PLG.format(d["version"], PyVersion())
            assert d["pickler"] == pickle.__name__, Lang.PICKLER_MISMATCH_PLG.format(d["pickler"], pickle.__name__)
        else:
            plugin_state = None

        plgman = PluginMan(plgfile, pout, inst, plg_pool, disabled_plugins, plugin_state)

        # Create a data logger
        if logging_items is None: logging_items = ["fcs", "scs", "gs"]
        stats = StaWriter(pout, inst, plgman.GetPlugins(), sta_pool, logging_items)

        return plgman, stats


def _create_inst(case_data:CaseData, state_dir:Optional[str], tlogger:TripLogger, seed:int, 
        silent:bool, vscfg:Optional[CommonConfig] = None, config: Union[None, SUMOConfig, UXsimConfig] = None):
    if vscfg is None: vscfg = CommonConfig()
    if case_data.case_type == CaseType.SUMO:
        from .sim.sumo import TrafficSUMO
        if config is None: config = SUMOConfig()
        assert isinstance(config, SUMOConfig), "Invalid config"
        if state_dir is not None:
            # Load SUMO project files from saved state
            inst = TrafficSUMO.load(case_data, state_dir, tlogger, vscfg, config, seed, silent)
        else:
            inst = TrafficSUMO.create(case_data, tlogger, vscfg, config, seed, silent)
        return inst, True
    else:
        from .sim.ux import TrafficUX
        if config is None: config = UXsimConfig()
        assert isinstance(config, UXsimConfig), "Invalid config"
        if state_dir is not None:
            # Load UXSim project files from saved state
            # Note: in UXSim mode, we load directly from the state directory, here is unecessary but kept for consistency
            inst = TrafficUX.load(state_dir, tlogger)
        else:
            inst = TrafficUX.create(case_data, tlogger, vscfg, config, seed, silent)
        return inst, not inst.show_uxsim_info

class LoadStateOption(Enum):
    Skip = 0
    FromGiven = 1
    FromCase = 2
    FromLastResult = 3


def check_state_dir(state_option:LoadStateOption, state_dir:Optional[str], pproj:Path):
    if state_option == LoadStateOption.Skip:
        state_dir = None
    elif state_option == LoadStateOption.FromGiven:
        assert state_dir is not None and Path(state_dir).is_dir(), "Given state directory does not exist"
    elif state_option == LoadStateOption.FromLastResult:
        state_dir = find_latest_results_folder(str(pproj))
        if state_dir is None:
            raise FileNotFoundError("Cannot find a result folder with saved state")
    else: # FromCase
        psd = pproj / SAVED_STATE_FOLDER
        assert psd.is_dir(), "No saved state folder in the project directory"
        state_dir = str(psd)
    return state_dir


class SaveStateOptions(Enum):
    Skip = 0
    OnAbort = 1
    OnFinish = 2
    Both = 3 # OnAbort | OnFinish


@dataclass
class MsgPack:
    clntID:int
    cmd:str
    obj:Any = None


@dataclass
class ClientOptions:
    clientID: int = -1
    hostQ: Optional[Queue] = None

    def __post_init__(self):
        if self.clientID != -1:
            assert self.hostQ is not None, Lang.ERROR_CLIENT_ID_NOT_SPECIFIED


class V2SimInstance:
    def __mpsend(self, con:str, obj:Any = None):
        if self.__mpQ:
            try:
                self.__mpQ.put_nowait(MsgPack(self.__clntID, con, obj))
            except:
                print(Lang.WARN_SIM_COMM_FAILED)
    
    def __print(self, con:str="", *, file:Any = sys.stdout, end="\n"):
        if not self.__silent: print(con, file=file, end=end)

    def __init__(
        self, out_dir:Path, traffic: TrafficInst, plugins:PluginMan, stats:StaWriter,              
        break_at:Optional[int] = None, client_options: Optional[ClientOptions] = None,
        save:SaveStateOptions = SaveStateOptions.Skip, vb = None, silent: bool = False,
        show_progress: bool = True,
    ):
        # Client options
        if client_options is None:
            client_options = ClientOptions()
        self.__mpQ = client_options.hostQ
        self.__clntID = client_options.clientID
        if self.__mpQ:
            assert client_options.clientID != -1, Lang.ERROR_CLIENT_ID_NOT_SPECIFIED
            self.__silent = True
            self.__vb = None

        # Simulation parameters
        self.__inst = traffic
        self.__plgman = plugins
        self.__sta = stats
        self.__silent = silent
        self.__vb = vb
        self.__outdir = str(out_dir)
        self.__pout = out_dir
        self.__working_flag = False
        self.__break_at = self.__inst._et if break_at is None else break_at
        assert self.__break_at > self.__inst._st, "Break time must be larger than start time"
        assert self.__break_at <= self.__inst._et, "Break time must be less than or equal to end time"
        self.__actual_start_time = self.__inst._st
        self.__sim_dur = self.__break_at - self.__actual_start_time
        self.__show_prog = show_progress
        self.save_options = save
        self.__progress = 0.0
        self.__progress_lock = threading.Lock()

        # Create simulation info log file
        self.__out = open(out_dir / SIM_INFO_LOG, "w", encoding="utf-8")

        # Find the power grid plugin
        self.__gridplg = None
        for plugname, plugin in self.__plgman.GetPlugins().items():
            if isinstance(plugin, PluginPDN):
                self.__gridplg = plugin
            self.__print(Lang.INFO_PLG.format(plugname, plugin.Description))
        
    @staticmethod
    def from_project(
        proj_dir:str, time:TimeConfig, break_at:Optional[int] = None, out_dir: Optional[str] = None, 
        seed = 0, silent:bool = False, vb = None, vscfg:Union[None, CommonConfig] = None,
        config: Union[None, SUMOConfig, UXsimConfig] = None, 
        disabled_plugins:Optional[List[str]] = None, logging_items:Optional[List[str]] = None,
        state_option: LoadStateOption = LoadStateOption.Skip, state_dir:Optional[str] = None, 
        save_option: SaveStateOptions = SaveStateOptions.Skip, client_options: Optional[ClientOptions] = None
    ):
        show_prog = True
        proj = DetectFiles(proj_dir)
        if proj.py:
            with open(proj.py, "r", encoding="utf-8") as f:
                code = f.read()
                exec(code)
        
        pproj = Path(proj_dir)
        pout, tlogger = create_output_directory(pproj, out_dir)

        state_dir = check_state_dir(state_option, state_dir, pproj)     

        if proj.sumo is None and state_dir is not None:
            # Load UXSim project files from saved state
            from .sim.ux import TrafficUX
            inst = TrafficUX.load(state_dir, tlogger)
            show_prog = not inst.show_uxsim_info
            files = DetectFiles(pproj)
            plgfile = files.plg
        else:
            # Load case data from project files
            case_data = CaseData.parse(proj_dir, time, silent)  
            inst, show_prog = _create_inst(case_data, state_dir, tlogger, seed, silent, vscfg, config)
            plgfile = case_data.files.plg

        plgman, stats = _create_plg_and_stats(plgfile, state_dir, pout, inst, logging_items, disabled_plugins)

        return V2SimInstance(pout, inst, plgman, stats, break_at, client_options, save_option, vb, silent, show_prog)

    @staticmethod
    def from_case_data(
        case_data:CaseData, pout:Path, break_at:Optional[int] = None,
        seed = 0, silent:bool = False, vb = None, vscfg:Union[None, CommonConfig] = None,
        config: Union[None, SUMOConfig, UXsimConfig] = None, 
        disabled_plugins:Optional[List[str]] = None, logging_items:Optional[List[str]] = None,
        state_option: LoadStateOption = LoadStateOption.Skip, state_dir:Optional[str] = None, 
        save_option: SaveStateOptions = SaveStateOptions.Skip, client_options: Optional[ClientOptions] = None
    ):
        pout.mkdir(parents=True, exist_ok=True)
        tlogger = TripLogger(pout / TRIP_EVENT_LOG)
        state_dir = check_state_dir(state_option, state_dir, Path(case_data.case_dir))
        inst, show_prog = _create_inst(case_data, state_dir, tlogger, seed, silent, vscfg, config)
        plgfile = case_data.files.plg
        plgman, stats = _create_plg_and_stats(plgfile, state_dir, pout, inst, logging_items, disabled_plugins)

        return V2SimInstance(pout, inst, plgman, stats, break_at, client_options, save_option, vb, silent, show_prog)
 
    @property
    def result_dir(self):
        '''Folder of results'''
        return self.__outdir
    
    @property
    def ctime(self):
        '''Current simulation time, in second'''
        return self.__inst._ct
    
    @property
    def step_length(self):
        '''Step length, in second'''
        return self.__inst._step
    
    @property
    def btime(self):
        '''Simulation start time, in second'''
        return self.__inst._st
    
    @property
    def etime(self):
        '''Simulation end time, in second'''
        return self.__inst._et
    
    @property
    def clientID(self):
        '''Client ID in multiprocessing simulation'''
        return self.__clntID
    
    @property
    def silent(self):
        '''Indicate whether disable output'''
        return self.__silent
    
    @property
    def plugins(self):
        '''Plugins in the project'''
        return self.__plgman
    
    @property
    def statistics(self):
        '''Statistics in the project'''
        return self.__sta
    
    @property
    def core(self):
        '''Simulation core'''
        return self.__inst
    
    @property
    def fcs(self):
        '''List of FCSs'''
        return self.__inst.fcs
    
    @property
    def scs(self):
        '''List of SCSs'''
        return self.__inst.scs
    
    @property
    def gs(self):
        '''List of GSs'''
        return self.__inst.gs
    
    @property
    def vehicles(self):
        '''Dict of vehicles'''
        return self.__inst.vehicles
    
    @property
    def edges(self):
        '''List of the edges'''
        return self.__inst.edges
    
    @property
    def edge_names(self):
        '''Name list of the edges'''
        return self.__inst.get_edge_names()
    
    @property
    def veh_count(self):
        '''Number of vehicles'''
        return len(self.__inst.vehicles)
    
    @property
    def is_working(self):
        '''Determine whether the simulation has started'''
        return self.__working_flag
    
    @property
    def pdn(self) -> Optional[PluginPDN]:
        '''Power grid plugin'''
        return self.__gridplg

    @property
    def trips_logger(self) -> TripsLogger:
        '''Trip logger'''
        return self.__inst.trips_logger
    
    @property
    def uxsim(self):
        '''Traffic simulator object'''
        from .sim.ux import TrafficUX
        assert isinstance(self.__inst, TrafficUX), "Only available in UXsim mode"
        return self.__inst.W
    
    def send_to_host(self, command:str, obj:Any = None):
        '''Send message to host process'''
        assert self.__mpQ is not None, Lang.NO_HOST_EXISTS
        self.__mpsend(command, obj)
    
    def start(self):
        '''
        Start simulation.
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        '''
        with self.__progress_lock:
            self.__progress = 0.0
        self.__working_flag = True
        self.__inst.simulation_start()
        self.__plgman.PreSimulationAll()
    
    def step(self) -> int:
        '''
        Simulation steps. 
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        Return the simulation time after this step.
        '''
        t = self.__inst.current_time
        self.__plgman.PreStepAll(t)
        self.__inst.simulation_step(self.__inst._step)
        self.__plgman.PostStepAll(t)
        self.__sta.Log(t)
        return self.__inst.current_time
    
    def step_until(self, t:int) -> int:
        '''
        Simulation steps till time t. 
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        Return the simulation time after stepping.
        '''
        while self.__inst.current_time < t:
            self.step()
        return self.__inst.current_time
    
    def _save_obj(self):
        """Save plugin states. Advanced users only, at your own risk!"""
        return pickle.dumps({
            "obj": self.__plgman.SaveStates(),
            "version": PyVersion(),
            "pickler": pickle.__name__
        })
    
    def save(self, folder:Union[str, Path]):
        '''Save the current state of the simulation'''
        p = Path(folder) if isinstance(folder, str) else folder
        self.__inst.save(p)
        with gzip.open(p / PLUGINS_FILE, "wb") as f:
            pickle.dump({
                "obj": self.__plgman.SaveStates(),
                "version": PyVersion(),
                "pickler": pickle.__name__
            }, f)
    
    def stop(self, save_state_to:Union[str, Path] = ""):
        '''
        Stop simulation.
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        '''
        if save_state_to != "":
            self.save(save_state_to)
        self.__plgman.PostSimulationAll()
        self.__inst.simulation_stop()
        self.__sta.close()
        self.__out.close()
        self.__working_flag = False
    
    def simulate(self, use_signal:bool = True):
        '''
        Main simulation function
            If you use this function, do not use start - step - stop paradigm
        Returns:
            (Whether the simulation ends normally, TrafficInst instance, StaWriter instance)
        '''
        self.__stopsig = False

        def eh(signum, frame):
            self.__print()
            self.__print(Lang.MAIN_SIGINT)
            self.__mpsend("exit")
            self.__stopsig = True
        
        if use_signal and self.__vb is None and self.__clntID == -1:
            import signal
            signal.signal(signal.SIGINT, eh)
        
        self.__st_time = time.time()
        self.__last_print_time = 0
        self.__last_mp_time = 0
        self.__mpsend("sim:start")
        self.start()

        while self.__inst.current_time < self.__break_at:
            self.step()
            if self.__stopsig:
                if self.save_options.value & SaveStateOptions.OnAbort.value:
                    p = self.__pout / SAVED_STATE_FOLDER
                    p.mkdir(parents=True, exist_ok=True)
                    self.save(p)
                break
            ctime = time.time()
            if ctime - self.__last_print_time > 1 or self.__inst.current_time >= self.__break_at:
                progress = 100 * (self.__inst.current_time - self.__actual_start_time) / self.__sim_dur
                with self.__progress_lock:
                    self.__progress = progress
                if self.__show_prog:
                    if self.__vb is not None:
                        counter = [0, 0, 0, 0, 0]
                        for veh in self.__inst._vehs.values():
                            counter[veh._sta] += 1
                        upd:Dict[str, Any] = {
                            "Time": time2str(self.__inst.current_time),
                            "Driving": counter[VehStatus.Driving],
                            "Pending": counter[VehStatus.Pending],
                            "Charging": counter[VehStatus.Charging],
                            "Parking": counter[VehStatus.Parking],
                            "Depleted": counter[VehStatus.Depleted],
                        }
                        upd.update(self.__vis_str())
                        self.__vb.set_val(upd)
                    else:
                        eta = (
                            time2str((ctime - self.__st_time) * (100 - progress) / progress)
                            if ctime - self.__st_time > 3
                            else "N/A"
                        )
                        self.__print("\r",end="")
                        self.__print(
                            Lang.MAIN_SIM_PROG.format(
                                round(progress, 2), 
                                self.__inst.current_time, 
                                self.__break_at, 
                                time2str(ctime - self.__st_time), 
                                eta
                            ),
                            end="",
                        )
                if ctime - self.__last_mp_time > 5:
                    # Communicate with the main process every 5 seconds in multi-process mode
                    self.__mpsend(f"sim:{progress:.2f}")
                    self.__last_mp_time = ctime
                self.__last_print_time = ctime
        
        self.__print()
        dur = time.time() - self.__st_time
        self.__out.write(Lang.MAIN_SIM_DONE.format(time2str(dur)))
        self.__out.close()
        self.__print(Lang.MAIN_SIM_DONE.format(time2str(dur)))
        self.stop(self.__pout / SAVED_STATE_FOLDER 
            if self.save_options.value & SaveStateOptions.OnFinish.value else "")
        self.__mpsend("sim:done")
        return not self.__stopsig, self.__inst, self.__sta

    def __vis_str(self):
        for fcs in self.__inst.fcs:
            yield fcs._name, f"{fcs.veh_count()} cars, {fcs.Pc_kW:.1f} kW"
    
    def _istep(self):
        if self.__vb is not None:
            counter = [0, 0, 0, 0, 0]
            for veh in self.__inst._vehs.values():
                counter[veh._sta] += 1
            upd:Dict[str, Any] = {
                "Time": time2str(self.__inst.current_time),
                "Driving": counter[VehStatus.Driving],
                "Pending": counter[VehStatus.Pending],
                "Charging": counter[VehStatus.Charging],
                "Parking": counter[VehStatus.Parking],
                "Depleted": counter[VehStatus.Depleted],
            }
            upd.update(self.__vis_str())
            self.__vb.set_val(upd)
        else:
            ctime = time.time()
            if ctime - self.__last_print_time > 1 or self.__inst.current_time >= self.__break_at:
                # Progress in command line updates once per second
                progress = 100 * (self.__inst.current_time - self.__actual_start_time) / self.__sim_dur
                eta = (
                    time2str((ctime - self.__st_time) * (100 - progress) / progress)
                    if ctime - self.__st_time > 3
                    else "N/A"
                )
                self.__print("\r",end="")
                self.__print(
                    Lang.MAIN_SIM_PROG.format(
                        round(progress,2), 
                        self.__inst.current_time, 
                        self.__break_at, 
                        time2str(ctime-self.__st_time), 
                        eta
                    ),
                    end="",
                )
                if ctime - self.__last_mp_time > 5:
                    # Communicate with the main process every 5 seconds in multi-process mode
                    self.__mpsend(f"sim:{progress:.2f}")
                    self.__last_mp_time = ctime
                self.__last_print_time = ctime
    
    def __del__(self):
        if hasattr(self, "_V2SimInstance__out") and hasattr(self.__out, "closed") and not self.__out.closed:
            self.__out.close()
    
    @property
    def progress(self) -> float:
        '''Simulation progress in percentage'''
        with self.__progress_lock:
            return self.__progress


__all__ = [
    "V2SimInstance",
    "MsgPack",
    "PLUGINS_FILE",
    "RESULTS_FOLDER",
    "TRIP_EVENT_LOG",
    "SIM_INFO_LOG",
    "PLUGINS_DIR",
    "load_external_components",
    "create_pools",
    "find_latest_results_folder",
    "check_output",
    "create_output_directory",
    "LoadStateOption",
    "SaveStateOptions",
    "ClientOptions",
]