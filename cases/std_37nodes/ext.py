from ftraffic import EV, AllocEnv

# 定义V2G分配方案 Define V2G allocation scheme
# 如果要使用V2G功能, 请在插件类中定义V2G方案
# 如果要将某一充电站的V2G分配方案设置为下列函数，则在*.scs.xml文件中将该充电站的v2galloc属性设置为"MyAverage"
# V2G分配函数名称必须以ActualRatio结尾, 其输入如函数签名所示，输出是针对ev_ids列表中，每辆车的放电功率乘数，需要保持与ev_ids相同的顺序
def MyAverageActualRatio(env: 'AllocEnv', v2g_k: 'float') -> 'list[float]':
    return len(env.EVs) * [v2g_k]

import ftraffic.cs
ftraffic.cs.V2GAllocPool.add("MyAverage",MyAverageActualRatio)

# 定义电池充电特性函数
# 如果要将某一电动车的电池修正设为下列函数，则在*.veh.xml文件中将该电动车的rmod属性设置为"MyEqual"
# 电池修正函数示例如下：其输入如函数签名所示，输出是实际充电功率
def MyEqualChargeRate(rate: float, ev: 'EV') -> float:
    return rate

import ftraffic.ev
ftraffic.ev.ChargeRatePool.add("MyEqual",MyEqualChargeRate)