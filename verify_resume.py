#!/usr/bin/env python3
"""V2Sim 连续仿真 / 保存恢复一致性验证器（配合修正版 V2Sim 使用）。

将本文件放在 v2sim 包所在目录，或先把该目录加入 PYTHONPATH。
示例：
  python verify_resume.py ./case --split 3600
  python verify_resume.py ./case --begin 0 --end 7200 --step 10 --split 3600 \
      --seed 0 --atol 1e-7 --rtol 1e-6 --out ./resume_check
  python verify_resume.py ./case --split 3600 --samples 20

时间单位：秒，均为绝对仿真时刻。未指定时间/种子时读取 *.v2simcfg。
默认快速模式：只在起点、断点、终点读取全量状态，不逐步遍历全部车辆或记录统计。
--samples 20 可增加约 20 个均匀分布的中途采样点；--every N 可指定采样步距。
--every 1 显式开启昂贵的逐步全量检查；大型项目不建议直接使用。
默认误差判据：abs(a-b) <= atol + rtol*max(abs(a),abs(b))。
--atol 0 --rtol 0 可作严格数值比较。NaN 一律判为不一致。
默认每秒刷新仿真进度、速度和预计剩余时间；--progress-interval 可调整刷新秒数。
初始化、单步求解或保存较慢时仍会显示已等待时间，详细输出保留在 worker.log。

可选手动 V2G 指令文件 --actions actions.json（基于绝对仿真时刻）：
  [{"time": 300, "dispatch_kW": {"station_name": 10}, "replace": true},
   {"time": 900, "clear": true}]
指令在该时刻的物理步骤结束后、下一步开始前提交；断点时的指令先提交再保存，
恢复时不重放，因而也能检查未执行的 manual_dispatch_dirty 是否正确保存。

输出：report.json、三个独立进程的 worker.log、采样 trace.jsonl.gz、
checkpoint/。不会修改项目源文件；不会恢复 Python/NumPy 全局 RNG 来掩盖遗漏。
输出目录必须不存在。退出码：0=比较通过，1=存在差异，2=参数/仿真/检查错误。
通过仅表示本次场景、采样点和误差容限下的已列出观测量一致；不证明所有内部
状态、外部控制器或未来所有输入一致。快速模式不能证明未采样步骤完全一致。
统计通道仅在采样点读取，不生成逐步 CSV，不对 pickle 文件作字节比较。
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import gzip
import itertools
import json
import math
import numbers
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback


CHANNELS = ("ev", "fcs", "scs", "gs", "bus", "gen", "line", "pvw", "ess")
PHASE_NAMES = {"continuous": "1/3 连续仿真", "prefix": "2/3 断点前仿真",
               "resumed": "3/3 恢复后仿真"}


def duration(seconds):
    if seconds is None or not math.isfinite(seconds):
        return "--:--:--"
    seconds = max(0, int(seconds))
    return f"{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}"


class ProgressLine:
    def __init__(self, interval):
        self.interval = interval
        self.last = -math.inf
        self.tty = sys.stdout.isatty()

    def show(self, message, force=False):
        now = time.monotonic()
        if force or now - self.last >= self.interval:
            print(("\r\033[K" if self.tty else "") + message,
                  end="" if self.tty else "\n", flush=True)
            self.last = now

    def finish(self):
        if self.tty:
            print(flush=True)


class WorkerProgress:
    """Small atomic status file; the parent remains responsive during long steps."""
    def __init__(self, job):
        self.job = job
        self.started = None
        self.path = Path(job["output"]) / "progress.json"
        self.state = None
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def update(self, stage, current=None, force=False):
        # The simulation thread only updates memory; a background thread writes
        # at the display cadence, including while a solver call is blocked.
        self.state = {"stage": stage, "current": current, "updated_at": time.time(),
                      "running_since": self.started}
        if force:
            self._publish()

    def _loop(self):
        while not self.done.wait(self.job.get("progress_interval", 1.)):
            self._publish()

    def _publish(self):
        if self.state is None:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            with self.lock:
                write_json(temporary, self.state)
                os.replace(temporary, self.path)
        except OSError:
            # Display failures must not interrupt simulator cleanup or execution.
            pass

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)


def run_worker(jobfile, job, environment, interval):
    phase = job["phase"]
    begin = job["split"] if phase == "resumed" else job["begin"]
    end = job["split"] if phase == "prefix" else job["end"]
    offset = {"continuous": 0, "prefix": job["end"]-job["begin"],
              "resumed": job["end"]-job["begin"]+job["split"]-job["begin"]}[phase]
    total = 2*(job["end"]-job["begin"])
    started = time.monotonic()
    display = ProgressLine(interval)
    state = {"stage": "启动独立进程", "current": None, "updated_at": time.time()}
    previous_stage = None
    folder = Path(job["output"])
    with (folder / "worker.log").open("w", encoding="utf-8") as log:
        with subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()),
                               "--_worker-job", str(jobfile)], stdout=log,
                              stderr=subprocess.STDOUT, env=environment) as proc:
            try:
                while True:
                    finished = proc.poll() is not None
                    try:
                        state = json.loads((folder / "progress.json").read_text(encoding="utf-8"))
                    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                        pass
                    current = state.get("current")
                    done = max(0, min(end-begin, current-begin)) if current is not None else 0
                    elapsed = time.monotonic()-started
                    running = max(0, time.time()-state["running_since"]) if state.get("running_since") else 0
                    rate = done/running if running > 0 and done > 0 else 0
                    eta = (end-begin-done)/rate if rate > 0 else None
                    stale = max(0, time.time()-state["updated_at"])
                    message = (f"[{PHASE_NAMES[phase]}] {state['stage']} | "
                               f"时刻 {current if current is not None else '--'}/{end}s | "
                               f"阶段 {100*done/(end-begin):6.2f}% 总体仿真 {100*(offset+done)/total:6.2f}% | "
                               f"已用 {duration(elapsed)} | {rate:.1f} 仿真秒/秒 | 阶段剩余约 {duration(eta)}")
                    if stale >= max(2., interval*2):
                        message += f" | 当前操作已等待 {duration(stale)}"
                    display.show(message, force=finished or state["stage"] != previous_stage)
                    previous_stage = state["stage"]
                    if finished:
                        break
                    try:
                        proc.wait(timeout=min(.2, interval))
                    except subprocess.TimeoutExpired:
                        pass
            except BaseException:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise
            finally:
                display.finish()
            return proc.returncode


def freeze(value):
    """Convert checkpoint data to stable JSON; unsupported data fails explicitly."""
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": freeze(value.value)}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        value = float(value)
        return value if math.isfinite(value) else {"nonfinite": str(value)}
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("Snapshot dictionaries must use string keys")
        return {k: freeze(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, deque)):
        return [freeze(x) for x in value]
    if isinstance(value, (set, frozenset)):
        return sorted((freeze(x) for x in value), key=lambda x: json.dumps(x, sort_keys=True))
    if is_dataclass(value) and not isinstance(value, type):
        return freeze(asdict(value))
    if hasattr(value, "tolist"):
        return freeze(value.tolist())
    raise TypeError(f"Unsupported state value {type(value).__module__}.{type(value).__name__}; "
                    "add an explicit observer instead of ignoring it")


def scalar_fields(obj):
    """Runtime scalar attributes, excluding object identity and computational caches."""
    return {k: v for k, v in vars(obj).items()
            if v is None or isinstance(v, (str, bool, numbers.Real, Enum))}


def snapshot(sim, observers=None):
    inst, pdn, t = sim.core, sim.pdn, sim.ctime
    # Query public observations before taking the internal scalar snapshot.
    grid_status = pdn.get_grid_state(t)
    v2g_status = pdn.get_V2G_status(t)
    stats = {}
    for name, logger in sorted((observers if observers is not None else sim.statistics._StaWriter__items).items()):
        values = list(logger.GetData(inst, sim.plugins.GetPlugins()))
        if len(values) != len(logger._cols):
            raise ValueError(f"Statistics channel length mismatch: {name}")
        stats[name] = dict(zip(logger._cols, values))
    stations = {}
    for cs in inst.stations:
        state = scalar_fields(cs)
        state["charging_vehicles"] = sorted(ev.name for ev in cs._chi)
        state["waiting_vehicles"] = [ev.name for ev in cs._buf]
        for attr in ("_v2g_dispatch_plan", "_pc_actual", "_pd_actual"):
            if hasattr(cs, attr):
                state[attr] = freeze(getattr(cs, attr))
        for attr in ("_c_evs", "_d_evs"):
            if hasattr(cs, attr):
                # These lists are derived from a set; compare membership.
                # Per-EV executed powers/energy still detect allocation changes.
                state[attr] = sorted(ev.name for ev in getattr(cs, attr))
        stations[cs.name] = state
    grid = pdn.Grid
    generators = {}
    for gen in grid.Gens:
        row = scalar_fields(gen)
        for attr in ("P", "Q", "Pmin", "Pmax", "CostB"):
            value = getattr(gen, attr)
            row[attr] = value(t) if callable(value) else value
        generators[gen.ID] = row
    return freeze({
        "time": t,
        "vehicles": {name: scalar_fields(ev) for name, ev in inst.vehs.items()},
        "stations": stations,
        "hub_membership": {name: getattr(inst, name)._veh for name in ("fcs", "scs", "gs")},
        "traffic_queues": {name: getattr(inst, name)._q for name in ("_que", "_fQ")},
        "grid": grid_status,
        "v2g": v2g_status,
        "pdn_runtime": {name: getattr(pdn, "_IntegratedPDN__" + name)
                        for name in pdn._STATE_FIELDS},
        "bid_blocks": [[(b.ev.name, b.price, b.user_price, b.quantity) for b in blocks]
                       for blocks in pdn._IntegratedPDN__v2g_bid_blocks],
        "generators": generators,
        "buses": {b.ID: scalar_fields(b) for b in grid.Buses},
        "lines": {line.ID: scalar_fields(line) for line in grid.Lines},
        "ess": {ess.ID: scalar_fields(ess) for ess in grid.ESSs},
        "pvwind": {pv.ID: scalar_fields(pv) for pv in grid.PVWinds},
        "statistics": stats,
        "plugins": sim.plugins.SaveStates(),
    })


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def worker(job):
    progress = WorkerProgress(job)
    progress.update("加载依赖和项目", force=True)
    import random
    import numpy as np
    import v2sim
    from v2sim import (CommonConfig, DetectFiles, LoadStateOption, SUMOConfig,
                       TimeConfig, UXsimConfig, V2SimConfig, V2SimInstance)
    random.seed(job["seed"])
    np.random.seed(job["seed"] % 2**32)
    files = DetectFiles(job["project"])
    cfg = V2SimConfig.load(files.pref) if files.pref else V2SimConfig()
    common = CommonConfig(routing_algorithm=cfg.routing_method,
                          add_veh_to_scs=cfg.add_veh_to_scs,
                          allow_scs_redirect=cfg.allow_scs_redirect)
    if files.sumo:
        engine = SUMOConfig(ignore_driving=cfg.sumo_ignore_driving,
                            suppress_route_not_found=not cfg.sumo_raise_routing_error,
                            mesosim=cfg.sumo_mesosim)
    else:
        engine = UXsimConfig(show_uxsim_info=False, randomize_uxsim=cfg.ux_rand,
                             no_parallel=cfg.ux_no_para)
        if cfg.ux_internal_step_len is not None:
            common.internal_step_len = cfg.ux_internal_step_len
    phase = job["phase"]
    out = Path(job["output"])
    resumed = phase == "resumed"
    sim = V2SimInstance.from_project(
        job["project"], TimeConfig(job["begin"], job["step"], job["end"]),
        out_dir=str(out), seed=job["seed"], silent=True, vscfg=common, config=engine,
        state_option=LoadStateOption.FromGiven if resumed else LoadStateOption.Skip,
        state_dir=job["checkpoint"] if resumed else None,
        logging_items={},
    )
    def apply_actions(t):
        for action in actions_by_time.get(t, ()):
            if action.get("clear", False):
                sim.pdn.clear_manual_v2g_dispatch()
            else:
                sim.pdn.set_manual_v2g_dispatch(action["dispatch_kW"],
                                               action.get("replace", True), t=t)
    limit = job["split"] if phase == "prefix" else job["end"]
    count = 0
    snapshot_seconds = 0.
    step_seconds = 0.
    checkpoint_seconds = 0.
    observers = {}
    statistics_dir = None
    actions_by_time = {}
    for action in job["actions"]:
        actions_by_time.setdefault(action["time"], []).append(action)
    sample_times = set(job.get("sample_times", []))
    try:
        # Initialize statistics observers once, but never call Log() per step.
        # Their temporary header files are removed after the worker finishes.
        statistics_dir = tempfile.TemporaryDirectory(prefix="observers_", dir=out)
        pool = sim.statistics._StaWriter__pool
        for name in CHANNELS:
            observers[name] = pool.Get(name)(statistics_dir.name, sim.core, sim.plugins.GetPlugins())
        progress.update("启动交通后端", force=True)
        sim.start()
        expected_start = job["split"] if resumed else job["begin"]
        if sim.ctime != expected_start:
            raise ValueError(f"{phase}: expected start {expected_start}, got {sim.ctime}")
        progress.started = time.time()
        progress.update("仿真与采样", sim.ctime, force=True)
        with gzip.open(out / "trace.jsonl.gz", "wt", encoding="utf-8", compresslevel=1) as trace:
            while True:
                if not (resumed and sim.ctime == job["split"]):
                    apply_actions(sim.ctime)
                index = (sim.ctime - job["begin"]) // job["step"]
                every = job.get("every")
                sampled = (every is not None and index % every == 0) or sim.ctime in sample_times
                if sampled or sim.ctime in (job["begin"], job["split"], limit):
                    progress.update("读取全量状态并写出采样", sim.ctime, force=True)
                    sample_started = time.perf_counter()
                    trace.write(json.dumps(snapshot(sim, observers), ensure_ascii=False,
                                           allow_nan=False, separators=(",", ":")) + "\n")
                    snapshot_seconds += time.perf_counter()-sample_started
                    count += 1
                progress.update("仿真与采样", sim.ctime, force=sim.ctime == limit)
                if sim.ctime == limit:
                    break
                previous = sim.ctime
                progress.update("仿真与采样", previous)
                step_started = time.perf_counter()
                sim.step()
                step_seconds += time.perf_counter()-step_started
                if sim.ctime != previous + job["step"] or sim.ctime > limit:
                    raise RuntimeError("Simulator did not advance by the configured step")
        if phase == "prefix":
            progress.update("保存断点", sim.ctime, force=True)
            save_started = time.perf_counter()
            sim.save(job["checkpoint"])
            checkpoint_seconds = time.perf_counter()-save_started
    finally:
        progress.update("关闭后端和输出文件", sim.ctime, force=True)
        try:
            sim.stop()
        finally:
            for observer in observers.values():
                observer.close()
            if statistics_dir is not None:
                statistics_dir.cleanup()
            progress.close()
    write_json(out / "worker_status.json", {
        "completed": True, "samples": count, "time": limit,
        "python": sys.version, "v2sim_version": getattr(v2sim, "__version__", None),
        "v2sim_source": str(Path(v2sim.__file__).resolve()),
        "engine": "SUMO" if files.sumo else "UXSim", "config": asdict(cfg),
        "step_seconds": step_seconds, "snapshot_seconds": snapshot_seconds,
        "checkpoint_seconds": checkpoint_seconds,
    })
    progress.update("完成", limit, force=True)


def differences(left, right, path="$", *, atol, rtol):
    if isinstance(left, dict) and isinstance(right, dict):
        if left.get("nonfinite") == "nan" or right.get("nonfinite") == "nan":
            yield path, left, right
            return
        for key in sorted(left.keys() | right.keys()):
            here = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
            if key not in left or key not in right:
                yield here, left.get(key, {"missing": True}), right.get(key, {"missing": True})
            else:
                yield from differences(left[key], right[key], here, atol=atol, rtol=rtol)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            yield path + ".length", len(left), len(right)
        for i, (a, b) in enumerate(zip(left, right)):
            yield from differences(a, b, f"{path}[{i}]", atol=atol, rtol=rtol)
    elif type(left) is int and type(right) is int:
        if left != right:
            yield path, left, right
    elif (isinstance(left, (int, float)) and not isinstance(left, bool)
          and isinstance(right, (int, float)) and not isinstance(right, bool)):
        if abs(left-right) > atol + rtol * max(abs(left), abs(right)):
            yield path, left, right
    elif type(left) is not type(right) or left != right:
        yield path, left, right


def rows(path, begin, end, on_scan=None):
    previous = None
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if on_scan is not None:
                on_scan(row["time"])
            if previous is not None and row["time"] <= previous:
                raise ValueError(f"Non-increasing trace times: {path}")
            previous = row["time"]
            if row["time"] > end:
                break
            if begin <= row["time"] <= end:
                yield row


def compare(left, right, begin, end, args, phase):
    result = {"phase": phase, "samples_compared": 0, "differing_samples": 0,
              "difference_count": 0, "first_difference": None, "examples": []}
    display = ProgressLine(args.progress_interval)
    started = time.monotonic()
    def on_scan(t):
        display.show(f"[结果比较 {phase}] 扫描时刻 {t}s | "
                     f"已比 {result['samples_compared']} 个采样点，{result['difference_count']} 项差异 | "
                     f"已用 {duration(time.monotonic()-started)}")
    display.show(f"[结果比较 {phase}] 开始读取轨迹 ...", force=True)
    for a, b in itertools.zip_longest(rows(left, begin, end, on_scan), rows(right, begin, end, on_scan)):
        if a is None or b is None or a["time"] != b["time"]:
            raise ValueError(f"{phase}: missing or misaligned trace sample")
        result["samples_compared"] += 1
        different = False
        for path, av, bv in differences(a, b, atol=args.atol, rtol=args.rtol):
            different = True
            result["difference_count"] += 1
            item = {"time": a["time"], "path": path, "continuous": av, "other": bv}
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                item["absolute_error"] = freeze(abs(av-bv))
            if result["first_difference"] is None:
                result["first_difference"] = item
            if len(result["examples"]) < args.max_diffs:
                result["examples"].append(item)
        result["differing_samples"] += int(different)
    if result["samples_compared"] == 0:
        raise ValueError(f"{phase}: no samples were compared")
    display.show(f"[结果比较 {phase}] 完成 | {result['samples_compared']} 个采样点，"
                 f"{result['difference_count']} 项差异 | 已用 {duration(time.monotonic()-started)}", force=True)
    display.finish()
    return result


def parse_actions(path, begin, end, step):
    actions = json.loads(Path(path).read_text(encoding="utf-8")) if path else []
    if not isinstance(actions, list):
        raise ValueError("Actions file must contain a JSON list")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Each action must be a JSON object")
        t = action["time"]
        if isinstance(t, bool) or not isinstance(t, int) or not begin <= t <= end or (t-begin) % step:
            raise ValueError(f"Action time must be aligned and within the simulation: {t}")
        if type(action.get("clear", False)) is not bool or type(action.get("replace", True)) is not bool:
            raise ValueError("clear/replace must be JSON booleans")
        if action.get("clear", False) and "dispatch_kW" in action:
            raise ValueError("An action cannot both clear and set dispatch")
        if not action.get("clear", False):
            dispatch = action["dispatch_kW"]
            if not isinstance(dispatch, dict) or not all(
                isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v >= 0 for k, v in dispatch.items()
            ):
                raise ValueError("dispatch_kW must map station names to finite nonnegative numbers")
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", help="V2Sim 项目目录")
    parser.add_argument("--split", type=int, help="保存/恢复断点（绝对秒）")
    for name in ("begin", "end", "step", "seed"):
        parser.add_argument("--" + name, type=int)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--every", type=int, help="每 N 步全量检查；1 为昂贵的逐步模式")
    sampling.add_argument("--samples", type=int, default=0, help="增加约 N 个中途全量采样点（默认 0）")
    parser.add_argument("--atol", type=float, default=1e-7)
    parser.add_argument("--rtol", type=float, default=1e-6)
    parser.add_argument("--max-diffs", type=int, default=50)
    parser.add_argument("--progress-interval", type=float, default=1., help="进度刷新间隔（秒，默认 1）")
    parser.add_argument("--actions", help="可选手动 V2G 指令 JSON")
    parser.add_argument("--out", help="新建的结果目录（必须不存在）")
    parser.add_argument("--_worker-job", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker_job:
        try:
            worker(json.loads(Path(args._worker_job).read_text(encoding="utf-8")))
            return 0
        except Exception:
            traceback.print_exc()
            return 2
    if not args.project or args.split is None:
        parser.error("必须指定 project 和 --split")
    output = None
    created_output = False
    try:
        from v2sim import DetectFiles, V2SimConfig
        project = Path(args.project).resolve()
        if not project.is_dir():
            raise ValueError(f"Project directory does not exist: {project}")
        files = DetectFiles(project)
        cfg = V2SimConfig.load(files.pref) if files.pref else V2SimConfig()
        defaults = {"begin": cfg.start_time, "end": cfg.end_time,
                    "step": cfg.traffic_step, "seed": cfg.seed}
        values = {k: getattr(args, k) if getattr(args, k) is not None else v for k, v in defaults.items()}
        begin, end, step = (values[k] for k in ("begin", "end", "step"))
        if not (step > 0 and begin < args.split < end and (args.split-begin) % step == 0
                and (end-begin) % step == 0):
            raise ValueError("必须满足 begin < split < end，且 split/end 都与 step 对齐")
        if (args.every is not None and args.every < 1) or args.samples < 0 or args.max_diffs < 1 or not all(
            math.isfinite(v) and v >= 0 for v in (args.atol, args.rtol)
        ):
            raise ValueError("every/max-diffs 必须为正数，samples 必须非负，atol/rtol 必须为有限非负数")
        if not math.isfinite(args.progress_interval) or args.progress_interval <= 0:
            raise ValueError("progress-interval 必须为有限正数")
        actions = parse_actions(args.actions, begin, end, step)
        total_steps = (end-begin)//step
        sample_times = {begin, args.split, end}
        for i in range(1, min(args.samples, total_steps-1)+1):
            index = round(i*total_steps/(min(args.samples, total_steps-1)+1))
            sample_times.add(begin+index*step)
        mode = "every_step" if args.every == 1 else ("periodic" if args.every else
                 ("sampled" if args.samples else "boundaries"))
        all_steps_checked = args.every == 1 or len(sample_times) == total_steps+1
        output = Path(args.out).resolve() if args.out else project.parent / ("resume_check_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        output.mkdir(parents=True, exist_ok=False)
        created_output = True
        job = dict(values, project=str(project), split=args.split, every=args.every,
                   actions=actions, checkpoint=str(output / "checkpoint"),
                   progress_interval=args.progress_interval, sample_times=sorted(sample_times),
                   verification_mode=mode, all_steps_checked=all_steps_checked)
        if args.every:
            print(f"检查模式：每 {args.every} 步全量检查；不再逐步记录车辆 CSV。", flush=True)
        else:
            print(f"快速检查：共 {len(sample_times)} 个全量检查时刻：{sorted(sample_times)}；"
                  "未采样的中间步骤不作一致性保证。", flush=True)
        print("总仿真步数为普通单次仿真的两倍，另有初始化、存读盘及采样开销。", flush=True)
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = "0"
        # Preserve the import path selected by the caller for all fresh workers.
        environment["PYTHONPATH"] = os.pathsep.join(str(Path(p or os.getcwd()).resolve()) for p in sys.path)
        workers = {}
        for phase in ("continuous", "prefix", "resumed"):
            folder = output / phase
            folder.mkdir()
            current = dict(job, phase=phase, output=str(folder))
            jobfile = output / (phase + "_job.json")
            write_json(jobfile, current)
            returncode = run_worker(jobfile, current, environment, args.progress_interval)
            if returncode:
                raise RuntimeError(f"{phase} 仿真失败；详见 {folder / 'worker.log'}")
            workers[phase] = json.loads((folder / "worker_status.json").read_text(encoding="utf-8"))
        baseline = output / "continuous/trace.jsonl.gz"
        prefix = compare(baseline, output / "prefix/trace.jsonl.gz", begin, args.split, args, "before_checkpoint")
        restore = compare(baseline, output / "resumed/trace.jsonl.gz", args.split, args.split, args, "at_restore")
        suffix = compare(baseline, output / "resumed/trace.jsonl.gz", args.split+step, end, args, "after_restore")
        checks = [prefix, restore, suffix]
        passed = all(c["difference_count"] == 0 for c in checks)
        status = "PASS" if passed else ("NONDETERMINISTIC_PREFIX" if prefix["difference_count"] else "FAIL")
        report = {"status": status, "settings": job, "atol": args.atol, "rtol": args.rtol,
                  "hash_seed": "0", "channels": list(CHANNELS), "checks": checks, "workers": workers,
                  "coverage": "车辆标量/位置统计、站点成员/排队/结算、PDN运行态、V2G、物理电网、ESS、PVWind、插件保存状态和统计通道；不比较求解器缓存及文件字节"}
        write_json(output / "report.json", report)
        print(f"{status}: {output / 'report.json'}")
        print("覆盖范围：" + ("逐步检查" if all_steps_checked else "仅检查报告中所列采样时刻"))
        print(f"耗时统计：物理仿真 {sum(w['step_seconds'] for w in workers.values()):.2f}s，"
              f"全量采样 {sum(w['snapshot_seconds'] for w in workers.values()):.2f}s，"
              f"保存断点 {sum(w['checkpoint_seconds'] for w in workers.values()):.2f}s（另有初始化/恢复开销）")
        for check in checks:
            print(f"  {check['phase']}: {check['samples_compared']} 个采样点，{check['difference_count']} 项差异")
            if check["first_difference"]:
                print("    首个差异: " + json.dumps(check["first_difference"], ensure_ascii=False))
        return 0 if passed else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if created_output:
            write_json(output / "report.json", {"status": "ERROR", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
