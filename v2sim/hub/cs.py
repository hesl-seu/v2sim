from abc import abstractmethod, ABC
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Optional, List, Dict, Set, Tuple, TypedDict
from xml.etree.ElementTree import Element
from feasytools import RangeList
from itertools import chain
from ..veh import EV
from .s import BaseStation, PriceGetterLike, _pget_from_like


class BidCurvePoint(TypedDict):
    """One point on a V2G bid curve.

    ``price`` is the system-side offer price in $/kWh, ``user_price`` is the
    pay-as-bid revenue received by the EV, and ``quantity_kW`` is grid-side
    power in kW after discharge efficiency.
    """
    vehicle: str
    price: float
    user_price: float
    service_fee: float
    quantity_kW: float
    cumulative_quantity_kW: float
    energy_headroom_kWh: float
    grid_deliverable_energy_kWh: float
    current_soc: float
    v2g_entry_soc_kv: float
    v2g_floor_soc_ks: float


@dataclass
class AllocEnv:
    cs: 'CS'
    EVs: Iterable[EV]
    CTime: int


@dataclass(frozen=True)
class V2GBidBlock:
    """One EV's V2G offer block.

    ``price`` is the system-side offer price in $/kWh, ``user_price`` is the
    pay-as-bid revenue received by the EV, and ``quantity`` is grid-side power
    in kWh/s after discharge efficiency.
    """
    ev: EV
    price: float
    user_price: float
    quantity: float


V2GAllocator = Callable[[AllocEnv, int, float, float], None]

def _AverageV2GAllocator(env:AllocEnv, veh_cnt: int, v2g_demand: float, v2g_cap: float):
    if veh_cnt == 0 or v2g_demand == 0: return
    # v2g_demand is power delivered to the grid, while EV.set_temp_pd and
    # bidirectional_discharge use battery-side discharge power.  Compensate
    # for each EV's discharge efficiency so actual grid injection matches the
    # PDN dispatch target.
    pd = v2g_demand / veh_cnt
    for ev in env.EVs:
        ev.set_temp_pd(pd / ev._ed if ev._ed > 1e-12 else 0.0)

class V2GAllocPool:
    """Charging rate correction function pool"""
    _pool:'Dict[str, V2GAllocator]' = {
        "Average":_AverageV2GAllocator, 
    }

    @staticmethod
    def add(name: str, func: V2GAllocator):
        """Add charging rate correction function"""
        V2GAllocPool._pool[name] = func

    @staticmethod
    def get(name: str) -> V2GAllocator:
        """Get charging rate correction function"""
        return V2GAllocPool._pool[name]

MaxPCAllocator = Callable[[AllocEnv, int, float, float], None]

def _AverageMaxPCAllocator(env: AllocEnv, vcnt:int, max_pc0: float, max_pc_tot: float):
    """
    Average maximum charging power allocator
        env: Allocation environment
        vcnt: Number of vehicles being charged
        max_pc0: Maximum charging power of a single pile, kWh/s
        max_pc_tot: Maximum charging power of the entire CS given by the PDN, kWh/s
    """
    if vcnt == 0: return
    pc0 = min(max_pc_tot / vcnt, max_pc0)
    for ev in env.EVs:
        ev.set_temp_max_pc(pc0)

def _PrioritizedMaxPCAllocator(env: AllocEnv, vcnt:int, max_pc0: float, max_pc_tot: float):
    for ev in env.EVs:
        if max_pc_tot > max_pc0:
            ev.set_temp_max_pc(max_pc0)
            max_pc_tot -= max_pc0
        else:
            ev.set_temp_max_pc(max_pc_tot)
            max_pc_tot = 0

def _TimeBasedMaxPCAllocator(env: AllocEnv, vcnt:int, max_pc0: float, max_pc_tot: float):
    loban:List[Tuple[int, EV]] = []
    for ev in env.EVs:
        loban.append((max(0, ev.trip.depart_time - env.CTime), ev))
        # For EVs in FCS, departure time of this trip is smaller than current time. Therefore, the sequence of EVs is held the same as the original.
        # For EVs in SCS, departure time of this trip is larger than current time. Therefore, EVs departed earlier are charged first.
    loban.sort()
    for _, ev in loban:
        if max_pc_tot > max_pc0:
            ev.set_temp_max_pc(max_pc0)
            max_pc_tot -= max_pc0
        else:
            ev.set_temp_max_pc(max_pc_tot)
            max_pc_tot = 0


class MaxPCAllocPool:
    """Charging rate correction function pool"""
    _pool:'Dict[str, MaxPCAllocator]' = {
        "Average":_AverageMaxPCAllocator,
        "Prioritized":_PrioritizedMaxPCAllocator,
        "TimeBased":_TimeBasedMaxPCAllocator,
    }

    @staticmethod
    def add(name: str, func: MaxPCAllocator):
        """Add charging rate correction function"""
        MaxPCAllocPool._pool[name] = func

    @staticmethod
    def get(name: str) -> MaxPCAllocator:
        """Get charging rate correction function"""
        return MaxPCAllocPool._pool[name]


