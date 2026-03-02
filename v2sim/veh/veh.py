import enum
from dataclasses import dataclass
from xml.etree.ElementTree import Element
from typing import Any, Dict, List, Optional, Union

EPS = 1e-6

@dataclass
class Trip:
    id:str
    depart_time:int
    O:str
    D:str
    edges:Optional[List[str]] = None
    OType:str = ""
    DType:str = ""
    OTaz:str = ""
    DTaz:str = ""

    def __repr__(self):
        return str(self)
    
    def __str__(self):
        return f"{self.O}->{self.D}@{self.depart_time}"
    
    def to_xml(self) -> Element:
        e = Element("trip", {
            "id": self.id,
            "depart": str(self.depart_time),
            "O": self.O,
            "D": self.D,
        })
        if self.edges is not None:
            e.attrib["route_edges"] = ' '.join(self.edges)
        if self.OType is not None:
            e.attrib["OType"] = self.OType
        if self.DType is not None:
            e.attrib["DType"] = self.DType
        return e
    
    toXML = to_xml  # backward compatibility
    

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


class VehType(enum.IntEnum):
    """Vehicle type enumeration"""
    Private = 0     # Private vehicle/私家车
    Taxi = 1        # Taxi/出租车
    Bus = 2         # Bus/公交车
    Truck = 3       # Truck/卡车
    Van = 4         # Van/面包车
    Sanitation = 5  # Sanitation vehicle/环卫车
    Emergency = 6   # Emergency vehicle/急救车

    @staticmethod
    def from_str(s: str) -> 'VehType':
        s = s.lower()
        if s == "private":
            return VehType.Private
        elif s == "taxi":
            return VehType.Taxi
        elif s == "bus":
            return VehType.Bus
        elif s == "truck":
            return VehType.Truck
        elif s == "van":
            return VehType.Van
        elif s == "sanitation":
            return VehType.Sanitation
        elif s == "emergency":
            return VehType.Emergency
        else:
            raise ValueError(f"Unknown VehType string: {s}")


