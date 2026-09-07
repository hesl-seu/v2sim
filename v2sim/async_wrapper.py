import asyncio
from typing import List, Optional, Callable, Any, Union

from .locale import Lang
from .core import ClientOptions, V2SimInstance, LoadStateOption, SaveStateOptions
from .sim import TimeConfig, CommonConfig, SUMOConfig, UXsimConfig
from .wrapper import GenerationCommand, PlotCommand, AltCommand

DEFAULT_MANUAL_V2G_DISPATCH_INTERVAL = 900

class AsyncSimHandle:
    """异步仿真句柄，用于控制后台仿真并查询进度。"""

    def __init__(
        self, inst: V2SimInstance, break_at: int, start_paused: bool = False,
        manual_v2g_dispatch_interval: int = DEFAULT_MANUAL_V2G_DISPATCH_INTERVAL,
    ):
        self._inst = inst
        self._break_at = break_at
        self._progress = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._result: Optional[bool] = None
        self._stop_requested = False
        self._manual_v2g_mode = bool(inst.pdn.is_manual_v2g_mode())
        self._manual_v2g_dispatch_interval = max(
            int(inst.step_length), int(manual_v2g_dispatch_interval)
        )
        self._manual_v2g_was_online = (
            self._manual_v2g_mode and bool(inst.pdn.v2g_online(inst.btime))
        )
        self._next_manual_v2g_dispatch_time: Optional[int] = (
            inst.btime + self._manual_v2g_dispatch_interval
            if self._manual_v2g_was_online else None
        )
        auto_pause = self._manual_v2g_was_online
        self._paused = bool(start_paused or auto_pause)
        self._pause_reason: Optional[str] = (
            "v2g_manual_dispatch" if auto_pause else ("user" if start_paused else None)
        )
        self._step_budget = 0
        self._control_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        if not self._paused:
            self._control_event.set()

    @property
    def progress(self) -> float:
        """当前仿真进度（0~100）。"""
        return self._progress

    @property
    def is_running(self) -> bool:
        """仿真是否正在运行。"""
        return self._running

    @property
    def result(self) -> Optional[bool]:
        """仿真结束后的结果（True=正常结束，False=被停止或出错）。"""
        return self._result

    async def wait(self) -> bool:
        """等待仿真结束，返回最终结果。"""
        if self._task is not None:
            await self._task
            return bool(self._result)
        return False

    async def wait_until_ready(self) -> int:
        """Wait until simulation_start has completed and live state is queryable."""
        await self._ready_event.wait()
        return self._inst.ctime

    def stop(self):
        """请求停止仿真（将在下次步进时生效）。"""
        self._stop_requested = True
        self._control_event.set()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> Optional[str]:
        return self._pause_reason

    @property
    def manual_v2g_dispatch_interval(self) -> Optional[int]:
        return self._manual_v2g_dispatch_interval if self._manual_v2g_mode else None

    @property
    def next_manual_v2g_dispatch_time(self) -> Optional[int]:
        return self._next_manual_v2g_dispatch_time if self._manual_v2g_mode else None

    def get_control_status(self):
        """Return scheduler state used by an external/LLM dispatcher."""
        return {
            "manual_v2g_mode": self._manual_v2g_mode,
            "awaiting_agent_dispatch": (
                self._paused and self._pause_reason == "v2g_manual_dispatch"
            ),
            "pause_reason": self._pause_reason,
            "manual_v2g_dispatch_interval_s": self.manual_v2g_dispatch_interval,
            "next_manual_v2g_dispatch_time": self.next_manual_v2g_dispatch_time,
        }

    def pause(self):
        """Pause before the next simulation step."""
        self._paused = True
        self._pause_reason = "user"
        self._control_event.clear()

    def resume(self):
        """Resume simulation; v2g_manual auto-pauses at the next dispatch epoch."""
        self._paused = False
        self._pause_reason = None
        self._step_budget = 0
        self._control_event.set()

    async def step_once(self) -> int:
        """Advance exactly one step while keeping the simulation paused."""
        if not self._running:
            return self._inst.ctime
        before = self._inst.ctime
        self._paused = True
        self._pause_reason = "step"
        self._step_budget += 1
        self._control_event.set()
        while self._running and self._inst.ctime == before and not self._stop_requested:
            await asyncio.sleep(0)
        return self._inst.ctime

    def get_v2g_status(self):
        """Return current V2G mode, bid curves, capacity, dispatch and agent-control state."""
        status = self._inst.pdn.get_V2G_status(self._inst.ctime)
        status["agent_control"] = self.get_control_status()
        return status

    def get_grid_state(self):
        """Return the latest solved grid state for an external/LLM controller."""
        return self._inst.pdn.get_grid_state(self._inst.ctime)

    def check_manual_v2g_dispatch(self, dispatch_kW, replace: bool = True):
        """Preflight-check a manual V2G command without changing simulation state."""
        return self._inst.pdn.check_manual_v2g_dispatch(self._inst.ctime, dispatch_kW, replace)

    def set_manual_v2g_dispatch(self, dispatch_kW, replace: bool = True):
        """Set manual V2G station targets in kW for the next simulation step."""
        self._inst.pdn.set_manual_v2g_dispatch(dispatch_kW, replace, self._inst.ctime)

    def clear_manual_v2g_dispatch(self):
        """Clear all persistent manual V2G targets."""
        self._inst.pdn.clear_manual_v2g_dispatch()

    def _update_manual_v2g_scheduler(self):
        """Auto-pause v2g_manual at online entry and then at fixed dispatch epochs."""
        if not self._manual_v2g_mode:
            return
        t = int(self._inst.ctime)
        online = bool(self._inst.pdn.v2g_online(t))
        pause_now = False

        if online and not self._manual_v2g_was_online:
            # Do not wait up to a full interval when a V2G window opens.
            pause_now = True
            self._next_manual_v2g_dispatch_time = t + self._manual_v2g_dispatch_interval
        elif online:
            if self._next_manual_v2g_dispatch_time is None:
                self._next_manual_v2g_dispatch_time = t + self._manual_v2g_dispatch_interval
            elif t >= self._next_manual_v2g_dispatch_time:
                pause_now = True
                while self._next_manual_v2g_dispatch_time <= t:
                    self._next_manual_v2g_dispatch_time += self._manual_v2g_dispatch_interval
        else:
            self._next_manual_v2g_dispatch_time = None

        self._manual_v2g_was_online = online
        if pause_now:
            self._paused = True
            self._step_budget = 0
            self._pause_reason = "v2g_manual_dispatch"
            self._control_event.clear()

    async def _run(self, progress_callback: Optional[Callable[[float], Any]] = None) -> bool:
        """后台仿真主循环。"""
        self._running = True
        self._result = False
        start_t = self._inst.btime
        end_t = self._break_at
        total_dur = end_t - start_t
        started = False
        try:
            self._inst.start()
            started = True
            self._ready_event.set()
            while self._inst.ctime < end_t and not self._stop_requested:
                while self._paused and self._step_budget <= 0 and not self._stop_requested:
                    self._control_event.clear()
                    await self._control_event.wait()
                if self._stop_requested:
                    break
                if self._paused and self._step_budget > 0:
                    self._step_budget -= 1
                self._inst.step()
                self._update_manual_v2g_scheduler()
                # 更新进度
                elapsed = self._inst.ctime - start_t
                self._progress = 100.0 * elapsed / total_dur if total_dur > 0 else 0.0
                if progress_callback is not None:
                    progress_callback(self._progress)
                if self._paused and self._step_budget <= 0:
                    self._control_event.clear()
                await asyncio.sleep(0)  # 让出控制权，使其他协程得以运行
            self._result = not self._stop_requested
        except Exception:
            self._result = False
            raise
        finally:
            self._ready_event.set()
            if started:
                self._inst.stop()
            self._running = False
        return bool(self._result)


