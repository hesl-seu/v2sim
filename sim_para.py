"""
Multi-process Parallel Simulation Tool
"""

import queue
import signal
import time, os, shutil, sys
import multiprocessing as mp
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor
from pathlib import Path
from typing import Optional
from feasytools import time2str, ArgChecker
from v2sim import (
    Lang, PluginPool, StaPool,
    get_sim_params,
    simulate_multi,
    load_external_components,
    simulate_single,
)


def _create_argchk(cmd: str) -> ArgChecker:
    return ArgChecker(cmd, ["plot", "gen-veh", "gen-fcs", "gen-scs"])


class SimCommand:
    """A class to represent a simulation command."""
    def __init__(self, cmd: str, fromfile: bool = True, data_dir: str = ""):
        """
        Create a new simulation command.
            cmd: Command string.
            fromfile: Whether the command is from a file.
            data_dir: Data directory.
        """
        self.args = _create_argchk(cmd)
        self.fromfile = fromfile
        if fromfile:
            self.no_parallel = self.args.pop_bool("no-parallel")
            self.output = self.args.pop_str("o", "")
        else:
            self.args.pop_int("seed", 0)
            self.args.pop_str("o", "")
            self.gen_veh = ArgChecker(self.args.pop_str("gen-veh", ""))
            self.gen_veh.pop_int("seed", 0)
            self.gen_fcs = ArgChecker(self.args.pop_str("gen-fcs", ""))
            self.gen_fcs.pop_int("seed", 0)
            self.gen_scs = ArgChecker(self.args.pop_str("gen-scs", ""))
            self.gen_scs.pop_int("seed", 0)
            self.plot = ArgChecker(self.args.pop_str("plot", ""))
            self.no_parallel = False
            self.data_dir = data_dir

    def __arg2str(self, arg: ArgChecker, seed: Optional[int] = None) -> str:
        ret = ""
        for k, v in arg.items():
            ret += f"-{k} '{v}' "
        if seed is None:
            return ret
        return ret + f"-seed {seed}"

    def get_new_command(self, seed: int, resdir: str) -> str:
        """
        Get the new command string with the given seed and result directory.
            seed: Seed to use.
            resdir: Result directory.
        """
        if self.fromfile:
            return self.__arg2str(self.args) + f" -o '{resdir}'"
        return (
            self.__arg2str(self.args, seed)
            + f" -d '{self.data_dir}' -o '{resdir}'"
            + (
                f' -gen-veh "{self.__arg2str(self.gen_veh, seed)}"'
                if not self.gen_veh.empty()
                else ""
            )
            + (
                f' -gen-fcs "{self.__arg2str(self.gen_fcs, seed)}"'
                if not self.gen_fcs.empty()
                else ""
            )
            + (
                f' -gen-scs "{self.__arg2str(self.gen_scs, seed)}"'
                if not self.gen_scs.empty()
                else ""
            )
            + f' -plot "{self.__arg2str(self.plot)}"'
        )


def work(
    i: int,
    resdir: str,
    cmd: SimCommand,
    plg_pool: PluginPool,
    sta_pool: StaPool,
    mpQ: Optional[queue.Queue[tuple[int, str]]] = None,
) -> bool:
    """
    Run a simulation task.
        i: Task index.
        resdir: Result directory.
        cmd: Simulation command.
        plg_pool: Plugin pool.
        sta_pool: Statistics pool.
        mpQ: The multiprocessing queue for communicating with the main process.
    """
    # Create a copy of the simulation folder
    pname = f"_sim_temp/{i:03}"
    Path(pname).mkdir(parents=True, exist_ok=True)
    if "d" in cmd.args:
        data_root = cmd.args["d"]
    else:
        data_root = cmd.data_dir
    shutil.copytree(data_root, pname, dirs_exist_ok=True)

    if cmd.fromfile:
        resdir = str(Path(resdir).parent / cmd.output)
    cmd_text = cmd.get_new_command(i, resdir)
    pars = get_sim_params(_create_argchk(cmd_text), plg_pool, sta_pool)
    pars["cfgdir"] = pname
    if mpQ:
        ret = simulate_multi(mpQ, i, **pars)
    else:
        ret = simulate_single(**pars)

    # Clear the temporary folder
    shutil.rmtree(pname)
    return ret


