from abc import abstractmethod, ABC
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Optional, List, Dict, Set, Tuple
from xml.etree.ElementTree import Element
from feasytools import RangeList
from itertools import chain
from ..veh import EV
from .s import BaseStation, PriceGetterLike, _pget_from_like


@dataclass
class AllocEnv:
    cs: 'CS'
    EVs: Iterable[EV]
    CTime: int

V2GAllocator = Callable[[AllocEnv, int, float, float], None]

def _AverageV2GAllocator(env:AllocEnv, veh_cnt: int, v2g_demand: float, v2g_cap: float):
    if veh_cnt == 0 or v2g_demand == 0: return
    pd = v2g_demand / veh_cnt
    for ev in env.EVs:
        ev.set_temp_pd(pd)

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
        pc_alloc: str="Average", pd_alloc: str="Average", allow_queuing: bool=True
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
        super().__init__(name, bind, slots, x, y, price_buy, price_buy_is_service_fee, offline, allow_queuing)
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
        if v2g:
            attrib["max_pd"] = f"{self._pd_lim1 * 3600:.2f}"
            attrib["pd_alloc"] = self._pd_alloc_str
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
    def get_V2G_cap(self, t: int) -> float:
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
    
    def get_V2G_cap(self, _t:int, /) -> float:
        return 0.0
    
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

    def get_V2G_cap(self, _t:int, /) -> float:
        if self.is_offline(_t): return 0.0
        assert self._psell is not None, "V2G not supported in %s." % self._name
        self._d_evs = [ev for ev in self._chi if ev.willing_to_v2g(_t, self._psell(_t, self, ev))]
        tot_pd = sum(ev._pdv * ev._ed for ev in self._d_evs)
        self._cur_v2g_cap = tot_pd
        self.__d_evs_upd_t = _t
        return tot_pd
    
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
        v2g_enabled = v2g_demand > 0 and self._cur_v2g_cap > 0
        if v2g_enabled:
            # V2G is enabled now. Some EVs charge and some EVs discharge.
            if self.__d_evs_upd_t != cur_time:
                # Update both lists of vehicles willing to charge and discharge via V2G
                self._c_evs.clear(); self._d_evs.clear()
                if self._cs_type == CSType.FCS:
                    for ev in self._chi:
                        if ev.soc < ev._kv:
                            self._c_evs.append(ev)
                        elif ev.willing_to_v2g(cur_time, self.real_psell(cur_time, ev, ps_e)):
                            self._d_evs.append(ev)
                else:
                    for ev in self._chi:
                        if ev.willing_to_slow_charge(cur_time, self.real_pbuy(cur_time, ev, pb_e)) and ev.soc < ev._kv:
                            self._c_evs.append(ev)
                        elif ev.willing_to_v2g(cur_time, self.real_psell(cur_time, ev, ps_e)):
                            self._d_evs.append(ev)
            else:
                # Use the previously updated list of vehicles willing to discharge via V2G
                # Only update the list of vehicles willing to charge via V2G
                if self._cs_type == CSType.FCS:
                    self._c_evs = [ev for ev in self._chi if ev.soc < ev._kv]
                else:
                    self._c_evs = [ev for ev in self._chi if ev.soc < ev._kv and 
                        ev.willing_to_slow_charge(cur_time, self.real_pbuy(cur_time, ev, pb_e))]
        else:
            # V2G is not enabled now, all vehicles charging to their _etar
            self._d_evs.clear()
            if self._cs_type == CSType.FCS:
                self._c_evs = list(self._chi)
            else:
                self._c_evs = [ev for ev in self._chi if ev.willing_to_slow_charge(cur_time, self.real_pbuy(cur_time, ev, pb_e))]
            
        m = len(self._c_evs)
        if m > 0:
            # Allocate charging power to vehicles, where set_temp_pc is called.
            # If _pc_alloc do not allocate power to a vehicle, the vehicle's charging power is set to maximum charging power.
            self._pc_alloc(AllocEnv(self, self._c_evs, cur_time), m, self._pc_lim1, self._pc_limtot)
            
            if v2g_enabled:
                # When V2G is enabled, vehicles only charge to min(_cap * _kv, _etar)
                for ev in self._c_evs:
                    pb = self.real_pbuy(cur_time, ev, pb_e)
                    if ev._leave_at_etar:
                        c_, m_ = ev._bidirectional_charge(sec, pb, ev._etar)
                        Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                        if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
                    else:
                        c_, m_ = ev._bidirectional_charge(sec, pb, min(ev._cap * ev._kv, ev._etar))
                        Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
            else:
                # When V2G is not enabled, vehicles charge to _etar
                for ev in self._c_evs:
                    c_, m_ = ev._bidirectional_charge(sec, self.real_pbuy(cur_time, ev, pb_e), ev._etar)
                    Wcharge += c_; self._revenue += m_; self._cost += c_ * pb_e
                    if ev._energy >= ev._etar and ev._leave_at_etar: ret.append(ev)
        
        n = len(self._d_evs)
        if n > 0:
            # Allocate V2G power to vehicles, where set_temp_pd is called.
            # If _pd_alloc do not allocate power to a vehicle, the vehicle's discharging power is set to maximum discharging power.
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


__all__ = ["CS", "V2GAllocPool", "MaxPCAllocPool", "AllocEnv", "V2GAllocator", "MaxPCAllocator", "CSType", "OwnerGroup", "UniCS", "BiCS"]