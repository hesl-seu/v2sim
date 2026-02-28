from abc import ABC, abstractmethod
from typing import List, Optional

from ..veh import Trip


class TripGenerator(ABC):
    @abstractmethod
    def first_trip(self, t:int) -> Trip: ...

    @abstractmethod
    def next_trip(self, t:int) -> Trip: ...

    @abstractmethod
    def final_trip(self, t:int) -> Trip: ...


class PrivateCarTripGenerator(TripGenerator):
    def __init__(self, home: str, work: str):
        self.home = home
        self.work = work

class LLMPrivateCarTripGenerator(TripGenerator):
    def __init__(self, home: str, work: str, llm_model: str):
        self.home = home
        self.work = work
        self.llm_model = llm_model

class BusTripGenerator(TripGenerator):
    def __init__(self, route_edges: List[str]):
        self.route_edges = route_edges


class TaxiTripGenerator(TripGenerator):
    def __init__(self, base:str, service_area: Optional[List[str]] = None):
        self.base = base
        self.service_area = service_area
