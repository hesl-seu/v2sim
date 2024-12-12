'''
Necessary information for trip chain
'''

class Trip:
    def __init__(
        self, trip_id: str, depart_time: int, fromTAZ: str, toTAZ: str, route: list[str]
    ):
        self.ID = trip_id
        self.depart_time = depart_time
        self.from_TAZ = fromTAZ
        self.to_TAZ = toTAZ
        assert isinstance(route, list) and len(route) >= 2, "Route should be a list with at least 2 elements"
        self.route = route
    
    @property
    def depart_edge(self):
        return self.route[0]

    @property
    def arrive_edge(self):
        return self.route[-1]

    def __repr__(self):
        return str(self)
    
    def __str__(self):
        return f"{self.depart_edge}->{self.arrive_edge}@{self.depart_time}"
