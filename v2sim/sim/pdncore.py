"""Integrated power-distribution-network dispatch for V2Sim.

PDN, smart charging, and V2G are owned by the simulation core.  Their runtime
mode and solver settings come exclusively from the project *.v2simcfg file.
The plugin subsystem has no PDN/V2G configuration or implementation.

Each station step follows one deterministic sequence:

    station demand/capability -> PDN dispatch -> actual charge/discharge
"""

import math
import os
from copy import deepcopy
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
GRID_PREFLIGHT_VOLTAGE_TOL_PU = 1e-4
GRID_PREFLIGHT_THERMAL_TOL_PU = 1e-4


class V2GStationStatus(TypedDict):
    name: str
    bus: str
    capacity_kW: float
    energy_headroom_kWh: float
    grid_deliverable_energy_kWh: float
    dispatch_kW: float
    manual_target_kW: float
    bid_curve: List[BidCurvePoint]
    shadow_price_per_kWh: Optional[float]
    effective_buy_price_per_kWh: Optional[float]
    effective_sell_price_per_kWh: Optional[float]
    price_source: str
    metered_v2g_energy_step_kWh: float
    metered_v2g_system_payment_step: float
    metered_v2g_user_revenue_step: float
    metered_v2g_system_payment_rate_per_hour: float
    metered_v2g_user_revenue_rate_per_hour: float
    metered_v2g_energy_total_kWh: float
    metered_v2g_system_payment_total: float
    metered_v2g_user_revenue_total: float


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
    manual_runtime_saturation_since_command: bool
    manual_runtime_last_saturation_time: Optional[int]
    last_manual_check: Dict[str, object]
    stations: List[V2GStationStatus]
    effective_control: str
    metered_v2g_energy_total_kWh: float
    metered_v2g_system_payment_total: float
    metered_v2g_user_revenue_total: float
    metered_v2g_system_payment_rate_per_hour: float
    metered_v2g_user_revenue_rate_per_hour: float
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
    reference_grid_checked: bool
    reference_grid_absolute_feasible: bool
    reference_solve_result: str
    reference_grid_summary: Dict[str, object]
    candidate_grid_checked: bool
    candidate_grid_feasible: bool
    candidate_grid_absolute_feasible: bool
    candidate_grid_relative_safe: bool
    candidate_grid_basis: str
    candidate_solve_result: str
    candidate_objective: Optional[float]
    post_dispatch_shadow_price_per_kWh: Dict[str, Optional[float]]
    post_dispatch_effective_sell_price_per_kWh: Dict[str, Optional[float]]
    post_dispatch_price_source: Dict[str, str]
    post_dispatch_accepted_kW: Dict[str, float]
    recommended_dispatch_kW: Dict[str, float]
    price_consistent: bool
    candidate_grid_summary: Dict[str, object]
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
        # Most recent actual PDN/OPF solve (periodic or event-triggered).
        self.__last_solve_t = -1
        # Anchor for the configured periodic PDN cadence. Native V2G runtime
        # correction solves do not move this clock.
        self.__last_periodic_solve_t = -1
        self.__last_apply_t = -1
        self.__post_solve_hooks: List[Callable[[int], None]] = []

        self.__v2g_online = RangeList(config.v2g_online) if config.v2g_online else None
        self.__interval = max(1, int(config.pdn_interval))
        self.__manual_fallback_enabled = bool(config.v2g_manual_fallback_to_v2g)
        self.__manual_fallback_active = False
        self.__manual_fallback_reason: Optional[str] = None
        self.__manual_dispatch_dirty = False
        self.__last_manual_check: Dict[str, object] = {}
        # Runtime saturation is graceful degradation of a persistent Agent plan,
        # not Native fallback. Keep a per-command flag so the external controller
        # can audit whether its plan was clipped at any point in the interval.
        self.__manual_runtime_saturation_since_command = False
        self.__manual_runtime_last_saturation_time: Optional[int] = None
        # Same-time zero-manual reference used by reversible candidate preflight.
        # It is valid only while the simulator remains paused at one dispatch epoch.
        self.__candidate_reference_t = -1
        self.__candidate_reference_trial: Optional[Dict[str, object]] = None
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
        self.__bus_charge_qbase_pu: Dict[str, float] = {b: 0.0 for b in self.__gr.BusNames}
        # Manual V2G is represented as negative active load. Keep its reactive
        # injection separately so charging PF and V2G PF can differ.
        self.__bus_v2g_qinj_pu: Dict[str, float] = {b: 0.0 for b in self.__gr.BusNames}
        self.__bus_ratio: Dict[str, float] = {b: 1.0 for b in self.__gr.BusNames}
        self.__max_reduce_prop_cs: Dict[str, float] = {}
        self.__max_reduce_prop: Dict[str, float] = {}

        pf_charge = 0.9
        tan_phi = math.tan(math.acos(pf_charge))
        # V2G inverter fixed power factor. Positive Q means the V2G inverter
        # injects reactive power into the grid together with positive P.
        self.__v2g_pf = 0.95
        self.__v2g_tan_phi = math.tan(math.acos(self.__v2g_pf))

        for b, css in self.__pds.items():
            load_p = TimeImplictFunc(self._create_bus_load_getter(b, False))
            load_qbase = TimeImplictFunc(self._create_bus_load_getter(b, True))
            v2g_qload = TimeImplictFunc(self._create_bus_v2g_qload_getter(b))
            self.__gr.Bus(b).Pd += load_p
            self.__gr.Bus(b).Qd += load_qbase * tan_phi
            self.__gr.Bus(b).Qd += v2g_qload
            if b in decs:
                assert isinstance(self.__sol.est, LRSolverBase)
                self.__sol.est.AddReduce(b, load_p, tan_phi)
                self.__max_reduce_prop[b] = 0.0
                print(f"Enable load reduction at bus {b}", file=self.__fh)

        self.__v2g_stations: List[CS] = list(chain(inst.fcs, inst.scs))
        self.__v2g_cap: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_dispatch: List[float] = [0.0] * len(self.__v2g_stations)
        self.__v2g_bid_blocks: List[List[V2GBidBlock]] = [[] for _ in self.__v2g_stations]
        # Internal OPF-only V2G generators are dynamic.  Each station owns one
        # generator per *current exact price group*, not one per EV and not a
        # preallocated fleet-wide price pool.  Generator IDs are stable slot
        # names (0..n-1) so price changes with an unchanged group count only
        # update CVXPY Parameters; AddGen/DelGen is needed only when the group
        # count changes at an actual PDN solve.
        self.__v2g_gen_names: List[List[str]] = [[] for _ in self.__v2g_stations]
        self.__v2g_opf_groups: List[List[Tuple[float, float]]] = [
            [] for _ in self.__v2g_stations
        ]
        # Fixed station-level logical generator names used by statistics.
        # These are not Grid generators and therefore remain stable even though
        # the internal price-group generator set changes dynamically.
        v2g_mode_enabled = self.__mode in ("v2g", "v2g_manual")
        self.__v2g_log_gen_names: List[Optional[str]] = [
            (f"V2G_{cs._name}" if (v2g_mode_enabled and cs.supports_V2G) else None)
            for cs in self.__v2g_stations
        ]
        # Persistent station targets used only by charging_mode='v2g_manual'.
        self.__manual_v2g_target: List[float] = [0.0] * len(self.__v2g_stations)

        for cs in self.__v2g_stations:
            cs.set_integrated_v2g_mode(False)

    def _create_bus_load_getter(self, bus: str, reactive_base: bool):
        def _sumP():
            if reactive_base:
                return self.__bus_charge_qbase_pu[bus]
            return self.__bus_charge_pu[bus]
        return _sumP

    def _create_bus_v2g_qload_getter(self, bus: str):
        def _sumQ():
            # Bus.Qd uses positive sign for reactive demand. V2G reactive
            # injection is therefore represented as a negative Q demand.
            return -self.__bus_v2g_qinj_pu[bus]
        return _sumQ

    @property
    def V2GLogGenNames(self) -> List[str]:
        """Stable station-level V2G generator names exposed to statistics."""
        return [x for x in self.__v2g_log_gen_names if x is not None]

    @property
    def V2GBuses(self) -> List[str]:
        """Buses that may receive V2G generation during this simulation."""
        if self.__mode not in ("v2g", "v2g_manual"):
            return []
        return list(dict.fromkeys(
            cs.bus for cs in self.__v2g_stations if cs.supports_V2G
        ))

    def get_v2g_generator_log_data(self, t: int) -> Dict[str, Tuple[float, float, float]]:
        """Return station-aggregated V2G OPF output for ``gen`` statistics.

        Values use the same units as StaGen: MW, Mvar, and $/h.  Internal
        price-group generators remain fully heterogeneous in the OPF; this
        method only aggregates their solved outputs for logging.
        """
        out: Dict[str, Tuple[float, float, float]] = {}
        sb_MVA = self.__gr.Sb_MVA
        sb_kVA = self.__gr.Sb_kVA
        automatic = self._automatic_v2g_enabled(t)
        for i, log_name in enumerate(self.__v2g_log_gen_names):
            if log_name is None:
                continue
            p_pu = 0.0
            q_pu = 0.0
            cost = 0.0
            if automatic:
                for name in self.__v2g_gen_names[i]:
                    try:
                        g = self.__gr.Gen(name)
                    except KeyError:
                        continue
                    p = g.P(t) if callable(g.P) else g.P
                    q = g.Q(t) if callable(g.Q) else g.Q
                    gp = 0.0 if p is None else float(p)
                    gq = 0.0 if q is None else float(q)
                    p_pu += gp
                    q_pu += gq
                    # CostB was constructed as price[$/kWh] * Sb_kVA, so
                    # price * pu * Sb_kVA gives $/h.
                    price = float(getattr(g, "V2GBidPrice", 0.0))
                    cost += price * gp * sb_kVA
            elif self.is_manual_v2g_mode() and self.v2g_online(t):
                # In manual mode there is no OPF V2G generator output to log.
                # Use the station's ACTUAL post-update discharge and exact
                # per-step pay-as-bid system payment meter instead.  _dload is
                # kWh/s, so *3.6 converts to MW.
                cs = self.__v2g_stations[i]
                p_mw = float(getattr(cs, "_dload", 0.0)) * 3.6
                q_mvar = p_mw * self.__v2g_tan_phi
                cost = float(getattr(cs, "_v2g_actual_system_payment_rate_per_hour", 0.0))
                out[log_name] = (p_mw, q_mvar, cost)
                continue
            out[log_name] = (p_pu * sb_MVA, q_pu * sb_MVA, cost)
        return out

    def _make_v2g_group_generator(self, i: int, j: int) -> Generator:
        """Create one OPF generator slot for station ``i`` price-group ``j``."""
        cs = self.__v2g_stations[i]
        name = f"V2G_{cs._name}_BIDGROUP_{j}"
        gen = Generator(
            name, cs._bus,
            0.0, ComFunc(self._v2g_bid_cost_getter(i, j)), 0.0,
            -1.0, -1.0, None,
            0.0, ComFunc(self._v2g_bid_cap_getter(i, j)),
            None, None,
            None, 0.0,
        )
        # Native V2G uses a fixed 0.95 PF without an independent qg variable.
        gen.fixQ(0.0)
        gen.QtoPRatio = self.__v2g_tan_phi
        gen.IsV2GBidGroup = True
        gen.V2GStation = cs.name
        gen.V2GBidSlot = j
        return gen

    def _refresh_v2g_opf_groups(self) -> None:
        """Build exact current price groups from the per-EV bid curves.

        Grouping is exact: unequal floating-point prices are never rounded or
        merged.  The public/MCP bid curve remains per EV.
        """
        grouped: List[List[Tuple[float, float]]] = []
        for blocks in self.__v2g_bid_blocks:
            by_price: Dict[float, float] = {}
            for block in blocks:
                quantity = max(0.0, float(block.quantity))
                if quantity <= 0.0:
                    continue
                price = float(block.price)
                by_price[price] = by_price.get(price, 0.0) + quantity
            grouped.append(sorted(by_price.items(), key=lambda x: x[0]))
        self.__v2g_opf_groups = grouped

    def _sync_v2g_group_generators(self, t: int) -> bool:
        """Match Grid generators to the current exact price-group counts.

        This is called only immediately before a PDN solve.  Price/capacity
        changes with the same number of groups require no topology change: the
        existing ComFunc-backed Parameters are simply updated by FPowerKit.
        A group-count change adds/removes only trailing slot generators and then
        refreshes the estimator islands/cache exactly once.

        Returns True when Grid generator topology changed.
        """
        automatic = self._automatic_v2g_enabled(t)
        changed = False
        for i, cs in enumerate(self.__v2g_stations):
            desired = len(self.__v2g_opf_groups[i]) if (automatic and cs.supports_V2G) else 0
            names = self.__v2g_gen_names[i]

            while len(names) < desired:
                j = len(names)
                gen = self._make_v2g_group_generator(i, j)
                self.__gr.AddGen(gen)
                names.append(gen.ID)
                changed = True

            while len(names) > desired:
                name = names.pop()
                self.__gr.DelGen(name)
                changed = True

            # Snapshot the exact bid price represented by each slot at this
            # solve.  Statistics use this rather than the live ComFunc value so
            # held dispatch does not get repriced when EV groups change between
            # PDN solves.
            for j, name in enumerate(names):
                g = self.__gr.Gen(name)
                g.V2GBidPrice = float(self.__v2g_opf_groups[i][j][0])

        if changed and hasattr(self.__sol.est, "UpdateGrid"):
            # Generator membership changed, so Island.Gens and the cached CVXPY
            # graph must be rebuilt.  If counts are unchanged, no UpdateGrid is
            # issued and the parameterized problem is reused.
            self.__sol.est.UpdateGrid(self.__gr)
        return changed

    def _v2g_bid_cost_getter(self, i: int, j: int):
        def func(t: int) -> float:
            if not self._automatic_v2g_enabled(t):
                return 0.0
            if i >= len(self.__v2g_opf_groups) or j >= len(self.__v2g_opf_groups[i]):
                return 0.0
            price, _ = self.__v2g_opf_groups[i][j]
            # $/kWh -> coefficient for pu-h generation in FPowerKit.
            return price * self.__gr.Sb_kVA
        return func

    def _v2g_bid_cap_getter(self, i: int, j: int):
        def func(t: int) -> float:
            if not self._automatic_v2g_enabled(t):
                return 0.0
            if i >= len(self.__v2g_opf_groups) or j >= len(self.__v2g_opf_groups[i]):
                return 0.0
            _, quantity = self.__v2g_opf_groups[i][j]
            # kWh/s -> kW -> pu. This remains instantaneous V2G capacity;
            # grouping changes only the solver representation.
            return quantity * 3600.0 / self.__gr.Sb_kVA
        return func

    def _automatic_v2g_enabled(self, t: int) -> bool:
        if not self.v2g_online(t):
            return False
        if self.__mode == "v2g":
            return True
        return self.is_manual_v2g_mode() and self.__manual_fallback_enabled and self.__manual_fallback_active

    def _manual_dispatch_enabled(self, t: int) -> bool:
        return self.is_manual_v2g_mode() and self.v2g_online(t) and not self.__manual_fallback_active

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

        # Build the instantaneous per-EV V2G supply curve first.  New V2G
        # participation requires SoC>kv; an EV already present in the held
        # dispatch may remain available down to ks.  Charging behaviour is
        # handled by CS.get_requested_pc()/update() using the same hysteresis.
        if v2g_active:
            self.__v2g_bid_blocks = [cs.get_V2G_bid_blocks(t) for cs in self.__v2g_stations]
            self.__v2g_cap = [sum(x.quantity for x in blocks) for blocks in self.__v2g_bid_blocks]
            self._refresh_v2g_opf_groups()
            for cs, cap in zip(self.__v2g_stations, self.__v2g_cap):
                cs._cur_v2g_cap = cap
        else:
            self.__v2g_bid_blocks = [[] for _ in self.__v2g_stations]
            self.__v2g_cap = [0.0] * len(self.__v2g_stations)
            self.__v2g_opf_groups = [[] for _ in self.__v2g_stations]

        # Dynamic bid generators may remain in Grid until the next PDN solve.
        # When automatic V2G is not active, clear their held numerical outputs
        # immediately so bus/gen statistics never report stale V2G injection.
        if not self._automatic_v2g_enabled(t):
            for names in self.__v2g_gen_names:
                for name in names:
                    try:
                        g = self.__gr.Gen(name)
                    except KeyError:
                        continue
                    g._p = 0.0
                    g._q = 0.0

        manual_active = self._manual_dispatch_enabled(t)
        if manual_active:
            # Keep the agent target persistent, but execute only the currently
            # feasible instantaneous power. User minimum-price acceptance is
            # enforced here as well as in preflight. Energy headroom does NOT
            # enter this power limit.
            self.__v2g_dispatch = [
                min(target, self._manual_accepted_capacity(i))
                for i, target in enumerate(self.__manual_v2g_target)
            ]
            for i, cs in enumerate(self.__v2g_stations):
                cs.set_V2G_dispatch_plan(self._plan_from_total(i, self.__v2g_dispatch[i]))
        else:
            # Keep the previous automatic V2G plan through request collection
            # so an EV already discharging between periodic solves is not
            # simultaneously counted as charging after it crosses below kv.
            # The plan is replaced by _set_v2g_demands() later in this step.
            if not v2g_active:
                for cs in self.__v2g_stations:
                    cs.clear_V2G_dispatch_plan()

        requested_cs = []
        for cs in self.__v2g_stations:
            # Native and Manual V2G share the same entry/exit hysteresis:
            # enter above kv, and an already-selected discharge may continue
            # down to ks. No additional pre-allocation layer is used.
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
                self.__mode in ("v2g", "v2g_manual"),
            ))

        for b in self.__bus_charge_pu:
            self.__bus_charge_pu[b] = 0.0
            self.__bus_charge_qbase_pu[b] = 0.0
            self.__bus_v2g_qinj_pu[b] = 0.0
        for cs, pc in zip(self.__v2g_stations, requested_cs):
            pu = pc * 3.6 / self.__gr.Sb_MVA
            self.__bus_charge_pu[cs.bus] += pu
            self.__bus_charge_qbase_pu[cs.bus] += pu

        if manual_active:
            # Manual V2G is represented as negative load. Apply the same 0.95
            # PF as native V2G: P injection is accompanied by positive Q
            # injection, i.e. negative reactive demand at the bus. During
            # fallback the market V2G generators provide both P and Q instead.
            for cs, pd in zip(self.__v2g_stations, self.__v2g_dispatch):
                p_pu = pd * 3.6 / self.__gr.Sb_MVA
                self.__bus_charge_pu[cs.bus] -= p_pu
                self.__bus_v2g_qinj_pu[cs.bus] += p_pu * self.__v2g_tan_phi

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
                held = [
                    min(target, self._manual_accepted_capacity(i))
                    for i, target in enumerate(self.__manual_v2g_target)
                ]
                self.__v2g_dispatch = held
            else:
                # Automatic V2G (native v2g mode or manual fallback) holds the
                # last OPF dispatch command unchanged between periodic solves.
                # Current EV availability/SOC may make actual station discharge
                # lower; execution is clipped by the station/EV model and is
                # reflected by actual discharge statistics, not by a PDN re-solve.
                held = list(self.__v2g_dispatch)
        else:
            held = [0.0] * len(self.__v2g_stations)
            self.__v2g_dispatch = held
        self._set_v2g_demands(held)

        if self.is_smartcharge_mode():
            for b in self.__bus_charge_pu:
                ratio = self.__bus_ratio.get(b, 1.0)
                self.__bus_charge_pu[b] *= ratio
                self.__bus_charge_qbase_pu[b] *= ratio

    def _manual_accepted_capacity(self, i: int) -> float:
        """Current instantaneous manual-dispatch capacity accepted by users.

        This remains a power quantity (kWh/s). Energy headroom is deliberately
        not used here; it is exposed only as observation data to the agent.
        """
        cap = self.__v2g_cap[i]
        cs = self.__v2g_stations[i]
        _, sell_price, _ = self.__station_price_snapshot.get(cs.name, (None, None, "unavailable"))
        if sell_price is None:
            return cap
        price_cap = sum(
            block.quantity for block in self.__v2g_bid_blocks[i]
            if block.price <= float(sell_price) + 1e-12
        )
        return min(cap, price_cap)

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

        If a persistent manual target becomes larger than the currently
        dispatchable V2G resource, execution saturates at all currently available
        and price-accepted power while preserving the original plan for possible
        recovery later in the same decision interval.  Native fallback is reserved
        for PDN/grid-safety failures, not ordinary capacity/price shrinkage.
        """
        # Physical simulation state is about to advance/re-form requests, so any
        # cached same-time candidate-preflight reference is no longer valid.
        self.__candidate_reference_t = -1
        self.__candidate_reference_trial = None

        self.__last_pb_e = float(pb_e)
        self.__last_ps_e = float(ps_e)
        # Snapshot prices once per traffic step so PDN request formation and the
        # subsequent station update use the same price signal. A newly solved
        # ShadowPrice therefore takes effect on the next traffic step (normally
        # one simulation step later), avoiding an endogenous-price inconsistency
        # within a single step.
        self.__station_price_snapshot = self._build_station_price_snapshot(t, pb_e, ps_e)

        # A manual command is valid only inside the V2G-online window in which
        # it was issued.  Clear persistent targets as soon as V2G becomes
        # offline so a later online window can never inherit stale dispatch.
        # The first offline step also gets an event PDN solve to remove the
        # previous manual injection without shifting the regular periodic clock.
        manual_offline_clear_event = False
        if self.is_manual_v2g_mode() and not self.v2g_online(t):
            had_manual_state = (
                any(abs(float(x)) > 1e-12 for x in self.__manual_v2g_target)
                or any(abs(float(x)) > 1e-12 for x in self.__v2g_dispatch)
                or self.__manual_fallback_active
                or self.__manual_runtime_saturation_since_command
            )
            if had_manual_state:
                self.__manual_v2g_target = [0.0] * len(self.__v2g_stations)
                self.__v2g_dispatch = [0.0] * len(self.__v2g_stations)
                for cs in self.__v2g_stations:
                    cs.clear_V2G_dispatch_plan()
                self._clear_manual_fallback()
                self.__manual_runtime_saturation_since_command = False
                self.__manual_runtime_last_saturation_time = None
                self.__manual_dispatch_dirty = False
                self.__last_manual_check = {
                    "time": int(t),
                    "cleared": True,
                    "clear_reason": "v2g_offline",
                    "fallback_triggered": False,
                    "runtime_saturated": False,
                    "planned_total_kW": 0.0,
                    "effective_dispatch_total_kW": 0.0,
                }
                manual_offline_clear_event = True
                print(
                    f"[{t}] Cleared persistent manual V2G plan because V2G is offline.",
                    file=self.__fh,
                )

        # Native/fallback V2G is intentionally a snapshot OPF baseline.  The
        # network solver is not re-run when a previously dispatched V2G resource
        # later loses energy/capacity between periodic solves. Station execution
        # remains subject to the real EV V2G hysteresis (entry above kv, active
        # discharge floor at ks), and actual discharge is accounted by the
        # station statistics.
        periodic_due = (
            self.__last_periodic_solve_t < 0
            or self.__last_periodic_solve_t + self.__interval <= t
        )

        # Keep the original Agent plan persistent for the whole decision interval.
        # _collect_requests() computes the CURRENT executable manual dispatch as
        # min(planned target, current instantaneous capacity, current price-accepted
        # capacity).  If resources shrink after the decision, the controller now
        # saturates at all currently dispatchable power instead of abandoning the
        # manual plan and switching to Native V2G.  When resources recover, the
        # same persistent plan can rise again up to the original target.
        prev_manual_dispatch = list(self.__v2g_dispatch)
        requested_cs = self._collect_requests(t, pb_e, ps_e)
        self.__last_apply_t = t

        manual_attempt = self._manual_dispatch_enabled(t)
        capacity_violations = self._manual_capacity_violations() if manual_attempt else []
        violation_types = {str(v.get("type", "")) for v in capacity_violations}
        runtime_saturated = bool(manual_attempt and capacity_violations)
        runtime_saturation_reason = None
        if runtime_saturated:
            if "v2g_minimum_price" in violation_types and "v2g_capacity" in violation_types:
                runtime_saturation_reason = "manual_price_and_capacity_saturation"
            elif "v2g_minimum_price" in violation_types:
                runtime_saturation_reason = "manual_price_saturation"
            else:
                runtime_saturation_reason = "manual_capacity_saturation"
            self.__manual_runtime_saturation_since_command = True
            self.__manual_runtime_last_saturation_time = int(t)

        # Trigger an event solve only when the executable manual dispatch actually
        # changes.  This avoids solving every 10 s merely because the persistent
        # plan remains above a temporarily smaller available resource.  A recovery
        # toward the original plan also triggers a solve because injection rises.
        manual_dispatch_changed = bool(
            manual_attempt
            and any(
                abs(float(now) - float(prev)) > 1e-12
                for now, prev in zip(self.__v2g_dispatch, prev_manual_dispatch)
            )
        )
        manual_command_event = bool(manual_attempt and self.__manual_dispatch_dirty)
        manual_runtime_event = bool(
            manual_attempt and not manual_command_event and manual_dispatch_changed
        )

        # Native/fallback V2G solves only on the configured periodic PDN cadence.
        # Manual control is event-driven when a new command is submitted or the
        # CURRENT executable dispatch changes because availability/price changed.
        due = periodic_due or manual_command_event or manual_runtime_event or manual_offline_clear_event
        # Runtime saturation/recovery and offline-plan clearing must not move the
        # regular PDN clock.
        reanchor_periodic = periodic_due or manual_command_event
        if manual_runtime_event:
            planned_total = sum(self.__manual_v2g_target) * 3600.0
            effective_total = sum(self.__v2g_dispatch) * 3600.0
            print(
                f"[{t}] V2G runtime saturation/recovery solve: "
                f"plan={planned_total:.3f} kW, executable={effective_total:.3f} kW.",
                file=self.__fh,
            )
        if manual_offline_clear_event:
            print(f"[{t}] V2G offline-clear PDN solve.", file=self.__fh)
        if manual_attempt:
            self.__last_manual_check = {
                "time": int(t),
                # 'capacity_feasible' retains its old meaning: whether the FULL
                # persistent plan is currently executable without saturation.
                "capacity_feasible": not bool(capacity_violations),
                "violations": capacity_violations,
                "grid_feasible": None,
                "fallback_triggered": False,
                "runtime_saturated": runtime_saturated,
                "runtime_saturation_reason": runtime_saturation_reason,
                "planned_total_kW": sum(self.__manual_v2g_target) * 3600.0,
                "effective_dispatch_total_kW": sum(self.__v2g_dispatch) * 3600.0,
                "planned_targets_kW": {
                    cs.name: self.__manual_v2g_target[i] * 3600.0
                    for i, cs in enumerate(self.__v2g_stations)
                    if self.__manual_v2g_target[i] > 1e-12
                },
                "effective_dispatch_kW": {
                    cs.name: self.__v2g_dispatch[i] * 3600.0
                    for i, cs in enumerate(self.__v2g_stations)
                    if self.__v2g_dispatch[i] > 1e-12
                },
            }

        # IMPORTANT: ordinary runtime capacity/price shrinkage no longer activates
        # Native fallback.  The manual plan remains persistent and execution uses
        # all currently dispatchable power up to that plan.  Native fallback is
        # reserved for an actual PDN solve failure / grid-constraint safety event
        # below, where continuing manual control cannot be certified.

        # PDN is always active. Only V2G participation is time-gated by
        # v2g_online; the network itself continues solving at pdn_interval.
        if not due:
            self._apply_held_dispatch(requested_cs, t)
            return

        prev_solve_t = self.__last_solve_t
        # Materialize exactly one internal generator per current exact price
        # group only when an actual PDN solve is about to occur.
        self._sync_v2g_group_generators(t)
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
            self._sync_v2g_group_generators(t)
            ok, _ = self.__sol.solve(t)
        elif self.is_manual_v2g_mode() and self.__last_manual_check:
            self.__last_manual_check["grid_feasible"] = (
                ok != GridSolveResult.Failed and not self._solve_result_has_grid_violation(ok)
            )

        self.__last_solve_t = t
        if reanchor_periodic:
            self.__last_periodic_solve_t = t
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
                    min(target, self._manual_accepted_capacity(i))
                    for i, target in enumerate(self.__manual_v2g_target)
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

    def _snapshot_candidate_trial_state(self) -> Dict[str, object]:
        """Snapshot mutable numerical state touched by a candidate PDN trial solve.

        CVXPY canonicalization/warm-start caches are intentionally not copied: they
        are computational caches, not simulation state, and retaining them makes a
        successful preflight cheaper to execute for real on the next step.
        """
        est = self.__sol.est
        estimator_state: Dict[str, object] = {
            "internal_error": getattr(est, "internal_error", None),
            "islands": [
                (il, getattr(il, "result", None), getattr(il, "result_value", None))
                for il in getattr(est, "Islands", [])
            ],
        }
        for attr in ("_DistFlowSolver__il_relax", "_ofbuses", "_oflines"):
            if hasattr(est, attr):
                estimator_state[attr] = deepcopy(getattr(est, attr))
        reductions: List[Tuple[object, object]] = []
        if isinstance(est, LRSolverBase):
            for lim in est.DecBuses.values():
                reductions.append((lim, getattr(lim, "Reduction", None)))

        return {
            "bus_charge_pu": dict(self.__bus_charge_pu),
            "bus_charge_qbase_pu": dict(self.__bus_charge_qbase_pu),
            "bus_v2g_qinj_pu": dict(self.__bus_v2g_qinj_pu),
            "v2g_dispatch": list(self.__v2g_dispatch),
            "manual_fallback_active": self.__manual_fallback_active,
            "manual_fallback_reason": self.__manual_fallback_reason,
            "last_ok": self.last_ok,
            "last_solve_t": self.__last_solve_t,
            "station_plans": [
                (cs, dict(getattr(cs, "_v2g_dispatch_plan", {})), bool(getattr(cs, "_integrated_v2g_mode", False)))
                for cs in self.__v2g_stations
            ],
            "buses": [
                (bus, getattr(bus, "_v", None), getattr(bus, "_t", None), getattr(bus, "ShadowPrice", None))
                for bus in self.__gr.Buses
            ],
            "lines": [
                (line, getattr(line, "P", None), getattr(line, "Q", None), getattr(line, "I", None))
                for line in self.__gr.Lines
            ],
            "gens": [
                (gen, getattr(gen, "_p", None), getattr(gen, "_q", None), getattr(gen, "CostShadow", None))
                for gen in self.__gr.Gens
            ],
            "pvwinds": [
                (pv, getattr(pv, "_pr", None), getattr(pv, "_qr", None), getattr(pv, "_cr", None))
                for pv in self.__gr.PVWinds
            ],
            "ess": [(ess, getattr(ess, "P", None)) for ess in self.__gr.ESSs],
            "reductions": reductions,
            "estimator": estimator_state,
        }

    def _restore_candidate_trial_state(self, snap: Dict[str, object]) -> None:
        self.__bus_charge_pu.clear()
        self.__bus_charge_pu.update(snap["bus_charge_pu"])  # type: ignore[arg-type]
        self.__bus_charge_qbase_pu.clear()
        self.__bus_charge_qbase_pu.update(snap["bus_charge_qbase_pu"])  # type: ignore[arg-type]
        self.__bus_v2g_qinj_pu.clear()
        self.__bus_v2g_qinj_pu.update(snap["bus_v2g_qinj_pu"])  # type: ignore[arg-type]
        self.__v2g_dispatch = list(snap["v2g_dispatch"])  # type: ignore[arg-type]
        self.__manual_fallback_active = bool(snap["manual_fallback_active"])
        self.__manual_fallback_reason = snap["manual_fallback_reason"]  # type: ignore[assignment]
        self.last_ok = snap["last_ok"]  # type: ignore[assignment]
        self.__last_solve_t = int(snap["last_solve_t"])  # type: ignore[assignment]

        for cs, plan, integrated in snap["station_plans"]:  # type: ignore[assignment]
            cs.set_V2G_dispatch_plan(plan)
            cs.set_integrated_v2g_mode(bool(integrated))
        for bus, v, theta, shadow in snap["buses"]:  # type: ignore[assignment]
            bus._v = v
            bus._t = theta
            bus.ShadowPrice = shadow
        for line, pp, qq, ii in snap["lines"]:  # type: ignore[assignment]
            line.P = pp
            line.Q = qq
            line.I = ii
        for gen, pp, qq, cshadow in snap["gens"]:  # type: ignore[assignment]
            gen._p = pp
            gen._q = qq
            gen.CostShadow = cshadow
        for pv, pr, qr, cr in snap["pvwinds"]:  # type: ignore[assignment]
            pv._pr = pr
            pv._qr = qr
            pv._cr = cr
        for ess, power in snap["ess"]:  # type: ignore[assignment]
            ess.P = power
        for lim, reduction in snap["reductions"]:  # type: ignore[assignment]
            lim.Reduction = reduction

        est = self.__sol.est
        est_state = snap["estimator"]  # type: ignore[assignment]
        est.internal_error = est_state.get("internal_error")
        for il, result, result_value in est_state.get("islands", []):
            il.result = result
            il.result_value = result_value
        for attr in ("_DistFlowSolver__il_relax", "_ofbuses", "_oflines"):
            if attr in est_state:
                setattr(est, attr, deepcopy(est_state[attr]))

    @staticmethod
    def _grid_violation_metrics(grid_state: Dict[str, object]) -> Dict[str, float]:
        """Return continuous violation magnitudes for relative candidate safety.

        CombinedSolver may legitimately return OK while its downstream AC calculator
        reports a voltage outside the static OPF bounds.  Therefore candidate
        preflight compares a proposed action against a same-time zero-manual
        reference instead of rejecting every action solely because an exogenous
        baseline violation already exists.
        """
        v_excess: List[float] = []
        for row in grid_state.get("buses", []) or []:
            if not isinstance(row, dict):
                continue
            try:
                v = float(row.get("voltage_pu"))
            except (TypeError, ValueError, OverflowError):
                continue
            excess = 0.0
            try:
                vmin = row.get("min_voltage_pu")
                if vmin is not None:
                    excess = max(excess, float(vmin) - v)
            except (TypeError, ValueError, OverflowError):
                pass
            try:
                vmax = row.get("max_voltage_pu")
                if vmax is not None:
                    excess = max(excess, v - float(vmax))
            except (TypeError, ValueError, OverflowError):
                pass
            v_excess.append(max(0.0, excess))

        i_excess: List[float] = []
        for row in grid_state.get("lines", []) or []:
            if not isinstance(row, dict):
                continue
            try:
                loading = float(row.get("loading_pu"))
            except (TypeError, ValueError, OverflowError):
                continue
            i_excess.append(max(0.0, loading - 1.0))

        return {
            "voltage_violation_count": float(sum(x > 1e-12 for x in v_excess)),
            "voltage_violation_max_pu": max(v_excess, default=0.0),
            "voltage_violation_sum_pu": sum(v_excess),
            "thermal_violation_count": float(sum(x > 1e-12 for x in i_excess)),
            "thermal_violation_max_pu": max(i_excess, default=0.0),
            "thermal_violation_sum_pu": sum(i_excess),
        }

    @staticmethod
    def _candidate_relative_grid_safe(
        reference: Dict[str, object], candidate: Dict[str, object]
    ) -> Tuple[bool, str]:
        """Judge electrical safety against a same-time zero-manual reference.

        If the reference is absolutely feasible, the candidate must also be
        absolutely feasible.  If the reference already violates AC voltage/current
        limits, a candidate is allowed only when it does not worsen the continuous
        violation magnitudes beyond small numerical tolerances.
        """
        if not bool(candidate.get("solver_feasible", False)):
            return False, "candidate_solver_failed_or_relaxed"

        ref_abs = bool(reference.get("grid_feasible", False))
        cand_abs = bool(candidate.get("grid_feasible", False))
        if ref_abs:
            return cand_abs, "absolute_feasibility_required_from_feasible_reference"
        if cand_abs:
            return True, "candidate_restores_absolute_feasibility"
        if not bool(reference.get("solver_feasible", False)):
            return False, "reference_solver_unusable"

        rm = reference.get("grid_metrics") or {}
        cm = candidate.get("grid_metrics") or {}
        if not isinstance(rm, dict) or not isinstance(cm, dict):
            return False, "missing_grid_violation_metrics"

        def f(d: Dict[str, object], key: str) -> float:
            try:
                return float(d.get(key, 0.0) or 0.0)
            except (TypeError, ValueError, OverflowError):
                return 0.0

        voltage_not_worse = (
            f(cm, "voltage_violation_max_pu")
            <= f(rm, "voltage_violation_max_pu") + GRID_PREFLIGHT_VOLTAGE_TOL_PU
            and f(cm, "voltage_violation_sum_pu")
            <= f(rm, "voltage_violation_sum_pu") + GRID_PREFLIGHT_VOLTAGE_TOL_PU
        )
        thermal_not_worse = (
            f(cm, "thermal_violation_max_pu")
            <= f(rm, "thermal_violation_max_pu") + GRID_PREFLIGHT_THERMAL_TOL_PU
            and f(cm, "thermal_violation_sum_pu")
            <= f(rm, "thermal_violation_sum_pu") + GRID_PREFLIGHT_THERMAL_TOL_PU
        )
        return bool(voltage_not_worse and thermal_not_worse), "relative_non_worsening_from_infeasible_reference"

    @staticmethod
    def _plan_from_blocks_for_trial(blocks: List[V2GBidBlock], target_kW: float) -> Dict[str, Tuple[float, float, float]]:
        left = max(0.0, float(target_kW)) / 3600.0
        plan: Dict[str, Tuple[float, float, float]] = {}
        for block in blocks:
            if left <= 1e-15:
                break
            power = min(left, float(block.quantity))
            if power > 0.0:
                plan[block.ev._name] = (power, float(block.user_price), float(block.price))
                left -= power
        return plan

    def _trial_manual_v2g_dispatch(
        self,
        t: int,
        effective_kW: Dict[str, float],
        curves: Dict[str, List[BidCurvePoint]],
    ) -> Dict[str, object]:
        """Solve a candidate manual dispatch, then restore all physical simulation state.

        The trial uses the configured PDN estimator/calculator on current EV/network
        state.  It also recomputes station ShadowPrices after the candidate injection
        so minimum-price feasibility is checked against the *post-dispatch* nodal
        value rather than only the stale pre-dispatch value.
        """
        snap = self._snapshot_candidate_trial_state()
        try:
            pb_e, ps_e = self._current_grid_prices(t)
            station_prices = self._build_station_price_snapshot(t, pb_e, ps_e)
            online = self.v2g_online(t)

            # A manual candidate must be solved without Native/fallback V2G market
            # generators. Their Pmax getters observe this flag and collapse to zero.
            self.__manual_fallback_active = False
            self.__manual_fallback_reason = None

            candidate_dispatch: List[float] = []
            for cs in self.__v2g_stations:
                target_kw = max(0.0, float(effective_kW.get(cs.name, 0.0)))
                target = target_kw / 3600.0
                candidate_dispatch.append(target)
                cs.set_integrated_v2g_mode(online)
                blocks = cs.get_V2G_bid_blocks(t) if (online and cs.supports_V2G) else []
                cs.set_V2G_dispatch_plan(self._plan_from_blocks_for_trial(blocks, target_kw))

            # Recreate the current same-step charging request under the candidate
            # dispatch plan. This mirrors _collect_requests() without modifying EV SOC.
            for b in self.__bus_charge_pu:
                self.__bus_charge_pu[b] = 0.0
                self.__bus_charge_qbase_pu[b] = 0.0
                self.__bus_v2g_qinj_pu[b] = 0.0
            for cs, target in zip(self.__v2g_stations, candidate_dispatch):
                cs_pb_e, cs_ps_e, _ = station_prices.get(
                    cs.name, (pb_e, ps_e, "cprice_dprice_fallback")
                )
                req = cs.get_requested_pc(
                    t,
                    pb_e if cs_pb_e is None else cs_pb_e,
                    ps_e if cs_ps_e is None else cs_ps_e,
                    self.__mode in ("v2g", "v2g_manual"),
                )
                req_pu = float(req) * 3.6 / self.__gr.Sb_MVA
                self.__bus_charge_pu[cs.bus] += req_pu
                self.__bus_charge_qbase_pu[cs.bus] += req_pu
                if target > 0.0:
                    p_pu = target * 3.6 / self.__gr.Sb_MVA
                    self.__bus_charge_pu[cs.bus] -= p_pu
                    self.__bus_v2g_qinj_pu[cs.bus] += p_pu * self.__v2g_tan_phi

            self.__v2g_dispatch = candidate_dispatch
            ok, objective = self.__sol.solve(t)
            self.last_ok = ok
            self.__last_solve_t = int(t)
            trial_grid = self.get_grid_state(t)
            solver_feasible = bool(
                ok != GridSolveResult.Failed
                and not self._solve_result_has_grid_violation(ok)
            )
            candidate_grid_absolute_feasible = bool(
                solver_feasible and trial_grid.get("feasible", False)
            )
            grid_metrics = self._grid_violation_metrics(trial_grid)

            post_shadow: Dict[str, Optional[float]] = {}
            post_effective_sell: Dict[str, Optional[float]] = {}
            post_price_source: Dict[str, str] = {}
            post_accepted: Dict[str, float] = {}
            recommended: Dict[str, float] = {}
            price_violations: List[Dict[str, object]] = []
            for name, target in effective_kW.items():
                if target <= 1e-9:
                    continue
                idx = next((i for i, cs in enumerate(self.__v2g_stations) if cs.name == name), None)
                if idx is None:
                    continue
                cs = self.__v2g_stations[idx]
                shadow = self._bus_shadow_price_per_kWh(cs.bus)
                _, post_sell, source = self._effective_bus_prices(cs.bus, pb_e, ps_e)
                post_shadow[name] = shadow
                post_effective_sell[name] = post_sell
                post_price_source[name] = source
                if post_sell is None:
                    cap = 0.0
                else:
                    cap = sum(
                        float(row["quantity_kW"]) for row in curves.get(name, [])
                        if float(row.get("price", row.get("user_price", 0.0))) <= float(post_sell) + 1e-12
                    )
                post_accepted[name] = cap
                recommended[name] = min(float(target), cap)
                if float(target) > cap + 1e-9:
                    price_violations.append({
                        "type": "candidate_post_price_infeasible",
                        "station": name,
                        "requested_kW": float(target),
                        "maximum_accepted_kW": cap,
                        "post_dispatch_shadow_price_per_kWh": shadow,
                        "post_dispatch_effective_sell_price_per_kWh": post_sell,
                        "post_dispatch_price_source": source,
                    })

            return {
                "checked": True,
                "solver_feasible": solver_feasible,
                # Backward-compatible name: this is ABSOLUTE AC-state feasibility.
                # check_manual_v2g_dispatch applies the same-time relative-safety
                # rule separately when the reference is already infeasible.
                "grid_feasible": candidate_grid_absolute_feasible,
                "grid_metrics": grid_metrics,
                "solve_result": getattr(ok, "name", str(ok)),
                "objective": float(objective) if isinstance(objective, (int, float)) and math.isfinite(float(objective)) else None,
                "post_shadow_price_per_kWh": post_shadow,
                "post_effective_sell_price_per_kWh": post_effective_sell,
                "post_price_source": post_price_source,
                "post_accepted_kW": post_accepted,
                "recommended_dispatch_kW": recommended,
                "price_consistent": not price_violations,
                "price_violations": price_violations,
                "grid_summary": {
                    "min_voltage_pu": trial_grid.get("min_voltage_pu"),
                    "min_voltage_bus": trial_grid.get("min_voltage_bus"),
                    "max_voltage_pu": trial_grid.get("max_voltage_pu"),
                    "max_voltage_bus": trial_grid.get("max_voltage_bus"),
                    "max_line_loading_pu": trial_grid.get("max_line_loading_pu"),
                    "max_line_loading_line": trial_grid.get("max_line_loading_line"),
                    "voltage_violation_count": len(trial_grid.get("voltage_violations") or []),
                    "thermal_violation_count": len(trial_grid.get("thermal_violations") or []),
                },
            }
        except Exception as exc:
            return {
                "checked": True,
                "solver_feasible": False,
                "grid_feasible": False,
                "grid_metrics": {},
                "solve_result": "trial_error",
                "objective": None,
                "post_shadow_price_per_kWh": {},
                "post_effective_sell_price_per_kWh": {},
                "post_price_source": {},
                "post_accepted_kW": {},
                "recommended_dispatch_kW": {},
                "price_consistent": False,
                "price_violations": [{
                    "type": "candidate_trial_error",
                    "message": f"{type(exc).__name__}: {exc}",
                }],
                "grid_summary": {},
            }
        finally:
            self._restore_candidate_trial_state(snap)

    def check_manual_v2g_dispatch(
        self, t: int, dispatch_kW: Dict[str, float], replace: bool = True
    ) -> V2GDispatchCheck:
        """Preflight-check a manual station dispatch without advancing simulation state.

        The check has two stages. First, validate names, values, instantaneous EV
        capacity, and current-price bid acceptance. If those pass, solve a reversible
        SAME-TIME zero-manual reference and the proposed manual injection. When the
        reference is already AC-infeasible, the candidate is accepted electrically
        only if it is non-worsening (or restores feasibility); otherwise absolute
        feasibility is required. Bid acceptance is then re-checked against the
        candidate *post-dispatch* nodal ShadowPrice. All physical/grid numerical
        state is restored; only solver computational caches may remain warmed.
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
        if not self.is_manual_v2g_mode():
            violations.append({"type": "not_v2g_manual_mode"})
        if not online:
            violations.append({"type": "v2g_offline", "time": int(t)})

        accepted: Dict[str, float] = {}
        pb_fallback, ps_fallback = self._current_grid_prices(t)
        for name, target in effective.items():
            cap = float(available.get(name, 0.0))
            price_cap = cap
            if name in index:
                cs = self.__v2g_stations[index[name]]
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
        trial: Dict[str, object] = {
            "checked": False,
            "solver_feasible": False,
            "grid_feasible": False,
            "grid_metrics": {},
            "solve_result": "not_run",
            "objective": None,
            "post_shadow_price_per_kWh": {},
            "post_effective_sell_price_per_kWh": {},
            "post_price_source": {},
            "post_accepted_kW": {},
            "recommended_dispatch_kW": {
                name: min(float(target), float(accepted.get(name, 0.0)))
                for name, target in effective.items() if target > 1e-9
            },
            "price_consistent": False,
            "price_violations": [],
            "grid_summary": {},
        }
        reference: Dict[str, object] = {
            "checked": False,
            "solver_feasible": False,
            "grid_feasible": False,
            "grid_metrics": {},
            "solve_result": "not_run",
            "grid_summary": {},
        }
        candidate_relative_safe = False
        candidate_grid_basis = "candidate trial not run"

        # A candidate trial is meaningful only after the cheap deterministic
        # checks pass.  Electrical safety is judged against a SAME-TIME zero-
        # manual reference. This is essential when the exogenous/reference grid
        # already has an AC voltage violation: an empty action must remain a
        # valid neutral action, and V2G that improves/does-not-worsen that state
        # must not be rejected merely because the absolute violation persists.
        if self.is_manual_v2g_mode() and online and not violations:
            if self.__candidate_reference_t == int(t) and isinstance(self.__candidate_reference_trial, dict):
                reference = deepcopy(self.__candidate_reference_trial)
            else:
                zero_effective = {cs.name: 0.0 for cs in self.__v2g_stations}
                reference = self._trial_manual_v2g_dispatch(t, zero_effective, curves)
                self.__candidate_reference_t = int(t)
                self.__candidate_reference_trial = deepcopy(reference)

            is_zero_candidate = not any(float(v) > 1e-9 for v in effective.values())
            trial = deepcopy(reference) if is_zero_candidate else self._trial_manual_v2g_dispatch(t, effective, curves)
            candidate_relative_safe, candidate_grid_basis = self._candidate_relative_grid_safe(reference, trial)
            if not candidate_relative_safe:
                violations.append({
                    "type": "candidate_grid_worsens_reference",
                    "solve_result": trial.get("solve_result"),
                    "basis": candidate_grid_basis,
                    "reference_grid_summary": reference.get("grid_summary", {}),
                    "candidate_grid_summary": trial.get("grid_summary", {}),
                    "reference_grid_metrics": reference.get("grid_metrics", {}),
                    "candidate_grid_metrics": trial.get("grid_metrics", {}),
                })
            for item in trial.get("price_violations", []) or []:
                if isinstance(item, dict):
                    violations.append(item)

        feasible = bool(
            self.is_manual_v2g_mode()
            and online
            and not violations
            and bool(trial.get("checked", False))
            and candidate_relative_safe
            and bool(trial.get("price_consistent", False))
        )
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
            "grid_validation": (
                "same-time zero-manual reference + reversible candidate PDN solve + "
                "relative AC-grid safety + post-dispatch nodal ShadowPrice consistency"
                if trial.get("checked") else "candidate trial skipped because basic preflight failed"
            ),
            # current_grid_feasible is the latest previously solved observation and
            # may be from the prior PDN interval. reference_* is the authoritative
            # same-time zero-manual comparison used by this preflight.
            "current_grid_feasible": current_grid_feasible,
            "reference_grid_checked": bool(reference.get("checked", False)),
            "reference_grid_absolute_feasible": bool(reference.get("grid_feasible", False)),
            "reference_solve_result": str(reference.get("solve_result", "not_run")),
            "reference_grid_summary": reference.get("grid_summary", {}),
            "candidate_grid_checked": bool(trial.get("checked", False)),
            # Backward-compatible candidate_grid_feasible now means the HARD
            # preflight electrical verdict (absolute when reference is feasible,
            # relative non-worsening when reference is already infeasible).
            "candidate_grid_feasible": bool(candidate_relative_safe),
            "candidate_grid_absolute_feasible": bool(trial.get("grid_feasible", False)),
            "candidate_grid_relative_safe": bool(candidate_relative_safe),
            "candidate_grid_basis": candidate_grid_basis,
            "candidate_solve_result": str(trial.get("solve_result", "not_run")),
            "candidate_objective": trial.get("objective"),
            "post_dispatch_shadow_price_per_kWh": trial.get("post_shadow_price_per_kWh", {}),
            "post_dispatch_effective_sell_price_per_kWh": trial.get("post_effective_sell_price_per_kWh", {}),
            "post_dispatch_price_source": trial.get("post_price_source", {}),
            "post_dispatch_accepted_kW": trial.get("post_accepted_kW", {}),
            "recommended_dispatch_kW": trial.get("recommended_dispatch_kW", {}),
            "price_consistent": bool(trial.get("price_consistent", False)),
            "candidate_grid_summary": trial.get("grid_summary", {}),
            "fallback_enabled": self.__manual_fallback_enabled,
            # Runtime capacity/price shrinkage is saturated, not sent to Native.
            # Only candidate PDN/grid-safety failures imply a Native fallback path.
            "would_fallback": bool(
                self.__manual_fallback_enabled
                and any(
                    str(v.get("type", "")) in {
                        "candidate_grid_infeasible",
                        "candidate_pdn_solve_failed",
                    }
                    for v in violations
                )
            ),
        }
        self.__last_manual_check = dict(ret)
        return ret

    def set_manual_v2g_dispatch(
        self, dispatch_kW: Dict[str, float], replace: bool = True, t: Optional[int] = None
    ):
        """Set persistent manual station V2G targets in kW.

        A new command exits any previous fallback state and forces a PDN solve
        on the next simulation step.  The submitted target is the persistent plan:
        during execution it is automatically saturated to current dispatchable
        capacity/price acceptance.  Native fallback is reserved for PDN/grid-safety
        failures rather than ordinary runtime resource shrinkage.
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
        cached = self.__last_manual_check
        reuse_cached = bool(
            isinstance(cached, dict)
            and cached.get("time") == check_t
            and bool(cached.get("replace", True)) == bool(replace)
            and cached.get("requested_kW") == normalized
            and cached.get("candidate_grid_checked", False)
        )
        # MCP callers normally run check_v2g_dispatch immediately before set.
        # Reuse that reversible trial result while the simulation is paused so
        # set_v2g_dispatch does not perform the same expensive candidate solve twice.
        check = cached if reuse_cached else self.check_manual_v2g_dispatch(check_t, normalized, replace)
        if not check.get("feasible", False) and not self.__manual_fallback_enabled:
            raise ValueError(f"Manual V2G preflight failed: {check.get('violations', [])}")
        self._clear_manual_fallback()
        self.__manual_runtime_saturation_since_command = False
        self.__manual_runtime_last_saturation_time = None
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
        self.__manual_runtime_saturation_since_command = False
        self.__manual_runtime_last_saturation_time = None
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
            battery_headroom, grid_headroom = cs.get_V2G_energy_headroom(t)
            station: V2GStationStatus = {
                "name": cs.name,
                "bus": cs.bus,
                "capacity_kW": cap,
                "energy_headroom_kWh": battery_headroom,
                "grid_deliverable_energy_kWh": grid_headroom,
                "dispatch_kW": self.__v2g_dispatch[i] * 3600.0,
                "manual_target_kW": self.__manual_v2g_target[i] * 3600.0,
                "bid_curve": curve,
                "shadow_price_per_kWh": shadow,
                "effective_buy_price_per_kWh": eff_buy,
                "effective_sell_price_per_kWh": eff_sell,
                "price_source": price_source,
                "metered_v2g_energy_step_kWh": float(getattr(cs, "_v2g_actual_energy_step_kWh", 0.0)),
                "metered_v2g_system_payment_step": float(getattr(cs, "_v2g_actual_system_payment_step", 0.0)),
                "metered_v2g_user_revenue_step": float(getattr(cs, "_v2g_actual_user_revenue_step", 0.0)),
                "metered_v2g_system_payment_rate_per_hour": float(getattr(cs, "_v2g_actual_system_payment_rate_per_hour", 0.0)),
                "metered_v2g_user_revenue_rate_per_hour": float(getattr(cs, "_v2g_actual_user_revenue_rate_per_hour", 0.0)),
                "metered_v2g_energy_total_kWh": float(getattr(cs, "_v2g_actual_energy_total_kWh", 0.0)),
                "metered_v2g_system_payment_total": float(getattr(cs, "_v2g_actual_system_payment_total", 0.0)),
                "metered_v2g_user_revenue_total": float(getattr(cs, "_v2g_actual_user_revenue_total", 0.0)),
            }
            stations.append(station)
        pb_e, ps_e = self._current_grid_prices(t)
        station_shadows:List[float] = []
        for x in stations:
            v = x.get("shadow_price_per_kWh")
            if v is not None: station_shadows.append(v)
        metered_energy_total = sum(float(x.get("metered_v2g_energy_total_kWh", 0.0)) for x in stations)
        metered_payment_total = sum(float(x.get("metered_v2g_system_payment_total", 0.0)) for x in stations)
        metered_user_revenue_total = sum(float(x.get("metered_v2g_user_revenue_total", 0.0)) for x in stations)
        metered_payment_rate = sum(float(x.get("metered_v2g_system_payment_rate_per_hour", 0.0)) for x in stations)
        metered_user_revenue_rate = sum(float(x.get("metered_v2g_user_revenue_rate_per_hour", 0.0)) for x in stations)
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
            "manual_runtime_saturation_since_command": self.__manual_runtime_saturation_since_command,
            "manual_runtime_last_saturation_time": self.__manual_runtime_last_saturation_time,
            "effective_control": (
                "original_v2g_fallback"
                if self.__manual_fallback_active
                else (
                    "manual_saturated"
                    if self.is_manual_v2g_mode() and bool(self.__last_manual_check.get("runtime_saturated"))
                    else ("manual" if self.is_manual_v2g_mode() else self.__mode)
                )
            ),
            "metered_v2g_energy_total_kWh": metered_energy_total,
            "metered_v2g_system_payment_total": metered_payment_total,
            "metered_v2g_user_revenue_total": metered_user_revenue_total,
            "metered_v2g_system_payment_rate_per_hour": metered_payment_rate,
            "metered_v2g_user_revenue_rate_per_hour": metered_user_revenue_rate,
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