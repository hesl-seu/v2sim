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
        args:Union[str,ArgChecker],
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
        }
    if check_illegal and len(args) > 0:
        for key in args.keys():
            raise ValueError(Lang.ERROR_ILLEGAL_CMD.format(key))
    return kwargs

def _simulate(
    *,
    cfgdir: str,            
    gen_veh_command:str="", 
    gen_fcs_command:str="", 
    gen_scs_command:str="", 
    plot_command:str="",    
    outdir: str,            
    traffic_step: int,      
    start_time: int,        
    end_time: int,
    no_plg: str,            
    log: str,               
    seed: int,              
    copy: bool,             
    plg_pool: PluginPool,   
    sta_pool: StaPool,      
    vb=None,                
    silent: bool,           
    mpQ: Optional[queue.Queue[tuple[int, str]]] = None, 
    clntID: int = -1,       
) -> tuple[bool, TrafficInst, StaWriter]:
    '''
    Main simulation function
        cfgdir: Configuration folder
        gen_veh_command: command to generate vehicle
        gen_fcs_command: Generate fast charging station command
        gen_scs_command: Generate slow charging station command
        plot_command: Plot command
        outdir: Output folder
        traffic_step: Simulation step
        start_time: Start time
        end_time: End time
        no_plg: Disabled plugins, separated by commas
        log: Data to be recorded, separated by commas
        seed: Randomization seed
        copy: Whether to copy the configuration file after the simulation ends
        plg_pool: Available plugin pool
        sta_pool: Available statistical item pool
        vb: Whether to enable the visualization window, None means not enabled, when running this function in multiple processes, please set to None
        silent: Whether to silent mode, default is False, when running this function in multiple processes, please set to True
        mpQ: Queue for communication with the main process when running this function in multiple processes, set to None if not using multi-process function
        clntID: Identifier of this process when running this function in multiple processes, set to -1 if not using multi-process function
    Returns:
        (Whether the simulation ends normally, TrafficInst instance, StaWriter instance)
    '''

    if mpQ:
        assert clntID != -1, Lang.ERROR_CLIENT_ID_NOT_SPECIFIED
        silent = True
        vb = None
    
    def mp_write(con:str):
        if mpQ:
            try:
                mpQ.put_nowait((clntID, con))
            except:
                print(Lang.WARN_SIM_COMM_FAILED)
    
    def elprint(con:str="", *, file:Any = sys.stdout, end="\n"):
        if not silent:
            print(con, file=file, end=end)

    # Check if there is a previous results
    pres = Path(outdir) / Path(cfgdir).name
    if pres.is_dir() and (pres / "cproc.clog").exists():
        tm = time.strftime("%Y%m%d_%H%M%S", time.localtime(pres.stat().st_mtime))
        tm2 = time.time_ns() % int(1e9)
        pres.rename(f"{str(pres)}_{tm}_{tm2}")
    pres.mkdir(parents=True, exist_ok=True)

    # Create cproc.log
    ostream = open(str(pres / "cproc.log"), "w", encoding="utf-8")
    StopSignal = False

    def eh(signum, frame):
        nonlocal StopSignal
        elprint()
        elprint(Lang.MAIN_SIGINT)
        mp_write("exit")
        StopSignal = True

    proj_dir = Path(cfgdir)

    if gen_veh_command != "" or gen_scs_command != "" or gen_fcs_command != "":
        traff_gen = TrafficGenerator(str(proj_dir),silent)
        if gen_fcs_command != "":
            traff_gen.FCSFromArgs(gen_fcs_command)
            elprint(Lang.INFO_REGEN_FCS)
            mp_write("fcs:done")
        if gen_scs_command != "":
            traff_gen.SCSFromArgs(gen_scs_command)
            elprint(Lang.INFO_REGEN_SCS)
            mp_write("scs:done")
        if gen_veh_command != "":
            vehicles = traff_gen.EVTripsFromArgs(gen_veh_command)
            elprint(Lang.INFO_REGEN_VEH)
            mp_write("veh:done")
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
    elprint(f"  SUMO: {sumocfg_file}")

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
    elprint(Lang.INFO_NET.format(rnet_file))
    
    # Check vehicles and trips
    if not proj_cfg.veh:
        raise FileNotFoundError(Lang.ERROR_TRIPS_FILE_NOT_FOUND)
    veh_file = proj_cfg.veh
    if vehicles is None:
        vehicles = EVDict(veh_file)
    elprint(Lang.INFO_TRIPS.format(veh_file,len(vehicles)))

    # Check FCS file
    if not proj_cfg.fcs:
        raise FileNotFoundError(Lang.ERROR_FCS_FILE_NOT_FOUND)
    fcs_file = proj_cfg.fcs
    fcs_obj = CSList(vehicles, filePath = fcs_file, csType = FCS)
    elprint(Lang.INFO_FCS.format(fcs_file,len(fcs_obj)))

    # Check SCS file
    if not proj_cfg.scs:
        raise FileNotFoundError(Lang.ERROR_SCS_FILE_NOT_FOUND)
    scs_file = proj_cfg.scs
    scs_obj = CSList(vehicles, filePath = scs_file, csType = SCS)
    elprint(Lang.INFO_SCS.format(scs_file,len(scs_obj)))

    # Check start and end time
    if start_time == -1:
        start_time = _stt
    if end_time == -1:
        end_time = _edt
    if start_time == -1 or end_time == -1:
        raise ValueError(Lang.ERROR_ST_ED_TIME_NOT_SPECIFIED)
    sim_duration = end_time - start_time
    elprint(Lang.INFO_TIME.format(start_time,end_time,traffic_step))

    # Create a simulation instance
    myNet = TrafficInst(
        rnet_file, start_time, end_time, str(pres / "cproc.clog"), seed,
        vehfile = veh_file, veh_obj = vehicles,
        fcsfile = fcs_file, fcs_obj = fcs_obj,
        scsfile = scs_file, scs_obj = scs_obj
    )

    # Enable plugins
    if proj_cfg.plg:
        plg_file = proj_cfg.plg
        plg_man = PluginMan(
            str(plg_file), 
            pres,
            myNet,
            list(map(lambda x: x.strip().lower(), no_plg.split(","))),
            plg_pool
        )
        for plugname, plugin in plg_man.GetPlugins().items():
            elprint(Lang.INFO_PLG.format(plugname, plugin.Description))
    else:
        plg_man = PluginMan(None, pres, myNet, [], plg_pool)

    # Create a data logger
    log_item = log.strip().lower().split(",")
    mySta = StaWriter(str(pres), myNet, plg_man.GetPlugins(), sta_pool)
    for itm in log_item:
        mySta.Add(itm)

    # Start simulation
    if vb is None and clntID == -1:
        signal.signal(signal.SIGINT, eh)
    
    st_time = time.time()
    last_print_time = 0
    last_mp_time = 0
    mp_write("sim:start")
    myNet.simulation_start(sumocfg_file, rnet_file, start_time, vb is not None)
    plg_man.PreSimulationAll()
    while myNet.current_time < end_time:
        plg_man.PreStepAll(myNet.current_time)
        myNet.simulation_step(traffic_step)
        plg_man.PostStepAll(myNet.current_time)
        mySta.Log(myNet.current_time)

        # Visualization
        if vb is not None:
            counter = [0, 0, 0, 0, 0]
            for veh in myNet.vehicles.values():
                counter[veh.status] += 1
            upd = {
                "Driving": counter[VehStatus.Driving],
                "Pending": counter[VehStatus.Pending],
                "Charging": counter[VehStatus.Charging],
                "Parking": counter[VehStatus.Parking],
                "Depleted": counter[VehStatus.Depleted],
            }
            upd.update(zip(myNet.FCSList.get_CS_names(), myNet.FCSList.get_veh_count()))
            vb.set_val(upd)
        else:
            ctime = time.time()
            if ctime - last_print_time > 1 or myNet.current_time >= end_time:
                # Progress in command line updates once per second
                progress = 100 * (myNet.current_time - start_time) / sim_duration
                eta = (
                    time2str((ctime - st_time) * (100 - progress) / progress)
                    if ctime - st_time > 3
                    else "N/A"
                )
                elprint("\r",end="")
                elprint(
                    Lang.MAIN_SIM_PROG.format(
                        round(progress,2), 
                        myNet.current_time, 
                        end_time, 
                        time2str(ctime-st_time), 
                        eta
                    ),
                    end="",
                )
                if ctime - last_mp_time > 5:
                    # Communicate with the main process every 5 seconds in multi-process mode
                    mp_write(f"sim:{progress:.2f}")
                    last_mp_time = ctime
                last_print_time = ctime
        if StopSignal:
            break
    dur = time.time() - st_time
    print(Lang.MAIN_SIM_DONE.format(time2str(dur)),file=ostream)
    ostream.close()
    plg_man.PostSimulationAll()
    myNet.simulation_stop()
    mySta.close()
    if copy:
        shutil.copy(veh_file, pres / ("veh.xml"))
        shutil.copy(fcs_file, pres / ("cs.xml"))
        shutil.copy(scs_file, pres / ("pk.xml"))
        shutil.copy(plg_file, pres / ("plg.xml"))
    elprint()
    elprint(Lang.MAIN_SIM_DONE.format(time2str(dur)))
    mp_write("sim:done")
    if plot_command != "" and not StopSignal:
        AdvancedPlot().configure(plot_command)
    mp_write("plot:done")
    return not StopSignal, myNet, mySta

def simulate_single(vb=None, **kwargs)->bool:
    '''
    Single process simulation
        vb: Visualization window. None means no visualization.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return _simulate(**kwargs,vb=vb,silent=False)[0]

def simulate_multi(mpQ:Optional[queue.Queue[tuple[int, str]]], clntID:int, **kwargs)->bool:
    '''
    Multi-process simulation
        mpQ: Queue for communication with the main process.
        clntID: Client ID.
        kwargs: Simulation parameters. Use function 'get_sim_params' to get.
    '''
    return _simulate(**kwargs, mpQ=mpQ, clntID=clntID, silent=True)[0]

if __name__ == "__main__":
    print(Lang.CORE_NO_RUN)