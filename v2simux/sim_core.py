import gzip
import dill as pickle
import importlib, os, queue, shutil, signal, time, sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union
from feasytools import ArgChecker, time2str
from pathlib import Path
from .plotkit import AdvancedPlot
from .plugins import *
from .statistics import *
from .traffic import *
from .locale import Lang
from .trafficgen import TrafficGenerator
import inspect

PLUGINS_FILE = "plugins.gz"
RESULTS_FOLDER = "results"
TRIP_EVENT_LOG = "cproc.clog"
SIM_INFO_LOG = "cproc.log"


@dataclass
class MsgPack:
    clntID:int
    cmd:str
    obj:Any = None


def load_external_components(
    external_plugin_dir: str, plugin_pool: PluginPool, sta_pool: StaPool
):
    exp = Path(os.getcwd()) / Path(external_plugin_dir)
    if not (exp.exists() and exp.is_dir()):
        return
    for module_file in exp.iterdir():
        if not (
            module_file.is_file()
            and module_file.suffix == ".py"
            and not module_file.name.startswith("_")
        ):
            continue
        module_name = module_file.stem
        try:
            module = importlib.import_module(f"{external_plugin_dir}.{module_name}")
        except Exception as e:
            print(Lang.WARN_EXT_LOAD_FAILED.format(module_name, e))
            module = None
        if hasattr(module, "plugin_exports"):
            try:
                plugin_pool._Register(*module.plugin_exports) # type: ignore
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_PLUGIN.format(module_name, e))
        if hasattr(module, "sta_exports"):
            try:
                sta_pool.Register(*module.sta_exports) # type: ignore
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_STA.format(module_name, e))
                
def get_sim_params(
        args:Union[str, ArgChecker],
        plg_pool:PluginPool,
        sta_pool:StaPool,
        check_illegal:bool = True
    )->Dict[str,Any]:
    '''
    Get simulation parameters used by the simulate function
        args: Command line parameters or ArgChecker instance
        plg_pool: Plugin pool
        sta_pool: Statistical item pool
        check_illegal: Whether to check illegal parameters, default is True
    '''
    if isinstance(args, str):
        args = ArgChecker(args, force_parametric=["plot", "gen-veh", "gen-fcs", "gen-scs"])
    if isinstance(args, ArgChecker):
        kwargs = {
            "cfgdir":               args.pop_str("d"),
            "outdir":               args.pop_str("o", ""),
            "outdir_direct":        args.pop_str("od", ""),
            "traffic_step":         args.pop_int("l", 10),
            "start_time":           args.pop_int("b", 0),
            "break_at":             args.pop_int("break-at", -1),
            "end_time":             args.pop_int("e", 172800),
            "no_plg":               args.pop_str("no-plg", ""),
            "log":                  args.pop_str("log", "fcs,scs"),
            "seed":                 args.pop_int("seed", time.time_ns() % 65536),
            "copy":                 args.pop_bool("copy"),
            "gen_veh_command":      args.pop_str("gen-veh", ""),
            "gen_fcs_command":      args.pop_str("gen-fcs", ""),
            "gen_scs_command":      args.pop_str("gen-scs", ""),
            "plot_command":         args.pop_str("plot", ""),
            "initial_state":        args.pop_str("initial-state", ""),
            "load_last_state":      args.pop_bool("load-last-state"),
            "save_on_abort":        args.pop_bool("save-on-abort"),
            "save_on_finish":       args.pop_bool("save-on-finish"),
            "copy_state":           args.pop_bool("copy-state"),
            "route_algo":           args.pop_str("route-algo", "astar"),
            "show_uxsim_info":      args.pop_bool("show-uxsim-info"),
            "no_parallel":          args.pop_bool("no-parallel"),
            "plg_pool":             plg_pool,
            "sta_pool":             sta_pool,
        }
    if check_illegal and len(args) > 0:
        for key in args.keys():
            raise ValueError(Lang.ERROR_ILLEGAL_CMD.format(key))
    return kwargs

def _calc_output_folder(cfgdir: str, outdir: str, outdir_direct: str) -> Path:
    if outdir_direct != "":
        pres = Path(outdir_direct)
    else:
        if outdir == "":
            pres = Path(cfgdir) / RESULTS_FOLDER
        else:
            pres = Path(outdir) / Path(cfgdir).name
    return pres
