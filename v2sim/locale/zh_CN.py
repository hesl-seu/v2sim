class _locale:
    LANG_CODE = "zh_CN"

    TRIPGEN_HELP_STR = """
行程生成程序
{} -n <车辆数> -d <SUMO配置文件夹> [-c <行程参数文件夹>] [-v <V2G概率>] [--seed <随机化种子>]
    n: 车辆数
    d: SUMO配置文件夹
    c: 行程参数文件夹, 默认使用"{}"
    v: 每个用户愿意参加V2G的概率, 默认为1
    seed: 随机化种子, 不指定则使用当前时间(纳秒)
"""

    CSGEN_HELP_STR = """
充电站生成程序
{} -d <SUMO配置文件夹> [--type <scs,fcs>] [--slots <充电桩数量>] [--pbuy <购电价格>] [--randomize-pbuy] \\
[--psell <售电价格>] [--randomize-psell] [--seed <随机化种子>] [--n-cs <充电站数量>] [--cs-names] [--n-bus <母线数量>] [--bus-names <使用的母线>]
    h/help: 显示此帮助信息
    d: SUMO配置文件夹
    type: 充电站类型, 默认fcs, 可选fcs(快充站), scs(慢充站)
    slots: 充电桩数量, 默认10
    pbuy: 购电价格, 默认1.5元/kWh
    randomize-pbuy: 随机化购电价格
    psell: 售电价格, 默认1元/kWh
    randomize-psell: 随机化售电价格
    seed: 随机化种子, 不指定则使用当前时间(纳秒)
充电站选择:
    默认为使用所有可用的充电站, 可以通过以下选项改变:
    n-cs: 快充站数量, 指定该项则快充站选择方式为"随机"
    cs-names: 快充站名称, 指定该项则快充站选择方式为"指定"
    以上两项不能一起使用
母线选择:
    默认使用所有母线, 可以通过以下选项改变:
    n-bus: 使用的母线数量, 指定该项则母线选择方式为"随机"
    bus-names: 使用的母线, 指定该项则母线选择方式为"指定"
    以上两项不能一起使用
"""
    
    MAIN_HELP_STR = """EV充电负荷负荷生成模拟器 - 使用帮助
{} -d <配置文件夹> [-b <开始时间>] [-e <结束时间>] [-l <数据记录步长>] [-o <输出文件夹>] \\
[--seed <随机种子>] [--log <要记录的数据>] [--no-plg <要禁用的插件>] [--show] [--no-daemon] \\
[--copy] [--debug] [-h/help] [--file <文件>] [--ls-plg] [--ls-log]
以下参数应当单独使用, 不可与其他参数配合:
    h/help: 显示本帮助信息
    file: 从外部文件读取参数并串行的实行命令行仿真, 该文件的内容应当是一个以空格分隔的参数列表, 如果该文件有多行则只考虑第1行. 例如: "-d 12nodes -b 0 -e 172800"
    ls-com: 列出所有可用的插件和记录项
以下参数用于单次仿真:
    d: 配置文件夹
    b: 开始时间, 单位为秒, 默认从SUMO配置中读取
    e: 结束时间, 单位为秒, 默认从SUMO配置中读取
    l: 数据记录步长, 单位为秒, 默认值10
    o: 输出文件夹, 默认为当前目录下的results文件夹
    seed: 自动生成车辆、充电站以及SUMO使用的随机种子, 默认值为当前时间(ns)%65536
    log: 要记录的数据, 包括电动汽车(ev), 快充站(fcs), 慢充站(scs), 发电机(gen), 母线(bus)和输电线(line), 多项数据用逗号隔开, 默认值为"fcs,scs"
    no-plg: 禁用指定的插件, 多个插件用逗号隔开, 默认不禁用任何插件
    copy: 仿真结束后将配置文件复制到输出文件夹, 默认不复制
    gen-veh: 强制重新生成车辆文件的命令行, 默认不生成
    gen-fcs: 强制重新生成充电站文件的命令行, 默认不生成
    gen-scs: 强制重新生成充电站文件的命令行, 默认不生成
    plot: 完成仿真后的绘图命令行, 默认不绘图
    initial-state: 仿真的初始状态文件夹, 默认不加载(使用SUMO的默认行为)
    load-last-state: 加载上次仿真保存的状态, 启用该项将使initial-state失效
    save-on-abort: 当仿真意外中断时, 保存仿真状态
    save-on-finish: 当仿真完成时, 保存仿真状态
以下参数用于图形化仿真:
    show: 启用该选项以GUI模式启动. 该选项仅在Linux下有用, 在Windows下请调整ftraffic/params.py的WINDOWS_VISSUALIZE来改变可见性级别
    no-daemon: 启用该选项以将仿真线程与显示窗口分离, 不启用时显示窗口一旦关闭, 仿真也会停止
    debug: 针对图形仿真启用调试模式, 图形仿真出错时会输出详细的错误信息
"""

    PARA_HELP_STR = """多进程并行仿真工具
用法: python {} [-p <最大并行任务数>] [-r <输出文件夹>] [-f <命令行文件>] [-c "<仿真参数命令行>"] [-n <仿真次数>] [-h/help]
    h/help: 显示此帮助
    p: 最大并行任务数, 默认为CPU核心数-1
    r: 输出文件夹, 默认为results_set
以下2组参数二选一:
组1:
    f: 从文件读取仿真参数, 该文件每行一个仿真参数命令行, 仿真参数命令行格式参照下方的-c参数
组2:
    c: 仿真参数命令行, 格式参照main.py的参数, 
        但必须省略一切-seed参数, (seed参数由并行仿真器自动分配)
        至少指定gen-veh参数, gen-fcs参数和gen-scs参数中的一个
    n: 仿真次数, 默认为50
    
范例参数:
    -p 7 -d 37nodes -r results_set -c "-gen-veh '-n 5000' -gen-fcs '-pbuy 1.5 -slots 10' -gen-scs '-pbuy 1.5 -slots 10'" -n 50
"""

    CONV_HELP_STR = """文件转换工具
用法: python {} -i <输入文件> -o <输出文件> [-t <数据类型>] [-h/help]
    h/help: 显示此帮助
    i: 输入文件, 可以是CSV、SDT或SDT.GZ文件
    o: 输出文件, 可以是CSV、SDT或SDT.GZ文件
    t: 输入文件的数据类型, 可选int32或float32, 默认为float32, 该选项只对CSV文件有效
"""

    CONV_INFO = "转换{0}到{1}..."

    ERROR_GENERAL = "错误: {}"
    ERROR_BAD_TYPE = "错误: 无效的数据类型{}."
    ERROR_ILLEGAL_CMD = "错误: 非法的命令行参数'{}'."
    ERROR_CANNOT_USE_TOGETHER = "错误: 选项'{0}'和'{1}'不能同时使用."
    ERROR_UNKNOWN_CS_TYPE = "错误: 未知的充电站类型{}"
    ERROR_CMD_NOT_SPECIFIED = "错误: 必须指定参数'{}'."
    ERROR_SUMO_CONFIG_NOT_SPECIFIED = "错误: 未指定SUMO配置文件."
    ERROR_SUMO_N_VEH_NOT_SPECIFIED = "错误: 未指定车辆数."
    ERROR_FAIL_TO_OPEN = "错误: 无法打开文件{0}: {1}"
    ERROR_NET_FILE_NOT_SPECIFIED = "错误: 未指定路网文件."
    ERROR_TRIPS_FILE_NOT_FOUND = "错误: 未找到EV和行程文件."
    ERROR_FCS_FILE_NOT_FOUND = "错误: 未找到快充站文件."
    ERROR_SCS_FILE_NOT_FOUND = "错误: 未找到慢充站文件."
    ERROR_STATE_FILE_NOT_FOUND = "错误: 状态文件未找到, {0}."
    ERROR_ST_ED_TIME_NOT_SPECIFIED = "错误: 仿真起止时间未指定."
    ERROR_CLIENT_ID_NOT_SPECIFIED = "错误: 未指定客户端ID."
    ERROR_CONFIG_DIR_FILE_DUPLICATE = "错误: 配置文件夹中{0}有重复: {1}和{2}"
    ERROR_PLUGIN_INTERVAL = "错误: 未指定或非法的插件运行间隔"
    ERROR_STA_UNIDENTICAL_DATA_LEN_AND_HEAD = "错误: {0}的数据长度{1}与表头长度{2}不一致"
    ERROR_STA_REGISTERED = "错误: 统计项{0}已经注册过."
    ERROR_STA_ADDED = "错误: 统计项{0}已经添加过."
    ERROR_STA_LOG_ITEM = "错误: 记录项{0}时发生错误: {1}."
    ERROR_STA_CLOSE_ITEM = "错误: 关闭项{0}时发生错误: {1}."
    ERROR_STA_TIMELINE_NOT_FOUND = "错误: 未找到时间线文件."
    ERROR_FILE_EXISTS = "错误: 文件已存在: {}"
    ERROR_NUMBER_NOT_SPECIFIED = "错误: 当选择随机时必须指定n"
    ERROR_FILE_TYPE_NOT_SUPPORTED = "错误: 不支持的XML文件{}类型"
    ERROR_NO_TAZ_OR_POLY = "错误: 未找到TAZ或POLY文件"
    ERROR_RANDOM_CANNOT_EXCLUDE = "错误: 序列抽样中的所有元素都被排除"
    ERROR_ROUTE_NOT_FOUND = "错误: 无法找到从{0}到{1}的路径"

    WARN_EXT_LOAD_FAILED = "警告: {0}是Python文件, 但无法作为包加载: {1}"
    WARN_EXT_INVALID_PLUGIN = "警告: {0}的plugin_exports无效, 无法作为插件导入: {1}"
    WARN_EXT_INVALID_STA = "警告: {0}的sta_exports无效, 无法作为统计项导入: {1}"
    WARN_MAIN_SHOW_MEANINGLESS = "警告: show选项在Windows下没有意义, 请在ftraffic/params.py中调整WINDOWS_VISSUALIZE来改变可见性级别."
    WARN_MAIN_DEBUG_MEANINGLESS = "警告: debug选项在命令行模式下没有意义, 将自动关闭."
    WARN_MAIN_GUI_NOT_FOUND = "警告: 未找到GUI模块, 请检查是否安装了tkinter库. 将切换到命令行模式."
    WARN_SIM_COMM_FAILED = "警告: 与主进程通信失败."
    WARN_CS_NOT_IN_SCC = "警告: 快充站{}不在最大的强连通分量中."
    WARN_SCC_TOO_SMALL = "警告: 最大的强连通分量太小, 只有{0}/{1}条边在内."

    INFO_DONE_WITH_DURATION = "已完成. 用时: {}."
    INFO_DONE_WITH_SECOND = "已完成. 用时{:.1f}秒."
    INFO_SUMO = "  SUMO: {}"
    INFO_NET = "  路网: {}"
    INFO_TRIPS = "  行程: {0}, {1}辆EV"
    INFO_FCS = "  快充: {0}, {1}个站点"
    INFO_SCS = "  慢充: {0}, {1}个站点"
    INFO_TIME = "  起止时间: {0} ~ {1}, 步长：{2}"
    INFO_PLG = "  插件: {0} - {1}"
    INFO_REGEN_SCS = "慢充站已重新生成."
    INFO_REGEN_FCS = "快充站已重新生成."
    INFO_REGEN_VEH = "EV和行程已重新生成."

    CORE_NO_RUN = "这是仿真系统的核心模块。不要直接运行此文件。请改用sim_single.py或sim_para.py。"

    MAIN_LS_TITLE_PLG = "=== 插件 ==="
    MAIN_LS_TITLE_STA = "=== 统计项 ==="
    MAIN_SIM_START = "仿真开始, 按Ctrl-C中断"
    MAIN_SIGINT = "收到Ctrl-C退出信号, 提前退出"
    MAIN_SIM_DONE = "仿真结束. 用时: {}"
    MAIN_SIM_PROG = "进度: {0:.2f}%, {1}/{2}. 已用时: {3}, 预计剩余时间: {4}"

    PARA_SIM_SKIP_LIST = "跳过: {}"
    PARA_SIM_DONE_PARA = "并行部分完成. 用时: {}"
    PARA_SIM_START_SERIAL = "执行非并行任务..."
    PARA_SIM_DONE_SERIAL = "串行部分完成. 用时: {}"
    PARA_SIM_PROG = "进度: {0:.2f}%, {1}已用时: {2}, 预计剩余时间: {3}"

    PLOT_GRP_EMPTY_SEC_LIST = "秒列表为空"
    PLOT_GRP_START_TIME_EXCEED = "MinAvgGrouper的起始时间({0})超过了数据记录的时间{1}"
    PLOT_GRP_X_LABEL = "第{0}天 {1:02}:{2:02}"
    PLOT_GRP_DATA_UNMATCH = "时间轴长度{}和数据数量{}不匹配"

    CSLIST_INVALID_ELEMENT = "csList中的元素必须是FCS或SCS"
    CSLIST_MIXED_ELEMENT = "CSList禁止同时存在FCS和SCS元素, 将ALLOW_MIXED_CSTYPE_IN_CSLIST设为True以移除此限制"
    CSLIST_INVALID_TAG = "用xml文件初始化CSList时, 遇到无效的tag{}"
    CSLIST_PBUY_NOT_SPECIFIED = "用xml文件初始化CSList时, 未指定购电价格"
    CSLIST_INVALID_INIT_PARAM = "无效的CSList初始化参数类型"
    CSLIST_KDTREE_DISABLED = "    由于存在无效充电站位置，KD树已禁用，将不能使用select_near功能"

    CPROC_ARRIVE = "到达"
    CPROC_ARRIVE_CS = "充电"
    CPROC_DEPART = "出发"
    CPROC_DEPART_DELAY = "延误"
    CPROC_DEPART_CS = "充完"
    CPROC_DEPART_FAILED = "故障"
    CPROC_FAULT_DEPLETE = "耗尽"
    CPROC_WARN_SMALLCAP = "警告"

    CPROC_INFO_ARRIVE = "车辆{0}已到达{1}, {2}, 下一行程: {3}"
    CPROC_INFO_ARRIVE_0 = "不充电"
    CPROC_INFO_ARRIVE_1 = "开始慢充"
    CPROC_INFO_ARRIVE_2 = "无可用慢充桩, 充电失败"
    CPROC_INFO_ARRIVE_CS = "车辆{0}到达{1}, 排队充电."
    CPROC_INFO_DEPART = "车辆{0}出发, 行程{1}."
    CPROC_INFO_DEPART_WITH_DELAY = " 延迟{0}秒."
    CPROC_INFO_DEPART_WITH_CS = " 将在{0}充电, 参数 = {1}."
    CPROC_INFO_DEPART_DELAY = "车辆{0}未能出发, 因为现有电量{1}, 而需要电量{2}. 延迟{3}秒再试."
    CPROC_INFO_DEPART_CS = "车辆{0}在{1}充完电, 继续前往{2}."
    CPROC_INFO_DEPART_FAILED = "车辆{0}由于电量不足无法发车. 需要{1}但只有{2}. 将会在{4}秒后传送到{3}."
    CPROC_INFO_FAULT_DEPLETE = "车辆{0}电量耗尽. 将会在{2}秒后传送到{1}."
    CPROC_INFO_WARN_SMALLCAP = "车辆{0}的电池容量为{1}, 少于完成行程的需求{2}. 将在行程中耗尽电量."

    PLG_REGISTERED = "插件{}已注册."
    PLG_DEPS_MUST_BE_STRLIST = "插件依赖必须是字符串列表."
    PLG_NOT_SUBCLASS = "插件{}不是PluginBase的子类."
    PLG_DEPS_NOT_REGISTERED = "插件{0}依赖的插件{1}尚未注册."
    PLG_INTERVAL_NOT_SPECIFIED = "插件{0}未指定或非法的运行间隔."
    PLG_NOT_EXIST = "文件{}不存在. 跳过插件加载."
    PLG_NOT_EXIST_OR_BAD = "文件{}不存在或无法导入."
    PLG_INVALID_PLUGIN = "无效插件{}"
    PLG_DEPS_NOT_LOADED = "插件{0}依赖的插件{1}尚未加载."
    PLG_ALREADY_EXISTS = "插件{}已经存在于插件列表."

    PLOT_CMD_HELP = '''
绘图程序 - 使用方法
{} [-h] [--help] [-d <仿真结果文件夹>] [-t <开始时间>] 
[--trips <trip_file> [--trips-num <行程编号>]]
[--load-accum [--show-peak] [--peak-range <peak_range>] [--no-stackplot]]
[--cs-curve [<充电站名称>] [--show-waitcount] [--show-chargeload] [--show-dischargeload] [--show-netchargeload] [--show-v2gcap]]
[--cs-price [<充电站名称>] [--show-pbuy] [--show-psell]]
[--ev-attrib <电动汽车ID> --ev-attrib-list <要绘制的属性>] [--ev-route <电动汽车ID>]
[--gen-compare] [--gen-total] [--gen-curve [<发电机名称>]]
[--bus-curve <母线名称>] [--bus-total]
    h/help: 显示此帮助
    d: 仿真结果文件夹，默认是"results"
    t: 绘图开始时间，默认是86400
    trips: 绘制行程直方图
        trips-num: 指定要绘制的行程编号
    load-accum: 绘制累计充电负荷
        show-peak: 显示峰值
        peak-range: 峰值范围，例如0.85
        no-stackplot: 禁用堆积图（采用曲线图）
    cs-curve: 绘制充电站曲线，充电站应给出为逗号分隔的字符串列表，如果不给出，则绘制所有CS
        hide-waitcount: 隐藏等待数
        hide-chargeload: 隐藏充电负荷
        hide-dischargeload: 隐藏放电负荷
        hide-netchargeload: 隐藏净充电负荷
        hide-v2gcap: 隐藏V2G容量
    cs-price: 绘制充电站价格，充电站应给出为逗号分隔的字符串列表，如果不给出，则绘制所有CS
        hide-pbuy: 隐藏购电价格
        hide-psell: 隐藏售电价格
    ev-attrib: 绘制电动汽车属性，电动汽车应给出为逗号分隔的字符串列表
        ev-attrib-list: 要绘制的属性列表，例如"cost,earn"
    ev-route: 绘制电动汽车路径，电动汽车应给出为逗号分隔的字符串列表
    gen-compare: 绘制发电机比较
    gen-total: 绘制发电机总参数
    gen-curve: 绘制发电机曲线，发电机应给出为逗号分隔的字符串列表
    bus-curve: 绘制母线曲线，母线应给出为逗号分隔的字符串列表
    bus-total: 绘制母线总参数
'''

    PLOT_FONT = "SimHei"
    PLOT_FONT_SIZE_SMALL = "13"
    PLOT_FONT_SIZE_MEDIUM = "15"
    PLOT_FONT_SIZE_LARGE = "18"
    PLOT_STR_ALL = "全部"
    PLOT_STR_FAST = "快"
    PLOT_STR_SLOW = "慢"
    PLOT_NOT_SUPPORTED = "既有数据不支持绘制{}的图形"

    ADV_PLOT_HELP = '''命令:
    plot <series_name> [<label> <color> <linestyle> <side>]: 绘制一个数据序列
    title <title>: 设置标题
    xlabel <label>: 设置x轴标签
    yleftlabel/ylabel <label>: 设置左y轴标签
    yrightlabel <label>: 设置右y轴标签
    yticks <ticks> [<labels>]: 设置y轴刻度
    legend <loc>: 显示图例
    save <path>: 保存图像到指定路径
    exit: 退出绘图程序
示例:
    plot "results:cs_load:CS1" "CS1 Load" "blue" "-" "left"
    plot "results:cs_load:CS2" "CS2 Load" "red" "--" "left"
    title "CS1 & CS2 Load"
    xlabel "Time"
    yleftlabel "Load/kWh"
    legend
    save "test.png"
序列名称的格式为"<results>:<attribute>:<instances>:<starting_time>", 其中
    "results"是结果文件夹名,
    "attribute"是要绘制的属性, 可选["cs_load", "cs_wait_count", "cs_net_load", 
        "cs_price_buy", "cs_price_sell", "cs_discahrge_load", "cs_v2g_cap", "ev_soc", "ev_cost", 
        "ev_status", "ev_cpure", "ev_earn", "gen_active", "gen_reactive", "gen_costp", "bus_active_gen", 
        "bus_reactive_gen", "bus_active_load", "bus_reactive_load", "bus_shadow_price"],
    "instances"是实例名称，例如
        充电站(CS): "CS1", "CS2", "<all>", "<fast>", "<slow>"
        电动汽车(EV): "v1", "v2"
        发电机: "G1", "G2"
        母线: "B1", "B2"
        etc.,
    "starting_time"是绘图的起始时间, 默认为0, 该项可以省略
你可以从文件中读取命令。通过将文件名作为命令行参数传递给程序来实现。
'''

    PLOT_EV = "电动汽车: {0}"
    PLOT_FCS_ACC_TITLE = "快充站: 总负荷"
    PLOT_SCS_ACC_TITLE = "慢充站: 总负荷"
    PLOT_YLABEL_POWERKW = "功率(kW)"
    PLOT_YLABEL_POWERMW = "功率(MW或Mvar)"
    PLOT_YLABEL_VOLTKV = "电压(kV)"
    PLOT_YLABEL_CURRENT = "电流(kA)"
    PLOT_YLABEL_COST = "钱($)"
    PLOT_YLABEL_COUNT = "数量"
    PLOT_YLABEL_SOC = "荷电状态(%)"
    PLOT_YLABEL_STATUS = "车辆状态"
    PLOT_YLABEL_PRICE = "价格($/kWh)"
    PLOT_XLABEL_TIME = "时间"
    PLOT_FCS_TITLE = "快充站: {0}"
    PLOT_SCS_TITLE = "慢充站: {0}"
    PLOT_BUS_TOTAL = "总母线负荷"
    PLOT_GEN_TOTAL = "总发电机"
    PLOT_LINE = "线路: {0}"
    PLOT_GEN = "发电机: {0}"
    PLOT_BUS = "母线: {0}"
