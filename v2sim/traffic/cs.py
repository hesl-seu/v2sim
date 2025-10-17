from abc import abstractmethod, ABC
from collections import deque
from dataclasses import dataclass
from itertools import chain
from typing import Callable, Deque, Iterable, Optional, List, Dict, Set, Union
import warnings
from feasytools import RangeList, makeFunc, OverrideFunc, TimeFunc, ConstFunc, SegFunc
from .ev import EV
from .utils import IntPairList, PriceList


def _get_price_xml(t: TimeFunc, elem:str) -> str:
    if isinstance(t, ConstFunc):
        return f'<{elem}>\n  <item btime="0" price="{t._val}" />\n</{elem}>'
    elif isinstance(t, SegFunc):
        return t.toXML(elem, "item", "btime", "price")
    elif isinstance(t, OverrideFunc):
        return _get_price_xml(t._val, elem)
    else:
        raise ValueError("Unsupported type of TimeFunc")

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
    loban = []
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
    

class CS(ABC):
    """Charging Station"""

    @abstractmethod
    def __init__(self,
        name: str, slots: int, bus: str, x: float, y: float, offline: Union[IntPairList, RangeList, None],
        max_pc: float, max_pd: float, price_buy: PriceList, price_sell: PriceList,
        pc_alloc: str="Average", pd_alloc: str="Average"
    ):
        """
        Initialize the CS
            name: CS name, also the name of the corresponding edge in the network.
            slots: Number of charging piles in the CS.
            bus: The PDN bus to which the CS connects.
            x: The x-coordinate of the CS.
            y: The y-coordinate of the CS.
            offline: Time range when the CS is offline, such as [(start1, end1), (start2, end2), ...]. 
                None means always online.
            max_pc: Each pile's maximum power for charging an EV, kWh/s.
            max_pd: Each pile's maximum power for discharging an EV, kWh/s.
            price_buy: User charging price list, $/kWh.
                The first list is the time range, and the second list is the price,
                such as ([0, 3600, 7200], [1.1, 1.2, 1.1]).
            price_sell: Electricity selling price list, $/kWh.
                The format is the same as price_buy.
                The CS does not support V2G if an empty tuple `()` is passed.
            pc_alloc:
                The method of allocating the maximum charging power to the vehicle.
                The default is "Average", which means that the power is evenly distributed to all vehicles.
            pd_alloc:
                The method of allocating the actual V2G power to the vehicle.
                The default is "Average", which means that the power is evenly distributed to all vehicles.
        """
        self._name: str = name
        self._slots: int = slots
        self._bus: str = bus
        if offline is None:
            self._offline: RangeList = RangeList()
        elif isinstance(offline, RangeList):
            self._offline = offline
        else:
            self._offline: RangeList = RangeList(offline)
        self._manual_offline: Optional[bool] = None
        self._pbuy: OverrideFunc = OverrideFunc(makeFunc(*price_buy))
        self._psell: Optional[OverrideFunc] = (
            None if price_sell == () else OverrideFunc(makeFunc(*price_sell))
        )

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
        self._x: float = x
        self._y: float = y
    
    def __repr__(self):
        return f"CS(name='{self._name}',slots={self._slots},pbuy={self._pbuy},psell={self._psell},offline={self._offline})"
    
    def __str__(self):
        return f"CS(name='{self._name}')"
    
    @abstractmethod
    def to_xml(self) -> str: ...

    @property
    def x(self) -> float:
        """X-coordinate of the charging station"""
        return self._x
    
    @property
    def y(self) -> float:
        """Y-coordinate of the charging station"""
        return self._y
    
    @property
    def name(self) -> str:
        """Charging station name"""
        return self._name

    @property
    def slots(self) -> int:
        """Number of charging piles in the charging station"""
        return self._slots

    @property
    def bus(self) -> str:
        """The distribution network bus to which the charging station belongs"""
        return self._bus
    
    @property
    def node(self) -> str:
        """The distribution network bus to which the charging station belongs"""
        warnings.warn("The 'node' property is deprecated. Please use 'bus' instead.", DeprecationWarning)
        return self._bus

    @property
    def pbuy(self) -> OverrideFunc:
        """Vehicle purchase price, $/kWh"""
        return self._pbuy

    @property
    def psell(self) -> OverrideFunc:
        """Electricity selling price, $/kWh"""
        if self._psell is None:
            raise AttributeError("V2G not supported in %s." % self.name)
        return self._psell

    @property
    def supports_V2G(self) -> bool:
        """Check if this charging station supports V2G"""
        return self._psell is not None

    def is_online(self, t: int) -> bool:
        """
        Check if the charging station is available at $t$ seconds.
            t: Time point
        Return:
            True if available, False if not available (fault)
        """
        if self._manual_offline is not None:
            return not self._manual_offline
        return not self._offline.__contains__(t)
    
    def is_offline(self, t: int) -> bool:
        """
        Check if the charging station is unavailable at $t$ seconds.
            t: Time point
        Return:
            True if not available (fault), False if available
        """
        if self._manual_offline is not None:
            return self._manual_offline
        return self._offline.__contains__(t)
    
    def force_shutdown(self):
        """Manually shut down the charging station"""
        self._manual_offline = True
    
    def force_reopen(self):
        """Manually reopen the charging station"""
        self._manual_offline = False
    
    def clear_manual_offline(self):
        """Clear manual shutdown status"""
        self._manual_offline = None

    @abstractmethod
    def add_veh(self, veh_id: str) -> bool:
        """
        Add a vehicle to the charging queue. Wait when the charging pile is insufficient.
            veh_id: Vehicle ID
        Return:
            True if added successfully, False if the vehicle is already charging.
        """
        raise NotImplementedError

    @abstractmethod
    def pop_veh(self, veh_id: str) -> bool:
        """
        Remove the vehicle from the charging queue.
            veh_id: Vehicle ID
        Return:
            True if removed successfully, False if the vehicle does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def __contains__(self, veh_id: str) -> bool:
        pass

    def has_veh(self, veh_id: str) -> bool:
        """
        Check if there is a vehicle with the specified ID.
            veh_id: Vehicle ID
        Return:
            True if exists, False if not exists.
        """
        return self.__contains__(veh_id)

    @abstractmethod
    def __len__(self) -> int:
        """Return the number of vehicles in the charging station"""
        raise NotImplementedError

    @abstractmethod
    def update(
        self, sec: int, cur_time: int, v2g_demand: float
    ) -> List[str]:
        """
        Charge and discharge the EV in the given EVDict with the current parameters for sec seconds.
            ev_dict: EVDict corresponding to the vehicle ID stored in this CS
            sec: Seconds
            cur_time: Current time
            v2g_demand: V2G power demanded by the PDN, kWh/s
        Return:
            List of vehicles removed from CS
        """
        raise NotImplementedError

    @abstractmethod
    def is_charging(self, veh_id: str) -> bool:
        """
        Get the charging status of the vehicle. If the vehicle does not exist, a ValueError will be raised.
            veh_id: Vehicle ID
        Return:
            True if charging, False if waiting.
        """
        raise NotImplementedError

    @abstractmethod
    def veh_count(self, only_charging: bool=False) -> int:
        """
        Return the number of vehicles in the charging station.
        When only_charging is True, only the number of vehicles being charged is returned.
        """
        raise NotImplementedError

    @abstractmethod
    def get_V2G_cap(self) -> float:
        """
        Charge and discharge the EV according to the given EV in EVDict, 
        and get the maximum power of V2G under the current situation, unit kWh/s
        """
        raise NotImplementedError
    
    def set_Pc_lim(self, value: float):
        """
        Set the maximum charging power of the charging station
            value: Maximum charging power, kWh/s
        """
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
    
    def vehicles(self):
        """Get an iterator of all vehicles in the charging station"""
        raise NotImplementedError

    @abstractmethod
    def averageSOC(self, only_charging: bool = False) -> float:
        """Average SOC of all vehicles in the charging station"""
        raise NotImplementedError


class SCS(CS):
    """Slow Charging Station"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._chi: Set[EV] = set()  # Vehicles being charged
        self._free: Set[EV] = set()  # Vehicles that have been fully charged

    def to_xml(self) -> str:
        ret = f'<scs name="{self._name}" edge="{self._name}" slots="{self._slots}" bus="{self._bus}" ' \
            f'x="{self._x}" y="{self._y}" max_pc="{self._pc_lim1 * 3600:.2f}" max_pd="{self._pd_lim1 * 3600:.2f}" ' \
            f'pc_alloc="{self._pc_alloc_str}" pd_alloc="{self._pd_alloc_str}">\n'
        ret += _get_price_xml(self._pbuy, "pbuy") + "\n"
        if self._psell: ret += _get_price_xml(self._psell, "psell") + "\n"
        if len(self._offline) > 0: ret += self._offline.toXML("offline") + "\n"
        ret += "</scs>"
        return ret
    
    def add_veh(self, veh: EV) -> bool:
        if veh in self._chi or veh in self._free:
            return False
        if len(self._chi) + len(self._free) < self._slots:
            self._chi.add(veh)
            return True
        else:
            return False

    def pop_veh(self, veh: EV) -> bool:
        try:
            self._chi.remove(veh)
        except KeyError:
            try:
                self._free.remove(veh)
            except:
                return False
        return True

    def __contains__(self, veh: EV) -> bool:
        return veh in self._chi or veh in self._free

    def __len__(self) -> int:
        return len(self._chi) + len(self._free)

    def is_charging(self, veh: EV) -> bool:
        return veh in self._chi

    def veh_count(self, only_charging:bool = False) -> int:
        if only_charging:
            return len(self._chi)
        else:
            return len(self._chi) + len(self._free)

    def get_V2G_cap(self, _t:int, /) -> float:
        if self.is_offline(_t): return 0.0
        tot_rate_ava = 0.0
        # Do not check if psell is None due to performance considerations
        v2gp = self._psell(_t) # type: ignore
        for ev in chain(self._chi, self._free):
            if ev.willing_to_v2g(_t, v2gp):
                tot_rate_ava += ev.max_v2g_rate * ev.eta_discharge
        self._cur_v2g_cap = tot_rate_ava
        return tot_rate_ava

    def vehicles(self):
        return chain(self._chi, self._free)
    
    def averageSOC(self, only_charging:bool = True) -> float:
        if only_charging:
            n = len(self._chi)
            if n == 0: return 0.0
            return sum(ev.SOC for ev in self._chi) / n
        else:
            n = len(self._chi) + len(self._free)
            if n == 0: return 0.0
            return sum(ev.SOC for ev in chain(self._chi, self._free)) / n

    def update(
        self, sec: int, cur_time: int, v2g_demand: float
    ) -> List[EV]:
        """
        Charge and discharge the EV in the given EVDict with the current parameters for sec seconds.
            sec: Seconds
            cur_time: Current time
            v2g_demand: V2G power demanded by the PDN, kWh/s
        Return:
            List of vehicles removed from CS
        Note:
            Ensure get_V2G_cap() is called before update() in each time step to get the latest V2G capacity.
        """
        # Do nothing when the charging station fails
        if self.is_offline(cur_time):
            self._cload = self._dload = 0
            return []
        
        Wcharge = Wdischarge = 0
        pb = self._pbuy(cur_time)
        
        # Set temporary maximum charging, where set_temp_max_pc is called.
        # If _pc_alloc do not allocate power to a vehicle, the vehicle's maximum charging power is not limited.
        if len(self._chi) > 0:
            self._pc_alloc(
                AllocEnv(self, self._chi, cur_time),
                len(self._chi), self._pc_lim1, self._pc_limtot
            )

        ret: Set[EV] = set()
        for ev in self._chi:
            if ev.willing_to_slow_charge(cur_time, pb):
                # If V2G discharge is in progress, don't charge to full
                Wcharge += ev.charge(sec, pb, ev._esc_rate)
                if v2g_demand > 0:
                    if ev._elec >= ev._bcap * ev._kv2g or ev._elec >= ev._chtar: ret.add(ev)
                else:
                    if ev._elec >= ev._chtar: ret.add(ev)

        self._chi -= ret
        self._free |= ret

        if v2g_demand > 0 and self._cur_v2g_cap > 0: # Ensure that V2G capacity is greater than 0 and there is V2G demand
            assert self._psell is not None, "V2G not supported in %s." % self.name
            ps = self._psell(cur_time)

            # Get vehicles willing to V2G
            v2g_cars = [ev for ev in self._free if ev.willing_to_v2g(cur_time, ps)]
            
            # Allocate V2G power to vehicles, where set_temp_pd is called.
            # If _pd_alloc do not allocate power to a vehicle, the vehicle's discharging power is set to maximum discharging power.
            n = len(v2g_cars)
            if n > 0:
                self._pd_alloc(
                    AllocEnv(self, v2g_cars, cur_time), 
                    len(v2g_cars), v2g_demand, self._cur_v2g_cap
                )

            for ev in v2g_cars:
                Wdischarge += ev.discharge(sec, ps)

        self._cload = Wcharge / sec
        self._dload = Wdischarge / sec
        return []


