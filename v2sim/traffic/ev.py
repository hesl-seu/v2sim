import enum
import math
from typing import Callable, Dict, Iterable, List, Tuple, Union, Optional
from feasytools import RangeList
from .utils import IntPairList

_INF = float('inf')

class Trip:
    def __init__(
        self, trip_id: str, depart_time: int, fromTAZ: str, toTAZ: str, route: List[str], 
        fixed_route: Optional[bool] = None, addtional: Optional[Dict[str, str]] = None
    ):
        self.ID = trip_id
        self.depart_time = depart_time
        self.from_TAZ = fromTAZ
        self.to_TAZ = toTAZ
        assert isinstance(route, list) and len(route) >= 2, "Route should be a list with at least 2 elements"
        self.route = route
        if fixed_route:
            self.fixed_route = True
        elif fixed_route is None:
            self.fixed_route = len(route)>=2
        else:
            self.fixed_route = True
        self.additional = addtional if addtional else {}
    
    @property
    def depart_edge(self):
        return self.route[0]

    @property
    def arrive_edge(self):
        return self.route[-1]

    def get(self, key: str, default:str="")->str:
        return self.additional.get(key, "")
    
    def __repr__(self):
        return str(self)
    
    def __str__(self):
        return f"{self.depart_edge}->{self.arrive_edge}@{self.depart_time}"
    

class VehStatus(enum.IntEnum):
    """
    Vehicle status enumeration
        Driving: Driving to destination or charging station
        Pending: Already notified SUMO to start, but the vehicle has not yet started in SUMO
        Charging: Charging at charging station
        Parking: Parking (between two trips, or before the trip, or after the trip)
        Depleted: Battery depleted
    """
    Driving = 0
    Pending = 1
    Charging = 2
    Parking = 3
    Depleted = 4

def _EqualChargeRate(rate: float, ev: 'EV') -> float:
    return rate

def _LinearChargeRate(rate: float, ev: 'EV') -> float:
    if ev.SOC <= 0.8:
        return rate
    return rate * (3.4 - 3 * ev.SOC)

class ChargeRatePool:
    """Charging rate correction function pool"""
    _pool:'Dict[str, Callable[[float, EV], float]]' = {
        "Equal":_EqualChargeRate, 
        "Linear":_LinearChargeRate,
    }

    @staticmethod
    def add(name: str, func: 'Callable[[float, EV], float]'):
        """Add charging rate correction function"""
        ChargeRatePool._pool[name] = func

    @staticmethod
    def get(name: str) -> 'Callable[[float, EV], float]':
        """Get charging rate correction function"""
        return ChargeRatePool._pool[name]

