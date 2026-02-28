from typing import Any, Dict, Callable, List, Optional, Tuple, Union
from xml.etree.ElementTree import Element
from feasytools import RangeList
from .veh import *

_INF = float('inf')

def _EqualChargeRate(rate: float, ev: 'EV') -> float:
    return rate

def _LinearChargeRate(rate: float, ev: 'EV') -> float:
    if ev.soc <= 0.8:
        return rate
    return rate * (3.4 - 3 * ev.soc)

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

class EV(Vehicle):
    """Electric Vehicle Class"""
    def __init__(
        self, name: str, vtype: VehType, cap: float, pct: float, epm: float,
        ecf: float, ecs: float, ed: float, pcf: float, pcs: float, pdv: float, omega: float,
        kr: float, kf: float, ks: float, kv: float, 
        trips: List[Trip], trip_info: Dict[str, Any], base: Optional[str] = None, rmod: str = "Linear",
        sc_time: Union[None, RangeList] = None, max_sc_cost: float = 100.0,
        v2g_time: Union[None, RangeList] = None, min_v2g_earn: float = 0.0,
    ):
        """
        Initialize Electric Vehicle
        
        :param name: Vehicle name
        :param vtype: Vehicle type
        :param cap: Vehicle battery capacity (kWh)
        :param pct: Initial battery percentage (0.0~1.0)
        :param epm: Energy consumption per meter (Wh/m)
        :param ec_fast: Fast charging efficiency (0.0~1.0)
        :param ec_slow: Slow charging efficiency (0.0~1.0)
        :param ed: V2G discharging efficiency (0.0~1.0)
        :param pc_fast: Maximum fast charging power (kW)
        :param pc_slow: Maximum slow charging power (kW)
        :param pd_v2g: Maximum V2G power (kW)
        :param omega: Decision parameter for selecting charging station
        :param kr: User's estimation deviation of distance. For example, if kr=0.9, it means that the user thinks that the current energy can support 90% of the actual mileage.
        :param kf: SoC threshold for user selecting fast charging (0.0~1.0)
        :param ks: SoC threshold for user selecting slow charging (kf~1.0)
        :param kv: SoC threshold for user allowing V2G (ks~1.0). When V2G is enabled, the vehicle's SoC will not be lower than kv, and the user will not participate in V2G when SoC<=kv.
        :param trips: Vehicle trip list
        :param trip_info: Trip generation related information
        :param base: Vehicle base element (node or edge) in the road network
        :param rmod: Charging rate correction function name
        :param sc_time: Time range that the user is willing to join slow charge. None means all day.
        :param max_sc_cost: Maximum slow charging cost willing to join slow charge, $/kWh
        :param v2g_time: Time range that the user is willing to join V2G. None means all day.
        :param min_v2g_earn: Minimum V2G earn user willing to join V2G, $/kWh
        """
        super().__init__(name, vtype, cap, pct, epm / 1000, omega, kr, kf, trips, trip_info, base)
        self._earn = 0                  # Total discharge revenue of the vehicle, $

        self._pcf = pcf / 3600          # Maximal fast charging power, kW -> kWh/s
        self._pcs = pcs / 3600          # Maximal slow charging power, kW -> kWh/s
        self._pcr = 0                   # Actual charging power, kWh/s
        self._pdv = pdv / 3600          # Maximal V2G power, kW -> kWh/s
        self._pdr = 0                   # Actual discharging power, kWh/s
        self._ecf = ecf                 # Fast charging efficiency
        self._ecs = ecs                 # Slow charging efficiency
        self._ed = ed                   # Discharge efficiency

        self.__rmod_name = rmod
        self._chrate_mod = ChargeRatePool.get(rmod)
                                        # Charging rate correction function
        self._sc_time = sc_time if isinstance(sc_time, RangeList) else RangeList(sc_time)
                                        # RangeList of slow charging time, None means all day
        self._max_sc_cost = max_sc_cost # Maximum slow charging cost, $/kWh
        self._v2g_time = v2g_time if isinstance(v2g_time, RangeList) else RangeList(v2g_time)
                                        # RangeList of V2G time, None means all day
        self._min_v2g_earn = min_v2g_earn
                                        # Minimum V2G cost, $/kWh

        assert 0 < kf < 1
        self._kf = kf                   # User selects SoC for fast charging
        assert kf <= ks < 1
        self._ks = ks                   # User selects SoC for slow charging
        assert ks < kv
        self._kv = kv                   # SoC where the user is willing to join V2G

        self.__tmp_pc_max = _INF        # Temporary variable, maximum charging power kWh/s
        self.__tmp_pd = self._pdv       # Temporary variable, maximum discharging power kWh/s

        self._force_sc = False          # Whether to force slow charging

        self._leave_at_etar = True      # Whether to leave at target energy immediately
    
    def reset(self):
        """Reset the vehicle to the initial state"""
        super().reset()
        self._earn = 0                  # Total discharge revenue of the vehicle, $
        self._pcr = 0                   # Actual charging power, kWh/s
        self._pdr = 0                   # Actual discharging power, kWh/s
        self.__tmp_pc_max = _INF        # Temporary variable, maximum charging power kWh/s
        self.__tmp_pd = self._pdv       # Temporary variable, maximum discharging power kWh/s
        self._force_sc = False          # Whether to force slow charging
        self._leave_at_etar = True      # Whether to leave at target energy immediately

    def set_leave_at_etar(self, val: bool):
        """Set whether to leave immediately after reaching target energy.
        If set to True, the vehicle will not join V2G."""
        self._leave_at_etar = val

    def set_temp_max_pc(self, pc: float):
        """Set temporary maximum charging power kWh/s. 
        This function must be called in MaxPCAllocator."""
        self.__tmp_pc_max = pc

    def set_temp_pd(self, pd: float):
        """Set temporary discharging power kWh/s.
        This function must be called in V2GAllocator."""
        self.__tmp_pd = pd
    
    def set_force_fast_charge(self, cs: Optional[str] = None):
        """Force the vehicle to fast charge at next departure. 
        + If cs is not None, set the target fast charging station to cs. If cs is None, find a suitable FCS automatically.
        + After the next departure, this configuration will be cleared automatically, whether the vehicle departs successfully or not."""
        self._force_fc = True
        self._force_fcs = cs
    
    def set_force_slow_charge(self):
        """Force the vehicle to enter slow charge station at next arrival.
        Note:
        + If there is no vacancy in the SCS, this configuration will be ignored.
        + After the next arrival, this configuration will be cleared automatically, whether the vehicle enters the SCS or not."""
        self._force_sc = True

    @property
    def estimated_charging_time(self) -> float:
        """
        Time required to complete charging at the current charge level, target charge level and charging rate
        """
        if self._pcr > 0:
            return max((self._etar - self._energy) / self._pcr, 0)
        else:
            return _INF

    @property
    def kf(self) -> float:
        """SoC threshold for fast charging at departure"""
        return self._kf

    @kf.setter
    def kf(self, val: float):
        assert 0.0 <= val <= self._ks
        self._kf = val

    @property
    def ks(self) -> float:
        """Select the SOC threshold for slow charging"""
        return self._ks

    @ks.setter
    def ks(self, val: float):
        assert self._kf <= val <= 1.0
        self._ks = val

    @property
    def kv2g(self) -> float:
        """Select the SOC threshold for slow charging"""
        return self._kv

    @kv2g.setter
    def kv2g(self, val: float):
        assert self._ks < val
        self._kv = val

    @property
    def eta_fc(self) -> float:
        """Fast charging efficiency"""
        return self._ecf

    @property
    def eta_sc(self) -> float:
        """Slow charging efficiency"""
        return self._ecs

    @property
    def eta_d(self) -> float:
        """V2G discharging efficiency"""
        return self._ed

    @property
    def pc_actual(self) -> float:
        """Vehicle's actual charging rate, kWh/s"""
        return self._pcr

    @property
    def pcf(self) -> float:
        """Vehicle's maximum fast charging rate, kWh/s"""
        return self._pcf
    
    @property
    def pcs(self) -> float:
        """Vehicle's maximum slow charging rate, kWh/s"""
        return self._pcs
    
    @property
    def pd_actual(self) -> float:
        """Vehicle's actual V2G discharging rate, kWh/s"""
        return self._pdr
    
    @property
    def pdv(self) -> float:
        """Vehicle's maximum V2G reverse power rate, kWh/s"""
        return self._pdv

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
    
    def start_charging(self, pc: float, fast_charging:bool = True):
        """
        Start charging.
        
        :param pc: Maximal charging power the charger can supply (kWh/s)
        :param fast_charging: Whether to use fast charging power (True) or slow charging power (False)
        :return pcm: Maximal charging power (kWh/s) after considering vehicle's maximum charging power.
        Actual charging power may be lower due to temporary maximum charging power limit.
        """
        self.__ebeg = self._energy; self.__costbeg = self._cost
        self.__pcm = min(self._pcf if fast_charging else self._pcs, pc)
        self.__ec = self._ecf if fast_charging else self._ecs
        return self.__pcm
    
    def charge(self, seconds: int, unit_cost: float) -> Tuple[float, float]:
        """
        Charging the EV for a period of time
        Parameters:
            seconds: Charging duration (seconds)
        Returns:
            delta_energy: Energy drawn from the charger (kWh), used for power grid calculation and cost calculation.
            + Actual energy restored to the battery is less due to charging efficiency.
            money: Cost incurred ($)
        """
        self._pcr = min(self._chrate_mod(self.__pcm, self), self.__tmp_pc_max)
        self.__tmp_pc_max = _INF
        energy = self._energy
        self._energy += self._pcr * seconds * self.__ec
        if self._energy > self._etar: self._energy = self._etar
        delta_energy = (self._energy - energy) / self.__ec # Energy drawn from the charger
        money = delta_energy * unit_cost
        self._cost += money
        return delta_energy, money
    
    def end_charging(self) -> Tuple[float, float]:
        """
        End charging
        Returns:
            (delta_energy, cost): Tuple of (actual restored amount (kWh), cost incurred ($))
        """
        self._pcr = 0
        return self._energy - self.__ebeg, self._cost - self.__costbeg
    

    def start_bidirectional(self, pc: float, pd:float, fast_charging:bool = True):
        """
        Start charging/discharging bidirectional V2G process.
        Parameters:
            pc: Maximal charging power the charger can supply (kWh/s)
            pd: Maximal discharging power the charger can supply (kWh/s)
            fast_charging: Whether to use fast charging mode
        Returns:
            (pcm, pdm):
            + pcm = Maximal charging power (kWh/s) after considering vehicle's maximum charging power.
            + pdm = Maximal discharging power (kWh/s) after considering vehicle's maximum discharging power.
            + Actual charging power may be lower due to temporary maximum charging power limit.
        """
        self.__ebeg = self._energy; self.__costbeg = self._cost; self.__earnbeg = self._earn
        self.__pcm = min(self._pcf if fast_charging else self._pcs, pc)
        self.__ec = self._ecf if fast_charging else self._ecs
        self.__pdm = min(self._pdv, pd)
        # self.__ed = self._ed
        return (self.__pcm, self.__pdm)
    
    def bidirectional_charge(self, sec: int, unit_cost: float, real_etar: Optional[float] = None) -> Tuple[float, float]:
        """
        Bidirectional V2G charging/discharging for a period of time.
        Parameters:
            sec: Duration (seconds)
            unit_cost: Unit cost of charging ($/kWh)
            v2g_enabled: Whether V2G discharging is enabled
        Returns:
            delta_energy:
            + Energy drawn from the charger (kWh), used for power grid calculation and cost/earning calculation.
            + Actual energy restored to the battery is less due to charging/discharging efficiency.
        """
        if real_etar is None:
            real_etar = self._etar
        return self._bidirectional_charge(sec, unit_cost, real_etar)

    def _bidirectional_charge(self, sec: int, unit_cost: float, real_etar: float) -> Tuple[float, float]:
        _energy = self._energy
        self._pcr = min(self._chrate_mod(self.__pcm, self), self.__tmp_pc_max)
        self.__tmp_pc_max = _INF
        self._energy += self._pcr * sec * self.__ec
        if self._energy >= real_etar:
            self._energy = real_etar
        delta_energy = (self._energy - _energy) / self.__ec
        money = delta_energy * unit_cost
        self._cost += money
        return delta_energy, money

    def bidirectional_discharge(self, sec: int, unit_earn: float) -> Tuple[float, float]:
        """
        V2G discharging for a period of time.
        Parameters:
            sec: Duration (seconds)
            unit_earn: Unit earning of discharging ($/kWh)
        Returns:
            delta_energy:
            + Energy delivered to the grid (kWh), used for power grid calculation and earning calculation.
            + Actual energy drawn from the battery is more due to discharging efficiency.
        """
        _energy = self._energy
        self._pdr = min(self.__pdm, self.__tmp_pd) # Constant discharging power during the period, maybe changed in the future
        self.__tmp_pd = self._pdv
        self._energy -= self._pdr * sec
        if self._energy < self._cap * self._kv:
            self._energy = self._cap * self._kv
        delta_energy = (_energy - self._energy) * self._ed
        money = delta_energy * unit_earn
        self._earn += money
        return delta_energy, money  # Energy delivered to the grid
    
    def end_bidirectional(self) -> Tuple[float, float, float]:
        """
        End bidirectional V2G process.
        Returns:
            (delta_energy, cost, earn):
            1. Actual restored amount (kWh)
            2. Cost incurred ($)
            3. Earning obtained ($)
        """
        self._pcr = 0
        self._pdr = 0
        return (self._energy - self.__ebeg, self._cost - self.__costbeg, self._earn - self.__earnbeg)

    def willing_to_v2g(self, t:int, e:float) -> bool:
        """
        User determines whether the vehicle is willing to v2g
        Parameters:
            t: current time
            e: current V2G earn, $/kWh
        """
        return self.soc > self._kv and e >= self._min_v2g_earn and (self._v2g_time.__contains__(t) if self._v2g_time else True) and not self._leave_at_etar
    
    def willing_to_slow_charge(self, t:int, c:float) -> bool:
        """
        User determines whether the vehicle is willing to slow charge
        Parameters:
            t: current time
            c: current slow charge cost, $/kWh
        """
        return c <= self._max_sc_cost and self._sc_time.__contains__(t)

    def __repr__(self):
        return f"EV(name='{self._name}')"
    
    def to_xml(self) -> Element:
        e = super().to_xml()
        e.tag = "ev"
        e.attrib["e"] = f"{self._epm*1000:.6f}" # Wh/m
        e.attrib.update({
            "ks": f"{self._ks:.4f}",
            "kv": f"{self._kv:.4f}",
            "ecf": f"{self._ecf:.4f}",
            "ecs": f"{self._ecs:.4f}",
            "ed": f"{self._ed:.4f}",
            "pcf": f"{self._pcf*3600:.4f}",
            "pcs": f"{self._pcs*3600:.4f}",
            "pdv": f"{self._pdv*3600:.4f}",
            "rmod": self.__rmod_name,
            "max_sc_cost": f"{self._max_sc_cost:.4f}",
            "min_v2g_earn": f"{self._min_v2g_earn:.4f}",
        })
        e0 = self._sc_time.toXMLNode("sctime")
        if len(e0): e.append(e0)
        e0 = self._v2g_time.toXMLNode("v2gtime")
        if len(e0): e.append(e0)
        return e


class SV(EV):
    """Swapping Battery EV"""
    def __repr__(self):
        return f"SV(name='{self._name}')"
    
    def to_xml(self) -> Element:
        e = super().to_xml()
        e.tag = "sv"
        return e


__all__ = ["EV", "SV", "ChargeRatePool"]