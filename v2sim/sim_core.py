import importlib
import queue, shutil, signal, time, sys
from typing import Any, Optional
from feasytools import ArgChecker, time2str
from pathlib import Path
from .plotkit import AdvancedPlot
from .plugins import *
from .statistics import *
from .traffic import *
from .locale import Lang
from .trafficgen import TrafficGenerator, ELGraph

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
                plugin_pool._Register(*module.plugin_exports)
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_PLUGIN.format(module_name, e))
        if hasattr(module, "sta_exports"):
            try:
                sta_pool.Register(*module.sta_exports)
            except Exception as e:
                print(Lang.WARN_EXT_INVALID_STA.format(module_name, e))
                
def get_sim_params(
        args:Union[str, ArgChecker],
        plg_pool:PluginPool,
        sta_pool:StaPool,
        check_illegal:bool = True
    )->dict[str,Any]:
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
            "cfgdir":           args.pop_str("d"),
            "outdir":           args.pop_str("o", "results/"),
            "traffic_step":     args.pop_int("l", 10),
            "start_time":       args.pop_int("b", -1),
            "end_time":         args.pop_int("e", -1),
            "no_plg":           args.pop_str("no-plg", ""),
            "log":              args.pop_str("log", "fcs,scs"),
            "seed":             args.pop_int("seed", time.time_ns() % 65536),
            "copy":             args.pop_bool("copy"),
            "gen_veh_command":  args.pop_str("gen-veh", ""),
            "gen_fcs_command":  args.pop_str("gen-fcs", ""),
            "gen_scs_command":  args.pop_str("gen-scs", ""),
            "plot_command":     args.pop_str("plot", ""),
            "plg_pool":         plg_pool,
            "sta_pool":         sta_pool,
            "initial_state":    args.pop_str("initial-state", ""),
            "load_last_state":  args.pop_bool("load-last-state"),
            "save_on_abort":    args.pop_bool("save-on-abort"),
            "save_on_finish":   args.pop_bool("save-on-finish"),
        }
    if check_illegal and len(args) > 0:
        for key in args.keys():
            raise ValueError(Lang.ERROR_ILLEGAL_CMD.format(key))
    return kwargs