def parallel_sim(parallel: int, results_root: str, commands: list[SimCommand]):
    """
    Run parallel simulations.
        parallel: Maximum number of parallel tasks.
        results_root: Root directory of the results.
        commands: Simulation commands.
    """
    plg_pool = PluginPool()
    sta_pool = StaPool()
    if Path("external_components").exists():
        load_external_components("external_components", plg_pool, sta_pool)
    pool = ProcessPoolExecutor(parallel)
    mpQ = mp.Manager().Queue()

    skip_list: list[int] = []
    work_list: list[Future] = []
    work_id_list: list[int] = []
    non_paras: list[tuple[int, SimCommand]] = []
    pre_count = 0

    st_time = time.time()
    for i, cfg in enumerate(commands):
        resdir = Path(results_root + f"/{i:03}")
        if resdir.exists():
            skip_list.append(i)
            continue
        if cfg.no_parallel:
            non_paras.append((i, cfg))
        else:
            work_list.append(
                pool.submit(work, i, str(resdir), cfg, plg_pool, sta_pool, mpQ)
            )
            work_id_list.append(i)

    print(Lang.PARA_SIM_SKIP_LIST.format(skip_list))
    rounds = len(commands)
    progs: list[float] = [0.0] * rounds
    last_upd = 0
    real_rounds = rounds - len(skip_list) - len(non_paras)

    StopSignal = False

    def all_done():
        for f in work_list:
            if not f.done():
                return False
        return True

    def eh(signum, frame):
        nonlocal StopSignal
        print()
        print(Lang.MAIN_SIGINT)
        StopSignal = True
        pool.shutdown()

    signal.signal(signal.SIGINT, eh)

    while not all_done():
        try:
            clnt, con = mpQ.get(timeout=1)
            clnt: int
            con: str
            obj, sta = con.split(":")
            if obj == "sim":
                if sta == "done":
                    progs[clnt] = 100
                elif sta == "start":
                    progs[clnt] = 0
                    pre_count += 1
                else:
                    progs[clnt] = float(sta)
        except queue.Empty:
            pass
        if time.time() - last_upd > 1 and not StopSignal:
            pre_info = (
                f"Pre: {pre_count}/{real_rounds} " if pre_count < real_rounds else ""
            )
            last_upd = time.time()
            elapsed = time2str(last_upd - st_time)
            avg_prog = sum(progs) / real_rounds
            eta = (
                time2str((last_upd - st_time) * (100 - avg_prog) / avg_prog)
                if avg_prog > 0
                else "N/A"
            )
            print(
                Lang.PARA_SIM_PROG.format(avg_prog, pre_info, elapsed, eta),
                end="\r",
            )
        time.sleep(0.5)

    print()
    shutil.rmtree("_sim_temp", ignore_errors=True)

    for i, f in zip(work_id_list, work_list):
        e = f.exception()
        if e:
            if isinstance(e, (KeyboardInterrupt, CancelledError)):
                continue
            print("Error:", i, str(type(e)), e.with_traceback(e.__traceback__))

    if len(non_paras) > 0:
        print(Lang.PARA_SIM_DONE_PARA.format(time2str(time.time() - st_time)))
        st_time2 = time.time()
        print(Lang.PARA_SIM_START_SERIAL)
        for i, cfg in non_paras:
            if not work(i, results_root + f"/{i:03}", cfg, plg_pool, sta_pool):
                break  # Stop if any error occurs
        print(Lang.PARA_SIM_DONE_SERIAL.format(time2str(time.time() - st_time2)))
    print(Lang.MAIN_SIM_DONE.format(time2str(time.time() - st_time)))


if __name__ == "__main__":
    from version_checker import check_requirements
    check_requirements()
    args = ArgChecker(force_parametric=["p","d","r","c","n","f"])
    if args.pop_bool("h") or args.pop_bool("help"):
        print(Lang.PARA_HELP_STR.format(sys.argv[0]))
        exit()

    max_parallel = os.cpu_count()
    if max_parallel is None:
        max_parallel = 1
    else:
        max_parallel -= 1
    parallel = args.pop_int("p", max_parallel)
    root = args.pop_str("r", "results_set")
    from_file = args.pop_str("f", "")
    if from_file == "":
        data_root = args.pop_str("d")
        cmd = args.pop_str("c")
        n = args.pop_int("n", 50)
        commands = [SimCommand(cmd,False,data_root) for _ in range(n)]
    else:
        with open(from_file, "r") as f:
            lines = f.readlines()
        commands = []
        for line in lines:
            comment_start = line.find("#")
            if comment_start != -1:
                line = line[:comment_start]
            line = line.strip()
            if line == "":
                continue
            commands.append(SimCommand(line))
    parallel_sim(parallel, root, commands)
