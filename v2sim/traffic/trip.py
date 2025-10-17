from typing import Any, Callable, List, Literal, Optional, Dict, Tuple
from ..locale import Lang
from .ev import EV


_ArriveListener = Callable[[int, EV, Literal[0, 1, 2], float], None]
_ArriveFCSListener = Callable[[int, EV, str, float], None]
_ArriveCSListener = _ArriveFCSListener  # Alias for compatibility
_DepartListener = Callable[[int, EV, int, Optional[str], Any], None]
_DepartDelayListener = Callable[[int, EV, float, int], None]
_DepartFCSListener = Callable[[int, EV, str], None]
_DepartCSListener = _DepartFCSListener  # Alias for compatibility
_JoinSCSListener = Callable[[int, EV, str], None]
_LeaveSCSListener = Callable[[int, EV, str], None]
_DepartFailedListener = Callable[[int, EV, float, str, int], None]
_FaultDepleteListener = Callable[[int, EV, str, int], None]
_FaultNoChargeListener = Callable[[int, EV, str], None]
_FaultRedirectListener = Callable[[int, EV, str, str], None]
_WarnSmallCapListener = Callable[[int, EV, float], None]


class TripsLogger:
    ARRIVAL_NO_CHARGE = 0
    ARRIVAL_CHARGE_SUCCESSFULLY = 1
    ARRIVAL_CHARGE_FAILED = 2
    def __init__(self, file_name:str):
        self.__ostream = open(file_name, 'w', encoding='utf-8')
        self.__arrive_listeners:List[_ArriveListener] = []
        self.__arrive_cs_listeners:List[_ArriveFCSListener] = []
        self.__join_scs_listeners:List[_JoinSCSListener] = []
        self.__leave_scs_listeners:List[_LeaveSCSListener] = []
        self.__depart_listeners:List[_DepartListener] = []
        self.__depart_delay_listeners:List[_DepartDelayListener] = []
        self.__depart_cs_listeners:List[_DepartFCSListener] = []
        self.__depart_failed_listeners:List[_DepartFailedListener] = []
        self.__fault_deplete_listeners:List[_FaultDepleteListener] = []
        self.__fault_nocharge_listeners:List[_FaultNoChargeListener] = []
        self.__fault_redirect_listeners:List[_FaultRedirectListener] = []
        self.__warn_smallcap_listeners:List[_WarnSmallCapListener] = []
    
    def add_arrive_listener(self, func: _ArriveListener):
        self.__arrive_listeners.append(func)
    
    def add_arrive_fcs_listener(self, func: _ArriveFCSListener):
        self.__arrive_cs_listeners.append(func)
    
    add_arrive_cs_listener = add_arrive_fcs_listener # Alias for compatibility
    
    def add_depart_listener(self, func: _DepartListener):
        self.__depart_listeners.append(func)
    
    def add_depart_delay_listener(self, func: _DepartDelayListener):
        self.__depart_delay_listeners.append(func)
    
    def add_depart_fcs_listener(self, func: _DepartFCSListener):
        self.__depart_cs_listeners.append(func)
    
    add_depart_cs_listener = add_depart_fcs_listener # Alias for compatibility
    
    def add_join_scs_listener(self, func: _JoinSCSListener):
        self.__join_scs_listeners.append(func)
    
    def add_leave_scs_listener(self, func: _LeaveSCSListener):
        self.__leave_scs_listeners.append(func)

    def add_depart_failed_listener(self, func: _DepartFailedListener):
        self.__depart_failed_listeners.append(func)
    
    def add_fault_deplete_listener(self, func: _FaultDepleteListener):
        self.__fault_deplete_listeners.append(func)
    
    def add_fault_nocharge_listener(self, func: _FaultNoChargeListener):
        self.__fault_nocharge_listeners.append(func)
    
    def add_fault_redirect_listener(self, func: _FaultRedirectListener):
        self.__fault_redirect_listeners.append(func)
    
    def add_warn_smallcap_listener(self, func: _WarnSmallCapListener):
        self.__warn_smallcap_listeners.append(func)
    
    def __pr(self, *args):
        print(*args, file=self.__ostream, sep="|")

    def arrive(self, simT: int, veh: EV, status: Literal[0, 1, 2], dist: float = -1): 
        tid = veh.trip_id
        if tid < veh.trips_count - 1:
            nt = veh.trips[tid + 1]
        else:
            nt = None
        self.__pr(simT, 'A', veh.brief(), status, dist, veh.trip.to_node, nt)
        for l in self.__arrive_listeners:
            l(simT, veh, status, dist)

    def arrive_FCS(self, simT: int, veh: EV, cs: str, dist:float = -1):
        self.__pr(simT, 'AC', veh.brief(), cs, dist)
        for l in self.__arrive_cs_listeners:
            l(simT, veh, cs, dist)

    arrive_CS = arrive_FCS  # Alias for compatibility
    
    def join_SCS(self, simT: int, veh:EV, cs: str):
        self.__pr(simT, 'JS', veh.brief(), cs)
        for l in self.__join_scs_listeners:
            l(simT, veh, cs)
    
    def leave_SCS(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'LS', veh.brief(), cs)
        for l in self.__leave_scs_listeners:
            l(simT, veh, cs)

    def depart(self, simT: int, veh: EV, delay:int = 0, cs: Optional[str] = None):
        self.__pr(simT, 'D', veh.brief(), veh.trip, delay, cs, '')
        for l in self.__depart_listeners:
            l(simT, veh, delay, cs, None)

    def depart_delay(self, simT: int, veh: EV, batt_req: float, delay:int):
        self.__pr(simT, 'DD', veh.brief(), veh.battery, batt_req, delay)
        for l in self.__depart_delay_listeners:
            l(simT, veh, batt_req, delay)
    
    def depart_FCS(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'DC', veh.brief(), cs, veh.trip.to_node)
        for l in self.__depart_cs_listeners:
            l(simT, veh, cs)
    
    depart_CS = depart_FCS  # Alias for compatibility
    
    def depart_failed(self, simT: int, veh: EV, batt_req: float, cs: str, trT:int):
        self.__pr(simT, 'DF', veh.brief(), veh.battery, batt_req, cs, trT)
        for l in self.__depart_failed_listeners:
            l(simT, veh, batt_req, cs, trT)
    
    def fault_deplete(self, simT: int, veh: EV, cs: str, trT:int):
        self.__pr(simT, 'FD', veh.brief(), cs, trT)
        for l in self.__fault_deplete_listeners:
            l(simT, veh, cs, trT)
    
    def fault_nocharge(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'FN', veh.brief(), veh.battery, cs)
        for l in self.__fault_nocharge_listeners:
            l(simT, veh, cs)
    
    def fault_redirect(self, simT: int, veh: EV, cs_old: str, cs_new: str):
        self.__pr(simT, 'FR', veh.brief(), veh.battery, cs_old, cs_new)
        for l in self.__fault_redirect_listeners:
            l(simT, veh, cs_old, cs_new)

    def warn_smallcap(self, simT: int, veh: EV, batt_req: float):
        self.__pr(simT, 'WC', veh.brief(), veh.battery, batt_req)
        for l in self.__warn_smallcap_listeners:
            l(simT, veh, batt_req)
    
    def close(self):
        self.__ostream.close()