class V2SimInstance:
    def __mpsend(self, con:str, obj:Any = None):
        if self.__mpQ:
            try:
                self.__mpQ.put_nowait(MsgPack(self.__clntID, con, obj))
            except:
                print(Lang.WARN_SIM_COMM_FAILED)
    
    def __print(self, con:str="", *, file:Any = sys.stdout, end="\n"):
        if not self.__silent:
            print(con, file=file, end=end)

    def __init__(
        self, 
        cfgdir: str,
        outdir: str = "",
        *,
        outdir_direct: str = "",
        plg_pool: Optional[PluginPool] = None,
        sta_pool: Optional[StaPool] = None,
        gen_veh_command:str = "", 
        gen_fcs_command:str = "", 
        gen_scs_command:str = "", 
        alt_command:Optional[Dict[str,str]] = None,
        plot_command:str = "",
        traffic_step: int = 10,      
        start_time: int = 0,        
        end_time: int = 172800,
        break_at: int = -1,
        no_plg: str = "",            
        log: str = "fcs, scs",               
        seed: int = 0,              
        copy: bool = False,
        vb = None,                
        silent: bool = False,           
        mpQ: Optional[queue.Queue] = None, 
        clntID: int = -1,
        initial_state: str = "",
        load_last_state: bool = False,
        save_on_abort: bool = False,
        save_on_finish: bool = False,
        copy_state: bool = False,
        route_algo: str = "astar",
        show_uxsim_info: bool = False,
        no_parallel: bool = False,
    ):
        '''
        Initialization
            cfgdir: Configuration folder
            outdir: Output folder. Actual results will be saved in a subfolder named by the configuration folder
            outdir_direct: Direct output folder
            plg_pool: Available plugin pool
            sta_pool: Available statistical item pool
            gen_veh_command: command to generate vehicle
            gen_fcs_command: Generate fast charging station command
            gen_scs_command: Generate slow charging station command
            plot_command: Plot command
            traffic_step: Simulation step
            start_time: Start time
            end_time: End time
            no_plg: Disabled plugins, separated by commas
            log: Data to be recorded, separated by commas
            seed: Randomization seed
            copy: Whether to copy the configuration file after the simulation ends
            vb: Whether to enable the visualization window, None means not enabled, when running this function in multiple processes, please set to None
            silent: Whether to silent mode, default is False, when running this function in multiple processes, please set to True
            mpQ: Queue for communication with the main process when running this function in multiple processes, set to None if not using multi-process function
            clntID: Identifier of this process when running this function in multiple processes, set to -1 if not using multi-process function
            initial_state: Folder of the initial state of the simulation
            load_last_state: Load the state in result dir if there is a state folder. This will override initial_state if there is a state folder.
            save_on_abort: Whether to save the state when Ctrl+C is pressed
            save_on_finish: Whether to save the state when the simulation ends
            copy_state: Whether to copy the state folder after the simulation ends or when Ctrl+C is pressed
            route_algo: Routing algorithm, can be dijkstra or astar
            show_uxsim_info: Whether to show the information of uxsim
            no_parallel: Disable parallel simulation even if possible
        '''

        if plg_pool is None: plg_pool = PluginPool()
        if sta_pool is None: sta_pool = StaPool()

        self.__mpQ = mpQ
        self.__silent = silent
        self.__vb = vb
        self.__clntID = clntID
        if self.__mpQ:
            assert clntID != -1, Lang.ERROR_CLIENT_ID_NOT_SPECIFIED
            self.__silent = True
            self.__vb = None

        # Check if the folder exists
        proj_dir = Path(cfgdir)
        if not proj_dir.exists() or not proj_dir.is_dir():
            raise FileNotFoundError(f"Invalid project directory :{cfgdir}")
        
        # Determine result folder       
        pres = _calc_output_folder(cfgdir, outdir, outdir_direct)
        self.__outdir_direct = str(pres)
        self.__outdir = str(pres.parent)

        # Check if there is a previous results   
        if pres.is_dir() and (pres / TRIP_EVENT_LOG).exists():
            tm = time.strftime("%Y%m%d_%H%M%S", time.localtime(pres.stat().st_mtime))
            tm2 = 0
            while True:
                tm2 += 1
                new_path = f"{str(pres)}_{tm}_{tm2}"
                if not os.path.exists(new_path):
                    break
            if (pres / SAVED_STATE_FOLDER).exists() and load_last_state:
                initial_state = str(Path(new_path) / SAVED_STATE_FOLDER)
            pres.rename(new_path)
        pres.mkdir(parents=True, exist_ok=True)
        self.__pres = pres

        # Create simulation info log file
        self.__out = open(str(pres / SIM_INFO_LOG), "w", encoding="utf-8")

        # Record all __init__ parameters to file
        frame = inspect.currentframe()
        assert frame is not None
        args, _, _, values = inspect.getargvalues(frame)
        self.__out.write("Parameters:\n")
        for arg in args:
            if arg in ('self', 'vb', 'mpQ') or 'pool' in arg:
                continue
            self.__out.write(f"  {arg}: {values[arg]}\n")

        if gen_veh_command != "" or gen_scs_command != "" or gen_fcs_command != "":
            traff_gen = TrafficGenerator(str(proj_dir), silent)
            if gen_fcs_command != "":
                traff_gen.FCSFromArgs(gen_fcs_command)
                self.__print(Lang.INFO_REGEN_FCS)
                self.__mpsend("fcs:done")
            if gen_scs_command != "":
                traff_gen.SCSFromArgs(gen_scs_command)
                self.__print(Lang.INFO_REGEN_SCS)
                self.__mpsend("scs:done")
            if gen_veh_command != "":
                vehicles = traff_gen.EVTripsFromArgs(gen_veh_command)
                self.__print(Lang.INFO_REGEN_VEH)
                self.__mpsend("veh:done")
        else:
            vehicles = None
        
        proj_cfg = DetectFiles(str(proj_dir))

        if proj_cfg.py:
            with open(proj_cfg.py,"r",encoding="utf-8") as f:
                code = f.read()
                exec(code)
        
        # Create a simulation instance        
        if initial_state != "":
            self.__inst = TrafficInst.load(initial_state, Path(self.__outdir_direct) / TRIP_EVENT_LOG)
            self.__inst.silent = silent
            proj_cfg.net = self.__inst.net_file
            self.__print(Lang.INFO_NET.format(proj_cfg.net))
            self.__fcs_file = proj_cfg.fcs = self.__inst.fcs_file
            self.__print(Lang.INFO_FCS.format(proj_cfg.fcs, len(self.__inst.FCSList)))
            self.__scs_file = proj_cfg.scs = self.__inst.scs_file
            self.__print(Lang.INFO_SCS.format(proj_cfg.scs, len(self.__inst.SCSList)))
            self.__veh_file = proj_cfg.veh = self.__inst.veh_file
            self.__print(Lang.INFO_TRIPS.format(proj_cfg.veh, len(self.__inst.vehicles)))
            self.__start_time = self.__inst.start_time
            self.__actual_start_time = self.__inst.current_time
            self.__end_time = self.__inst.end_time
            self.__break_at = break_at if break_at >= 0 else self.__end_time
            self.__sim_dur = self.__break_at - self.__actual_start_time
            self.__steplen = self.__inst.step_len
            self.__print(Lang.INFO_TIME.format(self.__start_time, self.__end_time, self.__break_at, self.__steplen))
            self.routing_algo = self.__inst.routing_algo
            self.show_uxsim_info = self.__inst.show_uxsim_info
        else:
            # Detect road network file
            if not proj_cfg.net:
                raise RuntimeError(Lang.ERROR_NET_FILE_NOT_SPECIFIED)
            else:
                rnet_file = proj_cfg.net
            self.__print(Lang.INFO_NET.format(rnet_file))
            
            # Check vehicles and trips
            if not proj_cfg.veh:
                raise FileNotFoundError(Lang.ERROR_TRIPS_FILE_NOT_FOUND)
            self.__veh_file = proj_cfg.veh
            if vehicles is None:
                vehicles = EVDict(self.__veh_file)
            self.__print(Lang.INFO_TRIPS.format(self.__veh_file, len(vehicles)))

            # Check FCS file
            if not proj_cfg.fcs:
                raise FileNotFoundError(Lang.ERROR_FCS_FILE_NOT_FOUND)
            self.__fcs_file = proj_cfg.fcs
            fcs_obj:CSList[FCS] = CSList(filePath = self.__fcs_file, csType = FCS)
            self.__print(Lang.INFO_FCS.format(self.__fcs_file, len(fcs_obj)))

            # Check SCS file
            if not proj_cfg.scs:
                raise FileNotFoundError(Lang.ERROR_SCS_FILE_NOT_FOUND)
            self.__scs_file = proj_cfg.scs
            scs_obj:CSList[SCS] = CSList(filePath = self.__scs_file, csType = SCS)
            self.__print(Lang.INFO_SCS.format(self.__scs_file, len(scs_obj)))

            # Check start and end time
            if start_time == -1 or end_time == -1:
                raise ValueError(Lang.ERROR_ST_ED_TIME_NOT_SPECIFIED)
            self.__start_time = start_time
            self.__actual_start_time = self.__start_time
            self.__end_time = end_time
            self.__break_at = break_at if break_at >= 0 else self.__end_time
            self.__sim_dur = self.__break_at - self.__actual_start_time
            self.__steplen = traffic_step
            self.__print(Lang.INFO_TIME.format(start_time, end_time, self.__break_at, traffic_step))

            self.routing_algo = route_algo
            self.show_uxsim_info = show_uxsim_info

            self.__inst = TrafficInst(
                rnet_file, start_time, traffic_step, 
                end_time, str(pres / TRIP_EVENT_LOG), seed,
                vehfile = self.__veh_file, veh_obj = vehicles,
                fcsfile = self.__fcs_file, fcs_obj = fcs_obj,
                scsfile = self.__scs_file, scs_obj = scs_obj,
                routing_algo = route_algo,
                show_uxsim_info = show_uxsim_info,
                no_parallel = no_parallel,
                silent = silent
            )

        # Enable plugins
        if initial_state != "":
            plugin_state_file = Path(initial_state) / PLUGINS_FILE
            with gzip.open(plugin_state_file, "rb") as f:
                d = pickle.load(f)
                assert isinstance(d, dict) and "obj" in d and "version" in d and "pickler" in d, "Invalid plugin state file."
                plugin_state = d["obj"]
                assert isinstance(plugin_state, dict), "Invalid plugin states."
                assert CheckPyVersion(d["version"]), "Incompatible Python version for plugin states: saved {}, current {}".format(d["version"], PyVersion())
                assert d["pickler"] == pickle.__name__, "Incompatible pickler for plugin states: saved {}, current {}".format(d["pickler"], pickle.__name__)
        else:
            plugin_state = None

        if proj_cfg.plg:
            self.__plg_file = proj_cfg.plg
            disabled_plugins = list(map(lambda x: x.strip().lower(), no_plg.split(",")))
            self.__plgman = PluginMan(self.__plg_file, pres, self.__inst, disabled_plugins, plg_pool, plugin_state)
        else:
            self.__plgman = PluginMan(None, pres, self.__inst, [], plg_pool, plugin_state)
        
        # Find the power grid plugin
        self.__gridplg = None
        for plugname, plugin in self.__plgman.GetPlugins().items():
            if isinstance(plugin, PluginPDN):
                self.__gridplg = plugin
            self.__print(Lang.INFO_PLG.format(plugname, plugin.Description))

        # Create a data logger
        log_item = log.strip().lower().split(",")
        if len(log_item) == 1 and log_item[0] == "": log_item = []
        self.__sta = StaWriter(pres, self.__inst, self.__plgman.GetPlugins(), sta_pool, log_item)

        self.__copy = copy
        self.__plot_cmd = plot_command
        self.__proj_cfg = proj_cfg
        self.__proj_dir = proj_dir
        self.__working_flag = False
        self.save_on_abort = save_on_abort
        self.save_on_finish = save_on_finish
        self.copy_state = copy_state

        if alt_command is not None:
            assert initial_state == "", "Cannot use alt_command when initial_state is specified."
            for k, v in alt_command.items():
                if k == "start_time":
                    self.__start_time = int(v)
                elif k == "end_time":
                    self.__end_time = int(v)
                elif k == "traffic_step":
                    self.__steplen = int(v)
                elif k == "scs_slots":
                    for s in scs_obj:
                        s._slots = int(v)
                elif k == "fcs_slots":
                    for f in fcs_obj:
                        f._slots = int(v)

    @property
    def project_dir(self):
        '''Folder of the project'''
        return self.__proj_dir
    
    @property
    def result_dir(self):
        '''Folder of results'''
        return self.__outdir
    
    @property
    def result_dir_direct(self):
        '''Direct output folder'''
        return self.__outdir_direct
    
    @property
    def plot_command(self):
        '''Command for post-simulation plotting'''
        return self.__plot_cmd
    
    @property
    def ctime(self):
        '''Current simulation time, in second'''
        return self.__inst.current_time
    
    @property
    def step_length(self):
        '''Step length, in second'''
        return self.__steplen
    
    @property
    def btime(self):
        '''Simulation start time, in second'''
        return self.__start_time
    
    @property
    def etime(self):
        '''Simulation end time, in second'''
        return self.__end_time
    
    @property
    def copy(self):
        '''Indicate whether copy the source after simulation'''
        return self.__copy
    
    @property
    def clientID(self):
        '''Client ID in multiprocessing simulation'''
        return self.__clntID
    
    @property
    def silent(self):
        '''Indicate whether disable output'''
        return self.__silent
    
    @property
    def files(self):
        '''Files in the project'''
        return self.__proj_cfg
    
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
        return self.__inst.FCSList
    
    @property
    def scs(self):
        '''List of SCSs'''
        return self.__inst.SCSList
    
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
    def traffic_simulator(self):
        '''Traffic simulator object'''
        return self.__inst.W
    
    def send_to_host(self, command:str, obj:Any = None):
        '''Send message to host process'''
        assert self.__mpQ is not None, "Not working in multiprocessing mode. No host exists."
        self.__mpsend(command, obj)
    
    def start(self):
        '''
        Start simulation.
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        '''
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
        self.__inst.simulation_step(self.__steplen)
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
    
    def save(self, folder:Union[str, Path]):
        '''Save the current state of the simulation'''
        # Save the traffic instance
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
            if self.copy_state:
                shutil.copytree(save_state_to, self.__proj_dir / SAVED_STATE_FOLDER, dirs_exist_ok=True)
        self.__plgman.PostSimulationAll()
        self.__inst.simulation_stop()
        self.__sta.close()
        self.__out.close()
        if self.__copy:
            shutil.copy(self.__veh_file, self.__pres / Path(self.__veh_file).name)
            shutil.copy(self.__fcs_file, self.__pres / Path(self.__fcs_file).name)
            shutil.copy(self.__scs_file, self.__pres / Path(self.__scs_file).name)
            shutil.copy(self.__plg_file, self.__pres / Path(self.__plg_file).name)
        self.__working_flag = False
    
    def simulate(self):
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
        
        if self.__vb is None and self.__clntID == -1:
            signal.signal(signal.SIGINT, eh)
        
        self.__st_time = time.time()
        self.__last_print_time = 0
        self.__last_mp_time = 0
        self.__mpsend("sim:start")
        self.start()

        while self.__inst.current_time < self.__break_at:
            self.step()
            if self.__stopsig:
                if self.save_on_abort:
                    p = self.__pres / SAVED_STATE_FOLDER
                    p.mkdir(parents=True, exist_ok=True)
                    self.save(p)
                break
            if not self.show_uxsim_info:
                self._istep()
        
        dur = time.time() - self.__st_time
        print(Lang.MAIN_SIM_DONE.format(time2str(dur)), file=self.__out)
        self.__out.close()
        self.stop(str(self.__pres / SAVED_STATE_FOLDER) if self.save_on_finish else "")
        self.__print(Lang.MAIN_SIM_DONE.format(time2str(dur)))
        self.__mpsend("sim:done")
        if self.__plot_cmd != "" and not self.__stopsig:
            AdvancedPlot().configure(self.__plot_cmd)
        self.__mpsend("plot:done")
        return not self.__stopsig, self.__inst, self.__sta

    def _istep(self):
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
        if hasattr(self, "_V2SimInstance__out") and not self.__out.closed:
            self.__out.close()

def simulate_single(vb=None, **kwargs)->bool:
    '''
    Single process simulation
        vb: Visualization window. None means no visualization.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return V2SimInstance(**kwargs, vb=vb, silent=False).simulate()[0]

def simulate_multi(mpQ:Optional[queue.Queue], clntID:int, **kwargs)->bool:
    '''
    Multi-process simulation
        mpQ: Queue for communication with the main process.
        clntID: Client ID.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return V2SimInstance(**kwargs, mpQ=mpQ, clntID=clntID, silent=True).simulate()[0]

if __name__ == "__main__":
    print(Lang.CORE_NO_RUN)