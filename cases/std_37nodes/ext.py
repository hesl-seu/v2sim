import v2sim
from v2sim import EV, AllocEnv

def MyAverageAllocFunc(env:AllocEnv, veh_cnt: int, v2g_demand: float, v2g_cap: float):
    """
    Customized V2G Strategy
        env: Environment includes SCS, EVs and current time
        veh_cnt: Number of involved EVs
        v2g_demand: V2G power demanded by grid dispatcher
        v2g_cap: Maximum V2G power output of the SCS
    Returns nothing
    """
    if veh_cnt == 0 or v2g_demand == 0: return
    pd = v2g_demand / veh_cnt

    # Important: Must set the actual V2G power of each involved EV by set_temp_pd(...)
    for ev in env.EVs:
        ev.set_temp_pd(pd)

v2sim.V2GAllocPool.add("MyAverage", MyAverageAllocFunc)

def MyAverageMaxPCAllocator(env: AllocEnv, vcnt:int, max_pc0: float, max_pc_tot: float):
    """
    Average maximum charging power allocator
        env: Allocation environment
        vcnt: Number of vehicles being charged
        max_pc0: Maximum charging power of a single pile, kWh/s
        max_pc_tot: Maximum charging power of the entire CS given by the PDN, kWh/s
    Returns nothing
    """
    if vcnt == 0: return
    pc0 = min(max_pc_tot / vcnt, max_pc0)

    # Important: Must set the actual charging power of each involved EV by set_temp_pc(...)
    for ev in env.EVs:
        ev.set_temp_max_pc(pc0)

v2sim.MaxPCAllocPool.add("MyAverage", MyAverageMaxPCAllocator)

def MyEqualChargeRate(rate: float, ev: EV) -> float:
    """
    Charging power modifier
        rate: Nominal charging power
        ev: EV object
    Returns the actual charging power
    """
    return rate

v2sim.ChargeRatePool.add("MyEqual",MyEqualChargeRate)