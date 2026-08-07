import asyncio
from typing import List, Optional, Callable, Any, Union

from .locale import Lang
from .core import ClientOptions, V2SimInstance, LoadStateOption, SaveStateOptions
from .sim import TimeConfig, CommonConfig, SUMOConfig, UXsimConfig
from .wrapper import GenerationCommand, PlotCommand, AltCommand

class AsyncSimHandle:
    """异步仿真句柄，用于控制后台仿真并查询进度。"""

    def __init__(self, inst: V2SimInstance, break_at: int):
        self._inst = inst
        self._break_at = break_at
        self._progress = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._result: Optional[bool] = None
        self._stop_requested = False

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
            return await self._task
        return False

    def stop(self):
        """请求停止仿真（将在下次步进时生效）。"""
        self._stop_requested = True

    async def _run(self, progress_callback: Optional[Callable[[float], Any]] = None):
        """后台仿真主循环。"""
        self._running = True
        self._result = False
        start_t = self._inst.btime
        end_t = self._break_at
        total_dur = end_t - start_t
        self._inst.start()
        try:
            while self._inst.ctime < end_t and not self._stop_requested:
                self._inst.step()
                # 更新进度
                elapsed = self._inst.ctime - start_t
                self._progress = 100.0 * elapsed / total_dur if total_dur > 0 else 0.0
                if progress_callback is not None:
                    progress_callback(self._progress)
                await asyncio.sleep(0)  # 让出控制权，使其他协程得以运行
            self._result = not self._stop_requested
        except Exception:
            self._result = False
            raise
        finally:
            self._inst.stop()
            self._running = False


async def simulate_async(
    proj_dir:str, time:TimeConfig, break_at:Optional[int] = None, out_dir: Optional[str] = None, seed = 0, silent:bool = False, 
    vb = None, vscfg:Optional[CommonConfig] = None, config: Union[None, SUMOConfig, UXsimConfig] = None, 
    disabled_plugins:Optional[List[str]] = None, logging_items:Optional[List[str]] = None,
    state_option: LoadStateOption = LoadStateOption.Skip, state_dir:Optional[str] = None, 
    save_option: SaveStateOptions = SaveStateOptions.Skip, client_options: Optional[ClientOptions] = None, 
    gen_cmds:Optional[GenerationCommand] = None, plot_cmd:Optional[PlotCommand] = None,
    copy_proj_to_out:bool = False, copy_state_to_proj:bool = False, alt_cmds:Optional[AltCommand] = None,
    progress_callback: Optional[Callable[[float], Any]] = None,
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

    # 创建句柄
    handle = AsyncSimHandle(inst, break_at if break_at is not None else time.end_time)

    # 启动后台任务
    handle._task = asyncio.create_task(handle._run(progress_callback))

    # 注意：复制项目文件/保存状态等后处理应在仿真完成后由调用方处理，
    # 或通过 handle.wait() 后再执行。此处不自动执行。
    return handle