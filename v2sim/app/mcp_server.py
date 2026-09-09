#!/usr/bin/env python3
"""
V2Sim MCP Server
提供 V2Sim 仿真相关的工具：
1. 下载 OSM 算例（完整 SUMO 格式，保留所有文件）
2. 从高德地图下载充电站/加油站
3. 运行仿真（异步启动、查询进度、停止）
4. 读取结果数据（带缓存）
5. 列出所有可用算例
6. 将 SUMO 算例转换为 UXsim 算例
7. 生成快充站 (FCS)、慢充站 (SCS)、加油站 (GS) 配置文件
8. 列出算例中的站点信息
9. 生成车辆行程
"""

import asyncio
import datetime
import json
import math
import numbers
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server as mcp_server
import mcp.types as types
from mcp.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server import stdio

# 导入 V2Sim 所需模块
try:
    from v2sim import ConvertCase, LoadStateOption, SaveStateOptions
    from v2sim.plot import ReadOnlyStatistics
    from v2sim.utils import DetectFiles
    from v2sim.sim import TimeConfig, CommonConfig
    from v2sim.gen import TrafficGenerator, ListSelection, PricingMethod, ProcExisting
    from v2sim.gen.core import DEFAULT_CNAME
    from v2sim.gen.veh import TripsGenMode
    from v2sim.hub import LoadFCSList, LoadSCSList, LoadGSList
    from v2sim.hub.s import GS
    from v2sim.veh import Vehicle, VehType
    from v2sim.sim.pdncore import V2GStatus, GridState, V2GDispatchCheck
    # 异步仿真支持
    from v2sim.async_wrapper import simulate_async, AsyncSimHandle
except ImportError as e:
    print(f"Failed to import V2Sim modules: {e}", file=sys.stderr)
    sys.exit(1)

# 默认 case 存放目录：用户主目录下的 v2sim_cases
DEFAULT_CASES_DIR = Path.home() / "v2sim_cases"
DEFAULT_CASES_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(DEFAULT_CASES_DIR)  # 切换工作目录到默认算例目录

# 缓存 ReadOnlyStatistics 对象
_stats_cache: Dict[str, ReadOnlyStatistics] = {}

# 仿真任务管理
_sim_tasks: Dict[str, AsyncSimHandle] = {}          # task_id -> ready/starting handle
_sim_init_tasks: Dict[str, asyncio.Task] = {}         # task_id -> background initializer
_task_info: Dict[str, Dict[str, Any]] = {}            # task_id -> metadata/status