class CSType(Enum):
    FCS = "FCS"
    SCS = "SCS" 

class OwnerGroup:
    def __init__(self, e: Optional[Element] = None):
        self.members: Set[str] = set()
        self.subgroups: Set['OwnerGroup'] = set()
        if e is None: return
        for itm in e:
            if itm.tag == "member":
                self.members.add(itm.attrib["name"])
            elif itm.tag == "members":
                self.members.update(itm.attrib["names"].split(","))
            elif itm.tag == "group":
                self.subgroups.add(OwnerGroup(itm))
            else:
                raise ValueError(f"Invalid owner tag: {itm.tag}, only 'member', 'members', and 'group' are allowed.")
    
    def __contains__(self, owner: str) -> bool:
        if owner in self.members: return True
        for grp in self.subgroups:
            if owner in grp: return True
        return False
    
    def to_xml(self, tag = "owners") -> Element:
        ret = Element(tag)
        ret.append(Element("members", {"names": ",".join(self.members)}))
        for grp in self.subgroups:
            ret.append(grp.to_xml("group"))
        return ret
    
    toXML = to_xml

class CS(BaseStation[EV], ABC):
    """Charging Station"""
    def __init__(self,
        name: str, bind: str, slots: int, bus: str, x: float, y: float, cs_type: CSType,
        max_pc: float, max_pd: float, price_buy: PriceGetterLike, price_buy_is_service_fee:bool = False,
        price_sell: Optional[PriceGetterLike] = None, price_sell_is_service_fee:bool = False,
        offline: Optional[RangeList] = None, owners: Optional[OwnerGroup] = None,
        pc_alloc: str="Average", pd_alloc: str="Average", allow_queuing: bool=True,
        pos: float = float("inf")
    ):
        """
        Initialize the CS
        
        :param name: CS name.
        :param bind: The element in the road network where the CS is located.
        :param slots: Number of chargers in the CS
        :param bus: The PDN bus to which the CS connects.
        :param x: The x-coordinate of the CS.
        :param y: The y-coordinate of the CS.
        :param cs_type: Type of the charging station, either FCS or SCS.
        :param max_pc: Each pile's maximum power for charging an EV, kWh/s.
        :param max_pd: Each pile's maximum power for discharging an EV, kWh/s.
        :param price_buy: User charging price list, $/kWh.
        :param price_buy_is_service_fee: Whether the price_buy is a service fee (added on top of the cost) rather than the actual price of energy. If True, the actual unit cost for user is (price_buy + electrcity price), where cost is the electricity cost for CS. If False, the actual unit cost for user is price_buy.
        :param price_sell: Energy selling price, $/kWh. The CS does not support V2G if None is passed.
        :param price_sell_is_service_fee: Whether the price_sell is a service fee (deducted on top of the revenue) rather than the actual price of energy. If True, the actual unit revenue for user is (electrcity price - price_sell). If False, the actual unit revenue for user is price_sell.
        :param offline: Time range when the CS is offline. None means always online.
        :param owners: Set of owner IDs. None means public CS, otherwise private CS.
        :param pc_alloc:
                The method of allocating the maximum charging power to the vehicle.
                The default is "Average", which means that the power is evenly distributed to all vehicles.
        :param pd_alloc:
                The method of allocating the actual V2G power to the vehicle.
                The default is "Average", which means that the power is evenly distributed to all vehicles.
        :param allow_queuing:
                Whether to allow vehicles to queue when all charging piles are occupied.
        """
        super().__init__(name, bind, slots, x, y, price_buy, price_buy_is_service_fee, offline, allow_queuing, pos)
        self._owners: Optional[OwnerGroup] = owners
        self._bus: str = bus
        self._cs_type: CSType = cs_type
        self._pc_is_constrained: bool = False
        
        if (price_sell is None or 
            (isinstance(price_sell, tuple) and len(price_sell) == 0) or
            (isinstance(price_sell, list) and len(price_sell) == 0)
        ):
            self._psell = None
        else:
            self._psell = _pget_from_like(price_sell)
        self._psell_is_serv_fee = price_sell_is_service_fee

        self._pc_lim1: float = max_pc # Maximum charging power of a single pile
        self._pc_limtot: float = float("inf") # Maximum charging power of the entire CS given by the PDN
        self._pc_alloc_str: str = pc_alloc # Charging power allocation method
        self._pc_alloc: MaxPCAllocator = MaxPCAllocPool.get(pc_alloc)
        self._pc_actual: Optional[List[float]] = None # Actual charging power limit allocated to each slot

        self._pd_lim1: float = max_pd # Maximum V2G discharge power of a single pile
        self._pd_alloc_str: str = pd_alloc # V2G power allocation method
        self._pd_alloc: V2GAllocator = V2GAllocPool.get(pd_alloc) # V2G power allocation function
        self._pd_actual: List[float] = [] # Actual V2G power ratio allocated to each slot

        self._cload: float = 0.0
        self._dload: float = 0.0
        self._cur_v2g_cap: float = 0.0
        self._integrated_v2g_mode: bool = False
        # EV name -> (grid-side power kWh/s, EV revenue $/kWh, system payment $/kWh)
        self._v2g_dispatch_plan: Dict[str, Tuple[float, float, float]] = {}
    
    def add_single_owner(self, owner: str):
        """
        Add a single owner to the private charging station.
        
        :param owner: Vehicle owner ID
        """
        if self._owners is None:
            self._owners = OwnerGroup()
        self._owners.members.add(owner)
    
    def reset(self):
        """Reset the charging station to its initial state."""
        super().reset()
        self._cload = 0.0
        self._dload = 0.0
        self._cur_v2g_cap = 0.0
        self._pc_actual = None
        self._pd_actual = []
        self._pc_is_constrained = False
        self._v2g_dispatch_plan.clear()
    
    def __repr__(self):
        return f"CS(name='{self._name}', slots={self._slots}, price_buy={self._pbuy}, price_buy_is_service_fee={self._pbuy_is_serv_fee}, price_sell={self._psell}, price_sell_is_service_fee={self._psell_is_serv_fee}, offline={self._offline})"
    
    def __str__(self):
        return f"CS(name='{self._name}')"

    def is_pc_constrained(self) -> bool:
        """Check if the charging power is constrained by the PDN"""
        return self._pc_is_constrained
    
    def is_public(self) -> bool:
        """Check if this is a public charging station"""
        return self._owners is None
    
    def is_private(self) -> bool:
        """Check if this is a private charging station"""
        return self._owners is not None
    
    def is_owned_by(self, veh_name: str) -> bool:
        """
        Check if this charging station is owned by the specified owner.
        
        :param veh_name: Vehicle owner ID
        :return: True if owned, False if not owned or this is a public CS.
        """
        if self._owners is None: return False
        return veh_name in self._owners

    def to_xml(self, v2g: bool = True) -> Element:
        """Get the XML Element of the charging station"""
        tag = "scs" if self._cs_type == CSType.SCS else "fcs"
        attrib = {
            "name": self._name,
            "bind": self._bind,
            "slots": str(self._slots),
            "bus": self._bus,
            "x": str(self._x),
            "y": str(self._y),
            "max_pc": f"{self._pc_lim1 * 3600:.2f}",
            "pc_alloc": self._pc_alloc_str,
            "pbuy_is_service_fee": str(self._pbuy_is_serv_fee),
        }
        if self._pos != float("inf"):
            attrib["pos"] = str(self._pos)
        if v2g:
            attrib["max_pd"] = f"{self._pd_lim1 * 3600:.2f}"
            attrib["pd_alloc"] = self._pd_alloc_str
            attrib["psell_is_service_fee"] = str(self._psell_is_serv_fee)
        ret = Element(tag, attrib)
        ret.append(self._pbuy.to_xml("pbuy"))
        if v2g and self._psell:
            ret.append(self._psell.to_xml("psell"))
        if len(self._offline) > 0: 
            ret.append(self._offline.toXMLNode("offline"))
        if self._owners is not None:
            ret.append(self._owners.to_xml("owners"))
        return ret
    
    @property
    def bus(self) -> str:
        """The distribution network bus to which the charging station connects"""
        return self._bus

    def psell(self, t:int, veh: EV) -> float:
        """Electricity selling price, $/kWh"""
        if self._psell is None: raise ValueError("This charging station does not support V2G.")
        return self._psell(t, self, veh)
    
    def psell_is_service_fee(self) -> bool:
        """Whether the price_sell is a service fee rather than the actual price of energy."""
        if self._psell is None: raise ValueError("This charging station does not support V2G.")
        return self._psell_is_serv_fee
    
    def real_psell(self, t:int, veh: EV, elec_price: float) -> float:
        """The actual unit revenue for user, $/kWh"""
        if self._psell is None: raise ValueError("This charging station does not support V2G.")
        if self._psell_is_serv_fee:
            return elec_price - self._psell(t, self, veh)
            # Allow negative psell, which means the user pays the grid to discharge.
            # Of course, users will not choose to discharge when the revenue is negative, but this will be handled by the vehicle's willingness to discharge rather than the CS.
        else:
            return self._psell(t, self, veh)

    @property
    def supports_V2G(self) -> bool:
        """Check if this charging station supports V2G"""
        return self._psell is not None

    def get_V2G_bid_blocks(self, t: int) -> List[V2GBidBlock]:
        """Build the current merit-order V2G offer blocks for this station.

        Each physically available EV contributes one block.  In service-fee
        mode, the system-side offer is ``EV minimum revenue + service fee``.
        In direct-price mode, the EV minimum acceptable V2G price itself is the bid; the
        configured ``psell`` only enables V2G for that station in market modes.
        """
        if self.is_offline(t) or self._psell is None:
            return []
        blocks: List[V2GBidBlock] = []
        for ev in self._chi:
            # Hysteresis: new V2G participation requires SoC>kv.  An EV that
            # was already selected in the previous dispatch plan may remain a
            # supply block while SoC>ks so the held dispatch can actually run
            # down to the requested lower floor instead of stopping at kv.
            continuing = ev._name in self._v2g_dispatch_plan
            if continuing:
                physically_available = ev.v2g_can_continue(t)
            else:
                physically_available = ev.v2g_available(t, True)
            if not physically_available:
                continue
            quantity = min(ev._pdv, self._pd_lim1) * ev._ed
            if quantity <= 0.0:
                continue
            station_price = float(self._psell(t, self, ev))
            user_price = float(ev.minimum_v2g_earn)
            if self._psell_is_serv_fee:
                offer_price = user_price + station_price
            else:
                offer_price = user_price
            blocks.append(V2GBidBlock(ev, offer_price, user_price, quantity))
        blocks.sort(key=lambda x: (x.price, x.ev._name))
        return blocks

    def get_V2G_bid_curve(self, t: int) -> List[BidCurvePoint]:
        """Return the current sorted V2G bid-price/bid-quantity curve.

        Quantities are exposed in kW for external dispatchers.  One row is one
        EV block so heterogeneous user minimum acceptable prices are preserved.
        """
        ret: List[BidCurvePoint] = []
        cumulative = 0.0
        for block in self.get_V2G_bid_blocks(t):
            q_kw = block.quantity * 3600.0
            cumulative += q_kw
            # A block enters V2G only above kv, but once selected can discharge
            # to ks.  Therefore duration-aware headroom is measured to ks.
            energy_headroom = max(0.0, block.ev._energy - block.ev._cap * block.ev._ks)
            ret.append({
                "vehicle": block.ev._name,
                "price": block.price,
                "user_price": block.user_price,
                "service_fee": block.price - block.user_price,
                "quantity_kW": q_kw,
                "cumulative_quantity_kW": cumulative,
                "energy_headroom_kWh": energy_headroom,
                "grid_deliverable_energy_kWh": energy_headroom * block.ev._ed,
                "current_soc": block.ev.soc,
                "v2g_entry_soc_kv": block.ev._kv,
                "v2g_floor_soc_ks": block.ev._ks,
            })
        return ret

    def get_V2G_energy_headroom(self, t: int) -> Tuple[float, float]:
        """Return current V2G energy headroom without changing power capacity.

        The first value is battery-side energy above the EV ``ks`` discharge
        floor (kWh).  ``kv`` remains the entry threshold for starting a new
        V2G discharge.
        The second is the corresponding energy deliverable to the grid after
        discharge efficiency (kWh).  These are observation-only quantities: they
        do not alter instantaneous V2G bid quantities or PDN generator limits.
        """
        battery_kwh = 0.0
        grid_kwh = 0.0
        for block in self.get_V2G_bid_blocks(t):
            headroom = max(0.0, block.ev._energy - block.ev._cap * block.ev._ks)
            battery_kwh += headroom
            grid_kwh += headroom * block.ev._ed
        return battery_kwh, grid_kwh

    def set_V2G_dispatch_plan(self, plan: Dict[str, Tuple[float, float, float]]):
        """Set the integrated dispatch plan for the next station update."""
        self._v2g_dispatch_plan = {
            name: (float(power), float(user_price), float(system_price))
            for name, (power, user_price, system_price) in plan.items()
            if power > 0.0
        }

    def clear_V2G_dispatch_plan(self):
        self._v2g_dispatch_plan.clear()

    def set_integrated_v2g_mode(self, enabled: bool):
        """Enable the integrated V2G state machine.

        There is deliberately no separate reservation policy.  While V2G is
        active, an EV that is time-wise available for V2G charges only while
        ``soc < kv`` (toward ``kv``); at/above ``kv`` it is not counted as a
        charging load.  A new V2G discharge may start only with ``soc > kv``;
        once selected it may continue down to ``ks``.  Native OPF and manual
        dispatch share this exact hysteresis rule.
        """
        self._integrated_v2g_mode = bool(enabled and self.supports_V2G)

    @abstractmethod
    def get_requested_pc(self, t: int, pb_e: float, ps_e: float = 0.0, v2g_mode: bool = False) -> float:
        """Unconstrained charging request in kWh/s without changing EV state."""
        raise NotImplementedError

    @abstractmethod
    def update(
        self, sec: int, cur_time: int, v2g_demand: float, pb_e:float, ps_e:float
    ) -> List[EV]:
        """
        Charge and discharge the EV with the current parameters for sec seconds.

        :param sec: Seconds
        :param cur_time: Current time
        :param v2g_demand: V2G power demanded by the PDN, kWh/s
        :param pb_e: The cost for CS buying electricity from the grid, $/kWh
        :return: List of vehicles removed from CS
        """
        raise NotImplementedError

    def veh_count(self, only_charging: bool=False) -> int:
        """
        Return the number of vehicles in the charging station.
        When only_charging is True, only the number of vehicles being charged is returned.
        """
        if only_charging: return len(self._chi)
        return len(self._chi) + len(self._buf)

    @abstractmethod
    def get_V2G_cap(self, t: int, ps_e: Optional[float] = None) -> float:
        """
        Get the maximum power of V2G under the current situation, unit kWh/s
        """
        raise NotImplementedError
    
    def set_Pc_lim(self, value: float):
        """
        Set the maximum charging power of the charging station
        
        :param value: Maximum charging power, kWh/s
        """
        if value < self._pc_limtot:
            self._pc_is_constrained = True
        self._pc_limtot = value
    
    @property
    def Pc(self) -> float:
        """Current charging power, kWh/s"""
        return self._cload

    @property
    def Pc_kW(self) -> float:
        """Current charging power, kW, 3600kW = 1kWh/s"""
        return self._cload * 3600

    @property
    def Pc_MW(self) -> float:
        """Current charging power, MW, 3.6MW = 1kWh/s"""
        return self._cload * 3.6

    @property
    def Pd(self) -> float:
        """Current V2G discharge power, kWh/s"""
        return self._dload

    @property
    def Pd_kW(self) -> float:
        """Current V2G discharge power, kW, 3600kW = 1kWh/s"""
        return self._dload * 3600

    @property
    def Pd_MW(self) -> float:
        """Current V2G discharge power, MW, 3.6MW = 1kWh/s"""
        return self._dload * 3.6

    @property
    def Pv2g(self) -> float:
        """Current maximum V2G discharge power, kWh/s"""
        return self._cur_v2g_cap

    @property
    def Pv2g_kW(self) -> float:
        """Current maximum V2G discharge power, kW, 3600kW = 1kWh/s"""
        return self._cur_v2g_cap * 3600

    @property
    def Pv2g_MW(self) -> float:
        """Current maximum V2G discharge power, MW, 3.6MW = 1kWh/s"""
        return self._cur_v2g_cap * 3.6
    
    def is_charging(self, veh: EV) -> bool:
        """
        Get the charging status of the vehicle. If the vehicle does not exist, a ValueError will be raised.
        
        :param veh: Vehicle instance
        :return: True if charging, False if waiting.
        """
        return veh in self._chi

    def __contains__(self, veh: EV) -> bool:
        return veh in self._chi or veh in self._buf
    
    def __len__(self) -> int:
        return len(self._chi) + len(self._buf)
    
    def wait_count(self) -> int:
        '''Number of vehicles waiting for charging'''
        return len(self._buf)
    
    def vehicles(self):
        return chain(self._chi, self._buf)
    
    def averageSOC(self, include_waiting:bool = True) -> float:
        """
        Average SOC of all vehicles in the charging station.
        When include_waiting is True, the average SOC of all vehicles (including those waiting) is returned.
        When include_waiting is False, only the average SOC of vehicles being charged is returned.
        """
        if include_waiting:
            n = len(self._chi) + len(self._buf)
            if n == 0: return 0.0
            return sum(ev.soc for ev in self.vehicles()) / n
        else:
            n = len(self._chi)
            if n == 0: return 0.0
            return sum(ev.soc for ev in self._chi) / n
    
    @abstractmethod
    def _ev_enter_chi(self, veh: EV):
        """Handle vehicle entering the charging station"""
        raise NotImplementedError
    
    def add_veh(self, veh: EV) -> bool:
        """
        Add a vehicle to the charging queue. Wait when the charging pile is insufficient.
        
        :param veh: Vehicle instance
        :return: True if added successfully, False if the vehicle is already charging.
        """
        if veh in self._chi or veh in self._buf:
            return False
        if self._owners is not None and veh._name not in self._owners:
            return False
        if len(self._chi) < self._slots:
            self._ev_enter_chi(veh)
            self._chi.add(veh)
        elif self._allow_que:
            self._buf.append(veh)
        else:
            return False
        return True
    
    def _unsafe_add_veh(self, veh: EV):
        """
        Add a vehicle to the charging queue without any check. For internal use only.

        :param veh: Vehicle instance
        """
        if len(self._chi) < self._slots:
            self._ev_enter_chi(veh)
            self._chi.add(veh)
        else:
            self._buf.append(veh)

    @abstractmethod
    def _ev_leave_chi(self, veh: EV):
        """Handle vehicle entering the charging station"""
        raise NotImplementedError
    
    def pop_veh(self, ev: EV) -> bool:
        """
        Remove the vehicle from the charging queue.

        :param ev: Vehicle instance
        :return: True if removed successfully, False if the vehicle does not exist.
        """
        if ev in self._chi:
            self._ev_leave_chi(ev)
            self._chi.remove(ev)
        else:
            try:
                self._buf.remove(ev)
            except:
                return False
        if len(self._buf) > 0 and len(self._chi) < self._slots:
            veh = self._buf.popleft()
            self._ev_enter_chi(veh)
            self._chi.add(veh)
        return True

    def has_veh(self, veh: EV) -> bool:
        """
        Check if there is a vehicle with the specified ID.
        
        :param veh: Vehicle instance
        :return: True if exists, False if not exists.
        """
        return self.__contains__(veh)