class EV:
    """Electric Vehicle Class"""
    def __init__(
        self,
        id: str,
        trips: Iterable[Trip],
        eta_c: float,
        eta_d: float,
        bcap: float,
        soc: float,
        c: float,
        rf: float,
        rs: float,
        rv: float,
        omega: float,
        kr: float,
        kf: float,
        ks: float,
        kv: float,
        rmod: str = "Linear",
        sc_time: Union[None, IntPairList, RangeList] = None,
        max_sc_cost: float = 100.0,
        v2g_time: Union[None, IntPairList, RangeList] = None,
        min_v2g_earn: float = 0.0,
        cache_route: bool = False,
    ):
        self._id = id                   # Vehicle ID
        self._sta = VehStatus.Parking   # Vehicle status
        self._cs = None                 # Target charging station
        self._cost = 0                  # Total charging cost of the vehicle, $
        self._earn = 0                  # Total discharge revenue of the vehicle, $

        self._bcap = bcap               # Battery capacity, kWh
        assert 0.0 <= soc <= 1.0
        self._elec = soc * bcap         # Current battery capacity, kWh
        self._consumption = c / 1000    # Energy consumption per unit distance, kWh/m
        self._efc_rate = rf / 3600      # Expected fast charge power, kWh/s
        self._esc_rate = rs / 3600      # Expected slow charge power, kWh/s
        self._v2g_rate = rv / 3600      # Maximum reverse power, kWh/s
        self._eta_charge = eta_c        # Charging efficiency
        self._eta_discharge = eta_d     # Discharge efficiency
        self._chrate_mod = ChargeRatePool.get(rmod)
                                        # Charging rate correction function
        self._sc_time = sc_time if isinstance(sc_time, RangeList) else RangeList(sc_time)
                                        # RangeList of slow charging time, None means all day
        self._max_sc_cost = max_sc_cost # Maximum slow charging cost, $/kWh
        self._v2g_time = v2g_time if isinstance(v2g_time, RangeList) else RangeList(v2g_time)
                                        # RangeList of V2G time, None means all day
        self._min_v2g_earn = min_v2g_earn
                                        # Minimum V2G cost, $/kWh

        self._rate = 0                  # Actual charging power, kWh/s
        self._chtar = bcap              # When fast charging, how much kWh to charge before leaving

        self._dis = 0                   # Distance traveled, m
        self._trips = tuple(trips)      # Vehicle trip list
        self._trip_index = 0            # Current trip number (index)

        self._w = omega                 # Decision parameter
        assert 1 <= kr <= 2
        self._krel = kr                 # Tolerance coefficient
        assert 0 < kf < 1
        self._kfc = kf                  # User selects SoC for fast charging
        assert kf <= ks < 1
        self._ksc = ks                  # User selects SoC for slow charging
        assert ks < kv
        self._kv2g = kv                 # SoC where the user is willing to join V2G

        self._cache_route = cache_route # Whether to cache the route

        self.__tmp_pc_max = _INF # Temporary variable, maximum charging power kWh/s
        self.__tmp_pd = self._v2g_rate # Temporary variable, maximum discharging power kWh/s
    
    def set_temp_max_pc(self, pc: float):
        """Set temporary maximum charging power kWh/s. 
        This function must be called in MaxPCAllocator."""
        self.__tmp_pc_max = pc

    def set_temp_pd(self, pd: float):
        """Set temporary discharging power kWh/s.
        This function must be called in V2GAllocator."""
        self.__tmp_pd = pd

    @property
    def estimated_charge_time(self) -> float:
        """
        Time required to complete charging at the current charge level, target charge level and charging rate
        """
        if self._rate > 0:
            return max((self._chtar - self._elec) / self._rate, 0)
        else:
            return math.inf

    @property
    def elec(self) -> float:
        """Current battery capacity kWh"""
        return self._elec

    @property
    def SOC(self) -> float:
        """SoC of the battery (percentage)"""
        return self._elec / self._bcap

    @property
    def omega(self) -> float:
        """Decision parameter for selecting fast charging station"""
        return self._w

    @omega.setter
    def omega(self, val: float):
        self._w = val

    @property
    def krel(self) -> float:
        """Tolerance coefficient"""
        return self._krel

    @krel.setter
    def krel(self, val: float):
        assert 1.0 <= val <= 2.0
        self._krel = val

    @property
    def kfc(self) -> float:
        """Select the SOC threshold for fast charging"""
        return self._kfc

    @kfc.setter
    def kfc(self, val: float):
        assert 0.0 <= val <= self._ksc
        self._kfc = val

    @property
    def ksc(self) -> float:
        """Select the SOC threshold for slow charging"""
        return self._ksc

    @ksc.setter
    def ksc(self, val: float):
        assert self._kfc <= val <= 1.0
        self._ksc = val

    @property
    def kv2g(self) -> float:
        """Select the SOC threshold for slow charging"""
        return self._kv2g

    @kv2g.setter
    def kv2g(self, val: float):
        assert self._ksc < val
        self._kv2g = val

    @property
    def charge_target(self) -> float:
        """
        Charging target, that is, charge to this level and leave the fast charging station (kWh)
        """
        return self._chtar

    @charge_target.setter
    def charge_target(self, val):
        assert 0 <= val <= self._bcap
        self._chtar = val

    @property
    def eta_charge(self) -> float:
        """Vehicle charging efficiency"""
        return self._eta_charge

    @property
    def eta_discharge(self) -> float:
        """Vehicle discharge efficiency"""
        return self._eta_discharge

    @property
    def pc_actual(self) -> float:
        """Vehicle's actual charging rate, kWh/s"""
        return self._rate

    rate = pc_actual

    @property
    def max_v2g_rate(self) -> float:
        """Vehicle's maximum V2G reverse power rate, kWh/s"""
        return self._v2g_rate
    
    max_pd = max_v2g_rate

    def stop_charging(self):
        """Stop charging: set charging rate to 0"""
        self._rate = 0

    @property
    def status(self) -> VehStatus:
        """Current vehicle status"""
        return self._sta

    @status.setter
    def status(self, val):
        self._sta = val

    @property
    def target_CS(self) -> Union[None, str]:
        """
        Name of the target fast charging station. When this item is None, it means that it isn't guided to a CS
        """
        return self._cs

    @target_CS.setter
    def target_CS(self, val):
        self._cs = val

    @property
    def ID(self) -> str:
        """Vehicle's string ID"""
        return self._id

    @property
    def full_battery(self) -> float:
        """Vehicle's battery capacity kWh"""
        return self._bcap

    @property
    def battery(self) -> float:
        """Vehicle's battery level kWh"""
        return self._elec

    @property
    def consumption(self) -> float:
        """Vehicle's energy consumption kWh/m"""
        return self._consumption

    @property
    def odometer(self) -> float:
        """
        Distance traveled by the vehicle in this trip (m), note that leaving the charging station is considered a new trip
        """
        return self._dis

    @property
    def minimum_v2g_earn(self) -> float:
        """The minimum V2G earn user willing to join V2G, $/kWh"""
        return self._min_v2g_earn
    
    @property
    def maximum_slow_charge_cost(self) -> float:
        """The maximum slow charging cost willing to join slow charge, $/kWh"""
        return self._max_sc_cost
    
    @property
    def v2g_time(self) -> RangeList:
        """The time range that the user is willing to join V2G. None means all day"""
        return self._v2g_time
    
    @property
    def slow_charge_time(self) -> RangeList:
        """The time range that the user is willing to join slow charge. None means all day"""
        return self._sc_time
    
    def clear_odometer(self):
        """Before the trip starts, clear the odometer"""
        self._dis = 0

    def drive(self, new_dis: float):
        """
        Update the battery SOC and odometer in driving state
        """
        # Since SUMO save and load may lead to error, so -1.0 to tolerate the error
        assert new_dis >= self._dis - 1.0, f"EV {self._id}: self._dis = {self._dis:.8f} > new_dis = {new_dis:.8f}"
        self._elec -= (new_dis - self._dis) * self._consumption
        self._dis = new_dis

    def charge(self, sec: int, unit_cost: float, pc:float) -> float:
        """
        Charge the battery for sec seconds at given charging power pc kWh/s, 
        and return the actual charging amount (kWh) (considering losses)
        After charging, temporary maximum charging power is reset to infinity
        """
        _elec = self._elec
        self._rate = min(self._chrate_mod(pc, self), self.__tmp_pc_max)
        self.__tmp_pc_max = _INF
        self._elec += self._rate * sec * self._eta_charge
        if self._elec > self._bcap:
            self._elec = self._bcap
        if self._elec < 0:
            self._elec = 0
        delta_elec = self._elec - _elec
        self._cost += (delta_elec / self._eta_charge) * unit_cost
        return delta_elec

    def discharge(self, sec: int, unit_earn: float) -> float:
        """
        Discharge the battery for sec seconds, whose discharging power is set by set_temp_pd(),
        and return the actual discharge amount kWh (considering losses)
        After discharging, temporary discharging power is reset to the maximum discharging power
        """
        _elec = self._elec
        self._elec -= self.__tmp_pd * sec
        self.__tmp_pd = 0
        if self.SOC <= self._kv2g:
            self._elec = self._bcap * self._kv2g
        delta_elec = (_elec - self._elec) * self._eta_discharge
        assert delta_elec >= 0
        self._earn += delta_elec * unit_earn
        return delta_elec

    def willing_to_v2g(self, t:int, e:float) -> bool:
        """
        User determines whether the vehicle is willing to v2g
            t: current time
            e: current V2G earn, $/kWh
        """
        return self.SOC > self._kv2g and e >= self._min_v2g_earn and (self._v2g_time.__contains__(t) if self._v2g_time else True)
    
    def willing_to_slow_charge(self, t:int, c:float) -> bool:
        """
        User determines whether the vehicle is willing to slow charge
            t: current time
            c: current slow charge cost, $/kWh
        """
        return c <= self._max_sc_cost and self._sc_time.__contains__(t)
    
    @property
    def trips(self) -> Tuple[Trip, ...]:
        '''Get the list of trips for the vehicle'''
        return self._trips

    @property
    def trips_count(self) -> int:
        '''Get the number of trips for the vehicle'''
        return len(self._trips)
    
    @property
    def trip(self) -> Trip:
        '''Get the current trip'''
        return self._trips[self._trip_index]

    @property
    def trip_id(self) -> int:
        '''Get the ID of the current trip (indexed from 0)'''
        return self._trip_index

    def next_trip(self) -> int:
        """
        Increment the trip ID by 1 and return the trip ID. If it is already the last trip, return -1.
        """
        if self._trip_index == len(self.trips) - 1:
            return -1
        self._trip_index += 1
        return self._trip_index

    @property
    def max_mileage(self) -> float:
        """
        Maximum mileage under the current battery level (m)
        """
        return self._elec / self._consumption

    def is_batt_enough(self, dist: float) -> bool:
        """
        User determines whether the current battery level is sufficient to travel a distance of dist
        """
        return self.max_mileage >= self._krel * dist

    def brief(self):
        """Get a brief description of this vehicle"""
        return f"{self._id},{self.SOC*100:.1f}%,{self._elec:.1f}kWh,{self._trip_index}"

    def __repr__(self):
        return f"EV[ID='{self._id}', Status={self._sta}, Dist={self._dis}m, SOC={self.SOC*100:.1f}%, Bcap={self._bcap}kWh, ChTar={self._chtar}kWh, TarCS={self._cs}, Consump={self._consumption}KWh/m]"

    def __str__(self):
        return repr(self)

__all__ = ["Trip", "VehStatus", "EV", "ChargeRatePool"]