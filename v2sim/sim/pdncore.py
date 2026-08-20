"""Integrated power-distribution-network dispatch for V2Sim.

PDN, smart charging, and V2G are owned by the simulation core.  Their runtime
mode and solver settings come exclusively from the project *.v2simcfg file.
The plugin subsystem has no PDN/V2G configuration or implementation.

Each station step follows one deterministic sequence:

    station demand/capability -> PDN dispatch -> actual charge/discharge
"""

import math
import os
from collections import defaultdict
from itertools import chain
from pathlib import Path
from typing import Callable, Dict, List, Optional

from feasytools import ComFunc, RangeList, TimeImplictFunc
from fpowerkit import (
    Calculator,
    CombinedSolver,
    Estimator,
    Generator,
    Grid,
    GridSolveResult,
    LRSolverBase,
)

from ..hub import CS, ConstPriceGetter, ToUPriceGetter
from ..utils import V2SimConfig

INF = float("inf")


class IntegratedPDN:
    """Core-owned PDN, smart-charging, and V2G dispatcher."""

    def __init__(self, inst, config: V2SimConfig, res_dir: Path):
        self.__inst = inst
        self.__mode = config.charging_mode
        self.__gr: Grid = inst.pdn
        self.__fh = open(res_dir / "pdn_res.log", "w", encoding="utf-8")
        self.__save_to = str(res_dir / "pdn_logs")
        os.makedirs(self.__save_to, exist_ok=True)
        self.__badcnt = 0
        self.last_ok = GridSolveResult.Failed
        self.__last_solve_t = -1
        self.__last_apply_t = -1
        self.__post_solve_hooks: List[Callable[[int], None]] = []

        self.__v2g_online = RangeList(config.v2g_online) if config.v2g_online else None
        self.__interval = max(1, int(config.pdn_interval))

        dec_bus = config.pdn_dec_buses.strip()
        if dec_bus == r"%all%":
            decs = set(self.__gr.BusNames)
        else:
            decs = {x.strip() for x in dec_bus.split(",") if x.strip()}

        est = Estimator(config.pdn_estimator)
        if self.__mode == "smartcharge":
            if not decs:
                raise ValueError(
                    "charging_mode='smartcharge' requires at least one bus in pdn_dec_buses"
                )
            unknown = sorted(decs.difference(self.__gr.BusNames))
            if unknown:
                raise ValueError(
                    "Unknown buses in pdn_dec_buses: " + ", ".join(unknown)
                )
            if est not in (Estimator.DistFlow, Estimator.LinDistFlow, Estimator.LinDistFlow2):
                raise ValueError(
                    "charging_mode='smartcharge' requires a load-reduction estimator"
                )
        else:
            decs.clear()

        cal = Calculator(config.pdn_calculator)
        source_bus = config.pdn_source_bus if cal == Calculator.OpenDSS else ""
        self.__sol = CombinedSolver(
            self.__gr,
            estimator=est,
            estimator_solver=config.pdn_solver,
            calculator=cal,
            mlrp=config.pdn_mlrp,
            source_bus=source_bus,
            default_saveto=self.__save_to,
            max_workers=config.pdn_max_workers,
        )
        self.__sol.SetErrorSaveTo(self.__save_to)

        self.__pds: Dict[str, List[CS]] = defaultdict(list)
        for c in chain(inst.FCSList, inst.SCSList):
            if c.bus not in self.__gr.BusNames:
                raise ValueError(f"Charging station {c.name} refers to missing PDN bus {c.bus}")
            self.__pds[c.bus].append(c)

        self.__bus_charge_pu: Dict[str, float] = {b: 0.0 for b in self.__gr.BusNames}
        self.__bus_ratio: Dict[str, float] = {b: 1.0 for b in self.__gr.BusNames}
        self.__max_reduce_prop_cs: Dict[str, float] = {}
        self.__max_reduce_prop: Dict[str, float] = {}

        pf_charge = 0.9
        tan_phi = math.tan(math.acos(pf_charge))

        for b, css in self.__pds.items():
            load = TimeImplictFunc(self._create_bus_load_getter(b))
            self.__gr.Bus(b).Pd += load
            self.__gr.Bus(b).Qd += load * tan_phi
            if b in decs:
                assert isinstance(self.__sol.est, LRSolverBase)
                self.__sol.est.AddReduce(b, load, tan_phi)
                self.__max_reduce_prop[b] = 0.0
                print(f"Enable load reduction at bus {b}", file=self.__fh)

        self.__v2g_stations: List[CS] = list(chain(inst.fcs, inst.scs))
        self.__v2g_cap: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_dispatch: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_gen_names: List[Optional[str]] = [None] * len(self.__v2g_stations)
        self._configure_v2g_generators()

        for cs in self.__v2g_stations:
            cs.set_integrated_v2g_mode(False)

    def _create_bus_load_getter(self, bus: str):
        def _sumP():
            return self.__bus_charge_pu[bus]
        return _sumP

    def _configure_v2g_generators(self):
        if self.__mode != "v2g":
            return
        Sb_kVA = self.__gr.Sb_kVA
        for i, cs in enumerate(self.__v2g_stations):
            if cs._psell is None:
                continue
            if isinstance(cs._psell, ConstPriceGetter):
                psell_func = cs._psell._price * Sb_kVA
            elif isinstance(cs._psell, ToUPriceGetter):
                psell_func = cs._psell._price_func * Sb_kVA
            else:
                raise RuntimeError(
                    "Integrated V2G supports constant price or time-of-use price for selling electricity."
                )
            if cs._psell_is_serv_fee:
                psell_func = self.__gr._dp + psell_func
            name = "V2G_" + cs._name
            self.__v2g_gen_names[i] = name
            self.__gr.AddGen(Generator(
                name, cs._bus,
                0.0, psell_func, 0.0,
                -1.0, -1.0, None,
                0.0, ComFunc(self._v2g_cap_getter(i)), 0.0, 0.0,
            ))
        # V2G generators are part of the core grid before the first solve.
        if hasattr(self.__sol.est, "UpdateGrid"):
            self.__sol.est.UpdateGrid(self.__gr)

    def _v2g_cap_getter(self, i: int):
        def func(t: int) -> float:
            if not self.v2g_online(t):
                return 0.0
            # kWh/s -> kW -> pu: x * 3600 / Sb_kVA
            return self.__v2g_cap[i] * 3600.0 / self.__gr.Sb_kVA
        return func

    @property
    def Grid(self) -> Grid:
        return self.__gr

    @property
    def Solver(self):
        return self.__sol

    @property
    def LastPreStepSucceed(self) -> bool:
        return self.last_ok != GridSolveResult.Failed

    @property
    def LastTime(self) -> int:
        return self.__last_solve_t

    @property
    def charging_mode(self) -> str:
        return self.__mode

    def v2g_online(self, t: int) -> bool:
        return self.__mode == "v2g" and self.__v2g_online is not None and t in self.__v2g_online

    def is_smartcharge_mode(self) -> bool:
        return (
            self.__mode == "smartcharge"
            and isinstance(self.__sol.est, LRSolverBase)
            and len(self.__sol.est.DecBuses) > 0
        )

    def register_post_solve_hook(self, hook: Callable[[int], None]):
        """Register an auxiliary action to run after a successful PDN solve.

        This keeps grid-dependent auxiliary plugins (for example over-current
        protection) synchronized with the current-step core PDN result without
        turning PDN itself back into a plugin.
        """
        self.__post_solve_hooks.append(hook)

    def HasEverFailed(self) -> bool:
        return self.__badcnt > 0

    def _reset_station_limits(self):
        for c in self.__v2g_stations:
            c.set_Pc_lim(INF)

    def _collect_requests(self, t: int, pb_e: float, ps_e: float):
        self._reset_station_limits()
        v2g_active = self.v2g_online(t)
        requested_cs = []
        for cs in self.__v2g_stations:
            cs.set_integrated_v2g_mode(v2g_active)
            requested_cs.append(cs.get_requested_pc(t, pb_e, ps_e, v2g_active))

        for b in self.__bus_charge_pu:
            self.__bus_charge_pu[b] = 0.0
        for cs, pc in zip(self.__v2g_stations, requested_cs):
            # kWh/s -> MW -> pu
            self.__bus_charge_pu[cs.bus] += pc * 3.6 / self.__gr.Sb_MVA

        if self.v2g_online(t):
            self.__v2g_cap = [cs.get_V2G_cap(t, ps_e) for cs in self.__v2g_stations]
        else:
            self.__v2g_cap = [0.0] * len(self.__v2g_stations)
        return requested_cs

    def _apply_held_dispatch(self, requested_cs: List[float], t: int):
        # Between PDN solves, use the last bus service ratio against the current
        # charging request instead of feeding last step's actual load forward.
        if self.is_smartcharge_mode():
            for cs, req in zip(self.__v2g_stations, requested_cs):
                cs.set_Pc_lim(req * self.__bus_ratio.get(cs.bus, 1.0))
        else:
            self._reset_station_limits()

        if self.v2g_online(t):
            held = [min(x, cap) for x, cap in zip(self.__v2g_dispatch, self.__v2g_cap)]
        else:
            held = [0.0] * len(self.__v2g_stations)
        self._set_v2g_demands(held)

        # The grid log should represent the held served charging request.
        if self.is_smartcharge_mode():
            for b in self.__bus_charge_pu:
                self.__bus_charge_pu[b] *= self.__bus_ratio.get(b, 1.0)

    def _set_v2g_demands(self, demands: List[float]):
        nf = len(self.__inst.fcs)
        self.__inst.fcs.set_V2G_demand(demands[:nf])
        self.__inst.scs.set_V2G_demand(demands[nf:])

    def prepare_dispatch(self, t: int, step_len: int, pb_e: float, ps_e: float):
        """Compute requested power, solve PDN when due, and set station targets.

        This method never changes vehicle SOC.  Actual charging/discharging is
        performed later in the same TrafficInst.post_simulation_step call.
        """
        requested_cs = self._collect_requests(t, pb_e, ps_e)
        self.__last_apply_t = t

        # PDN is always active. Only V2G participation is time-gated by
        # v2g_online; the network itself continues solving at pdn_interval.
        due = self.__last_solve_t < 0 or self.__last_solve_t + self.__interval <= t
        if not due:
            self._apply_held_dispatch(requested_cs, t)
            return

        prev_solve_t = self.__last_solve_t
        ok, _ = self.__sol.solve(t)
        self.__last_solve_t = t
        self.last_ok = ok
        if ok == GridSolveResult.Failed:
            print(f"[{t}] Fail.", file=self.__fh)
            self.__gr.savePQofBus(os.path.join(self.__save_to, f"{t}_load.csv"), t)
            self.__badcnt += 1
            if prev_solve_t >= 0:
                self._apply_held_dispatch(requested_cs, t)
            else:
                self._reset_station_limits()
                self._set_v2g_demands([0.0] * len(self.__v2g_stations))
            return

        # Apply ESS after a successful solve.
        if prev_solve_t >= 0:
            try:
                self.__gr.ApplyAllESS(t - prev_solve_t)
            except Exception:
                # Some fpowerkit versions do not require explicit ESS application.
                pass

        if ok in (GridSolveResult.OKwithoutVICons, GridSolveResult.SubOKwithoutVICons):
            print(f"[{t}] Relax.", file=self.__fh)

        # Grid-dependent auxiliary plugins run here, against the current-step
        # solve, before charging/discharging is actually executed.
        for hook in self.__post_solve_hooks:
            hook(t)

        self.__bus_ratio = {b: 1.0 for b in self.__gr.BusNames}
        if self.is_smartcharge_mode():
            assert isinstance(self.__sol.est, LRSolverBase)
            for b, x in self.__sol.est.DecBuses.items():
                tot = x.Limit(t)
                if tot > 1e-12 and x.Reduction:
                    ratio = max(0.0, min(1.0, (tot - x.Reduction) / tot))
                    self.__bus_ratio[b] = ratio
                    self.__max_reduce_prop[b] = max(self.__max_reduce_prop.get(b, 0.0), 1.0 - ratio)
                    print(
                        f"[{t}] Load reduction: bus = {b}, proportion = {ratio:.6f}, "
                        f"load = {x.Reduction * self.__gr.Sb_kVA:.2f} kW",
                        file=self.__fh,
                    )
            for cs, req in zip(self.__v2g_stations, requested_cs):
                ratio = self.__bus_ratio.get(cs.bus, 1.0)
                cs.set_Pc_lim(req * ratio)
                self.__max_reduce_prop_cs[cs.name] = max(
                    self.__max_reduce_prop_cs.get(cs.name, 0.0), 1.0 - ratio
                )
            for b in self.__bus_charge_pu:
                self.__bus_charge_pu[b] *= self.__bus_ratio.get(b, 1.0)
        else:
            self._reset_station_limits()

        if self.v2g_online(t):
            dispatch = []
            for name in self.__v2g_gen_names:
                if name is None:
                    dispatch.append(0.0)
                    continue
                p = self.__gr.Gen(name).P
                pu = 0.0 if p is None else (float(p) if isinstance(p, (int, float)) else p(t))
                # pu -> kW -> kWh/s
                dispatch.append(max(0.0, pu * self.__gr.Sb_kVA / 3600.0))
            self.__v2g_dispatch = [min(x, cap) for x, cap in zip(dispatch, self.__v2g_cap)]
        else:
            self.__v2g_dispatch = [0.0] * len(self.__v2g_stations)
        self._set_v2g_demands(self.__v2g_dispatch)

    def GetMaxLoadReductionProportion(self, bus: str) -> float:
        return self.__max_reduce_prop.get(bus, 0.0)

    GetMaxLoadReductionProportionOfBus = GetMaxLoadReductionProportion

    def GetMaxLoadReductionProportionOfCS(self, cs_name: str) -> float:
        return self.__max_reduce_prop_cs.get(cs_name, 0.0)

    def GetAverageMaxLoadReductionProportion(self) -> float:
        if not self.__max_reduce_prop:
            return 0.0
        return sum(self.__max_reduce_prop.values()) / len(self.__max_reduce_prop)

    @property
    def GeneratorPlan(self) -> Dict[str, float]:
        if not self.LastPreStepSucceed:
            raise RuntimeError("Last integrated PDN solve failed")
        return {g.ID: (0.0 if not isinstance(g.P, (int, float)) else float(g.P)) for g in self.__gr.Gens}

    def close(self):
        if self.__badcnt:
            print(f"PDN solve failures: {self.__badcnt}", file=self.__fh)
        if not self.__fh.closed:
            self.__fh.close()