class Vehicle:
    """Vehicle Base Class"""
    def __init__(self, name: str, vtype: VehType, cap: float, pct: float, epm: float, omega: float, kr: float, kf: float, trips: List[Trip], trip_info: Dict[str, Any], base: Optional[str] = None):
        """
        Initialize Vehicle
        
        :param name: Vehicle name
        :param vtype: Vehicle type
        :param cap: Vehicle battery capacity (kWh for EV, L for GV)
        :param pct: Initial battery percentage (0.0~1.0)
        :param epm: Energy consumption per meter (kWh/m for EV, L/m for GV)
        :param omega: Decision parameter for selecting charging station
        :param kr: User's estimation deviation of distance. For example, if kr=0.9, it means that the user thinks that the current energy can support 90% of the actual mileage.
        :param kf: Minimum energy percentage required for direct departure without charging/refueling
        :param trips: Vehicle trip list
        :param trip_info: Trip generation related information
        :param base: Vehicle base element (node or edge) in the road network
        """
        self._name = name               # Vehicle name
        self._sta = VehStatus.Parking   # Vehicle status
        self._cost = 0.0                # Total charging cost of the vehicle, $
        self._vtype = vtype             # Vehicle type
        self._base = base               # Vehicle base element (node or edge) in the road network
        
        # Energy storage
        self._cap = cap                 # Energy capacity, kWh for EV, L for GV
        assert 0.0 <= pct <= 1.0
        self._energy = pct * cap        # Current energy stored, kWh for EV, L for GV
        self._epm = epm                 # Energy consumption per unit distance, kWh/m for EV, L/m for GV

        # Refueling/Recharging
        self._cs:Optional[str] = None   # Target charging station/gas station
        self._etar = self._cap          # The target energy to refuel/recharge, kWh for EV, L for GV
        self._w = omega                 # Decision parameter for selecting charging station/gas station

        # Trips and distance
        self._dis = 0.0                 # Distance traveled, m
        self._kr = kr                   # Tolerance coefficient
        self._kf = kf                   # Minimum energy percentage required for direct departure without charging/refueling
        self._trips = trips      # Vehicle trip list
        self._trip_index = 0            # Current trip number (index)
        self._tinfo = trip_info         # Trip generation related information

        # Force restore at FCS/GS when departing
        self._fr_on_dpt: Optional[bool] = None  # Whether to force restore at FCS/GS when departing
        self._dpt_rs: Optional[str] = None  # Forced fast charging station/gas station name
    
    @property
    def name(self) -> str:
        """Vehicle's name"""
        return self._name
    
    @property
    def vtype(self) -> VehType:
        """Vehicle type"""
        return self._vtype
    
    @property
    def status(self) -> VehStatus:
        """Current vehicle status"""
        return self._sta

    @status.setter
    def status(self, val: VehStatus):
        self._sta = val

    @property
    def target_CS(self) -> Union[None, str]:
        """Name of the target fast charging station. When this item is None, it means that it isn't guided to a CS"""
        return self._cs

    @target_CS.setter
    def target_CS(self, val):
        self._cs = val
    
    @property
    def soc(self) -> float:
        """Get the current energy percentage (0.0~1.0)"""
        return self._energy / self._cap

    pct = soc  # backward compatibility

    @property
    def E(self) -> float:
        """Get the current energy stored (kWh for EV, L for GV)"""
        return self._energy
    
    @property
    def Emax(self) -> float:
        """Get the energy capacity (kWh for EV, L for GV)"""
        return self._cap
    
    @property
    def omega(self) -> float:
        """Decision parameter for selecting fast charging station"""
        return self._w
    
    @omega.setter
    def omega(self, val: float):
        self._w = val
    
    @property
    def kr(self) -> float:
        """User's estimation deviation of distance. 
        For example, if kr=0.9, it means that the user thinks that the current energy can support 90% of the actual mileage."""
        return self._kr
    
    @kr.setter
    def kr(self, val: float):
        assert val > 0
        self._kr = val
    
    @property
    def kf(self) -> float:
        """Energy percentage threshold for fast charging/refueling at departure"""
        return self._kf
    
    @kf.setter
    def kf(self, val: float):
        assert 0.0 <= val <= 1.0
        self._kf = val

    @property
    def cost(self) -> float:
        """Total charging cost incurred by the vehicle ($)"""
        return self._cost
    
    @property
    def range(self) -> float:
        """Maximum distance under the current energy level (m)"""
        return self._energy / self._epm

    @property
    def odometer(self) -> float:
        """Distance traveled by the vehicle in this trip (m), note that leaving a CS is considered a new trip"""
        return self._dis

    def clear_odometer(self):
        """Set the distance traveled to 0 before the trip starts"""
        self._dis = 0

    def reset(self):
        """Reset the vehicle to the initial state"""
        self._sta = VehStatus.Parking
        self._cost = 0.0
        self._dis = 0.0
        self._trip_index = 0
    
    def drive(self, new_dis: float):
        """
        Update the distance traveled and energy consumption. The vehicle must not be in refueling/recharging state.
        
        :param new_dis: New distance traveled, m. No less than the previous distance.
        :returns: True if the vehicle has remaining energy after driving, False if the vehicle is depleted.
        """
        assert new_dis >= self._dis - EPS
        self._energy -= (new_dis - self._dis) * self._epm
        self._dis = new_dis
        if self._energy <= 0:
            self._energy = 0
            self._sta = VehStatus.Depleted
            return False
        return True
    
    def _unsafe_drive(self, new_dis: float):
        """
        Update the distance traveled and energy consumption in driving state without checking
        
        :param new_dis: New distance traveled, m. No less than the previous distance.
        """
        self._energy -= (new_dis - self._dis) * self._epm
        self._dis = new_dis

    def is_energy_enough(self, dist: float) -> bool:
        """
        Whether the current energy level is sufficient to travel a distance of dist. 
        Note that this function uses the user's estimated distance, that is, range >= kr * dist
        
        :param dist: Distance to be traveled (m)
        :returns: True if the current energy level is sufficient to travel the distance, False otherwise
        """
        return self.range >= self._kr * dist
    
    @property
    def trips(self):
        """Vehicle's trips"""
        return self._trips
    
    @property
    def trip(self):
        """Current trip"""
        return self._trips[self._trip_index]

    @property
    def trip_id(self):
        """Current trip ID (indexed from 0)"""
        return self._trip_index

    @property
    def trip_info(self) -> Dict[str, Any]:
        """Trip generation related information"""
        return self._tinfo
    
    def next_trip(self):
        """
        Increment the trip ID by 1 and return the trip ID. 
        If it is already the last trip, return -1, and the trip ID will not be changed.
        """
        if self._trip_index == len(self.trips) - 1:
            return -1
        self._trip_index += 1
        return self._trip_index
    
    def add_trip(self, trip: Trip, day: Optional[int] = None):
        """
        Add a trip to the vehicle's trip list
        
        :param trip: Trip to be added. Note that the instance's depart_time will be modified if day is not None.
        :param day: Day number (0 for the first day, 1 for the second day, etc.) to which the trip belongs. If None, the trip's depart_time will not be modified.
        """
        if day is not None:
            assert day >= 0 and trip.depart_time >= 0 and trip.depart_time < 86400, f"[{trip.id}] day {day} must be >=0 and depart_time {trip.depart_time} must be in [0, 86400)"
            trip.depart_time += day * 86400
        if len(self._trips) > 0:
            assert trip.depart_time >= self._trips[-1].depart_time, "Trips must be added in chronological order"
        self._trips.append(trip)
    
    def clear_trips(self):
        """Clear all trips of the vehicle"""
        self._trips.clear()
        self._trip_index = 0

    def brief(self):
        """Get a brief description of this vehicle"""
        return f"{self._name}, {self.soc*100:.1f}%, E={self._energy:.1f}, TripID={self._trip_index}"
    
    def __repr__(self) -> str:
        return f"Vehicle(name='{self._name}')"
    
    def __str__(self):
        return repr(self)
    
    def to_xml(self) -> Element:
        """Get the XML representation of the vehicle for SUMO"""
        e = Element("vehicle", {
            "id": self._name,
            "vtype": str(int(self._vtype)),
            "cap": f"{self._cap:.4f}",
            "pct": f"{self.soc:.4f}",
            "e": f"{self._epm:.6f}",
            "omega": f"{self._w:.6f}",
            "kr": f"{self._kr:.4f}",
            "kf": f"{self._kf:.4f}",
        })
        if self._base is not None:
            e.attrib["base"] = self._base
        for trip in self._trips:
            e.append(trip.to_xml())
        return e

    toXML = to_xml  # backward compatibility