class UniCS(CS):
    """Charging station not supporting V2G."""
    def to_xml(self):
        return super().to_xml(v2g=False)
    
    toXML = to_xml

    def _ev_enter_chi(self, veh: EV):
        veh.start_charging(self._pc_lim1, self._cs_type==CSType.FCS)

    def _ev_leave_chi(self, ev: EV):
        ev.end_charging()
    
    def get_V2G_cap(self, _t:int, /, ps_e: Optional[float] = None) -> float:
        return 0.0

    def get_requested_pc(self, t: int, pb_e: float, ps_e: float = 0.0, v2g_mode: bool = False) -> float:
        if self.is_offline(t):
            return 0.0
        if self._cs_type == CSType.FCS:
            evs = self._chi
        else:
            evs = [ev for ev in self._chi if ev.willing_to_slow_charge(t, self.real_pbuy(t, ev, pb_e))]
        return sum(ev.requested_charge_power() for ev in evs)
    
    def update(
        self, sec: int, cur_time: int, v2g_demand: float, pb_e:float, ps_e:float
    ) -> List[EV]:
        """
        Charge the EV with the current parameters for sec seconds.

        :param sec: Seconds
        :param cur_time: Current time
        :param v2g_demand: Useless parameter, ignored. Present for interface consistency only.
        :param pb_e: The cost for CS buying electricity from the grid, $/kWh
        :param ps_e: The revenue for CS selling electricity to the grid, $/kWh
        :return: List of vehicles removed from CS
        """
        ret:List[EV] = []
        if self.is_offline(cur_time):
            # If the charging station fails, remove all vehicles
            ret = list(chain(self._chi, self._buf))
            self._buf.clear()
            for ev in self._chi: self._ev_leave_chi(ev)
            self._chi.clear()
            self._cload = 0
            return ret
        
        Wcharge = 0

        # Set temporary maximum charging, where set_temp_max_pc is called.
        # If _pc_alloc do not allocate power to a vehicle, the vehicle's maximum charging power is not limited.
        if len(self._chi) > 0:
            self._pc_alloc(
                AllocEnv(self, self._chi, cur_time), 
                len(self._chi), self._pc_lim1, self._pc_limtot
            )
            if self._cs_type == CSType.FCS:
                for ev in self._chi:
                    c_, m_ = ev.charge(sec, self.real_pbuy(cur_time, ev, pb_e))
                    Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                    if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
            else:
                for ev in self._chi:
                    uc = self.real_pbuy(cur_time, ev, pb_e)
                    if not ev.willing_to_slow_charge(cur_time, uc): continue
                    c_, m_ = ev.charge(sec, uc)
                    Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                    if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
            for ev in ret: self.pop_veh(ev)
        self._cload = Wcharge / sec
        return ret
    
    def __str__(self):
        return f"UniCS(name='{self._name}')"
    