# stdio MCP shares stdout with the JSON-RPC transport.  Never use stdout for
# diagnostics here.  Optional debug breadcrumbs go to a file and stderr only.
_MCP_START_DEFER_SECONDS = max(0.05, float(os.getenv("V2SIM_MCP_START_DEFER_SECONDS", "0.50")))
_MCP_DEBUG = os.getenv("V2SIM_MCP_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
_MCP_DEBUG_FILE = DEFAULT_CASES_DIR / "v2sim_mcp_debug.log"

def _mcp_debug(message: str) -> None:
    if not _MCP_DEBUG:
        return
    line = f"[{datetime.datetime.now().isoformat(timespec='milliseconds')}] {message}"
    try:
        with _MCP_DEBUG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass

def get_stats(case_path: str) -> ReadOnlyStatistics:
    """获取或创建 ReadOnlyStatistics 实例"""
    if case_path not in _stats_cache:
        _stats_cache[case_path] = ReadOnlyStatistics(case_path)
    return _stats_cache[case_path]

def ensure_cases_dir(custom_dir: Optional[Path] = None) -> Path:
    """确保 cases 目录存在，返回其路径"""
    cases_dir = custom_dir if custom_dir is not None else DEFAULT_CASES_DIR
    cases_dir.mkdir(parents=True, exist_ok=True)
    return cases_dir

# 创建一个简单的 dummy 车辆对象，用于调用 pbuy/psell（部分价格获取器需要 veh 参数）
class DummyVehicle(Vehicle):
    def __init__(self):
        super().__init__("dummy", VehType.Private, 50, 0.5, 0.0001, 10, 1.0, 0.2, [], {})

def safe_get_price(price_getter, t: int, station, dummy_veh: Optional[Vehicle] = None):
    """安全地获取价格，若失败则返回 None"""
    if dummy_veh is None:
        dummy_veh = DummyVehicle()
    try:
        return price_getter(t, station, dummy_veh)
    except Exception:
        return None

# ================== 工具函数实现 ==================

# (保留原有辅助函数：run_simulation 被移除，其他如 read_results、list_cases 等保持不变)

def _strict_json_value(value: Any) -> Any:
    """Convert V2Sim/MCP payloads to strict JSON-safe values.

    Infinite limits are meaningful internally, but JSON-RPC consumers and web
    JSON parsers require RFC-compatible JSON.  Expose non-finite values as null.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, dict):
        return {str(k): _strict_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_strict_json_value(v) for v in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _strict_json_value(item())
        except Exception:
            pass
    return str(value)


def _json_dumps(data: Any, **kwargs: Any) -> str:
    kwargs.setdefault("allow_nan", False)
    kwargs.setdefault("default", str)
    return json.dumps(_strict_json_value(data), **kwargs)


async def read_results(
    case_path: str,
    table: str,
    column: str,
    start: int = 0,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """读取仿真结果数据，支持分页。"""
    stats = get_stats(case_path)
    seg = stats.GetColumn(table, column)
    times = seg.time
    values = seg.data
    total = len(times)

    end = min(start + limit, total) if limit > 0 else total
    if start >= total:
        return []

    result = []
    for i in range(start, end):
        result.append({"time": float(times[i]), "value": float(values[i])})
    return result

async def list_cases(cases_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出指定目录（默认 DEFAULT_CASES_DIR）中的所有可用算例。"""
    if cases_dir is not None:
        root = Path(cases_dir).resolve()
    else:
        root = DEFAULT_CASES_DIR
    if not root.exists():
        return []
    result = []
    for item in root.iterdir():
        if item.is_dir():
            files = DetectFiles(str(item))
            has_net = bool(files.net)
            has_veh = bool(files.veh)
            has_fcs = bool(files.fcs)
            has_scs = bool(files.scs)
            if has_net and has_veh and has_fcs and has_scs:
                result.append({
                    "name": item.name,
                    "path": str(item.absolute()),
                    "has_sumo": bool(files.sumo),
                    "has_ux": not bool(files.sumo),
                })
    return result

async def convert_to_uxsim(
    case_path: str,
    output_dir: Optional[str] = None,
    non_passenger_links: bool = True,
    non_scc_links: bool = True,
    auto_partition: bool = True,
    part_cnt: int = 1,
) -> str:
    """
    将 SUMO 算例转换为 UXsim 算例。
    case_path: SUMO 算例路径
    output_dir: 输出目录（默认在 case_path 同级创建 name_ux 文件夹）
    non_passenger_links: 是否保留非客运道路
    non_scc_links: 是否保留非强连通分量道路
    auto_partition: 是否自动分区
    part_cnt: 分区数（如果 auto_partition=False 则使用此值）
    返回转换后的 UXsim 算例路径。
    """
    src = Path(case_path).resolve()
    if not src.is_dir():
        raise NotADirectoryError(f"Case path does not exist or is not a directory: {case_path}")

    files = DetectFiles(str(src))
    if not files.sumo and files.net:
        # 如果没有 .sumocfg 但有 .net.xml，可能已经是 UXsim 或原始 net
        pass

    if output_dir is not None:
        out_dir = Path(output_dir).resolve()
    else:
        out_dir = src.parent / (src.name + "_ux")
    out_dir.mkdir(parents=True, exist_ok=True)

    converted = await asyncio.to_thread(
        ConvertCase,
        input_dir=str(src),
        output_dir=str(out_dir),
        part_cnt=part_cnt,
        auto_partition=auto_partition,
        non_passenger_links=non_passenger_links,
        non_scc_links=non_scc_links,
    )
    if not converted:
        raise RuntimeError(f"ConvertCase failed to convert {case_path} to UXsim.")

    return str(out_dir)

# ============ 站点生成 ============

async def generate_stations(
    case_path: str,
    station_type: str,
    slots: int = 10,
    price_buy: float = 1.5,
    price_sell: Optional[float] = None,
    seed: int = 0,
    csv_file: Optional[str] = None,
    overwrite: bool = False,
    allow_queue: Optional[bool] = None,
) -> str:
    """
    生成 FCS、SCS 或 GS 配置文件。
    station_type: 'fcs', 'scs', 'gs'
    slots: 每个站点的插槽数（充电桩或加油枪）
    price_buy: 用户购电/购油价格 ($/kWh 或 $/L)
    price_sell: 用户卖电价格 ($/kWh)，仅对 scs 有效（None 表示不支持 V2G）
    seed: 随机种子
    csv_file: 可选 CSV 文件（由 download_stations 生成），若提供则使用该文件中的站点位置
    overwrite: 若已存在同名文件是否覆盖
    allow_queue: 是否允许排队，默认 fcs/gs 为 True，scs 为 False
    """
    case_dir = Path(case_path).resolve()
    if not case_dir.is_dir():
        raise NotADirectoryError(f"Case path does not exist: {case_path}")

    # 检查网络文件
    files = DetectFiles(str(case_dir))
    if not files.net:
        raise FileNotFoundError(f"No network file found in {case_path}")

    # 检测现有站点文件
    existing_file = None
    if station_type == "fcs" and files.fcs:
        existing_file = files.fcs
    elif station_type == "scs" and files.scs:
        existing_file = files.scs
    elif station_type == "gs" and files.gs:
        existing_file = files.gs
    if existing_file and not overwrite:
        raise FileExistsError(f"{station_type.upper()} file already exists: {existing_file} (use overwrite=True to replace)")

    # 创建 TrafficGenerator 实例，设置 existing 处理方式
    proc_existing = ProcExisting.OVERWRITE if overwrite else ProcExisting.SKIP
    gen = TrafficGenerator(str(case_dir), silent=True, existing=proc_existing)

    # 根据类型调用相应方法
    if station_type == "fcs":
        gen.FCS(
            seed=seed,
            slots=slots,
            file=csv_file or "",
            bus=ListSelection.ALL,
            busCount=-1,
            grid_file=files.grid or "",
            givenBus=[],
            cs=ListSelection.ALL,
            csCount=-1,
            givenCS=[],
            priceBuyMethod=PricingMethod.FIXED,
            priceBuy=price_buy,
            priceBuyIsServiceFee=False,
        )
        generated_file = Path(case_dir) / f"{case_dir.name}.fcs.xml"
    elif station_type == "scs":
        has_sell = price_sell is not None
        gen.SCS(
            seed=seed,
            slots=slots,
            file=csv_file or "",
            bus=ListSelection.ALL,
            busCount=-1,
            grid_file=files.grid or "",
            givenBus=[],
            cs=ListSelection.ALL,
            csCount=-1,
            givenCS=[],
            priceBuyMethod=PricingMethod.FIXED,
            priceBuy=price_buy,
            priceBuyIsServiceFee=False,
            priceSellMethod=PricingMethod.FIXED if has_sell else PricingMethod.FIXED,
            priceSellIsServiceFee=False,
            priceSell=price_sell if has_sell else 0.0,
        )
        generated_file = Path(case_dir) / f"{case_dir.name}.scs.xml"
    elif station_type == "gs":
        gen.GS(
            seed=seed,
            slots=slots,
            file=csv_file or "",
            gs=ListSelection.ALL,
            gsCount=-1,
            givenGS=[],
            priceBuyMethod=PricingMethod.FIXED,
            priceBuy=price_buy,
            priceBuyIsServiceFee=False,
        )
        generated_file = Path(case_dir) / f"{case_dir.name}.gs.xml"
    else:
        raise ValueError(f"Unsupported station type: {station_type}")

    # 验证文件是否生成
    if not generated_file.exists():
        candidates = list(case_dir.glob(f"*.{station_type}.xml")) + list(case_dir.glob(f"*.{station_type}.xml.gz"))
        if candidates:
            generated_file = candidates[0]
        else:
            raise RuntimeError(f"Failed to generate {station_type.upper()} file.")

    return str(generated_file)

# ============ 列出站点 ============

async def list_stations(case_path: str, station_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    列出算例中的站点信息。
    station_type: 可选 'fcs', 'scs', 'gs'，不指定则列出全部。
    """
    case_dir = Path(case_path).resolve()
    if not case_dir.is_dir():
        raise NotADirectoryError(f"Case path does not exist: {case_path}")

    files = DetectFiles(str(case_dir))
    result = []
    dummy_veh = DummyVehicle()

    def parse_stations(file_path: str, type_name: str) -> List[Dict[str, Any]]:
        if not file_path:
            return []
        if type_name == "fcs":
            stations = LoadFCSList(file_path)
        elif type_name == "scs":
            stations = LoadSCSList(file_path)
        elif type_name == "gs":
            stations = LoadGSList(file_path)
        else:
            return []
        info = []
        for s in stations:
            entry = {
                "name": s.name,
                "bind": s.bind,
                "slots": s.slots,
                "x": s.x,
                "y": s.y,
                "allow_queue": s._allow_que if hasattr(s, '_allow_que') else None,
            }
            # 获取价格（若可用）
            if hasattr(s, '_pbuy'):
                entry["price_buy"] = safe_get_price(s._pbuy, 0, s, dummy_veh)
            if not isinstance(s, GS) and hasattr(s, '_psell') and s._psell is not None:
                entry["price_sell"] = safe_get_price(s._psell, 0, s, dummy_veh)
            # 对于 CS 子类，添加 bus 属性
            if not isinstance(s, GS) and hasattr(s, 'bus'):
                entry["bus"] = s.bus
            info.append(entry)
        return info

    if station_type is None or station_type == "fcs":
        result.extend(parse_stations(files.fcs or "", "fcs"))
    if station_type is None or station_type == "scs":
        result.extend(parse_stations(files.scs or "", "scs"))
    if station_type is None or station_type == "gs":
        result.extend(parse_stations(files.gs or "", "gs"))

    return result

# ============ 生成行程 ============

async def generate_trips(
    case_path: str,
    num_ev: int = 0,
    num_gv: int = 0,
    days: int = 7,
    seed: int = 0,
    v2g_prop: float = 1.0,
    mode: str = "auto",
    cname: Optional[str] = None,
    overwrite: bool = False,
    workers: Optional[int] = None,
) -> str:
    """
    生成车辆行程文件。
    num_ev: 电动车数量
    num_gv: 燃油车数量（至少一个 >0）
    days: 仿真天数
    seed: 随机种子
    v2g_prop: 电动车参与 V2G 的比例
    mode: 生成模式 'auto', 'node', 'taz', 'poly'
    cname: 行程参数文件夹路径（默认使用 v2sim 内置）
    overwrite: 是否覆盖已有的 veh 文件
    workers: 并行生成时的进程数（None 表示顺序生成）
    """
    if num_ev <= 0 and num_gv <= 0:
        raise ValueError("At least one of num_ev or num_gv must be > 0")

    case_dir = Path(case_path).resolve()
    if not case_dir.is_dir():
        raise NotADirectoryError(f"Case path does not exist: {case_path}")

    files = DetectFiles(str(case_dir))
    if files.veh and not overwrite:
        raise FileExistsError(f"Vehicle file already exists: {files.veh} (use overwrite=True to replace)")

    gen = TrafficGenerator(str(case_dir), silent=True, existing=ProcExisting.OVERWRITE if overwrite else ProcExisting.SKIP)

    # 组装 n 参数
    if num_ev > 0 and num_gv > 0:
        n = (num_ev, num_gv)
    else:
        n = num_ev + num_gv

    # 转换 mode 字符串为 TripsGenMode
    mode_map = {
        "auto": TripsGenMode.AUTO,
        "node": TripsGenMode.NODE,
        "taz": TripsGenMode.TAZ,
        "poly": TripsGenMode.POLY,
    }
    if mode not in mode_map:
        raise ValueError(f"Unsupported mode: {mode}")
    mode_enum = mode_map[mode]

    # 使用 VTrips 方法（它会根据 case 自动选择 SUMO 或 UXsim 生成器）
    veh_dict = await asyncio.to_thread(
        gen.VTrips,
        n=n,
        seed=seed,
        day_count=days,
        save=True,
        cname=cname if cname else DEFAULT_CNAME,
        mode=mode_enum,
        v2g_prop=v2g_prop,
        workers=workers,
    )

    # 确定生成的文件名
    veh_file = case_dir / f"{case_dir.name}.veh.xml.gz"
    if not veh_file.exists():
        veh_file_alt = case_dir / f"{case_dir.name}.veh.xml"
        if veh_file_alt.exists():
            veh_file = veh_file_alt
        else:
            raise RuntimeError(f"Vehicle file not found after generation: {veh_file}")

    return str(veh_file)

# ================== 异步仿真启动/查询/停止 ==================

def _normalize_logging_items(value: Any, step_length: int) -> Optional[Dict[str, int]]:
    """Normalize optional MCP logging configuration to V2Sim logging_items.

    This is transport/configuration only and does not change any power semantics.
    Intervals are counts of simulation steps.  ``None`` preserves V2Sim defaults.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        result: Dict[str, int] = {}
        for raw in text.split(','):
            item = raw.strip()
            if not item:
                continue
            if ':' in item:
                name, interval = item.split(':', 1)
                name = name.strip()
                try:
                    n = int(interval.strip())
                except ValueError as e:
                    raise ValueError(f"Invalid logging interval in {item!r}") from e
            else:
                name = item
                if name in ("fcs", "scs", "gs"):
                    n = max(1, 60 // max(1, int(step_length)))
                elif name in ("bus", "gen", "line", "pvw", "ess"):
                    n = max(1, 900 // max(1, int(step_length)))
                else:
                    n = 1
            if not name:
                raise ValueError("Logging item name cannot be empty")
            if n <= 0:
                raise ValueError(f"Logging interval for {name!r} must be positive")
            result[name] = n
        return result or None
    if isinstance(value, dict):
        result: Dict[str, int] = {}
        for raw_name, raw_interval in value.items():
            name = str(raw_name).strip()
            if not name:
                raise ValueError("Logging item name cannot be empty")
            try:
                n = int(raw_interval)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid logging interval for {name!r}: {raw_interval!r}") from e
            if n <= 0:
                raise ValueError(f"Logging interval for {name!r} must be positive")
            result[name] = n
        return result or None
    raise TypeError("log must be a comma-separated string, an object mapping names to step intervals, or null")

async def _initialize_simulation_task(
    task_id: str,
    case_path: str,
    start_time: int,
    end_time: int,
    step_length: int,
    seed: int,
    silent: bool,
    start_paused: bool,
    v2g_manual_interval: int,
    logging_items: Optional[Dict[str, int]],
) -> None:
    """Background initializer for a simulation task.

    Heavy project parsing and V2Sim/UXsim startup must not hold the MCP
    start_simulation request open.  Status transitions are exposed through
    query_simulation: initializing -> running -> finished/stopped/error.
    """
    try:
        _mcp_debug(f"initializer entered task_id={task_id}")
        _task_info[task_id]["initialization_phase"] = "loading_project"
        _mcp_debug(f"loading_project task_id={task_id}")
        time_cfg = TimeConfig(start_time, step_length, end_time)
        common_cfg = CommonConfig()

        handle = await simulate_async(
            proj_dir=case_path,
            time=time_cfg,
            break_at=end_time,
            out_dir=None,
            seed=seed,
            silent=silent,
            vscfg=common_cfg,
            state_option=LoadStateOption.Skip,
            save_option=SaveStateOptions.OnFinish,
            start_paused=start_paused,
            manual_v2g_dispatch_interval=v2g_manual_interval,
            logging_items=logging_items,
        )
        _sim_tasks[task_id] = handle
        _mcp_debug(f"simulate_async returned handle task_id={task_id}")
        _task_info[task_id]["initialization_phase"] = "starting_simulation"

        # _run() sets the ready event after V2SimInstance.start() completes.
        # That startup itself runs off the event loop in AsyncSimHandle._run.
        await handle.wait_until_ready()

        # If startup failed, _run may already have terminated.  Await it here
        # once so the original exception is captured in task metadata.
        if not handle.is_running:
            if handle._task is not None and handle._task.done():
                await handle.wait()
            if handle.result is False:
                raise RuntimeError("Simulation stopped during initialization.")

        _task_info[task_id]["status"] = "running"
        _task_info[task_id]["initialization_phase"] = "ready"
        _mcp_debug(f"simulation ready task_id={task_id}")
        asyncio.create_task(_monitor_simulation(task_id, handle))
    except asyncio.CancelledError:
        _task_info[task_id]["status"] = "stopped"
        _task_info[task_id]["initialization_phase"] = "cancelled"
        raise
    except Exception as e:
        _mcp_debug(f"initializer error task_id={task_id}: {type(e).__name__}: {e}")
        _task_info[task_id]["status"] = "error"
        _task_info[task_id]["initialization_phase"] = "failed"
        _task_info[task_id]["error"] = f"{type(e).__name__}: {e}"
    finally:
        _sim_init_tasks.pop(task_id, None)


async def _deferred_initialize_simulation_task(
    task_id: str,
    case_path: str,
    start_time: int,
    end_time: int,
    step_length: int,
    seed: int,
    silent: bool,
    start_paused: bool,
    v2g_manual_interval: int,
    logging_items: Optional[Dict[str, int]],
) -> None:
    """Yield a grace period before any heavy initialization begins.

    This is intentional for stdio MCP: it gives the server enough time to
    serialize and flush the start_simulation response before V2Sim/UXsim
    project loading starts in the background.
    """
    _task_info[task_id]["initialization_phase"] = "response_grace_period"
    _mcp_debug(
        f"deferred initializer sleeping {_MCP_START_DEFER_SECONDS:.2f}s task_id={task_id}"
    )
    await asyncio.sleep(_MCP_START_DEFER_SECONDS)
    await _initialize_simulation_task(
        task_id, case_path, start_time, end_time, step_length, seed, silent,
        start_paused, v2g_manual_interval, logging_items,
    )


def start_simulation_task(
    case_path: str,
    start_time: int = 0,
    end_time: int = 172800,
    step_length: int = 10,
    seed: int = 0,
    silent: bool = True,
    start_paused: bool = False,
    v2g_manual_interval: int = 900,
    logging_items: Optional[Dict[str, int]] = None,
) -> str:
    """Register an asynchronous simulation and return task_id immediately.

    This function deliberately contains no ``await``.  It performs only cheap
    validation/metadata registration and schedules a deferred initializer.
    Heavy project parsing and UXsim/V2Sim startup happen after a short grace
    period, allowing the stdio MCP response to be flushed first.
    """
    case_path = str(Path(case_path).expanduser().resolve())
    if not Path(case_path).is_dir():
        raise NotADirectoryError(f"Case path does not exist: {case_path}")

    task_id = uuid.uuid4().hex
    _task_info[task_id] = {
        "case_path": case_path,
        "start_time": start_time,
        "end_time": end_time,
        "step_length": step_length,
        "seed": seed,
        "silent": silent,
        "start_paused": start_paused,
        "v2g_manual_interval": v2g_manual_interval,
        "logging_items": dict(logging_items) if logging_items is not None else None,
        "status": "initializing",
        "initialization_phase": "registered",
        "created_at": datetime.datetime.now().isoformat(),
    }
    _mcp_debug(f"registered task_id={task_id} case={case_path}")

    init_task = asyncio.get_running_loop().create_task(
        _deferred_initialize_simulation_task(
            task_id, case_path, start_time, end_time, step_length, seed, silent,
            start_paused, v2g_manual_interval, logging_items,
        ),
        name=f"v2sim-init-{task_id}",
    )
    _sim_init_tasks[task_id] = init_task
    _mcp_debug(f"scheduled deferred initializer task_id={task_id}")
    return task_id


async def _monitor_simulation(task_id: str, handle: AsyncSimHandle):
    """监控仿真任务，完成后更新状态。"""
    try:
        result = await handle.wait()
        status = "finished" if result else "stopped"
    except Exception as e:
        status = "error"
        _task_info[task_id]["error"] = str(e)
    finally:
        _task_info[task_id]["status"] = status
        if status == "finished":
            # 记录结果目录
            if hasattr(handle, '_inst'):
                _task_info[task_id]["result_dir"] = handle._inst.result_dir

async def query_simulation(task_id: str) -> Dict[str, Any]:
    """Query task state, including background initialization progress."""
    if task_id not in _task_info:
        raise ValueError(f"Task ID {task_id} not found.")

    info = _task_info[task_id].copy()
    handle = _sim_tasks.get(task_id)
    if handle is None:
        # Preserve compatibility with clients that interpret is_running=False
        # as terminal.  An initializing task is active even though its live
        # AsyncSimHandle has not been published yet.
        active = info.get("status") in {"initializing", "running", "stopping"}
        info.update({
            "progress": 0.0,
            "current_time": info.get("start_time"),
            "time": info.get("start_time"),
            "is_running": active,
            "is_paused": False,
            "manual_v2g_mode": False,
            "awaiting_agent_dispatch": False,
            "pause_reason": None,
            "manual_v2g_dispatch_interval_s": None,
            "next_manual_v2g_dispatch_time": None,
        })
        return info

    info["progress"] = handle.progress
    info["is_running"] = handle.is_running
    info["is_paused"] = handle.is_paused
    # Expose the exact simulation clock.  The dashboard/agent previously had
    # only progress and therefore could not display an exact sim_time.
    try:
        current_time = int(handle._inst.ctime)
    except Exception:
        current_time = None
    info["current_time"] = current_time
    info["time"] = current_time  # backward-friendly alias
    info.update(handle.get_control_status())
    if not handle.is_running and info.get("status") == "running":
        if handle.result is not None:
            info["status"] = "finished" if handle.result else "stopped"
    return info


async def stop_simulation(task_id: str, wait: bool = True) -> str:
    """Stop a simulation, including one that is still initializing."""
    if task_id not in _task_info:
        raise ValueError(f"Task ID {task_id} not found.")

    handle = _sim_tasks.get(task_id)
    if handle is None:
        # asyncio.to_thread work cannot be force-killed safely.  Mark the task
        # stopped; the initializer will not be exposed as running to clients.
        _task_info[task_id]["status"] = "stopped"
        _task_info[task_id]["initialization_phase"] = "stop_requested"
        init_task = _sim_init_tasks.get(task_id)
        if init_task is not None:
            init_task.cancel()
        return "Stop requested during initialization."

    if not handle.is_running:
        return "Task is not running."
    handle.stop()
    if wait:
        await handle.wait()
    return "Stop signal sent."


def _require_ready_handle(task_id: str) -> AsyncSimHandle:
    if task_id not in _task_info:
        raise ValueError(f"Task ID {task_id} not found.")
    handle = _sim_tasks.get(task_id)
    if handle is None:
        status = _task_info[task_id].get("status", "initializing")
        phase = _task_info[task_id].get("initialization_phase")
        raise RuntimeError(
            f"Simulation {task_id} is not ready (status={status}, phase={phase}). "
            "Query the task until status='running'."
        )
    return handle


async def pause_simulation(task_id: str) -> Dict[str, Any]:
    handle = _require_ready_handle(task_id)
    handle.pause()
    return await query_simulation(task_id)


async def resume_simulation(task_id: str) -> Dict[str, Any]:
    handle = _require_ready_handle(task_id)
    handle.resume()
    return await query_simulation(task_id)


async def step_simulation(task_id: str) -> Dict[str, Any]:
    handle = _require_ready_handle(task_id)
    await handle.step_once()
    info = await query_simulation(task_id)
    if handle.is_running:
        info["v2g"] = handle.get_v2g_status()
    return info


async def get_v2g_status(task_id: str) -> V2GStatus:
    """Return live V2G bid curves, capacity and dispatch for a simulation."""
    return _require_ready_handle(task_id).get_v2g_status()


async def get_grid_state(task_id: str) -> GridState:
    """Return the latest solved PDN state and current grid prices."""
    return _require_ready_handle(task_id).get_grid_state()


async def check_v2g_dispatch(
    task_id: str, dispatch_kW: Dict[str, float], replace: bool = True
) -> V2GDispatchCheck:
    """Preflight-check a manual V2G dispatch without modifying the simulation."""
    return _require_ready_handle(task_id).check_manual_v2g_dispatch(dispatch_kW, replace)


async def set_v2g_dispatch(task_id: str, dispatch_kW: Dict[str, float], replace: bool = True) -> V2GStatus:
    """Set persistent station V2G targets for a v2g_manual simulation."""
    handle = _require_ready_handle(task_id)
    handle.set_manual_v2g_dispatch(dispatch_kW, replace)
    return handle.get_v2g_status()


async def clear_v2g_dispatch(task_id: str) -> V2GStatus:
    """Clear all manual V2G targets for a v2g_manual simulation."""
    handle = _require_ready_handle(task_id)
    handle.clear_manual_v2g_dispatch()
    return handle.get_v2g_status()

# ================== MCP 服务器 ==================

app = mcp_server.Server("v2sim-server")

@app.list_tools()
async def list_tools() -> List[types.Tool]:
    return [
        # ---------- 异步仿真管理工具 ----------
        types.Tool(
            name="start_simulation",
            description=(
                "Queue an asynchronous V2Sim simulation and return task_id immediately. "
                "Initialization continues in the background; query_simulation may initially return status='initializing'. "
                "WARNING: Running multiple simulations concurrently may cause severe CPU contention."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "start_time": {"type": "integer", "description": "Start time (seconds)", "default": 0},
                    "end_time": {"type": "integer", "description": "End time (seconds)", "default": 172800},
                    "step_length": {"type": "integer", "description": "Simulation step length (seconds)", "default": 10},
                    "seed": {"type": "integer", "description": "Random seed", "default": 0},
                    "silent": {"type": "boolean", "description": "Suppress output", "default": True},
                    "start_paused": {
                        "type": "boolean",
                        "description": "Force an initial pause. v2g_manual pauses automatically while V2G is online, so this is normally unnecessary for agent dispatch.",
                        "default": False,
                    },
                    "v2g_manual_interval": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Agent dispatch interval in seconds for charging_mode='v2g_manual'. Default 900 s (15 min). The simulation auto-pauses at each interval while V2G is online.",
                        "default": 900,
                    },
                    "log": {
                        "description": (
                            "Optional V2Sim result logging configuration. Use a string such as "
                            "'fcs:1,scs:1,bus:90' or an object such as {'fcs': 1, 'scs': 1}. "
                            "Intervals are counts of simulation steps. Omit this field to preserve V2Sim defaults."
                        ),
                        "anyOf": [
                            {"type": "string"},
                            {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}},
                        ],
                    },
                },
                "required": ["case_path"],
            },
        ),
        types.Tool(
            name="list_running_simulations",
            description="List all currently running simulation tasks.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="query_simulation",
            description="Query the status and progress of a previously started simulation task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="stop_simulation",
            description="Stop a running simulation task. Optionally wait for it to finish cleanly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to stop"},
                    "wait": {"type": "boolean", "description": "Wait for the task to fully terminate", "default": True},
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="pause_simulation",
            description="Pause a running simulation before its next step.",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="resume_simulation",
            description="Resume a paused simulation. In v2g_manual it runs until the next configured agent-dispatch epoch, then auto-pauses again.",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="step_simulation",
            description=(
                "Advance exactly one simulation step and remain paused. This is mainly for debugging; "
                "normal v2g_manual agent dispatch should use set_v2g_dispatch + resume_simulation and wait for the next auto-pause."
            ),
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="get_v2g_status",
            description=(
                "Get live instantaneous V2G bid-price/bid-quantity curves, instantaneous available capacity, dispatch, per-station nodal OPF shadow prices, fallback state, and agent-control timing. "
                "Energy headroom is also exposed separately as energy_headroom_kWh and grid_deliverable_energy_kWh for duration-aware agent reasoning; it never replaces or rescales instantaneous capacity_kW. "
                "Use stations[].shadow_price_per_kWh (or effective_*_price_per_kWh) for economic decisions; cprice/dprice are fallback only when a node has no shadow price. "
                "In charging_mode='v2g_manual', call this when awaiting_agent_dispatch is true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="get_grid_state",
            description=(
                "Get the latest solved distribution-grid state for an agent: bus voltages, line loading, "
                "violations, aggregate EV charging/V2G power, and per-bus OPF shadow prices. "
                "Use buses[].shadow_price_per_kWh as the primary nodal energy-value signal. "
                "Configured cprice/dprice are exposed only as fallback values for buses without a usable shadow price."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="check_v2g_dispatch",
            description=(
                "Preflight-check a v2g_manual station dispatch without changing simulation state. "
                "It validates station names, values, V2G online state, instantaneous EV capacity, and minimum V2G bid acceptance against the effective nodal sell price. "
                "Candidate-specific grid feasibility is validated by the PDN solve when the command executes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                    "dispatch_kW": {
                        "type": "object",
                        "description": "Mapping from charging-station name to non-negative V2G target in kW",
                        "additionalProperties": {"type": "number"},
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "Check as a full replacement; false merges with current targets",
                        "default": True,
                    },
                },
                "required": ["task_id", "dispatch_kW"],
            },
        ),
        types.Tool(
            name="set_v2g_dispatch",
            description=(
                "Set persistent manual V2G discharge targets by charging station for a v2g_manual simulation. "
                "Values are instantaneous kW targets. If v2g_manual_fallback_to_v2g is enabled, infeasible manual commands "
                "fall back to the original market/OPF V2G mechanism; otherwise a preflight-infeasible command is rejected."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                    "dispatch_kW": {
                        "type": "object",
                        "description": "Mapping from charging-station name to non-negative V2G target in kW",
                        "additionalProperties": {"type": "number", "minimum": 0},
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "Replace all previous targets; false updates only named stations",
                        "default": True,
                    },
                },
                "required": ["task_id", "dispatch_kW"],
            },
        ),
        types.Tool(
            name="clear_v2g_dispatch",
            description="Clear all persistent manual V2G discharge targets for a simulation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by start_simulation"},
                },
                "required": ["task_id"],
            },
        ),
        # ---------- 其他工具 ----------
        types.Tool(
            name="read_results",
            description="Read simulation result data from a case. Data is cached for performance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory (or results subdirectory)"},
                    "table": {"type": "string", "description": "Table name (e.g., fcs, scs, gs, ev, gen, bus, line, pvw, ess)"},
                    "column": {"type": "string", "description": "Column name (e.g., c, cnt, soc, P, V, etc.)"},
                    "start": {"type": "integer", "description": "Start index for pagination", "default": 0},
                    "limit": {"type": "integer", "description": "Number of records to return (-1 for all)", "default": 1000},
                },
                "required": ["case_path", "table", "column"],
            },
        ),
        types.Tool(
            name="list_cases",
            description="List all available cases in the default cases directory (or a custom directory).",
            inputSchema={
                "type": "object",
                "properties": {
                    "cases_dir": {"type": "string", "description": f"Optional path to the cases directory. Default is {Path.home() / 'v2sim_cases'}"},
                },
            },
        ),
        types.Tool(
            name="convert_to_uxsim",
            description="Convert a SUMO case to a UXsim case.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the SUMO case directory"},
                    "output_dir": {"type": "string", "description": "Optional output directory. Default is case_path + '_ux'"},
                    "non_passenger_links": {"type": "boolean", "description": "Keep non-passenger roads", "default": True},
                    "non_scc_links": {"type": "boolean", "description": "Keep roads outside the largest SCC", "default": True},
                    "auto_partition": {"type": "boolean", "description": "Auto-determine partition count", "default": True},
                    "part_cnt": {"type": "integer", "description": "Partition count (if auto_partition=False)", "default": 1},
                },
                "required": ["case_path"],
            },
        ),
        # ---------- 站点生成 ----------
        types.Tool(
            name="generate_fcs",
            description="Generate Fast Charging Station (FCS) configuration for a case.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "slots": {"type": "integer", "description": "Number of charging piles per station", "default": 10},
                    "price_buy": {"type": "number", "description": "Energy purchase price for users ($/kWh)", "default": 1.5},
                    "seed": {"type": "integer", "description": "Random seed", "default": 0},
                    "csv_file": {"type": "string", "description": "Optional CSV file with station locations (from download_stations)"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing FCS file", "default": False},
                },
                "required": ["case_path"],
            },
        ),
        types.Tool(
            name="generate_scs",
            description="Generate Slow Charging Station (SCS) configuration for a case.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "slots": {"type": "integer", "description": "Number of charging piles per station", "default": 10},
                    "price_buy": {"type": "number", "description": "Energy purchase price for users ($/kWh)", "default": 1.5},
                    "price_sell": {"type": "number", "description": "Energy sell price for users ($/kWh) – if omitted, V2G is disabled"},
                    "seed": {"type": "integer", "description": "Random seed", "default": 0},
                    "csv_file": {"type": "string", "description": "Optional CSV file with station locations"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing SCS file", "default": False},
                },
                "required": ["case_path"],
            },
        ),
        types.Tool(
            name="generate_gs",
            description="Generate Gas Station (GS) configuration for a case.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "slots": {"type": "integer", "description": "Number of fuel pumps per station", "default": 10},
                    "price_buy": {"type": "number", "description": "Fuel price for users ($/L)", "default": 1.5},
                    "seed": {"type": "integer", "description": "Random seed", "default": 0},
                    "csv_file": {"type": "string", "description": "Optional CSV file with station locations"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing GS file", "default": False},
                },
                "required": ["case_path"],
            },
        ),
        types.Tool(
            name="list_stations",
            description="List all stations (FCS, SCS, GS) in a case, optionally filtered by type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "station_type": {"type": "string", "enum": ["fcs", "scs", "gs"], "description": "Filter by station type (optional)"},
                },
                "required": ["case_path"],
            },
        ),
        types.Tool(
            name="generate_trips",
            description="Generate vehicle trips (EV and/or GV) for a case.",
            inputSchema={
                "type": "object",
                "properties": {
                    "case_path": {"type": "string", "description": "Path to the case directory"},
                    "num_ev": {"type": "integer", "description": "Number of electric vehicles", "default": 0},
                    "num_gv": {"type": "integer", "description": "Number of gasoline vehicles", "default": 0},
                    "days": {"type": "integer", "description": "Number of simulation days", "default": 7},
                    "seed": {"type": "integer", "description": "Random seed", "default": 0},
                    "v2g_prop": {"type": "number", "description": "Proportion of EVs willing to participate in V2G (0-1)", "default": 1.0},
                    "mode": {"type": "string", "enum": ["auto", "node", "taz", "poly"], "description": "Trip generation mode", "default": "auto"},
                    "cname": {"type": "string", "description": "Path to trip parameter folder (optional)"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing vehicle file", "default": False},
                    "workers": {"type": "integer", "description": "Number of parallel workers (optional, >1 enables parallel generation)"},
                },
                "required": ["case_path"],
            },
        ),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    try:
        if name == "start_simulation":
            case_path = arguments["case_path"]
            requested_silent = bool(arguments.get("silent", True))
            if not requested_silent:
                _mcp_debug(
                    "start_simulation requested silent=False; forcing silent=True because "
                    "stdio MCP reserves stdout for JSON-RPC framing"
                )
            step_length = int(arguments.get("step_length", 10))
            logging_items = _normalize_logging_items(arguments.get("log"), step_length)
            kwargs = {
                "start_time": arguments.get("start_time", 0),
                "end_time": arguments.get("end_time", 172800),
                "step_length": step_length,
                "seed": arguments.get("seed", 0),
                # stdout belongs exclusively to the stdio MCP transport.
                "silent": True,
                "start_paused": arguments.get("start_paused", False),
                "v2g_manual_interval": arguments.get("v2g_manual_interval", 900),
                "logging_items": logging_items,
            }
            _mcp_debug(f"call_tool start_simulation entered case={case_path}")
            task_id = start_simulation_task(case_path, **kwargs)
            payload = _json_dumps({"task_id": task_id}, indent=2)
            _mcp_debug(f"call_tool start_simulation returning task_id={task_id}")
            return [types.TextContent(type="text", text=payload)]

        elif name == "list_running_simulations":
            running_tasks = []
            for task_id, meta in _task_info.items():
                if meta.get("status") not in {"initializing", "running", "stopping"}:
                    continue
                info = await query_simulation(task_id)
                info["task_id"] = task_id
                running_tasks.append(info)
            json_data = _json_dumps(running_tasks, indent=2)
            return [types.TextContent(type="text", text=json_data)]
        
        elif name == "query_simulation":
            task_id = arguments["task_id"]
            info = await query_simulation(task_id)
            return [types.TextContent(type="text", text=_json_dumps(info, indent=2))]
        
        elif name == "stop_simulation":
            task_id = arguments["task_id"]
            wait = arguments.get("wait", True)
            msg = await stop_simulation(task_id, wait)
            return [types.TextContent(type="text", text=msg)]

        elif name == "pause_simulation":
            info = await pause_simulation(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(info, indent=2))]

        elif name == "resume_simulation":
            info = await resume_simulation(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(info, indent=2))]

        elif name == "step_simulation":
            info = await step_simulation(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(info, indent=2))]

        elif name == "get_v2g_status":
            status = await get_v2g_status(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(status, indent=2))]

        elif name == "get_grid_state":
            state = await get_grid_state(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(state, indent=2))]

        elif name == "check_v2g_dispatch":
            check = await check_v2g_dispatch(
                arguments["task_id"], arguments["dispatch_kW"], arguments.get("replace", True)
            )
            return [types.TextContent(type="text", text=_json_dumps(check, indent=2))]

        elif name == "set_v2g_dispatch":
            status = await set_v2g_dispatch(
                arguments["task_id"], arguments["dispatch_kW"], arguments.get("replace", True)
            )
            return [types.TextContent(type="text", text=_json_dumps(status, indent=2))]

        elif name == "clear_v2g_dispatch":
            status = await clear_v2g_dispatch(arguments["task_id"])
            return [types.TextContent(type="text", text=_json_dumps(status, indent=2))]

        elif name == "read_results":
            case_path = arguments["case_path"]
            table = arguments["table"]
            column = arguments["column"]
            start = arguments.get("start", 0)
            limit = arguments.get("limit", 1000)
            data = await read_results(case_path, table, column, start, limit)
            json_data = _json_dumps(data)
            return [types.TextContent(type="text", text=json_data)]

        elif name == "list_cases":
            cases_dir = arguments.get("cases_dir")
            cases = await list_cases(cases_dir)
            json_data = _json_dumps(cases, indent=2)
            return [types.TextContent(type="text", text=json_data)]

        elif name == "convert_to_uxsim":
            case_path = arguments["case_path"]
            output_dir = arguments.get("output_dir")
            non_passenger_links = arguments.get("non_passenger_links", True)
            non_scc_links = arguments.get("non_scc_links", True)
            auto_partition = arguments.get("auto_partition", True)
            part_cnt = arguments.get("part_cnt", 1)
            ux_path = await convert_to_uxsim(
                case_path, output_dir,
                non_passenger_links, non_scc_links,
                auto_partition, part_cnt
            )
            return [types.TextContent(type="text", text=f"UXsim case created at: {ux_path}")]

        elif name == "generate_fcs":
            case_path = arguments["case_path"]
            slots = arguments.get("slots", 10)
            price_buy = arguments.get("price_buy", 1.5)
            seed = arguments.get("seed", 0)
            csv_file = arguments.get("csv_file")
            overwrite = arguments.get("overwrite", False)
            out_file = await generate_stations(
                case_path, "fcs",
                slots=slots, price_buy=price_buy, seed=seed,
                csv_file=csv_file, overwrite=overwrite
            )
            return [types.TextContent(type="text", text=f"FCS file generated: {out_file}")]

        elif name == "generate_scs":
            case_path = arguments["case_path"]
            slots = arguments.get("slots", 10)
            price_buy = arguments.get("price_buy", 1.5)
            price_sell = arguments.get("price_sell")
            seed = arguments.get("seed", 0)
            csv_file = arguments.get("csv_file")
            overwrite = arguments.get("overwrite", False)
            out_file = await generate_stations(
                case_path, "scs",
                slots=slots, price_buy=price_buy, price_sell=price_sell,
                seed=seed, csv_file=csv_file, overwrite=overwrite
            )
            return [types.TextContent(type="text", text=f"SCS file generated: {out_file}")]

        elif name == "generate_gs":
            case_path = arguments["case_path"]
            slots = arguments.get("slots", 10)
            price_buy = arguments.get("price_buy", 1.5)
            seed = arguments.get("seed", 0)
            csv_file = arguments.get("csv_file")
            overwrite = arguments.get("overwrite", False)
            out_file = await generate_stations(
                case_path, "gs",
                slots=slots, price_buy=price_buy, seed=seed,
                csv_file=csv_file, overwrite=overwrite
            )
            return [types.TextContent(type="text", text=f"GS file generated: {out_file}")]

        elif name == "list_stations":
            case_path = arguments["case_path"]
            station_type = arguments.get("station_type")
            stations = await list_stations(case_path, station_type)
            json_data = _json_dumps(stations, indent=2)
            return [types.TextContent(type="text", text=json_data)]

        elif name == "generate_trips":
            case_path = arguments["case_path"]
            num_ev = arguments.get("num_ev", 0)
            num_gv = arguments.get("num_gv", 0)
            days = arguments.get("days", 7)
            seed = arguments.get("seed", 0)
            v2g_prop = arguments.get("v2g_prop", 1.0)
            mode = arguments.get("mode", "auto")
            cname = arguments.get("cname")
            overwrite = arguments.get("overwrite", False)
            workers = arguments.get("workers")
            out_file = await generate_trips(
                case_path, num_ev, num_gv, days, seed,
                v2g_prop, mode, cname, overwrite, workers
            )
            return [types.TextContent(type="text", text=f"Vehicle trips generated: {out_file}")]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except asyncio.TimeoutError:
        return [types.TextContent(type="text", text="Error: Operation timed out. Please try again or consider increasing the client timeout.")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    async with stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="v2sim-server",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

def entry():
    asyncio.run(main())

if __name__ == "__main__":
    entry()