class GV(Vehicle):
    """Gas Vehicle Class"""
    def start_refueling(self, energy_target: Optional[float] = None):
        """
        Start refueling
        
        :param energy_target: Target energy to restore, L. If None, restore to full capacity.
        """
        self._etar = self._cap if energy_target is None else energy_target
        self.__ebeg = self._energy
    
    def refuel(self, amount: float, unit_cost: float):
        """
        Add energy to the energy storage
        
        :param amount: Amount to restore, L.
        :param unit_cost: Unit cost of refueling, $/L.
        :returns (delta_energy, money):
            A tuple of actual amount restored (L) and money spent for this refueling ($).
        """
        _energy = self._energy
        self._energy += amount
        if self._energy > self._etar:
            self._energy = self._etar
        delta_energy = self._energy - _energy
        money = (self._energy - _energy) * unit_cost
        self._cost += money
        return delta_energy, money
    
    def end_refueling(self) -> float:
        """
        End refueling/recharging
        
        :returns: actual restored amount (L)
        """
        return self._energy - self.__ebeg

    def __repr__(self) -> str:
        return f"GV(name='{self._name}')"
    
    def to_xml(self) -> Element:
        e = super().to_xml()
        e.tag = "gv"
        return e


__all__ = ['Trip', 'VehStatus', 'VehType', 'Vehicle', 'GV']