class BiCS(CS):
    """Charging Station supporting V2G."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._c_evs: List[EV] = []
        self._d_evs: List[EV] = []
        self.__d_evs_upd_t: int = -1
    
    def reset(self):
        """Reset the charging station to its initial state."""
        super().reset()
        self._c_evs.clear()
        self._d_evs.clear()
        self.__d_evs_upd_t = -1

    def to_xml(self):
        return super().to_xml(v2g=True)
    
    toXML = to_xml
    
    def _ev_enter_chi(self, veh: EV):
        veh.start_bidirectional(self._pc_lim1, self._pd_lim1, self._cs_type==CSType.FCS)
        
    def _ev_leave_chi(self, veh: EV):
        veh.end_bidirectional()           

    def get_V2G_cap(self, _t:int, /, ps_e: Optional[float] = None) -> float:
        if self.is_offline(_t): return 0.0
        assert self._psell is not None, "V2G not supported in %s." % self._name
        if self._integrated_v2g_mode:
            blocks = self.get_V2G_bid_blocks(_t)
            self._d_evs = [block.ev for block in blocks]
            tot_pd = sum(block.quantity for block in blocks)
        else:
            self._d_evs = [
                ev for ev in self._chi
                if ev.willing_to_v2g(
                    _t,
                    self._psell(_t, self, ev) if ps_e is None else self.real_psell(_t, ev, ps_e)
                )
            ]
            tot_pd = sum(min(ev._pdv, self._pd_lim1) * ev._ed for ev in self._d_evs)
        self._cur_v2g_cap = tot_pd
        self.__d_evs_upd_t = _t
        return tot_pd

    def get_requested_pc(self, t: int, pb_e: float, ps_e: float = 0.0, v2g_mode: bool = False) -> float:
        """Return the current instantaneous charging request, in kWh/s.

        ``v2g_mode`` means that the project charging mode is ``v2g`` or
        ``v2g_manual``; it does not mean that the global V2G online window is
        active at this exact step.  This distinction is important because the
        original v1.6.0 behaviour intentionally falls back to the legacy
        non-integrated V2G charging-selection branch outside V2G online
        windows.

        For every non-smartcharge mode the request is intended to match the
        charging selection that ``update()`` will execute in the same step.
        """
        if self.is_offline(t):
            return 0.0

        configured_v2g_mode = bool(v2g_mode and self.supports_V2G)
        core_v2g = bool(configured_v2g_mode and self._integrated_v2g_mode)
        ret = 0.0

        for ev in self._chi:
            if core_v2g:
                # Integrated V2G window: entry is SoC>kv and an already-held
                # dispatch may continue down to ks.  Do not request charging
                # for an EV that is still executing the held V2G plan.
                charge_price = pb_e
                if self._cs_type == CSType.SCS and not ev.willing_to_slow_charge(t, charge_price):
                    continue
                available = ev.v2g_available(t, False)
                if available:
                    if ev._name in self._v2g_dispatch_plan and ev.v2g_can_continue(t):
                        continue
                    if ev.soc >= ev._kv:
                        continue
                    ret += ev.requested_charge_power(min(ev._cap * ev._kv, ev._etar))
                else:
                    ret += ev.requested_charge_power()
                continue

            if configured_v2g_mode:
                # Outside the global V2G online window, update() deliberately
                # uses the legacy non-integrated V2G branch.  Mirror that exact
                # charging selection here: an EV that is V2G-eligible at the
                # current selling price stops charging once it reaches kv; an
                # eligible EV below kv, or a non-eligible EV, charges normally
                # toward etar.  This is not smartcharge load reduction.
                buy_price = self.real_pbuy(t, ev, pb_e)
                sell_price = self.real_psell(t, ev, ps_e)
                if self._cs_type == CSType.SCS and not ev.willing_to_slow_charge(t, buy_price):
                    continue
                eligible = ev.v2g_eligible(t, sell_price, False)
                if eligible and ev.soc >= ev._kv:
                    continue
                ret += ev.requested_charge_power()
                continue

            # Ordinary non-V2G charging mode.
            buy_price = self.real_pbuy(t, ev, pb_e)
            if self._cs_type == CSType.SCS and not ev.willing_to_slow_charge(t, buy_price):
                continue
            ret += ev.requested_charge_power()

        return ret
    
    def update(
        self, sec: int, cur_time: int, v2g_demand: float, pb_e:float, ps_e:float
    ) -> List[EV]:
        """
        Charge and discharge the EV with the current parameters for sec seconds.
        Ensure get_V2G_cap() is called before update() in each time step to get the latest V2G capacity.
        
        :param sec: Seconds
        :param cur_time: Current time
        :param v2g_demand: V2G power demanded by the PDN, kWh/s
        :param pb_e: The cost for CS buying electricity from the grid, $/kWh
        :param ps_e: The revenue for CS selling electricity to the grid, $/kWh
        :return: List of vehicles removed from CS
        """
        # Do nothing when the charging station fails
        if self.is_offline(cur_time) or len(self._chi) == 0:
            self._cload = 0; self._dload = 0
            return []
        
        Wcharge = 0; Wdischarge = 0
         
        ret: List[EV] = []
        core_v2g = self._integrated_v2g_mode
        if core_v2g:
            # Native OPF/manual dispatch selects exact discharge blocks, but
            # charging and discharging use V2G hysteresis: a new discharge may
            # start only above kv; once selected it can continue down to ks.
            # Unselected time-wise V2G participants below kv charge toward kv,
            # while those at/above kv remain idle during the V2G window.
            plan = self._v2g_dispatch_plan if v2g_demand > 0.0 else {}
            selected = set(plan)
            self._c_evs.clear(); self._d_evs.clear()
            for ev in self._chi:
                available = ev.v2g_available(cur_time, False)
                can_charge = (
                    self._cs_type == CSType.FCS
                    or ev.willing_to_slow_charge(cur_time, pb_e)
                )
                if available:
                    if ev._name in selected and ev.v2g_can_continue(cur_time):
                        self._d_evs.append(ev)
                    elif ev.soc < ev._kv and can_charge:
                        self._c_evs.append(ev)
                elif can_charge:
                    self._c_evs.append(ev)
        else:
            # Legacy non-integrated behaviour: use the current station/user
            # selling price to decide willingness and the configured allocator.
            v2g_enabled = v2g_demand > 0 and self._cur_v2g_cap > 0
            if self.__d_evs_upd_t != cur_time:
                self._c_evs.clear(); self._d_evs.clear()
                if self._cs_type == CSType.FCS:
                    for ev in self._chi:
                        eligible = ev.v2g_eligible(cur_time, self.real_psell(cur_time, ev, ps_e), False)
                        if eligible and ev.soc < ev._kv:
                            self._c_evs.append(ev)
                        elif eligible and v2g_enabled and ev.willing_to_v2g(cur_time, self.real_psell(cur_time, ev, ps_e)):
                            self._d_evs.append(ev)
                        elif not eligible:
                            self._c_evs.append(ev)
                else:
                    for ev in self._chi:
                        can_charge = ev.willing_to_slow_charge(cur_time, self.real_pbuy(cur_time, ev, pb_e))
                        eligible = ev.v2g_eligible(cur_time, self.real_psell(cur_time, ev, ps_e), False)
                        if eligible and ev.soc < ev._kv and can_charge:
                            self._c_evs.append(ev)
                        elif eligible and v2g_enabled and ev.willing_to_v2g(cur_time, self.real_psell(cur_time, ev, ps_e)):
                            self._d_evs.append(ev)
                        elif not eligible and can_charge:
                            self._c_evs.append(ev)
            else:
                if self._cs_type == CSType.FCS:
                    self._c_evs = [
                        ev for ev in self._chi
                        if (not ev.v2g_eligible(cur_time, self.real_psell(cur_time, ev, ps_e), False)) or ev.soc < ev._kv
                    ]
                else:
                    self._c_evs = [
                        ev for ev in self._chi
                        if ev.willing_to_slow_charge(cur_time, self.real_pbuy(cur_time, ev, pb_e))
                        and ((not ev.v2g_eligible(cur_time, self.real_psell(cur_time, ev, ps_e), False)) or ev.soc < ev._kv)
                    ]
                if not v2g_enabled:
                    self._d_evs.clear()

        m = len(self._c_evs)
        if m > 0:
            # Allocate charging power to vehicles, where set_temp_pc is called.
            # If _pc_alloc do not allocate power to a vehicle, the vehicle's charging power is set to maximum charging power.
            self._pc_alloc(AllocEnv(self, self._c_evs, cur_time), m, self._pc_lim1, self._pc_limtot)
            
            if core_v2g:
                # Time-wise V2G participants that are not in an active held
                # discharge and are below kv charge only toward kv.  Selected
                # V2G EVs may continue through kv down to ks.
                for ev in self._c_evs:
                    pb = pb_e
                    available = ev.v2g_available(cur_time, False)
                    target = min(ev._cap * ev._kv, ev._etar) if available else ev._etar
                    c_, m_ = ev._bidirectional_charge(sec, pb, target)
                    Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                    if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
            else:
                # When V2G is not enabled, vehicles charge to _etar
                for ev in self._c_evs:
                    c_, m_ = ev._bidirectional_charge(sec, self.real_pbuy(cur_time, ev, pb_e), ev._etar)
                    Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                    if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
        
        n = len(self._d_evs)
        if n > 0:
            if core_v2g:
                # The dispatcher chooses blocks by each EV's minimum V2G bid,
                # while actual V2G settlement uses the station's effective
                # nodal price (ShadowPrice, or dprice fallback when unavailable).
                for ev in self._d_evs:
                    grid_power, user_bid, system_bid = self._v2g_dispatch_plan[ev._name]
                    ev.set_temp_pd(grid_power / ev._ed if ev._ed > 1e-12 else 0.0)
                    c_, m_ = ev.bidirectional_discharge(sec, ps_e)
                    Wdischarge += c_; self._cost += m_; self._revenue += c_ * ps_e
            else:
                # Legacy station-wide dispatch allocation.
                self._pd_alloc(AllocEnv(self, self._d_evs, cur_time), n, v2g_demand, self._cur_v2g_cap)
                for ev in self._d_evs:
                    c_, m_ = ev.bidirectional_discharge(sec, self.real_psell(cur_time, ev, ps_e))
                    Wdischarge += c_; self._cost += m_; self._revenue += c_ * ps_e
        
        self._cload = Wcharge / sec
        self._dload = Wdischarge / sec
        for ev in ret: self.pop_veh(ev)
        return ret
    
    def __str__(self):
        return f"BiCS(name='{self._name}')"


__all__ = ["CS", "BidCurvePoint", "V2GBidBlock", "V2GAllocPool", "MaxPCAllocPool", "AllocEnv", "V2GAllocator", "MaxPCAllocator", "CSType", "OwnerGroup", "UniCS", "BiCS"]