class FCS(CS):
    """Fast Charging Station"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._chi: Set[EV] = set()  # Vehicles being charged
        self._buf: Deque[EV] = deque()  # Vehicles in line

    def to_xml(self) -> str:
        ret = f'<fcs name="{self._name}" edge="{self._name}" slots="{self._slots}" bus="{self._bus}" ' \
            f'x="{self._x}" y="{self._y}" max_pc="{self._pc_lim1 * 3600:.2f}" pc_alloc="{self._pc_alloc_str}">\n'
        ret += _get_price_xml(self._pbuy, "pbuy") + "\n"
        if len(self._offline) > 0: ret += self._offline.toXML("offline") + "\n"
        ret += "</fcs>"
        return ret

    def add_veh(self, veh: EV) -> bool:
        if veh in self._chi or veh in self._buf:
            return False
        if len(self._chi) < self._slots:
            self._chi.add(veh)
        else:
            self._buf.append(veh)
        return True

    def pop_veh(self, ev: EV) -> bool:
        if ev in self._chi:
            self._chi.remove(ev)
        else:
            try:
                self._buf.remove(ev)
            except ValueError:
                return False
        return True

    def __contains__(self, veh: EV) -> bool:
        return veh in self._chi or veh in self._buf

    def is_charging(self, veh: EV) -> bool:
        return veh in self._chi

    def veh_count(self, only_charging:bool = False) -> int:
        if only_charging:
            return len(self._chi)
        else:
            return len(self._chi) + len(self._buf)

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
            return sum(ev.SOC for ev in chain(self._chi, self._buf)) / n
        else:
            n = len(self._chi)
            if n == 0: return 0.0
            return sum(ev.SOC for ev in self._chi) / n

    def wait_count(self) -> int:
        '''Number of vehicles waiting for charging'''
        return len(self._buf)

    def __len__(self) -> int:
        return len(self._chi) + len(self._buf)

    def update(
        self, sec: int, cur_time: int, v2g_demand: float
    ) -> List[EV]:
        """
        Charge the EV in the given EVDict with the current parameters for sec seconds.
            ev_dict: EVDict corresponding to the vehicle ID stored in this CS
            sec: Seconds
            cur_time: Current time
            v2g_demand: Useless parameter, ignored. Present for interface consistency only.
        Return:
            List of vehicles removed from CS
        Note:
            Fast charging station does not support V2G.
        """
        Wcharge = 0
        ret:List[EV] = []
        if self.is_offline(cur_time):
            # If the charging station fails, remove all vehicles
            ret = list(chain(self._chi,self._buf))
            self._chi.clear()
            self._buf.clear()
            self._cload = 0
            return ret
        
        # Set temporary maximum charging, where set_temp_max_pc is called.
        # If _pc_alloc do not allocate power to a vehicle, the vehicle's maximum charging power is not limited.
        if len(self._chi) > 0:
            self._pc_alloc(
                AllocEnv(self, self._chi, cur_time), 
                len(self._chi), self._pc_lim1, self._pc_limtot
            )

        for ev in self._chi:
            Wcharge += ev.charge(sec, self.pbuy(cur_time), ev._efc_rate)
            if ev.battery >= ev.charge_target:
                ret.append(ev)
        for ev in ret:
            self.pop_veh(ev)
            if len(self._buf) > 0:
                self._chi.add(self._buf.popleft())
        self._cload = Wcharge / sec
        return ret

    def get_V2G_cap(self, _t: int, /) -> float:
        """
        Fast charging station does not support V2G, always return 0.
        """
        return 0.0
