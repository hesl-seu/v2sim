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
from typing import Callable, Dict, List, Optional, Tuple, TypedDict

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

from ..hub import BidCurvePoint, CS, V2GBidBlock
from ..utils import V2SimConfig

INF = float("inf")


class V2GStationStatus(TypedDict):
    name: str
    bus: str
    capacity_kW: float
    dispatch_kW: float
    manual_target_kW: float
    bid_curve: List[BidCurvePoint]
    shadow_price_per_kWh: Optional[float]
    effective_buy_price_per_kWh: Optional[float]
    effective_sell_price_per_kWh: Optional[float]
    price_source: str


class V2GStatus(TypedDict, total=False):
    mode: str
    time: int
    online: bool
    last_solve_time: int
    grid_buy_price_per_kWh: Optional[float]
    grid_sell_price_per_kWh: Optional[float]
    grid_marginal_price_per_kWh: Optional[float]
    grid_marginal_price_basis: Optional[str]
    fallback_grid_buy_price_per_kWh: Optional[float]
    fallback_grid_sell_price_per_kWh: Optional[float]
    shadow_price_min_per_kWh: Optional[float]
    shadow_price_max_per_kWh: Optional[float]
    shadow_price_bus_count: int
    price_basis: str
    manual_fallback_enabled: bool
    manual_fallback_active: bool
    manual_fallback_reason: Optional[str]
    last_manual_check: Dict[str, object]
    stations: List[V2GStationStatus]
    effective_control: str
    agent_control: dict


class GridBusStatus(TypedDict):
    name: str
    voltage_pu: Optional[float]
    min_voltage_pu: Optional[float]
    max_voltage_pu: Optional[float]
    voltage_violation: bool
    shadow_price_per_kWh: Optional[float]
    effective_buy_price_per_kWh: Optional[float]
    effective_sell_price_per_kWh: Optional[float]
    price_source: str


class GridLineStatus(TypedDict):
    name: str
    current_kA: Optional[float]
    limit_kA: Optional[float]
    loading_pu: Optional[float]
    thermal_violation: bool


class GridState(TypedDict):
    time: int
    last_solve_time: int
    solve_result: str
    feasible: bool
    grid_buy_price_per_kWh: Optional[float]
    grid_sell_price_per_kWh: Optional[float]
    grid_marginal_price_per_kWh: Optional[float]
    grid_marginal_price_basis: Optional[str]
    fallback_grid_buy_price_per_kWh: Optional[float]
    fallback_grid_sell_price_per_kWh: Optional[float]
    shadow_price_min_per_kWh: Optional[float]
    shadow_price_max_per_kWh: Optional[float]
    shadow_price_bus_count: int
    price_basis: str
    gross_ev_charging_kW: float
    v2g_dispatch_kW: float
    net_ev_load_kW: float
    total_bus_load_kW: float
    total_generation_kW: float
    min_voltage_pu: Optional[float]
    min_voltage_bus: Optional[str]
    max_voltage_pu: Optional[float]
    max_voltage_bus: Optional[str]
    max_line_loading_pu: Optional[float]
    max_line_loading_line: Optional[str]
    voltage_violations: List[str]
    thermal_violations: List[str]
    buses: List[GridBusStatus]
    lines: List[GridLineStatus]


