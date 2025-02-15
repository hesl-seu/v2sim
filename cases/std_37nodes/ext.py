import v2sim
from v2sim import EV, AllocEnv

'''
Define V2G allocation scheme
    If you want to set the V2G allocation scheme of a charging station to the following function, 
    set the v2galloc attribute of the charging station to "MyAverage" in the *. scs.xml file.
    The name of the V2G allocation function must end with ActualRatio, 
    and its input is as shown in the function signature. 
    The output is the discharge power multiplier for each vehicle in the ev_ids list, 
    which needs to be kept in the same order as ev_ids.
'''
def MyAverageActualRatio(env: 'AllocEnv', v2g_k: 'float') -> 'list[float]':
    return len(env.EVs) * [v2g_k]

v2sim.cs.V2GAllocPool.add("MyAverage",MyAverageActualRatio)

'''
Define the battery correction function (BCF)
    If you want to set the BCF of a certain electric vehicle to the following function,
    set the rmod attribute of the electric vehicle to "MyEqual" in the *. veh. xml file.
    An BCF example is shown as follows:
    Its input is as shown in the function signature, and its output is the actual charging power.
'''
def MyEqualChargeRate(rate: float, ev: 'EV') -> float:
    return rate

v2sim.ev.ChargeRatePool.add("MyEqual",MyEqualChargeRate)