class V2SimInstance:
    def __mpwrite(self, con:str):
        if self.__mpQ:
            try:
                self.__mpQ.put_nowait((self.__clntID, con))
            except:
                print(Lang.WARN_SIM_COMM_FAILED)
    
    def __print(self, con:str="", *, file:Any = sys.stdout, end="\n"):
        if not self.__silent:
            print(con, file=file, end=end)

    def __init__(
        self, 
        cfgdir: str,
        outdir: str = "./results",
        *,
        plg_pool: Optional[PluginPool] = None,
        sta_pool: Optional[StaPool] = None,
        gen_veh_command:str = "", 
        gen_fcs_command:str = "", 
        gen_scs_command:str = "", 
        plot_command:str = "",
        traffic_step: int = 10,      
        start_time: int = 0,        
        end_time: int = 172800,
        no_plg: str = "",            
        log: str = "fcs, scs",               
        seed: int = 0,              
        copy: bool = False,
        vb = None,                
        silent: bool = False,           
        mpQ: Optional[queue.Queue[tuple[int, str]]] = None, 
        clntID: int = -1,
        initial_state: str = "",
        load_last_state: bool = False,
        save_on_abort: bool = False,
        save_on_finish: bool = False,
    ) -> tuple[bool, TrafficInst, StaWriter]:
        '''
        Initialization
            cfgdir: Configuration folder
            outdir: Output folder
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
            load_last_state: Load the state in result dir if there is a state folder
            save_on_abort: Whether to save the state when Ctrl+C is pressed
            save_on_finish: Whether to save the state when the simulation ends
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

        # Check if there is a previous results
        pres = Path(outdir) / Path(cfgdir).name
        if pres.is_dir() and (pres / "cproc.clog").exists():
            tm = time.strftime("%Y%m%d_%H%M%S", time.localtime(pres.stat().st_mtime))
            tm2 = time.time_ns() % int(1e9)
            new_path = f"{str(pres)}_{tm}_{tm2}"
            if (pres / "saved_state").exists() and load_last_state:
                initial_state = new_path + "/saved_state"
            pres.rename(new_path)
        pres.mkdir(parents=True, exist_ok=True)
        self.__pres = pres

        # Create cproc.log
        self.__out = open(str(pres / "cproc.log"), "w", encoding="utf-8")

        proj_dir = Path(cfgdir)

        if gen_veh_command != "" or gen_scs_command != "" or gen_fcs_command != "":
            traff_gen = TrafficGenerator(str(proj_dir),silent)
            if gen_fcs_command != "":
                traff_gen.FCSFromArgs(gen_fcs_command)
                self.__print(Lang.INFO_REGEN_FCS)
                self.__mpwrite("fcs:done")
            if gen_scs_command != "":
                traff_gen.SCSFromArgs(gen_scs_command)
                self.__print(Lang.INFO_REGEN_SCS)
                self.__mpwrite("scs:done")
            if gen_veh_command != "":
                vehicles = traff_gen.EVTripsFromArgs(gen_veh_command)
                self.__print(Lang.INFO_REGEN_VEH)
                self.__mpwrite("veh:done")
        else:
            vehicles = None
        
        proj_cfg = DetectFiles(str(proj_dir))

        if proj_cfg.py:
            with open(proj_cfg.py,"r",encoding="utf-8") as f:
                code = f.read()
                exec(code)
            
        # Detect SUMO configuration
        if not proj_cfg.cfg:
            raise FileNotFoundError(Lang.ERROR_SUMO_CONFIG_NOT_SPECIFIED)
        sumocfg_file = proj_cfg.cfg
        _stt, _edt, _rnet = get_sim_config(sumocfg_file)
        self.__print(f"  SUMO: {sumocfg_file}")

        # Detect road network file
        if _rnet is None:
            if not proj_cfg.net:
                raise RuntimeError(Lang.ERROR_NET_FILE_NOT_SPECIFIED)
            else:
                rnet_file = proj_cfg.net
        else:
            rnet_file = proj_dir / _rnet
            if rnet_file.exists():
                rnet_file = str(rnet_file)
            else:
                raise FileNotFoundError(Lang.ERROR_NET_FILE_NOT_SPECIFIED)
        elg = ELGraph(rnet_file)
        elg.checkBadCS()
        self.__print(Lang.INFO_NET.format(rnet_file))
        
        # Check vehicles and trips
        if not proj_cfg.veh:
            raise FileNotFoundError(Lang.ERROR_TRIPS_FILE_NOT_FOUND)
        veh_file = proj_cfg.veh
        if vehicles is None:
            vehicles = EVDict(veh_file)
        self.__print(Lang.INFO_TRIPS.format(veh_file,len(vehicles)))

        # Check FCS file
        if not proj_cfg.fcs:
            raise FileNotFoundError(Lang.ERROR_FCS_FILE_NOT_FOUND)
        fcs_file = proj_cfg.fcs
        fcs_obj = CSList(vehicles, filePath = fcs_file, csType = FCS)
        self.__print(Lang.INFO_FCS.format(fcs_file,len(fcs_obj)))
        if fcs_obj._kdtree is None: self.__print(Lang.CSLIST_KDTREE_DISABLED)

        # Check SCS file
        if not proj_cfg.scs:
            raise FileNotFoundError(Lang.ERROR_SCS_FILE_NOT_FOUND)
        scs_file = proj_cfg.scs
        scs_obj = CSList(vehicles, filePath = scs_file, csType = SCS)
        self.__print(Lang.INFO_SCS.format(scs_file,len(scs_obj)))
        if scs_obj._kdtree is None: self.__print(Lang.CSLIST_KDTREE_DISABLED)

        # Check start and end time
        if start_time == -1:
            start_time = _stt
        if end_time == -1:
            end_time = _edt
        if start_time == -1 or end_time == -1:
            raise ValueError(Lang.ERROR_ST_ED_TIME_NOT_SPECIFIED)
        self.__start_time = start_time
        self.__end_time = end_time
        self.__sim_dur = end_time - start_time
        self.__print(Lang.INFO_TIME.format(start_time,end_time,traffic_step))

        # Create a simulation instance
        self.__inst = TrafficInst(
            rnet_file, start_time, end_time, str(pres / "cproc.clog"), seed,
            vehfile = veh_file, veh_obj = vehicles,
            fcsfile = fcs_file, fcs_obj = fcs_obj,
            scsfile = scs_file, scs_obj = scs_obj,
            initial_state_folder = initial_state
        )

        # Enable plugins
        self.__gridplg = None
        if proj_cfg.plg:
            plg_file = proj_cfg.plg
            plg_man = PluginMan(
                str(plg_file), 
                pres,
                self.__inst,
                list(map(lambda x: x.strip().lower(), no_plg.split(","))),
                plg_pool
            )
            for plugname, plugin in plg_man.GetPlugins().items():
                if isinstance(plugin, PluginPDN):
                    self.__gridplg = plugin
                self.__print(Lang.INFO_PLG.format(plugname, plugin.Description))
        else:
            plg_man = PluginMan(None, pres, self.__inst, [], plg_pool)

        # Create a data logger
        log_item = log.strip().lower().split(",")
        if len(log_item) == 1 and log_item[0] == "": log_item = []
        mySta = StaWriter(str(pres), self.__inst, plg_man.GetPlugins(), sta_pool)
        for itm in log_item:
            mySta.Add(itm)
        
        self.__sta = mySta
        self.__plgman = plg_man
        if initial_state:
            self.__load_plugin_states(Path(initial_state) / "plugins.gz")
        self.__steplen = traffic_step
        self.__sumocfg_file = sumocfg_file
        self.__rnet_file = rnet_file
        self.__copy = copy
        self.__plot_cmd = plot_command
        self.__veh_file = veh_file
        self.__fcs_file = fcs_file
        self.__scs_file = scs_file
        self.__plg_file = plg_file
        self.__proj_cfg = proj_cfg
        self.__proj_dir = proj_dir
        self.__outdir = outdir
        self.__working_flag = False
        self.save_on_abort = save_on_abort
        self.save_on_finish = save_on_finish

    @property
    def project_dir(self):
        '''Folder of the project'''
        return self.__proj_dir
    
    @property
    def result_dir(self):
        '''Folder of results'''
        return self.__outdir
    
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
    
    def send_to_host(self, msg:str):
        '''Send message to host process'''
        assert self.__mpQ is not None, "Not working in multiprocessing mode. No host exists."
        self.__mpwrite(msg)
    
    def start(self, load_from:str = ""):
        '''
        Start simulation.
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        '''
        self.__working_flag = True
        self.__inst.simulation_start(self.__sumocfg_file, self.__rnet_file, self.__start_time, self.__vb is not None)
        self.__plgman.PreSimulationAll()
        if load_from != "":
            self.load_state(load_from)
    
    def step(self) -> int:
        '''
        Simulation steps. 
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        Return the simulation time after this step.
        '''
        self.__plgman.PreStepAll(self.__inst.current_time)
        self.__inst.simulation_step(self.__steplen)
        self.__plgman.PostStepAll(self.__inst.current_time)
        self.__sta.Log(self.__inst.current_time)
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
    
    def __load_plugin_states(self, p:Path):
        if not p.exists(): raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(p))
        with gzip.open(str(p), "rb") as f:
            self.__plgman.LoadStates(pickle.load(f))

    def load_state(self, load_from:str):
        '''Load the previous state of the simulation'''
        self.__inst.load_state(load_from)
        self.__load_plugin_states(Path(load_from) / "plugins.gz")
    
    def save_state(self, save_to:str):
        '''Save the current state of the simulation'''
        self.__inst.save_state(save_to)
        with gzip.open(str(Path(save_to) / "plugins.gz"), "wb") as f:
            pickle.dump(self.__plgman.SaveStates(), f)
    
    def stop(self, save_state_to:str = ""):
        '''
        Stop simulation.
            If you use this function, do not use function 'simulation'.
            Follow the start - step - stop paradigm.
        '''
        if save_state_to != "":
            self.save_state(save_state_to)
        self.__plgman.PostSimulationAll()
        self.__inst.simulation_stop()
        self.__sta.close()
        self.__out.close()
        if self.__copy:
            shutil.copy(self.__veh_file, self.__pres / ("veh.xml"))
            shutil.copy(self.__fcs_file, self.__pres / ("cs.xml"))
            shutil.copy(self.__scs_file, self.__pres / ("pk.xml"))
            shutil.copy(self.__plg_file, self.__pres / ("plg.xml"))
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
            self.__mpwrite("exit")
            self.__stopsig = True
        
        if self.__vb is None and self.__clntID == -1:
            signal.signal(signal.SIGINT, eh)
        
        self.__st_time = time.time()
        self.__last_print_time = 0
        self.__last_mp_time = 0
        self.__mpwrite("sim:start")
        self.start()

        while self.__inst.current_time < self.__end_time:
            self.step()
            self._istep()
            if self.__stopsig:
                if self.save_on_abort:
                    p = self.__pres / "saved_state"
                    p.mkdir(parents=True, exist_ok=True)
                    self.save_state(str(p))
                break
        
        dur = time.time() - self.__st_time
        print(Lang.MAIN_SIM_DONE.format(time2str(dur)),file=self.__out)
        self.__out.close()
        self.stop(self.__pres / "saved_state" if self.save_on_finish else "")
        self.__print()
        self.__print(Lang.MAIN_SIM_DONE.format(time2str(dur)))
        self.__mpwrite("sim:done")
        if self.__plot_cmd != "" and not self.__stopsig:
            AdvancedPlot().configure(self.__plot_cmd)
        self.__mpwrite("plot:done")
        return not self.__stopsig, self.__inst, self.__sta

    def _istep(self):
        # Visualization
        if self.__vb is not None:
            counter = [0, 0, 0, 0, 0]
            for veh in self.__inst.vehicles.values():
                counter[veh.status] += 1
            upd = {
                "Driving": counter[VehStatus.Driving],
                "Pending": counter[VehStatus.Pending],
                "Charging": counter[VehStatus.Charging],
                "Parking": counter[VehStatus.Parking],
                "Depleted": counter[VehStatus.Depleted],
            }
            upd.update(zip(self.__inst.FCSList.get_CS_names(), self.__inst.FCSList.get_veh_count()))
            self.__vb.set_val(upd)
        else:
            ctime = time.time()
            if ctime - self.__last_print_time > 1 or self.__inst.current_time >= self.__end_time:
                # Progress in command line updates once per second
                progress = 100 * (self.__inst.current_time - self.__start_time) / self.__sim_dur
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
                        self.__end_time, 
                        time2str(ctime-self.__st_time), 
                        eta
                    ),
                    end="",
                )
                if ctime - self.__last_mp_time > 5:
                    # Communicate with the main process every 5 seconds in multi-process mode
                    self.__mpwrite(f"sim:{progress:.2f}")
                    self.__last_mp_time = ctime
                self.__last_print_time = ctime


def simulate_single(vb=None, **kwargs)->bool:
    '''
    Single process simulation
        vb: Visualization window. None means no visualization.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return V2SimInstance(**kwargs, vb=vb, silent=False).simulate()[0]

def simulate_multi(mpQ:Optional[queue.Queue[tuple[int, str]]], clntID:int, **kwargs)->bool:
    '''
    Multi-process simulation
        mpQ: Queue for communication with the main process.
        clntID: Client ID.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return V2SimInstance(**kwargs, mpQ=mpQ, clntID=clntID, silent=True).simulate()[0]

if __name__ == "__main__":
    print(Lang.CORE_NO_RUN)