async def simulate_async(
    proj_dir:str, time:TimeConfig, break_at:Optional[int] = None, out_dir: Optional[str] = None, seed = 0, silent:bool = False, 
    vb = None, vscfg:Optional[CommonConfig] = None, config: Union[None, SUMOConfig, UXsimConfig] = None, 
    disabled_plugins:Optional[List[str]] = None, logging_items:Optional[List[str]] = None,
    state_option: LoadStateOption = LoadStateOption.Skip, state_dir:Optional[str] = None, 
    save_option: SaveStateOptions = SaveStateOptions.Skip, client_options: Optional[ClientOptions] = None, 
    gen_cmds:Optional[GenerationCommand] = None, plot_cmd:Optional[PlotCommand] = None,
    copy_proj_to_out:bool = False, copy_state_to_proj:bool = False, alt_cmds:Optional[AltCommand] = None,
    progress_callback: Optional[Callable[[float], Any]] = None,
    start_paused: bool = False,
    manual_v2g_dispatch_interval: int = DEFAULT_MANUAL_V2G_DISPATCH_INTERVAL,
) -> AsyncSimHandle:
    """
    异步执行单例仿真，返回一个可查询进度的句柄。

    参数与 `simulate_single` 完全一致，额外增加 `progress_callback` 用于实时进度通知。
    返回的 `AsyncSimHandle` 提供 `progress`、`is_running`、`wait()`、`stop()` 等方法和属性。
    """
    # 处理生成命令（与 simulate_single 相同）
    if gen_cmds is not None:
        gen_cmds.generate(proj_dir, silent)

    # Run simulation
    inst = V2SimInstance.from_project(
        proj_dir, time, break_at, out_dir, seed, silent, vb, vscfg, config, 
        disabled_plugins, logging_items, state_option, state_dir, save_option, client_options
    )

    # 应用额外配置（与 simulate_single 相同）
    if alt_cmds is not None:
        assert state_option == LoadStateOption.Skip, Lang.ALT_COMMAND_NOT_SUPPORTED
        alt_cmds.apply(inst)

    # 创建句柄。v2g_manual 在 V2G 在线时会自动暂停等待外部调度。
    handle = AsyncSimHandle(
        inst, break_at if break_at is not None else time.end_time, start_paused,
        manual_v2g_dispatch_interval,
    )

    # 启动后台任务
    handle._task = asyncio.create_task(handle._run(progress_callback))

    # 注意：复制项目文件/保存状态等后处理应在仿真完成后由调用方处理，
    # 或通过 handle.wait() 后再执行。此处不自动执行。
    return handle