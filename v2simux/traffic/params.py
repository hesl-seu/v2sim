# 默认快充速率kW, 1 kW=1/3600 kWh/s, 如果*.veh.xml或自动生成机构中定义了每辆EV的快充速率，则不会使用此项
# Default fast charge rate kW. This item will not be used if the fast charge rate of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_FAST_CHARGE_RATE = 120 

# 默认慢充速率kW, 如果*.veh.xml或自动生成机构中定义了每辆EV的慢充速率，则不会使用此项
# Default slow charge rate kW. This item will not be used if the slow charge rate of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_SLOW_CHARGE_RATE = 7

# 默认电池容量kWh, 如果*.veh.xml或自动生成机构中定义了每辆EV的电池容量，则不会使用此项
# Default battery capacity kWh. This item will not be used if the battery capacity of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_FULL_BATTERY = 50

# 默认初始电池SoC, 如果*.veh.xml或自动生成机构中定义了每辆EV的初始电池SoC，则不会使用此项
# Default initial battery SoC, this item will not be used if the initial battery SoC of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_INIT_SOC = 0.9

# 默认耗电速率Wh/m, 如果*.veh.xml或自动生成机构中定义了每辆EV的耗电速率，则不会使用此项
# Default power consumption rate Wh/m. This item will not be used if the power consumption rate of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_CONSUMPTION = 320 / DEFAULT_FULL_BATTERY

# 默认用户omega参数, 如果*.veh.xml或自动生成机构中定义了每辆EV的omega，则不会使用此项
# Default user omega parameter, this item will not be used if the omega of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_OMEGA = 75

# 默认用户K_rel参数, 如果*.veh.xml或自动生成机构中定义了每辆EV的Krel，则不会使用此项
# Default user K_rel parameter, this item will not be used if the Krel of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_KREL = 1.25

# 默认用户K_V2G参数, 如果*.veh.xml或自动生成机构中定义了每辆EV的Kv2g，则不会使用此项
# Default user K_V2G parameter, this item will not be used if the Kv2g of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_KV2G = 0.8

# 默认最大V2G返送功率kW, 如果*.veh.xml或自动生成机构中定义了每辆EV的max_v2g_rate，则不会使用此项
# Default maximum V2G return power by kW. This item will not be used if the max_v2g_rate of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_MAX_V2G_RATE = 20

# 指示根据电量是否满足行程长度来充电
# Indicate whether to charge according to whether the power is sufficient for the trip length
ENABLE_DIST_BASED_CHARGING_DECISION = False

# 默认快充阈值: 指定车辆出发时EV电量低于多少比例会去快充, 有效值0~1. 只在ENABLE_DIST_BASED_CHARGING_DECISION = False时生效
# 如果*.veh.xml或自动生成机构中定义了每辆EV的Kfc，则不会使用此项
# Default fast charge threshold: specifies the proportion of EV power when the vehicle departs that will go to fast charge, valid values 0~1. Only valid when ENABLE_DIST_BASED_CHARGING_DECISION = False
# This item will not be used if the Kfc of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_FAST_CHARGE_THRESHOLD = 0.2

# 默认快充阈值: 指定车辆出发时EV电量低于多少比例会去慢充, 有效值0~1.
# 如果*.veh.xml或自动生成机构中定义了每辆EV的Ksc，则不会使用此项
# Default slow charge threshold: specifies the proportion of EV power when the vehicle departs that will go to slow charge, valid values 0~1
# This item will not be used if the Ksc of each EV is defined in *.veh.xml or automatically generated organization
DEFAULT_SLOW_CHARGE_THRESHOLD = 0.5

# 指示在快充站是否根据行程长度确定充电量, True表示充电量刚好够行驶到终点(会稍微多充一点, 由Krel控制), False表示总是充满
# Indicate whether the charging quantity is determined based on the trip length at the fast charging station, True means that the charging quantity is just enough to drive to the end point (a little more charge, controlled by Krel), False means always full
ENABLE_DIST_BASED_CHARGING_QUANTITY = False

# 指示是否允许CSList中同时存在快充站和慢充站
# Indicate whether fast charging stations and slow charging stations are allowed to exist simultaneously in CSList
ALLOW_MIXED_CSTYPE_IN_CSLIST = False

# 默认充电效率
# Default charging efficiency
DEFAULT_ETA_CHARGE = 0.9

# 默认放电效率
# Default discharge efficiency
DEFAULT_ETA_DISCHARGE = 0.9

# 默认电动车充电功率修正函数
# Default electric vehicle charging power correction function
DEFAULT_RMOD = "Linear"

# Default maximum slow charge cost for an EV
DEFAULT_MAX_SC_COST = 100.0

# Default minimum V2G earning for an EV
DEFAULT_MIN_V2G_EARN = 0.0