class TripLogItem:
    OP_NAMEs = {
        'A': Lang.CPROC_ARRIVE,
        'AC': Lang.CPROC_ARRIVE_CS,
        'D': Lang.CPROC_DEPART,
        'DD': Lang.CPROC_DEPART_DELAY,
        'DC': Lang.CPROC_DEPART_CS,
        'DF': Lang.CPROC_DEPART_FAILED,
        'FD': Lang.CPROC_FAULT_DEPLETE,
        'FN': Lang.CPROC_FAULT_NOCHARGE,
        'FR': Lang.CPROC_FAULT_REDIRECT,
        'WC': Lang.CPROC_WARN_SMALLCAP,
        'JS': Lang.CPROC_JOIN_SCS,
        'LS': Lang.CPROC_LEAVE_SCS,
    }
    def __init__(self, simT:int, op:str, veh_id:str, veh_soc:str, veh_batt:str, trip_id:int, additional:Dict[str,str]):
        self.simT = simT
        self.__op = op
        self.veh = veh_id
        self.veh_soc = veh_soc
        self.veh_batt = veh_batt
        self.trip_id = trip_id
        self.additional = additional

    def to_tuple(self,conv:bool=False):
        op = self.__op if not conv else TripLogItem.OP_NAMEs[self.__op]
        return (self.simT, op, self.veh, self.veh_soc, self.veh_batt, self.trip_id, self.additional)
    
    @property
    def time(self):
        """Simulation time in seconds."""
        return self.simT
    
    @property
    def vehicle(self):
        """Vehicle ID."""
        return self.veh
    
    @property
    def soc(self):
        """Vehicle state of charge."""
        return self.veh_soc
    
    @property
    def id(self):
        """Trip ID."""
        return self.trip_id
    
    @property
    def op_raw(self):
        """Operation code."""
        return self.__op

    @property
    def op(self):
        """Operation name, translated if possible."""
        return TripLogItem.OP_NAMEs[self.__op]
    
    @property
    def cs_param(self):
        """Charging station selection parameters, if any."""
        return self.additional.get('cs_param', None)
    
    @property
    def cs(self):
        """Charging station ID, if any."""
        return self.additional.get('cs', None)
    
    def __repr__(self):
        return f"{self.simT}|{self.__op}|{self.veh},{self.veh_soc},{self.veh_batt:.1f},{self.trip_id}|{self.additional}"
    
    def __str__(self):
        ret = f"[{self.simT},{TripLogItem.OP_NAMEs[self.__op]}]"
        veh = f"{self.veh}(Soc={self.veh_soc},TripID={self.trip_id})"
        if self.__op == 'A':
            if self.additional['status'] == '0':
                pos2 = Lang.CPROC_INFO_ARRIVE_0
            elif self.additional['status'] == '1':
                pos2 = Lang.CPROC_INFO_ARRIVE_1
            elif self.additional['status'] == '2':
                pos2 = Lang.CPROC_INFO_ARRIVE_2
            ret += Lang.CPROC_INFO_ARRIVE.format(
                veh, 
                self.additional['arrive_edge'],
                pos2,
                self.additional['next_trip']
            )
        elif self.__op == 'AC':
            ret += Lang.CPROC_INFO_ARRIVE_CS.format(
                veh,
                self.additional['cs']
            )
        elif self.__op == 'D':
            ret += Lang.CPROC_INFO_DEPART.format(
                veh,
                self.additional['trip'],
            )
            if int(self.additional['delay']) > 0:
                ret += Lang.CPROC_INFO_DEPART_WITH_DELAY.format(
                    self.additional['delay']
                )
            if self.additional['cs'] != "None":
                ret += Lang.CPROC_INFO_DEPART_WITH_CS.format(
                    self.additional['cs'],
                    self.additional['cs_param']
                )
        elif self.__op == 'DD':
            ret += Lang.CPROC_INFO_DEPART_DELAY.format(
                veh,
                self.additional['veh_batt'],
                self.additional['batt_req'],
                self.additional['delay']
            )
        elif self.__op == 'DC':
            ret += Lang.CPROC_INFO_DEPART_CS.format(
                veh,
                self.additional['cs'],
                self.additional['arrive_edge']
            )
        elif self.__op == 'DF':
            ret += Lang.CPROC_INFO_DEPART_FAILED.format(
                veh,
                self.additional['veh_batt'],
                self.additional['batt_req'],
                self.additional['cs'],
                self.additional['trT']
            )
        elif self.__op == 'FD':
            ret += Lang.CPROC_INFO_FAULT_DEPLETE.format(
                veh,
                self.additional['cs'],
                self.additional['trT'],
            )
        elif self.__op == 'FN':
            ret += Lang.CPROC_INFO_FAULT_NOCHARGE.format(
                veh,
                self.additional['cs']
            )
        elif self.__op == 'FR':
            ret += Lang.CPROC_INFO_FAULT_REDIRECT.format(
                veh,
                self.additional['old_cs'],
                self.additional['new_cs']
            )
        elif self.__op == 'WC':
            ret += Lang.CPROC_INFO_FAULT_DEPLETE.format(
                veh,
                self.additional['veh_batt'],
                self.additional['batt_req']
            )
        elif self.__op == 'JS':
            ret += Lang.CPROC_INFO_JOIN_SCS.format(
                veh,
                self.additional['cs']
            )
        elif self.__op == 'LS':
            ret += Lang.CPROC_INFO_LEAVE_SCS.format(
                veh,
                self.additional['cs']
            )
        else:
            raise ValueError(f"Unknown operation {self.__op}")
        return ret
    
