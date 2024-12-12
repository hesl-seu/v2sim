from typing import Literal, Optional
from flocale.lang import Lang
from ftraffic.utils import TWeights
from .ev import EV


class CprocLogger:
    ARRIVAL_NO_CHARGE = 0
    ARRIVAL_CHARGE_SUCCESSFULLY = 1
    ARRIVAL_CHARGE_FAILED = 2
    def __init__(self, file_name:str):
        self.__ostream = open(file_name, 'w', encoding='utf-8')
    
    def __pr(self, *args):
        print(*args, file=self.__ostream, sep="|")

    def arrive(self, simT: int, veh: EV, status: Literal[0, 1, 2]): 
        tid = veh.trip_id
        if tid < veh.trips_count - 1:
            nt = veh.trips[tid + 1]
        else:
            nt = None
        self.__pr(simT, 'A', veh.brief(), status, veh.trip.arrive_edge, nt)

    def arrive_CS(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'AC', veh.brief(), cs)

    def depart(self, simT: int, veh: EV, delay:int = 0, cs: Optional[str] = None, cs_param:Optional[TWeights] = None):
        if cs_param:
            cs_param_str = f'{cs_param[0]:.3f},{cs_param[1]:.3f},{cs_param[2]:.3f}'
        else:
            cs_param_str = ''
        self.__pr(simT, 'D', veh.brief(), veh.trip, delay, cs, cs_param_str)

    def depart_delay(self, simT: int, veh: EV, batt_req: float, delay:int):
        self.__pr(simT, 'DD', veh.brief(), veh.battery, batt_req, delay)
    
    def depart_CS(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'DC', veh.brief(), cs, veh.trip.arrive_edge)
    
    def depart_failed(self, simT: int, veh: EV, batt_req: float, cs: str, trT:int):
        self.__pr(simT, 'DF', veh.brief(), veh.battery, batt_req, cs, trT)
    
    def fault_deplete(self, simT: int, veh: EV, cs: str, trT:int):
        self.__pr(simT, 'FD', veh.brief(), cs, trT)
    
    def fault_nocharge(self, simT: int, veh: EV, cs: str):
        self.__pr(simT, 'FN', veh.brief(), veh.battery, cs)
    
    def fault_redirect(self, simT: int, veh: EV, cs_old: str, cs_new: str):
        self.__pr(simT, 'FR', veh.brief(), veh.battery, cs_old, cs_new)

    def warn_smallcap(self, simT: int, veh: EV, batt_req: float):
        self.__pr(simT, 'WC', veh.brief(), veh.battery, batt_req)
    
    def close(self):
        self.__ostream.close()

class MetaData:
    OP_NAMEs = {
        'A': Lang.CPROC_ARRIVE,
        'AC': Lang.CPROC_ARRIVE_CS,
        'D': Lang.CPROC_DEPART,
        'DD': Lang.CPROC_DEPART_DELAY,
        'DC': Lang.CPROC_DEPART_CS,
        'DF': Lang.CPROC_DEPART_FAILED,
        'FD': Lang.CPROC_FAULT_DEPLETE,
        'WC': Lang.CPROC_WARN_SMALLCAP
    }
    def __init__(self, simT:int, op:str, veh_id:str, veh_soc:str, trip_id:int, additional:dict[str,str]):
        self.simT = simT
        self.__op = op
        self.veh = veh_id
        self.veh_soc = veh_soc
        self.trip_id = trip_id
        self.additional = additional

    def to_tuple(self,conv:bool=False):
        op = self.__op if not conv else MetaData.OP_NAMEs[self.__op]
        return (self.simT, op, self.veh, self.veh_soc, self.trip_id, self.additional.get('cs_param',''), self.additional)
    
    @property
    def op_raw(self):
        return self.__op

    @property
    def op(self):
        return MetaData.OP_NAMEs[self.__op]
    
    @property
    def cs_param(self):
        return self.additional.get('cs_param', None)
    
    def __repr__(self):
        return f"{self.simT}|{self.__op}|{self.veh},{self.veh_soc},{self.trip_id}|{self.additional}"
    
    def __str__(self):
        ret = f"[{self.simT},{MetaData.OP_NAMEs[self.__op]}]"
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
            if int(self.additional['delay']) <= 0:
                ret += Lang.CPROC_INFO_DEPART_WITH_DELAY.format(
                    self.additional['trip']
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
        elif self.__op == 'F':
            ret += Lang.CPROC_INFO_FAULT_DEPLETE.format(
                veh,
                self.additional['cs'],
                self.additional['trT'],
            )
        elif self.__op == 'W':
            ret += Lang.CPROC_INFO_FAULT_DEPLETE.format(
                veh,
                self.additional['veh_batt'],
                self.additional['batt_req']
            )
        else:
            raise ValueError(f"Unknown operation {self.__op}")
        return ret
    
class CprocReader:
    def __init__(self, filename:str):
        with open(filename, 'r', encoding='utf-8') as fp:
            self.raw_texts = fp.readlines()
        self.meta_data:list[MetaData] = []
        self.translated_texts:list[str] = []
        for d in map(lambda x: x.strip().split('|'), self.raw_texts):
            simT = int(d[0])
            op = d[1]
            veh, soc, tripid = d[2].split(',')
            additional:dict[str,str] = {}
            if op == 'A':
                assert len(d) == 6
                additional['status'] = d[3]
                additional['arrive_edge'] = d[4]
                additional['next_trip'] = d[5]
            elif op == 'AC':
                assert len(d) == 4
                additional['cs'] = d[3]
            elif op == 'D':
                assert len(d) == 7
                additional['trip'] = d[3]
                additional['delay'] = d[4]
                additional['cs'] = d[5]
                additional['cs_param'] = d[6]
            elif op == 'DD':
                assert len(d) == 6
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
                additional['delay'] = d[5]
            elif op == 'DC':
                assert len(d) == 5
                additional['cs'] = d[3]
                additional['arrive_edge'] = d[4]
            elif op == 'DF':
                assert len(d) == 7
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
                additional['cs'] = d[5]
                additional['trT'] = d[6]
            elif op == 'F':
                assert len(d) == 5
                additional['cs'] = d[3]
                additional['trT'] = d[4]
            elif op == 'W':
                assert len(d) == 5
                additional['veh_batt'] = d[3]
                additional['batt_req'] = d[4]
            else:
                raise ValueError(f"Unknown operation {op}")
            met = MetaData(simT, op, veh, soc, int(tripid), additional)
            self.meta_data.append(met)
            self.translated_texts.append(str(met))
            
    def __iter__(self):
        return iter(self.translated_texts)
    
    def __len__(self):
        return len(self.translated_texts)
    
    def filter(self, 
        time:Optional[tuple[Optional[int],Optional[int]]]=None, 
        action:Optional[list[str]]=None, 
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