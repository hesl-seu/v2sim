from abc import ABC, abstractmethod
from collections import deque
from itertools import chain
from typing import Deque, Dict, List, Optional, Set, Tuple, Type, TypeVar, Generic, Union
from xml.etree.ElementTree import Element
from feasytools import RangeList, SegFunc
from ..veh import Vehicle, GV


T_Vehicle = TypeVar("T_Vehicle", bound=Vehicle)


class PriceGetter(ABC):
    """Price getter interface"""
    @abstractmethod
    def get_price(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:...
    
    @abstractmethod
    def _to_xml(self, tag: str) -> Element: ...

    @abstractmethod
    def get_name(self) -> str: ...

    @staticmethod
    @abstractmethod
    def from_xml(e: Element) -> "PriceGetter": ...

    def to_xml(self, tag: str) -> Element:
        """Alias for to_xml"""
        ret = self._to_xml(tag)
        assert "type" not in ret.attrib, "Attribute 'type' is reserved. Please remove it from the XML."
        ret.tag = tag
        ret.attrib["type"] = self.get_name()
        return ret

    toXML = to_xml

    def set(self, value: float):
        """Override the price getter with a constant price"""
        self._val = value
    
    def clear(self):
        """Clear the override and restore the original price getter"""
        if hasattr(self, "_val"): del self._val

    def __call__(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:
        if hasattr(self, "_val"): return self._val
        return self.get_price(t, station, veh)


PriceGetterLike = Union[PriceGetter, float, SegFunc, Tuple[List[int], List[float]], List[Tuple[int, float]]]


class ConstPriceGetter(PriceGetter):
    """Constant price getter"""
    def __init__(self, price: float):
        super().__init__()
        self._price = price
    
    def get_price(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:
        return self._price

    def _to_xml(self, tag: str) -> Element:
        return Element(tag, {"value": str(self._price)})
    
    def get_name(self) -> str: return "const"

    @staticmethod
    def from_xml(e: Element) -> PriceGetter:
        price = float(e.attrib["value"])
        return ConstPriceGetter(price)
    
    def __str__(self) -> str:
        return str(self._price)


class ToUPriceGetter(PriceGetter):
    """Time-of-Use price getter"""
    def __init__(self, price_func: SegFunc):
        super().__init__()
        self._price_func = price_func
    
    def get_price(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:
        return self._price_func(t)

    def _to_xml(self, tag: str) -> Element:
        return self._price_func.toXMLNode(tag, "item", "btime", "price")
    
    def get_name(self) -> str: return "tou"

    @staticmethod
    def from_xml(e: Element) -> PriceGetter:
        tl = []; d = []
        for itm in e:
            assert itm.tag == "item", "Invalid ToU price XML: expected 'item' tag."
            if "btime" not in itm.attrib or "price" not in itm.attrib:
                raise ValueError("Invalid ToU price XML: missing 'btime' or 'price' attribute in item.")
            tl.append(int(itm.attrib["btime"]))
            d.append(float(itm.attrib["price"]))
        return ToUPriceGetter(SegFunc(tl, d))
    
    def __str__(self) -> str:
        return str(self._price_func)


class ToUSoCPriceGetter(ToUPriceGetter):
    """ToU price getter with SoC-based penalty"""
    def __init__(self, base_price: SegFunc, soc_threshold: float, penalty_price: float):
        super().__init__(base_price)
        self._soc_threshold = soc_threshold
        self._penalty_price = penalty_price
    
    def __call__(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:
        soc = veh.soc  # Assuming veh has a soc attribute representing State-of-Charge
        if soc > self._soc_threshold:
            return self._price_func(t) + self._penalty_price
        else:
            return self._price_func(t)
    
    def to_xml(self, tag: str) -> Element:
        elem = self._price_func.toXMLNode(tag, "item", "btime", "price")
        elem.attrib["soc_threshold"] = str(self._soc_threshold)
        elem.attrib["penalty_price"] = str(self._penalty_price)
        return elem
    
    def get_name(self) -> str: return "tou_soc"


class ToUQueuePriceGetter(ToUPriceGetter):
    """ToU price getter with queue-based penalty"""
    def __init__(self, base_price: SegFunc, queue_threshold: int, unit_penalty_price: float, max_penalty_price: float):
        super().__init__(base_price)
        self._queue_threshold = queue_threshold
        self._unit_penalty_price = unit_penalty_price
        self._max_penalty_price = max_penalty_price
    
    def __call__(self, t: int, station: "BaseStation[T_Vehicle]", veh: T_Vehicle) -> float:
        queue_length = station.wait_count()
        if queue_length > self._queue_threshold:
            return self._price_func(t) + min(self._unit_penalty_price * (self._queue_threshold - queue_length), self._max_penalty_price)
        else:
            return self._price_func(t)
    
    def to_xml(self, tag: str) -> Element:
        elem = self._price_func.toXMLNode(tag, "item", "btime", "price")
        elem.attrib["queue_threshold"] = str(self._queue_threshold)
        elem.attrib["unit_penalty_price"] = str(self._unit_penalty_price)
        elem.attrib["max_penalty_price"] = str(self._max_penalty_price)
        return elem
    
    def get_name(self) -> str: return "tou_queue"


class PriceGetterPool:
    """Pool of price getters"""
    __pool:Dict[str, Type[PriceGetter]] = {
        "const": ConstPriceGetter,
        "tou": ToUPriceGetter,
        "tou_soc": ToUSoCPriceGetter,
    }

    @staticmethod
    def register(name: str, getter: Type[PriceGetter]):
        if name in PriceGetterPool.__pool:
            raise ValueError(f"PriceGetter '{name}' already registered.")
        PriceGetterPool.__pool[name] = getter
    
    @staticmethod
    def unregister(name: str):  
        if name in PriceGetterPool.__pool:
            del PriceGetterPool.__pool[name]
        else:
            raise ValueError(f"PriceGetter '{name}' not found.")
    
    @staticmethod
    def get(name: str) -> Type[PriceGetter]:
        return PriceGetterPool.__pool[name]
    
    @staticmethod
    def from_elem(e: Element):
        name = e.attrib.get("type")
        if name is None:
            # Default to ToUPriceGetter if type not specified, for backward compatibility
            getter_cls = ToUPriceGetter
        else:
            getter_cls = PriceGetterPool.get(name)
        return getter_cls.from_xml(e)
    

def _pget_from_like(like: PriceGetterLike) -> PriceGetter:
    """Convert a PriceGetterLike to a PriceGetter instance"""
    if isinstance(like, PriceGetter):
        return like
    elif isinstance(like, (int, float)):
        return ConstPriceGetter(float(like))
    elif isinstance(like, SegFunc):
        return ToUPriceGetter(like)
    elif isinstance(like, tuple) and len(like) == 2:
        tl, d = like
        return ToUPriceGetter(SegFunc(tl, d))
    elif isinstance(like, list):
        tl = [item[0] for item in like]
        d = [item[1] for item in like]
        return ToUPriceGetter(SegFunc(tl, d))
    else:
        raise TypeError(f"Unsupported PriceGetterLike type: {type(like)}")


class BaseStation(Generic[T_Vehicle], ABC):
    def __init__(self, name: str, bind: str, slots: int, x: float, y: float, price_buy: PriceGetterLike, 
            price_buy_is_service_fee:bool = False, offline: Optional[RangeList] = None, allow_queuing: bool=True):
        """
        Initialize the station

        :param name: Name of the station
        :param bind: The element in the road network where the station is located
        :param slots: Number of chargers/oil pumps in the station
        :param x: X-coordinate of the station
        :param y: Y-coordinate of the station
        :param price_buy_is_service_fee: Whether the price_buy is a service fee (added on top of the cost) rather than the actual price of energy.
        :param price_buy: Price for users to buy energy, $/kWh or $/L. It can be a PriceGetter instance, a constant price (int or float), a SegFunc instance, or a list of (time, price) tuples.
        :param offline: Time range when the station is offline, such as RangeList([(start1, end1), (start2, end2), ...]). None means always online.
        :param allow_queuing: Whether to allow queuing when the station is full
        """
        self._name: str = name
        self._bind: str = bind
        self._slots: int = slots
        self._x: float = x
        self._y: float = y
        self._offline: RangeList = offline if offline is not None else RangeList([])
        self._manual_offline: Optional[bool] = None
        self._pbuy: PriceGetter = _pget_from_like(price_buy)
        self._pbuy_is_serv_fee:bool = price_buy_is_service_fee
        self._allow_que: bool = allow_queuing
        self._chi: Set[T_Vehicle] = set() # Vehicles currently charging
        self._buf: Deque[T_Vehicle] = deque() # Vehicles waiting in the queue
        self._revenue: float = 0.0  # Total revenue earned
        self._cost: float = 0.0     # Total cost incurred

    def reset(self):
        """Reset the station to initial state."""
        self._chi.clear()
        self._buf.clear()
        self._manual_offline = None
        self._revenue = 0.0
        self._cost = 0.0
    
    def reset_money(self):
        """Reset the revenue and cost to zero, while keeping the current vehicles and offline status. 
        This can be used when simulating multiple days and we want to reset the daily revenue and cost while keeping the station status."""
        self._revenue = 0.0
        self._cost = 0.0
    
    @property
    def revenue(self) -> float:
        """Revenue of charging/fueling service"""
        return self._revenue
    
    @property
    def cost(self) -> float:
        """Cost of electricity/fuel purchase"""
        return self._cost
    
    @property
    def profit(self) -> float:
        """Profit of the charging/fueling service"""
        return self._revenue - self._cost
    
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
        """Station name"""
        return self._name

    @property
    def bind(self) -> str:
        """The element in the road network where the station is located"""
        return self._bind
    
    @property
    def slots(self) -> int:
        """Number of chargers/oil pumps in the station"""
        return self._slots

    def pbuy(self, t: int, veh: T_Vehicle) -> float:
        """Price of unit energy for users, $/kWh or $/L. If price_buy_is_service_fee is True, this price is a service fee added on top of the energy cost (e.g., electricity purchase price), otherwise it is the actual price of energy."""
        return self._pbuy(t, self, veh)
    
    @property
    def pbuy_is_service_fee(self) -> bool:
        """Whether the price_buy is a service fee (added on top of the cost) rather than the actual price of energy."""
        return self._pbuy_is_serv_fee
    
    def real_pbuy(self, t: int, veh: T_Vehicle, energy_cost: float) -> float:
        """Return the real price of unit energy for a vehicle, considering service fees."""
        pb = self.pbuy(t, veh)
        if self._pbuy_is_serv_fee: pb += energy_cost  # Add service fee to the base price
        return pb

    def is_online(self, t: int) -> bool:
        """
        Check if the charging station is available at $t$ seconds.
        
        :param t: Time point
        :return: True if available, False if not available or fault
        """
        if self._manual_offline is not None:
            return not self._manual_offline
        return not self._offline.__contains__(t)
    
    def is_offline(self, t: int) -> bool:
        """
        Check if the charging station is unavailable at $t$ seconds.
        
        :param t: Time point
        :return: True if not available or fault, False if available
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
    def __contains__(self, veh: Vehicle) -> bool:
        """Check if the vehicle is in the charging station"""

    @abstractmethod
    def to_xml(self) -> Element: ...
    
    @abstractmethod
    def __len__(self) -> int: ...

    @abstractmethod
    def wait_count(self) -> int:
        '''Number of vehicles waiting in the queue'''

    @abstractmethod
    def vehicles(self):
        """Get an iterator of all vehicles in the charging station"""

    @abstractmethod
    def add_veh(self, veh: T_Vehicle) -> bool: ...
    
    @abstractmethod
    def pop_veh(self, veh: T_Vehicle) -> bool: ...


class GS(BaseStation[GV]):
    def __init__(self, name: str, bind: str, slots: int, x: float, y: float, 
                 price_buy: PriceGetterLike, price_buy_is_service_fee:bool = False,
                 offline: Optional[RangeList] = None, flow: float = 0.7):
        """
        Initialize the gas station
        
        :param name: Name of the gas station
        :param bind: The element in the road network where the gas station is located
        :param slots: Number of refueling slots
        :param x: X-coordinate of the gas station
        :param y: Y-coordinate of the gas station
        :param offline: Time range when the gas station is offline, such as [(start1, end1), (start2, end2), ...]. 
            None means always online.
        :param price_buy: Refueling price list, $/L.
            The first list is the time range, and the second list is the price,
            such as ([0, 3600, 7200], [1.1, 1.2, 1.1]).
        :param price_buy_is_service_fee: Whether the price_buy is a service fee (added on top of the cost) rather than the actual price of energy.
        :param flow: Refueling flow rate, L/s
        """
        super().__init__(name, bind, slots, x, y, price_buy, price_buy_is_service_fee, offline, True)
        self._flow: float = flow  # L/s

    def __contains__(self, veh: GV) -> bool:
        """Check if the vehicle is in the charging station"""
        return veh in self._chi or veh in self._buf

    def __len__(self) -> int:
        """Number of vehicles currently charging"""
        return len(self._chi) + len(self._buf)
    
    def to_xml(self) -> Element:
        """Export the charging station information to XML format"""
        ret = Element("gs", {
            "name": self._name,
            "bind": self._bind,
            "x": str(self._x),
            "y": str(self._y),
            "slots": str(self._slots),
            "pbuy_is_service_fee": str(self._pbuy_is_serv_fee),
        })
        ret.append(self._pbuy.to_xml("pbuy"))
        if len(self._offline) > 0: ret.append(self._offline.toXMLNode("offline"))
        return ret
    
    toXML = to_xml

    def wait_count(self) -> int:
        '''Number of vehicles waiting in the queue'''
        return len(self._buf)

    def vehicles(self):
        """Get an iterator of all vehicles in the charging station"""
        return chain(self._chi, self._buf)
    
    def update(
        self, sec: int, cur_time: int, pb_g:float
    ) -> Set[GV]:
        """
        Update the gas station state for sec seconds.
        
        :param sec: Seconds
        :param cur_time: Current time
        :param pb_g: The cost for CS buying gasoline, $/L
        :return: Set of vehicles removed from the gas station
        """
        
        ret:Set[GV] = set()
        if self.is_offline(cur_time):
            # If the gas station fails, remove all vehicles
            ret = set(chain(self._chi, self._buf))
            self._buf.clear(); self._chi.clear()
            return ret
        
        for gv in self._chi:
            uc = self.pbuy(cur_time, gv)
            if self._pbuy_is_serv_fee: uc += pb_g
            c_, m_ = gv.refuel(sec * self._flow, uc)
            self._revenue += m_; self._cost += c_ * pb_g
            if gv._energy >= gv._etar: ret.add(gv)
            
        for gv in ret: self.pop_veh(gv)
        return ret
    
    def add_veh(self, veh: GV) -> bool:
        """
        Add a vehicle to the refueling queue. Wait when the refueling pile is insufficient.
        
        :param veh: Vehicle instance
        :return: True if added successfully, False if the vehicle is already refueling.
        """
        if veh in self._chi or veh in self._buf:
            return False
        if len(self._chi) < self._slots:
            veh.start_refueling()
            self._chi.add(veh)
        elif self._allow_que:
            self._buf.append(veh)
        else:
            return False
        return True
    
    def pop_veh(self, veh: GV) -> bool:
        """
        Remove the vehicle from the charging queue.

        :param veh: Vehicle instance
        :return: True if removed successfully, False if the vehicle does not exist.
        """
        if veh in self._chi:
            veh.end_refueling()
            self._chi.remove(veh)
        else:
            try:
                self._buf.remove(veh)
            except:
                return False
        if len(self._buf) > 0 and len(self._chi) < self._slots:
            veh = self._buf.popleft()
            veh.start_refueling()
            self._chi.add(veh)
        return True
    
    
__all__ = ['BaseStation', 'GS', 'T_Vehicle', 'PriceGetter', 'PriceGetterLike',
           'ConstPriceGetter', 'ToUPriceGetter', 'ToUSoCPriceGetter', 'PriceGetterPool']