class V2GDispatchCheck(TypedDict, total=False):
    feasible: bool
    time: int
    online: bool
    replace: bool
    requested_kW: Dict[str, float]
    effective_targets_kW: Dict[str, float]
    available_kW: Dict[str, float]
    accepted_kW: Dict[str, float]
    violations: List[Dict[str, object]]
    grid_validation: str
    current_grid_feasible: bool
    fallback_enabled: bool
    would_fallback: bool


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
        self.__manual_fallback_enabled = bool(config.v2g_manual_fallback_to_v2g)
        self.__manual_fallback_active = False
        self.__manual_fallback_reason: Optional[str] = None
        self.__manual_dispatch_dirty = False
        self.__last_manual_check: Dict[str, object] = {}
        # cprice/dprice are retained only as a compatibility fallback for a
        # bus that has no usable OPF ShadowPrice yet (for example before the
        # first successful solve). Runtime charging/V2G economics otherwise use
        # the nodal ShadowPrice produced by fpowerkit.
        self.__last_pb_e: Optional[float] = None
        self.__last_ps_e: Optional[float] = None
        self.__station_price_snapshot: Dict[str, Tuple[Optional[float], Optional[float], str]] = {}

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
        # Gross charging active power used to form charging reactive demand.
        # Manual V2G is treated as unity-PF active injection and does not make
        # the charging station export reactive power.
        self.__bus_charge_qbase_pu: Dict[str, float] = {b: 0.0 for b in self.__gr.BusNames}
        self.__bus_ratio: Dict[str, float] = {b: 1.0 for b in self.__gr.BusNames}
        self.__max_reduce_prop_cs: Dict[str, float] = {}
        self.__max_reduce_prop: Dict[str, float] = {}

        pf_charge = 0.9
        tan_phi = math.tan(math.acos(pf_charge))

        for b, css in self.__pds.items():
            load_p = TimeImplictFunc(self._create_bus_load_getter(b, False))
            load_qbase = TimeImplictFunc(self._create_bus_load_getter(b, True))
            self.__gr.Bus(b).Pd += load_p
            self.__gr.Bus(b).Qd += load_qbase * tan_phi
            if b in decs:
                assert isinstance(self.__sol.est, LRSolverBase)
                self.__sol.est.AddReduce(b, load_p, tan_phi)
                self.__max_reduce_prop[b] = 0.0
                print(f"Enable load reduction at bus {b}", file=self.__fh)

        self.__v2g_stations: List[CS] = list(chain(inst.fcs, inst.scs))
        self.__v2g_cap: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_dispatch: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_bid_blocks: List[List[V2GBidBlock]] = [[] for _ in self.__v2g_stations]
        self.__v2g_gen_names: List[List[str]] = [[] for _ in self.__v2g_stations]
        # Persistent station targets used only by charging_mode='v2g_manual'.
        self.__manual_v2g_target: List[float] = [0.0] * len(self.__v2g_stations)
        self._configure_v2g_generators()

        for cs in self.__v2g_stations:
            cs.set_integrated_v2g_mode(False)

    def _create_bus_load_getter(self, bus: str, reactive_base: bool):
        def _sumP():
            if reactive_base:
                return self.__bus_charge_qbase_pu[bus]
            return self.__bus_charge_pu[bus]
        return _sumP

    def _configure_v2g_generators(self):
        """Create dynamic V2G bid generators used by automatic market dispatch.

        In ``v2g_manual`` mode these generators are also created when fallback
        is enabled, but their capacity is zero unless fallback is active.
        """
        if self.__mode != "v2g" and not (self.__mode == "v2g_manual" and self.__manual_fallback_enabled):
            return
        for i, cs in enumerate(self.__v2g_stations):
            if not cs.supports_V2G:
                continue
            for j in range(cs._slots):
                name = f"V2G_{cs._name}_{j}"
                self.__v2g_gen_names[i].append(name)
                self.__gr.AddGen(Generator(
                    name, cs._bus,
                    0.0, ComFunc(self._v2g_bid_cost_getter(i, j)), 0.0,
                    -1.0, -1.0, None,
                    0.0, ComFunc(self._v2g_bid_cap_getter(i, j)), 0.0, 0.0,
                ))
        if hasattr(self.__sol.est, "UpdateGrid"):
            self.__sol.est.UpdateGrid(self.__gr)

    def _automatic_v2g_enabled(self, t: int) -> bool:
        if not self.v2g_online(t):
            return False
        if self.__mode == "v2g":
            return True
        return self.is_manual_v2g_mode() and self.__manual_fallback_enabled and self.__manual_fallback_active

    def _manual_dispatch_enabled(self, t: int) -> bool:
        return self.is_manual_v2g_mode() and self.v2g_online(t) and not self.__manual_fallback_active

    def _v2g_bid_cost_getter(self, i: int, j: int):
        def func(t: int) -> float:
            if not self._automatic_v2g_enabled(t) or j >= len(self.__v2g_bid_blocks[i]):
                return 0.0
            # $/kWh -> coefficient for pu-h generation in FPowerKit.
            return self.__v2g_bid_blocks[i][j].price * self.__gr.Sb_kVA
        return func

    def _v2g_bid_cap_getter(self, i: int, j: int):
        def func(t: int) -> float:
            if not self._automatic_v2g_enabled(t) or j >= len(self.__v2g_bid_blocks[i]):
                return 0.0
            # kWh/s -> kW -> pu.
            return self.__v2g_bid_blocks[i][j].quantity * 3600.0 / self.__gr.Sb_kVA
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
        return self.__mode in ("v2g", "v2g_manual") and self.__v2g_online is not None and t in self.__v2g_online

    def is_manual_v2g_mode(self) -> bool:
        return self.__mode == "v2g_manual"

    def manual_v2g_dispatch_available(self, t: int) -> bool:
        """Whether an external manual V2G dispatch is meaningful at ``t``.

        A manual dispatch epoch should only interrupt the simulator when V2G is
        globally online *and* at least one connected EV currently contributes
        positive discharge capacity to a station bid curve.  This incorporates
        station availability, EV V2G time windows, SOC reserve, departure state,
        charger limits, and discharge efficiency through ``get_V2G_bid_curve``.

        Price is deliberately not used as a gate here: in ``v2g_manual`` mode
        the external agent is allowed to inspect the bid prices and decide whether
        dispatch is economically justified.
        """
        if not self.is_manual_v2g_mode() or not self.v2g_online(t):
            return False
        for cs in self.__v2g_stations:
            curve = cs.get_V2G_bid_curve(t)
            if any(float(row.get("quantity_kW", 0.0)) > 1e-9 for row in curve):
                return True
        return False

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

        # Build the instantaneous per-EV V2G supply curve first.  Charging
        # behaviour is not controlled by a separate reservation switch: the
        # v1.6.0 SOC/kv state machine in CS.get_requested_pc() decides whether
        # each EV is charging, idle, or V2G-capable.
        if v2g_active:
            self.__v2g_bid_blocks = [cs.get_V2G_bid_blocks(t) for cs in self.__v2g_stations]
            self.__v2g_cap = [sum(x.quantity for x in blocks) for blocks in self.__v2g_bid_blocks]
            for cs, cap in zip(self.__v2g_stations, self.__v2g_cap):
                cs._cur_v2g_cap = cap
        else:
            self.__v2g_bid_blocks = [[] for _ in self.__v2g_stations]
            self.__v2g_cap = [0.0] * len(self.__v2g_stations)

        manual_active = self._manual_dispatch_enabled(t)
        if manual_active:
            self.__v2g_dispatch = [
                min(target, cap) for target, cap in zip(self.__manual_v2g_target, self.__v2g_cap)
            ]
            for i, cs in enumerate(self.__v2g_stations):
                cs.set_V2G_dispatch_plan(self._plan_from_total(i, self.__v2g_dispatch[i]))
        else:
            for cs in self.__v2g_stations:
                cs.clear_V2G_dispatch_plan()

        requested_cs = []
        for cs in self.__v2g_stations:
            # Native and Manual V2G share the same v1.6.0 SOC/kv state rule.
            # No additional pre-allocation layer is used.
            cs.set_integrated_v2g_mode(v2g_active)
            cs_pb_e, cs_ps_e, _ = self.__station_price_snapshot.get(
                cs.name, (pb_e, ps_e, "cprice_dprice_fallback")
            )
            # The effective station energy price is the nodal OPF shadow price
            # when available. cprice/dprice are used only as a per-node fallback.
            requested_cs.append(cs.get_requested_pc(
                t,
                pb_e if cs_pb_e is None else cs_pb_e,
                ps_e if cs_ps_e is None else cs_ps_e,
                v2g_active,
            ))

        for b in self.__bus_charge_pu:
            self.__bus_charge_pu[b] = 0.0
            self.__bus_charge_qbase_pu[b] = 0.0
        for cs, pc in zip(self.__v2g_stations, requested_cs):
            pu = pc * 3.6 / self.__gr.Sb_MVA
            self.__bus_charge_pu[cs.bus] += pu
            self.__bus_charge_qbase_pu[cs.bus] += pu

        if manual_active:
            # Manual V2G is a fixed unity-PF active injection.  During fallback
            # the original market V2G generators provide the injection instead.
            for cs, pd in zip(self.__v2g_stations, self.__v2g_dispatch):
                self.__bus_charge_pu[cs.bus] -= pd * 3.6 / self.__gr.Sb_MVA
        return requested_cs

    def _plan_from_total(self, i: int, total: float) -> Dict[str, Tuple[float, float, float]]:
        """Allocate a station total along its current ascending bid curve."""
        left = max(0.0, min(float(total), self.__v2g_cap[i]))
        plan: Dict[str, Tuple[float, float, float]] = {}
        for block in self.__v2g_bid_blocks[i]:
            if left <= 1e-15:
                break
            power = min(left, block.quantity)
            if power > 0.0:
                plan[block.ev._name] = (power, block.user_price, block.price)
                left -= power
        return plan

    def _set_v2g_demands(self, demands: List[float]):
        nf = len(self.__inst.fcs)
        self.__inst.fcs.set_V2G_demand(demands[:nf])
        self.__inst.scs.set_V2G_demand(demands[nf:])
        for i, cs in enumerate(self.__v2g_stations):
            plan = self._plan_from_total(i, demands[i]) if i < len(demands) else {}
            cs.set_V2G_dispatch_plan(plan)

    def _apply_held_dispatch(self, requested_cs: List[float], t: int):
        # Between PDN solves, use the last bus service ratio against the current
        # charging request instead of feeding last step's actual load forward.
        if self.is_smartcharge_mode():
            for cs, req in zip(self.__v2g_stations, requested_cs):
                cs.set_Pc_lim(req * self.__bus_ratio.get(cs.bus, 1.0))
        else:
            self._reset_station_limits()

        if self.v2g_online(t):
            if self._manual_dispatch_enabled(t):
                held = [min(x, cap) for x, cap in zip(self.__manual_v2g_target, self.__v2g_cap)]
                self.__v2g_dispatch = held
            else:
                # Automatic V2G (native v2g mode or manual fallback) holds the
                # last market dispatch between PDN solves.
                held = [min(x, cap) for x, cap in zip(self.__v2g_dispatch, self.__v2g_cap)]
        else:
            held = [0.0] * len(self.__v2g_stations)
            self.__v2g_dispatch = held
        self._set_v2g_demands(held)

        if self.is_smartcharge_mode():
            for b in self.__bus_charge_pu:
                ratio = self.__bus_ratio.get(b, 1.0)
                self.__bus_charge_pu[b] *= ratio
                self.__bus_charge_qbase_pu[b] *= ratio

    def _manual_capacity_violations(self) -> List[Dict[str, object]]:
        """Check instantaneous power and user minimum-price feasibility."""
        ret: List[Dict[str, object]] = []
        if not self.is_manual_v2g_mode():
            return ret
        for i, (cs, target, cap) in enumerate(zip(
            self.__v2g_stations, self.__manual_v2g_target, self.__v2g_cap
        )):
            if target > cap + 1e-12:
                ret.append({
                    "type": "v2g_capacity",
                    "station": cs.name,
                    "requested_kW": target * 3600.0,
                    "maximum_kW": cap * 3600.0,
                })
                continue
            _, sell_price, _ = self.__station_price_snapshot.get(cs.name, (None, None, "unavailable"))
            if sell_price is None:
                continue
            accepted_cap = sum(
                block.quantity for block in self.__v2g_bid_blocks[i]
                if block.price <= float(sell_price) + 1e-12
            )
            if target > accepted_cap + 1e-12:
                ret.append({
                    "type": "v2g_minimum_price",
                    "station": cs.name,
                    "requested_kW": target * 3600.0,
                    "maximum_accepted_kW": accepted_cap * 3600.0,
                    "effective_sell_price_per_kWh": float(sell_price),
                })
        return ret

    @staticmethod
    def _solve_result_has_grid_violation(ok) -> bool:
        return ok in (GridSolveResult.OKwithoutVICons, GridSolveResult.SubOKwithoutVICons)

    def _activate_manual_fallback(self, reason: str):
        if not (self.is_manual_v2g_mode() and self.__manual_fallback_enabled):
            return
        self.__manual_fallback_active = True
        self.__manual_fallback_reason = str(reason)

    def _clear_manual_fallback(self):
        self.__manual_fallback_active = False
        self.__manual_fallback_reason = None

    def prepare_dispatch(self, t: int, step_len: int, pb_e: float, ps_e: float):
        """Compute requested power, solve PDN when due, and set station targets.

        This method never changes vehicle SOC.  Actual charging/discharging is
        performed later in the same TrafficInst.post_simulation_step call.

        When ``v2g_manual_fallback_to_v2g`` is enabled, an infeasible manual
        target is rejected and the same step is re-solved with the original
        market/OPF V2G mechanism.  Fallback remains active until the external
        controller submits or clears a manual target.
        """
        self.__last_pb_e = float(pb_e)
        self.__last_ps_e = float(ps_e)
        # Snapshot prices once per traffic step so PDN request formation and the
        # subsequent station update use the same price signal. A newly solved
        # ShadowPrice therefore takes effect on the next traffic step (normally
        # one simulation step later), avoiding an endogenous-price inconsistency
        # within a single step.
        self.__station_price_snapshot = self._build_station_price_snapshot(t, pb_e, ps_e)
        requested_cs = self._collect_requests(t, pb_e, ps_e)
        self.__last_apply_t = t

        # A newly submitted manual command is solved immediately so the agent
        # never executes a fresh command solely against stale grid constraints.
        due = (
            self.__last_solve_t < 0
            or self.__last_solve_t + self.__interval <= t
            or (self._manual_dispatch_enabled(t) and self.__manual_dispatch_dirty)
        )

        manual_attempt = self._manual_dispatch_enabled(t)
        capacity_violations = self._manual_capacity_violations() if manual_attempt else []
        if manual_attempt:
            self.__last_manual_check = {
                "time": int(t),
                "capacity_feasible": not bool(capacity_violations),
                "violations": capacity_violations,
                "grid_feasible": None,
                "fallback_triggered": False,
            }

        # Capacity infeasibility is known before power flow/OPF.  With fallback
        # enabled, discard the manual injection and rebuild requests using the
        # original automatic V2G market mechanism.
        if manual_attempt and capacity_violations and self.__manual_fallback_enabled:
            self._activate_manual_fallback("manual_capacity_infeasible")
            self.__last_manual_check["fallback_triggered"] = True
            self.__last_manual_check["fallback_reason"] = self.__manual_fallback_reason
            requested_cs = self._collect_requests(t, pb_e, ps_e)
            manual_attempt = False
            due = True

        # PDN is always active. Only V2G participation is time-gated by
        # v2g_online; the network itself continues solving at pdn_interval.
        if not due:
            self._apply_held_dispatch(requested_cs, t)
            return

        prev_solve_t = self.__last_solve_t
        ok, _ = self.__sol.solve(t)

        # A manual candidate that cannot satisfy the network solve (or needs
        # voltage/current constraints relaxed) is illegal. Re-solve the same
        # step with the native market V2G mechanism when fallback is enabled.
        if (
            self._manual_dispatch_enabled(t)
            and self.__manual_fallback_enabled
            and (ok == GridSolveResult.Failed or self._solve_result_has_grid_violation(ok))
        ):
            reason = (
                "manual_pdn_solve_failed"
                if ok == GridSolveResult.Failed
                else "manual_grid_constraint_violation"
            )
            self._activate_manual_fallback(reason)
            self.__last_manual_check["grid_feasible"] = False
            self.__last_manual_check["fallback_triggered"] = True
            self.__last_manual_check["fallback_reason"] = reason
            print(f"[{t}] Manual V2G rejected ({reason}); falling back to original V2G.", file=self.__fh)
            requested_cs = self._collect_requests(t, pb_e, ps_e)
            ok, _ = self.__sol.solve(t)
        elif self.is_manual_v2g_mode() and self.__last_manual_check:
            self.__last_manual_check["grid_feasible"] = (
                ok != GridSolveResult.Failed and not self._solve_result_has_grid_violation(ok)
            )

        self.__last_solve_t = t
        self.last_ok = ok
        self.__manual_dispatch_dirty = False
        if ok == GridSolveResult.Failed:
            # The current solve produced no usable shadow price. Use cprice/dprice
            # for the station execution of this step, exactly as the documented
            # per-node fallback rule requires.
            self.__station_price_snapshot = self._build_station_price_snapshot(t, pb_e, ps_e)
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
                ratio = self.__bus_ratio.get(b, 1.0)
                self.__bus_charge_pu[b] *= ratio
                self.__bus_charge_qbase_pu[b] *= ratio
        else:
            self._reset_station_limits()

        if self.v2g_online(t):
            if self._manual_dispatch_enabled(t):
                self.__v2g_dispatch = [
                    min(target, cap) for target, cap in zip(self.__manual_v2g_target, self.__v2g_cap)
                ]
            else:
                dispatch: List[float] = []
                for names in self.__v2g_gen_names:
                    total = 0.0
                    for name in names:
                        p = self.__gr.Gen(name).P
                        pu = 0.0 if p is None else (float(p) if isinstance(p, (int, float)) else p(t))
                        total += max(0.0, pu * self.__gr.Sb_kVA / 3600.0)
                    dispatch.append(total)
                self.__v2g_dispatch = [min(x, cap) for x, cap in zip(dispatch, self.__v2g_cap)]
        else:
            self.__v2g_dispatch = [0.0] * len(self.__v2g_stations)
        self._set_v2g_demands(self.__v2g_dispatch)

    @staticmethod
    def _value_at(value, t: int) -> Optional[float]:
        if value is None:
            return None
        try:
            if callable(value):
                value = value(t)
            return float(value) # type: ignore
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _magnitude(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(abs(value))
        except (TypeError, ValueError, OverflowError):
            return None

    def _current_grid_prices(self, t: int) -> Tuple[Optional[float], Optional[float]]:
        """Return configured cprice/dprice in $/kWh for fallback use only.

        V2Sim no longer treats these values as the primary electricity-price
        signal. They are used only when a station's connected bus has no usable
        OPF ``ShadowPrice`` (including before the first successful PDN solve).
        """
        pb_e, ps_e = self.__last_pb_e, self.__last_ps_e
        if pb_e is not None and ps_e is not None and self.__last_apply_t == t:
            return pb_e, ps_e
        pdn = getattr(self.__inst, "_pdn", None)
        try:
            if pdn is not None:
                sb_kva = float(self.__gr.Sb_kVA)
                pb_e = float(pdn._cp(t)) / sb_kva
                ps_e = float(pdn._dp(t)) / sb_kva
        except Exception:
            pass
        return pb_e, ps_e

    def _bus_shadow_price_per_kWh(self, bus_name: str) -> Optional[float]:
        """Return a bus OPF ShadowPrice converted from $/puh to $/kWh.

        A shadow price is considered usable only after a non-failed PDN solve.
        ``None`` and non-finite values are treated as unavailable. Zero and
        negative finite values are preserved because they can be legitimate
        marginal values in an OPF.
        """
        if self.__last_solve_t < 0 or self.last_ok == GridSolveResult.Failed:
            return None
        try:
            raw = getattr(self.__gr.Bus(bus_name), "ShadowPrice", None)
            if raw is None:
                return None
            value = float(raw)
            sb_kva = float(self.__gr.Sb_kVA)
            if not math.isfinite(value) or not math.isfinite(sb_kva) or sb_kva <= 0.0:
                return None
            return value / sb_kva
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            return None

    def _effective_bus_prices(
        self,
        bus_name: str,
        fallback_buy: Optional[float],
        fallback_sell: Optional[float],
    ) -> Tuple[Optional[float], Optional[float], str]:
        """Return nodal buy/sell signal and its source for one PDN bus."""
        shadow = self._bus_shadow_price_per_kWh(bus_name)
        if shadow is not None:
            # A nodal marginal value is direction-neutral: use the same local
            # energy value as the base price for charging and V2G selling.
            return shadow, shadow, "shadow_price"
        return fallback_buy, fallback_sell, "cprice_dprice_fallback"

    def _build_station_price_snapshot(
        self, t: int, fallback_buy: Optional[float], fallback_sell: Optional[float]
    ) -> Dict[str, Tuple[Optional[float], Optional[float], str]]:
        return {
            cs.name: self._effective_bus_prices(cs.bus, fallback_buy, fallback_sell)
            for cs in self.__v2g_stations
        }

    def station_price_snapshot(
        self, t: Optional[int] = None
    ) -> Dict[str, Tuple[Optional[float], Optional[float], str]]:
        """Return the per-station prices used for the current traffic step.

        The first two tuple values are the effective buy and sell energy prices
        in $/kWh. They are normally the connected bus ShadowPrice; cprice/dprice
        appear only when that bus has no usable shadow price.
        """
        if self.__station_price_snapshot:
            return dict(self.__station_price_snapshot)
        tt = self.__last_apply_t if t is None else int(t)
        pb_e, ps_e = self._current_grid_prices(tt)
        return self._build_station_price_snapshot(tt, pb_e, ps_e)

    def get_grid_state(self, t: int) -> GridState:
        """Return the latest solved electrical state and current prices.

        The values are observations of the latest PDN solution.  They do not
        run an additional power flow and therefore are safe to call while the
        asynchronous simulation is paused for agent dispatch.
        """
        pb_e, ps_e = self._current_grid_prices(t)
        buses: List[GridBusStatus] = []
        voltage_violations: List[str] = []
        min_v: Optional[float] = None
        max_v: Optional[float] = None
        min_v_bus: Optional[str] = None
        max_v_bus: Optional[str] = None
        total_bus_load_kw = 0.0

        for bus in self.__gr.Buses:
            name = str(bus.ID)
            v = self._magnitude(getattr(bus, "V", None))
            vmin = self._value_at(getattr(bus, "MinV", None), t)
            vmax = self._value_at(getattr(bus, "MaxV", None), t)
            violation = bool(
                v is not None
                and ((vmin is not None and v < vmin - 1e-9) or (vmax is not None and v > vmax + 1e-9))
            )
            if violation:
                voltage_violations.append(name)
            if v is not None:
                if min_v is None or v < min_v:
                    min_v, min_v_bus = v, name
                if max_v is None or v > max_v:
                    max_v, max_v_bus = v, name
            pd = self._value_at(getattr(bus, "Pd", None), t)
            if pd is not None:
                total_bus_load_kw += pd * float(self.__gr.Sb_MVA) * 1000.0
            shadow = self._bus_shadow_price_per_kWh(name)
            eff_buy, eff_sell, price_source = self._effective_bus_prices(name, pb_e, ps_e)
            buses.append({
                "name": name,
                "voltage_pu": v,
                "min_voltage_pu": vmin,
                "max_voltage_pu": vmax,
                "voltage_violation": violation,
                "shadow_price_per_kWh": shadow,
                "effective_buy_price_per_kWh": eff_buy,
                "effective_sell_price_per_kWh": eff_sell,
                "price_source": price_source,
            })

        lines: List[GridLineStatus] = []
        thermal_violations: List[str] = []
        max_loading: Optional[float] = None
        max_loading_line: Optional[str] = None
        ib_ka = self._magnitude(getattr(self.__gr, "Ib", None))
        for line in self.__gr.Lines:
            name = str(line.ID)
            i_pu = self._magnitude(getattr(line, "I", None))
            i_ka = i_pu * ib_ka if i_pu is not None and ib_ka is not None else None
            limit_ka = self._magnitude(getattr(line, "max_I", None))
            loading = (i_ka / limit_ka) if i_ka is not None and limit_ka not in (None, 0.0) else None
            violation = bool(loading is not None and loading > 1.0 + 1e-9)
            if violation:
                thermal_violations.append(name)
            if loading is not None and (max_loading is None or loading > max_loading):
                max_loading, max_loading_line = loading, name
            lines.append({
                "name": name,
                "current_kA": i_ka,
                "limit_kA": limit_ka,
                "loading_pu": loading,
                "thermal_violation": violation,
            })

        total_generation_kw = 0.0
        for gen in self.__gr.Gens:
            p = self._value_at(getattr(gen, "P", None), t)
            if p is not None:
                total_generation_kw += p * float(self.__gr.Sb_MVA) * 1000.0

        gross_ev_kw = sum(self.__bus_charge_qbase_pu.values()) * float(self.__gr.Sb_MVA) * 1000.0
        v2g_kw = sum(self.__v2g_dispatch) * 3600.0
        net_ev_kw = gross_ev_kw - v2g_kw
        solve_result = getattr(self.last_ok, "name", str(self.last_ok))
        solver_feasible = (
            self.last_ok != GridSolveResult.Failed
            and not self._solve_result_has_grid_violation(self.last_ok)
        )
        feasible = bool(solver_feasible and not voltage_violations and not thermal_violations)
        shadow_prices:List[float] = []
        for row in buses:
            v = row.get("shadow_price_per_kWh")
            if v is not None: shadow_prices.append(v)
        return {
            "time": int(t),
            "last_solve_time": self.__last_solve_t,
            "solve_result": solve_result,
            "feasible": feasible,
            # Legacy global price fields are retained only for compatibility;
            # they now expose fallback cprice/dprice, not the active nodal price.
            "grid_buy_price_per_kWh": pb_e,
            "grid_sell_price_per_kWh": ps_e,
            "grid_marginal_price_per_kWh": None,
            "grid_marginal_price_basis": "deprecated global field; use buses[].shadow_price_per_kWh (nodal OPF shadow price)",
            "fallback_grid_buy_price_per_kWh": pb_e,
            "fallback_grid_sell_price_per_kWh": ps_e,
            "shadow_price_min_per_kWh": min(shadow_prices) if shadow_prices else None,
            "shadow_price_max_per_kWh": max(shadow_prices) if shadow_prices else None,
            "shadow_price_bus_count": len(shadow_prices),
            "price_basis": "nodal_shadow_price_with_cprice_dprice_fallback",
            "gross_ev_charging_kW": gross_ev_kw,
            "v2g_dispatch_kW": v2g_kw,
            "net_ev_load_kW": net_ev_kw,
            "total_bus_load_kW": total_bus_load_kw,
            "total_generation_kW": total_generation_kw,
            "min_voltage_pu": min_v,
            "min_voltage_bus": min_v_bus,
            "max_voltage_pu": max_v,
            "max_voltage_bus": max_v_bus,
            "max_line_loading_pu": max_loading,
            "max_line_loading_line": max_loading_line,
            "voltage_violations": voltage_violations,
            "thermal_violations": thermal_violations,
            "buses": buses,
            "lines": lines,
        }

    def check_manual_v2g_dispatch(
        self, t: int, dispatch_kW: Dict[str, float], replace: bool = True
    ) -> V2GDispatchCheck:
        """Preflight-check a manual station dispatch without changing state.

        User/EV availability and station capacity are checked immediately from
        the current bid curve. Candidate-specific network feasibility requires
        a PDN solve, so it is validated when the command is executed on the next
        simulation step. If fallback is enabled, an illegal executed command is
        automatically re-solved with the original V2G mechanism.
        """
        violations: List[Dict[str, object]] = []
        index = {cs.name: i for i, cs in enumerate(self.__v2g_stations)}
        curves = self.get_V2G_bid_curve(t)
        available = {name: sum(row["quantity_kW"] for row in curve) for name, curve in curves.items()}
        effective = (
            {cs.name: self.__manual_v2g_target[i] * 3600.0 for i, cs in enumerate(self.__v2g_stations)}
            if not replace else {cs.name: 0.0 for cs in self.__v2g_stations}
        )
        requested: Dict[str, float] = {}
        for name, raw in dispatch_kW.items():
            if name not in index:
                violations.append({"type": "unknown_station", "station": str(name)})
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                violations.append({"type": "invalid_value", "station": name, "value": str(raw)})
                continue
            if not math.isfinite(value) or value < 0.0:
                violations.append({"type": "invalid_value", "station": name, "value": value})
                continue
            requested[name] = value
            effective[name] = value

        online = self.v2g_online(t)
        if not online:
            violations.append({"type": "v2g_offline", "time": int(t)})

        accepted: Dict[str, float] = {}
        for name, target in effective.items():
            cap = float(available.get(name, 0.0))
            price_cap = cap
            if name in index:
                cs = self.__v2g_stations[index[name]]
                pb_fallback, ps_fallback = self._current_grid_prices(t)
                _, sell_price, _ = self._effective_bus_prices(cs.bus, pb_fallback, ps_fallback)
                if sell_price is not None:
                    price_cap = sum(
                        float(row["quantity_kW"]) for row in curves.get(name, [])
                        if float(row.get("price", row.get("user_price", 0.0))) <= float(sell_price) + 1e-12
                    )
            accepted[name] = min(target, cap, price_cap)
            if target > cap + 1e-9:
                violations.append({
                    "type": "v2g_capacity",
                    "station": name,
                    "requested_kW": target,
                    "maximum_kW": cap,
                })
            elif target > price_cap + 1e-9:
                violations.append({
                    "type": "v2g_minimum_price",
                    "station": name,
                    "requested_kW": target,
                    "maximum_accepted_kW": price_cap,
                })

        current_grid_feasible = self.get_grid_state(t).get("feasible", False)
        feasible = bool(self.is_manual_v2g_mode() and online and not violations)
        ret: V2GDispatchCheck = {
            "feasible": feasible,
            "time": int(t),
            "online": online,
            "replace": bool(replace),
            "requested_kW": requested,
            "effective_targets_kW": effective,
            "available_kW": available,
            "accepted_kW": accepted,
            "violations": violations,
            "grid_validation": "candidate network feasibility is validated by the next PDN solve",
            "current_grid_feasible": current_grid_feasible,
            "fallback_enabled": self.__manual_fallback_enabled,
            "would_fallback": bool(self.__manual_fallback_enabled and violations),
        }
        self.__last_manual_check = dict(ret)
        return ret

    def set_manual_v2g_dispatch(
        self, dispatch_kW: Dict[str, float], replace: bool = True, t: Optional[int] = None
    ):
        """Set persistent manual station V2G targets in kW.

        A new command exits any previous fallback state and forces a PDN solve
        on the next simulation step. Without fallback, targets retain the legacy
        clipping behaviour; with fallback, infeasible targets invoke native V2G.
        """
        if not self.is_manual_v2g_mode():
            raise RuntimeError("Manual V2G dispatch requires charging_mode='v2g_manual'")
        index = {cs.name: i for i, cs in enumerate(self.__v2g_stations)}
        unknown = sorted(set(dispatch_kW).difference(index))
        if unknown:
            raise KeyError("Unknown charging stations: " + ", ".join(unknown))
        normalized: Dict[str, float] = {}
        for name, value in dispatch_kW.items():
            value = float(value)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"Manual V2G target for {name} must be a finite non-negative kW value")
            normalized[name] = value
        check_t = int(t) if t is not None else (self.__last_apply_t if self.__last_apply_t >= 0 else 0)
        check = self.check_manual_v2g_dispatch(check_t, normalized, replace)
        if not check.get("feasible", False) and not self.__manual_fallback_enabled:
            raise ValueError(f"Manual V2G preflight failed: {check.get('violations', [])}")
        self._clear_manual_fallback()
        if replace:
            self.__manual_v2g_target = [0.0] * len(self.__v2g_stations)
        for name, value in normalized.items():
            self.__manual_v2g_target[index[name]] = value / 3600.0
        self.__manual_dispatch_dirty = True

    def clear_manual_v2g_dispatch(self):
        if not self.is_manual_v2g_mode():
            raise RuntimeError("Manual V2G dispatch requires charging_mode='v2g_manual'")
        self.__manual_v2g_target = [0.0] * len(self.__v2g_stations)
        self._clear_manual_fallback()
        self.__manual_dispatch_dirty = True
        self.__last_manual_check = {
            "time": self.__last_apply_t,
            "feasible": True,
            "cleared": True,
            "fallback_triggered": False,
        }

    def get_V2G_bid_curve(self, t: int) -> Dict[str, List[BidCurvePoint]]:
        """Return current per-station V2G bid curves for an external dispatcher."""
        if not self.v2g_online(t):
            return {cs.name: [] for cs in self.__v2g_stations}
        return {cs.name: cs.get_V2G_bid_curve(t) for cs in self.__v2g_stations}

    def get_V2G_status(self, t: int) -> V2GStatus:
        curves: Dict[str, List[BidCurvePoint]] = self.get_V2G_bid_curve(t)
        stations: List[V2GStationStatus] = []
        for i, cs in enumerate(self.__v2g_stations):
            curve = curves[cs.name]
            cap = sum(row["quantity_kW"] for row in curve)
            shadow = self._bus_shadow_price_per_kWh(cs.bus)
            pb_e, ps_e = self._current_grid_prices(t)
            eff_buy, eff_sell, price_source = self._effective_bus_prices(cs.bus, pb_e, ps_e)
            station: V2GStationStatus = {
                "name": cs.name,
                "bus": cs.bus,
                "capacity_kW": cap,
                "dispatch_kW": self.__v2g_dispatch[i] * 3600.0,
                "manual_target_kW": self.__manual_v2g_target[i] * 3600.0,
                "bid_curve": curve,
                "shadow_price_per_kWh": shadow,
                "effective_buy_price_per_kWh": eff_buy,
                "effective_sell_price_per_kWh": eff_sell,
                "price_source": price_source,
            }
            stations.append(station)
        pb_e, ps_e = self._current_grid_prices(t)
        station_shadows:List[float] = []
        for x in stations:
            v = x.get("shadow_price_per_kWh")
            if v is not None: station_shadows.append(v)
        status:V2GStatus = {
            "mode": self.__mode,
            "time": int(t),
            "online": self.v2g_online(t),
            "last_solve_time": self.__last_solve_t,
            "grid_buy_price_per_kWh": pb_e,
            "grid_sell_price_per_kWh": ps_e,
            "grid_marginal_price_per_kWh": None,
            "grid_marginal_price_basis": "deprecated global field; use stations[].shadow_price_per_kWh",
            "fallback_grid_buy_price_per_kWh": pb_e,
            "fallback_grid_sell_price_per_kWh": ps_e,
            "shadow_price_min_per_kWh": min(station_shadows) if station_shadows else None,
            "shadow_price_max_per_kWh": max(station_shadows) if station_shadows else None,
            "shadow_price_bus_count": len({x["bus"] for x in stations if x.get("shadow_price_per_kWh") is not None}),
            "price_basis": "nodal_shadow_price_with_cprice_dprice_fallback",
            "manual_fallback_enabled": self.__manual_fallback_enabled,
            "manual_fallback_active": self.__manual_fallback_active,
            "manual_fallback_reason": self.__manual_fallback_reason,
            "effective_control": (
                "original_v2g_fallback"
                if self.__manual_fallback_active else ("manual" if self.is_manual_v2g_mode() else self.__mode)
            ),
            "last_manual_check": dict(self.__last_manual_check),
            "stations": stations,
        }
        return status

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