class TripsReader:
    def __init__(self, filename:str):
        with open(filename, 'r', encoding='utf-8') as fp:
            self.raw_texts = fp.readlines()
        self.meta_data:List[TripLogItem] = []
        self.translated_texts:List[str] = []
        for d in map(lambda x: x.strip().split('|'), self.raw_texts):
            simT = int(d[0])
            op = d[1]
            splits = d[2].split(',')
            if len(splits) == 4:
                veh, soc, batt, tripid = splits
            else:
                veh, soc, tripid = splits
                batt = "None"
            additional:Dict[str,str] = {}
            if op == 'A':
                if len(d) == 6:
                    additional['status'] = d[3]
                    additional['arrive_edge'] = d[4]
                    additional['next_trip'] = d[5]
                elif len(d) == 7:
                    additional['status'] = d[3]
                    additional['dist'] = d[4]
                    additional['arrive_edge'] = d[5]
                    additional['next_trip'] = d[6]
                else:
                    raise ValueError(f"Invalid A entry, expected 6 or 7 fields, got {len(d)}")
            elif op == 'AC':
                if len(d) == 4:
                    additional['cs'] = d[3]
                elif len(d) == 5:
                    additional['cs'] = d[3]
                    additional['dist'] = d[4]
                else:
                    raise ValueError(f"Invalid AC entry, expected 4 or 5 fields, got {len(d)}")
            elif op == 'D':
                assert len(d) == 7, f"Invalid D entry, expected 7 fields, got {len(d)}"
                additional['trip'] = d[3]
                additional['delay'] = d[4]
                additional['cs'] = d[5]
                additional['cs_param'] = d[6]
            elif op == 'DD':
                assert len(d) == 6, f"Invalid DD entry, expected 6 fields, got {len(d)}"
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
                additional['delay'] = d[5]
            elif op == 'DC':
                assert len(d) == 5, f"Invalid DC entry, expected 5 fields, got {len(d)}"
                additional['cs'] = d[3]
                additional['arrive_edge'] = d[4]
            elif op == 'DF':
                assert len(d) == 7, f"Invalid DF entry, expected 7 fields, got {len(d)}"
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
                additional['cs'] = d[5]
                additional['trT'] = d[6]
            elif op == 'FD':
                assert len(d) == 5, f"Invalid FD entry, expected 5 fields, got {len(d)}"
                additional['cs'] = d[3]
                additional['trT'] = d[4]
            elif op == 'FN':
                assert len(d) == 4, f"Invalid FN entry, expected 4 fields, got {len(d)}"
                additional['cs'] = d[3]
            elif op == 'FR':
                assert len(d) == 5, f"Invalid FR entry, expected 5 fields, got {len(d)}"
                additional['old_cs'] = d[3]
                additional['new_cs'] = d[4]
            elif op == 'WC':
                assert len(d) == 5, f"Invalid WC entry, expected 5 fields, got {len(d)}"
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
            elif op == 'JS':
                assert len(d) == 4, f"Invalid JS entry, expected 4 fields, got {len(d)}"
                additional['cs'] = d[3]
            elif op == 'LS':
                assert len(d) == 4, f"Invalid LS entry, expected 4 fields, got {len(d)}"
                additional['cs'] = d[3]
            else:
                raise ValueError(f"Unknown operation {op}")
            met = TripLogItem(simT, op, veh, soc, batt, int(tripid), additional)
            self.meta_data.append(met)
            self.translated_texts.append(str(met))
            
    def __iter__(self):
        return iter(self.translated_texts)
    
    def __len__(self):
        return len(self.translated_texts)
    
    def filter(self, 
        time:Optional[Tuple[Optional[int],Optional[int]]]=None, 
        action:Optional[List[str]]=None, 
        veh:Optional[str]=None, 
        trip_id:Optional[int]=None):
        for r,m,t in zip(self.raw_texts, self.meta_data, self.translated_texts):
            if time is not None:
                if time[0] is not None:
                    if not time[0] <= m.simT:
                        continue
                if time[1] is not None:
                    if not m.simT <= time[1]:
                        continue
            if action is not None:
                if m.op_raw not in action:
                    continue
            if veh is not None:
                if m.veh != veh:
                    continue
            if trip_id is not None:
                if m.trip_id != trip_id:
                    continue
            yield r, m, t

__all__ = ["TripsLogger", "TripLogItem", "TripsReader"]