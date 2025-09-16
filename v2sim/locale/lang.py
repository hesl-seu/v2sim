import copy
import importlib, locale
from pathlib import Path
from typing import List, Union

class Lang:
    LANG_CODE = "en"
    
    TRIPGEN_HELP_STR = "Read https://github.com/fmy-xfk/v2sim/wiki/gen_trip to see the usage."
    CSGEN_HELP_STR = "Read https://github.com/fmy-xfk/v2sim/wiki/gen_cs to see the usage."
    MAIN_HELP_STR = "Read https://github.com/fmy-xfk/v2sim/wiki/sim_single to see the usage."
    PARA_HELP_STR = "Read https://github.com/fmy-xfk/v2sim/wiki/sim_para to see the usage."
    
    ERROR_GENERAL = "Error: {}"
    ERROR_BAD_TYPE = "Error: Invalid data type '{}'."
    ERROR_NO_SUPPORTED_LANG = "Error: No supported language found."
    ERROR_UNSUPPORTED_LANG = "Error: Unsupported language '{}'."
    ERROR_ILLEGAL_CMD = "Error: Illegal command line parameter :{}."
    ERROR_CANNOT_USE_TOGETHER = "Error: Options '{0}' and '{1}' cannot be used together."
    ERROR_UNKNOWN_CS_TYPE = "Error: Unknown charging station (CS) type '{}'"
    ERROR_CMD_NOT_SPECIFIED = "Error: Option '{}' must be specified."
    ERROR_SUMO_CONFIG_NOT_SPECIFIED = "Error: SUMO configuration file not specified."
    ERROR_SUMO_N_VEH_NOT_SPECIFIED = "Error: Number of vehicles not specified."
    ERROR_FAIL_TO_OPEN = "Error: Failed to open file {0}: {1}"
    ERROR_NET_FILE_NOT_SPECIFIED = "Error: Road network file not specified."
    ERROR_TRIPS_FILE_NOT_FOUND = "Error: EV & Trips file not found."
    ERROR_FCS_FILE_NOT_FOUND = "Error: Fast charging station file not found."
    ERROR_SCS_FILE_NOT_FOUND = "Error: Slow charging station file not found."
    ERROR_STATE_FILE_NOT_FOUND = "Error: State file not found, {0}"
    ERROR_ST_ED_TIME_NOT_SPECIFIED = "Error: Start and end time not specified."
    ERROR_CLIENT_ID_NOT_SPECIFIED = "Error: Client ID not specified."
    ERROR_CONFIG_DIR_FILE_DUPLICATE = "Error: Duplicate item '{0}' in configuration directory: {1} and {2}"
    ERROR_PLUGIN_INTERVAL = "Error: Plugin interval not specified or invalid."
    ERROR_STA_UNIDENTICAL_DATA_LEN_AND_HEAD = "Error: Data length {1} of {0} is not identical to header length {2}"
    ERROR_STA_REGISTERED = "Error: Statistic item {0} is already registered."
    ERROR_STA_ADDED = "Error: Statistic item {0} is already added."
    ERROR_STA_LOG_ITEM = "Error: An error occurred when logging item {0}: {1}."
    ERROR_STA_CLOSE_ITEM = "Error: An error occurred when closing item {0}: {1}."
    ERROR_STA_TIMELINE_NOT_FOUND = "Error: Time line file not found."
    ERROR_FILE_EXISTS = "Error: File already exists: {}"
    ERROR_NUMBER_NOT_SPECIFIED = "Error: n must be specified when selecting randomly"
    ERROR_FILE_TYPE_NOT_SUPPORTED = "Error: XML File {} type not supported."
    ERROR_NO_TAZ_OR_POLY = "Error: No TAZ or polygon file found. If you want use poly mode, you have to specify a fcs file in addition."
    ERROR_RANDOM_CANNOT_EXCLUDE = "Error: No element in the sequence is different from the excluded value"
    ERROR_ROUTE_NOT_FOUND = "Error: Unable to find a path from {0} to {1}"
    ERROR_INVALID_CACHE_ROUTE = "Error: Invalid cache route: {0}"
    ERROR_INVALID_TRIP_GEN_MODE = "Error: Invalid trip generation mode: {0}"

    WARN_EXT_LOAD_FAILED = "Warning: {0} is a Python file, but cannot be loaded as a package: {1}"
    WARN_EXT_INVALID_PLUGIN = "Warning: {0}'s plugin_exports is invalid, cannot be imported as a plugin: {1}"
    WARN_EXT_INVALID_STA = "Warning: {0}'s sta_exports is invalid, cannot be imported as a statistic item: {1}"
    WARN_MAIN_SHOW_MEANINGLESS = "Warning: 'show' option is meaningless in Windows, please adjust WINDOWS_VISUALIZE in v2sim/traffic/win_vis.py to change visibility level"
    WARN_MAIN_DEBUG_MEANINGLESS = "Warning: 'debug' option is meaningless in command line mode, will be turned off automatically."
    WARN_MAIN_GUI_NOT_FOUND = "Warning: GUI module not found, please check if tkinter library is installed. Will switch to command line mode."
    WARN_SIM_COMM_FAILED = "Warning: Failed to communicate with simulation process."
    WARN_CS_NOT_IN_SCC = "Warning: some CS {} are not in the largest SCC"
    WARN_SCC_TOO_SMALL = "Warning: the largest SCC is too small, only {0} of {1} edges are included"

    INFO_DONE_WITH_DURATION = "Done. Duration: {}."
    INFO_DONE_WITH_SECOND = "Done. Duration: {:.1f} second(s)."
    INFO_SUMO = "  SUMO: {}"
    INFO_NET = "  Road Network: {}"
    INFO_TRIPS = "  EV & Trips: {0}, Number = {1}"
    INFO_FCS = "  Fast Charging Station: {0}, Number = {1}"
    INFO_SCS = "  Slow Charging Station: {0}, Number = {1}"
    INFO_TIME = "  Start & End Time: {0} ~ {1}, Step Length = {2}"
    INFO_PLG = "  Plugin: {0} - {1}"
    INFO_REGEN_SCS = "Slow charging stations regenerated."
    INFO_REGEN_FCS = "Fast charging stations regenerated."
    INFO_REGEN_VEH = "EVs & trips regenerated."

    CORE_NO_RUN = "This is the core module of the simulation system. Do not run this file directly. Use sim_single.py or sim_para.py instead."

    MAIN_LS_TITLE_PLG = "=== Plugins ==="
    MAIN_LS_TITLE_STA = "=== Statistic Items ==="
    MAIN_SIM_START = "Simulation started. Press Ctrl-C to stop."
    MAIN_SIGINT = "Received Ctrl-C signal, exiting prematurely."
    MAIN_SIM_DONE = "Simulation done. Duration: {}"
    MAIN_SIM_PROG = "Progress: {0:.2f}%, {1}/{2}. Elapsed: {3}, ETA: {4}"

    PARA_SIM_SKIP_LIST = "Skip list: {}"
    PARA_SIM_DONE_PARA = "Parallel part done. Duration: {}"
    PARA_SIM_START_SERIAL = "Execute non-parallel tasks..."
    PARA_SIM_DONE_SERIAL = "Serial part done. Duration: {}"
    PARA_SIM_PROG = "Progress: {0:.2f}%, {1}Elapsed: {2}, ETA: {3}"

    PLOT_GRP_EMPTY_SEC_LIST = "Empty second list."
    PLOT_GRP_START_TIME_EXCEED = "Start time {0} of MinAvgGrouper exceeds the last second {1} in the second list."
    PLOT_GRP_X_LABEL = "Day {0} {1:02}:{2:02}"
    PLOT_GRP_DATA_UNMATCH = "Time line length {} does not match data length {}."

    CSLIST_INVALID_ELEMENT = "Elements in csList must be FCS or SCS"
    CSLIST_MIXED_ELEMENT = "Elements in csList must be all FCS or all SCS. Set 'ALLOW_MIXED_CSTYPE_IN_CSLIST' to 'True' to remove this restriction."
    CSLIST_INVALID_TAG = "Invalid tag {} when initializing CSList with xml file."
    CSLIST_PBUY_NOT_SPECIFIED = "Purchase price not specified when initializing CSList with xml file."
    CSLIST_INVALID_INIT_PARAM = "Invalid initialization parameter type for CSList."
    CSLIST_KDTREE_DISABLED = "    KDTree is disabled due to invalid CS position. Cannot find nearest CS."

    CPROC_ARRIVE = "Arrival"
    CPROC_ARRIVE_CS = "Fast Charging Start"
    CPROC_DEPART = "Departure"
    CPROC_DEPART_DELAY = "Departure Delayed"
    CPROC_DEPART_CS = "Fast Charging Done"
    CPROC_DEPART_FAILED = "Departure Failed"
    CPROC_FAULT_DEPLETE = "Depletion"
    CPROC_FAULT_NOCHARGE = "No FCS available"
    CPROC_FAULT_REDIRECT = "Redirect"
    CPROC_WARN_SMALLCAP = "Warning"
    CPROC_JOIN_SCS = "Join Slow Charging Station"
    CPROC_LEAVE_SCS = "Leave Slow Charging Station"

    CPROC_INFO_ARRIVE = "Vehicle {0} arrived at {1}. {2}. Next trip: {3}"
    CPROC_INFO_ARRIVE_0 = "No charging"
    CPROC_INFO_ARRIVE_1 = "Start slow charging"
    CPROC_INFO_ARRIVE_2 = "No available slow charging station, charging failed"
    CPROC_INFO_ARRIVE_CS = "Vehicle {0} arrive at {1}. Queue to charge."
    CPROC_INFO_DEPART = "Vehicle {0} depart from {1}."
    CPROC_INFO_DEPART_WITH_DELAY = " With a delay of {0} second(s)."
    CPROC_INFO_DEPART_WITH_CS = " Will charge at {0}, params = {1}."
    CPROC_INFO_DEPART_DELAY = "Vehicle {0} currently has a battery level of {1}, failing the requirements of battery level {2}. Wait {3} seocnd(s) to retry."
    CPROC_INFO_DEPART_CS = "Vehicle {0} finished charging at {1}, continuing the trip to {2}."
    CPROC_INFO_DEPART_FAILED = "Vehicle {0} failed to depart due to insufficient battery level. Required: {1}, Current: {2}. Will be teleported to {3} after {4} second(s)."
    CPROC_INFO_FAULT_DEPLETE = "Vehicle {0} depleted. Will be teleported to {1} after {2} seconds."
    CPROC_INFO_FAULT_NOCHARGE = "Vehicle {0} has no charge. Will be teleported to {1}."
    CPROC_INFO_FAULT_REDIRECT = "Vehicle {0} cannot charge at {1} due to insufficient battery level. Redirecting to {2}."
    CPROC_INFO_WARN_SMALLCAP = "Vehicle {0} has a battery capacity of {1}, which is less than the required {2}. Will cause a depletion during the trip."
    CPROC_INFO_JOIN_SCS = "Vehicle {0} joined slow charging station at {1}."
    CPROC_INFO_LEAVE_SCS = "Vehicle {0} left slow charging station at {1}."

    PLG_REGISTERED = "Plugin '{}' has already been registered."
    PLG_DEPS_MUST_BE_STRLIST = "Dependencies must be a list of strings."
    PLG_NOT_SUBCLASS = "Plugin '{}' is not a subclass of PluginBase."
    PLG_DEPS_NOT_REGISTERED = "Plugin '{0}' depends on plugin '{1}', which has not been registered."
    PLG_INTERVAL_NOT_SPECIFIED = "Plugin {}'s interval is not specified."
    PLG_NOT_EXIST = "File {} does not exist. Skip loading plugins."
    PLG_NOT_EXIST_OR_BAD = "File {} does not exist or has been corrupted."
    PLG_INVALID_PLUGIN = "Invalid plugin '{}'."
    PLG_DEPS_NOT_LOADED = "Plugin '{0}' depends on plugin '{1}', which has not been loaded."
    PLG_ALREADY_EXISTS = "Plugin '{}' already exists."

    PLOT_CMD_HELP = '''Plotting program - Usage
{} [-h] [--help] [-d <simulation_result_directory>] [-t <plot_start_time>] 
[--trips <trip_file> [--trips-num <nums_to_draw>]]
[--load-accum [--show-peak] [--peak-range <peak_range>] [--no-stackplot]]
[--cs-curve [<cs_names>] [--show-waitcount] [--show-chargeload] [--show-dischargeload] [--show-netchargeload] [--show-v2gcap]]
[--cs-price [<cs_names>] [--show-pbuy] [--show-psell]]
[--ev-attrib <ev_ids> --ev-attrib-list <attributes_to_draw>] [--ev-route <ev_ids>]
[--gen-compare] [--gen-total] [--gen-curve [<generator_names>]]
[--bus-curve <bus_names>] [--bus-total]
    h/help: Display this help.
    d: Simulation result directory. 'results' by default.
    t: Plot start time. 86400 by default.
    trips: Plot the histogram of given trip file.
        trips-num: Which trips to be draw, should be a comma separated integer list
    load-accum: Plot accumulation of EVCL.
        show-peak: Show peak value.
        peak-range: Peak range.
        no-stackplot: Do not use stackplot.
    cs-curve: Plot CS curve. CS to be drawn should be given as a comma separated string list. If not given, all CS will be drawn.
        hide-waitcount: Hide waiting count.
        hide-chargeload: Hide charge load.
        hide-dischargeload: Hide discharge load.
        hide-netchargeload: Hide net charge load.
        hide-v2gcap: Hide V2G capacity.
    cs-price: Plot CS price. CS to be drawn should be given as a comma separated string list. If not given, all CS will be drawn.
        hide-pbuy: Hide purchase price.
        hide-psell: Hide selling price.
    ev-attrib: Plot EV attributes. EVs to be drawn should be given as a comma separated string list.
        ev-attrib-list: Attributes list to be drawn must be given. Should be a comma separated string list.
    ev-route: Plot EV route. EVs to be drawn should be given as a comma separated string list.
    gen-compare: Plot generator comparison.
    gen-total: Plot total power generation.
    gen-curve: Plot generator curve. Generators to be drawn should be given as a comma separated string list.
    bus-curve: Plot bus curve. Buses to be drawn should be given as a comma separated string list.
    bus-total: Plot total bus parameters.
'''
    
    PLOT_FONT = "Arial"
    PLOT_FONT_SIZE_SMALL = "12"
    PLOT_FONT_SIZE_MEDIUM = "14"
    PLOT_FONT_SIZE_LARGE = "18"
    PLOT_STR_ALL = "All"
    PLOT_STR_FAST = "Fast"
    PLOT_STR_SLOW = "Slow"
    PLOT_NOT_SUPPORTED = "The existing data does not support drawing the graph of {}"

    ADV_PLOT_HELP = '''Commands:
    plot <series_name> [<label> <color> <linestyle> <side>]: Add a series to the plot
    title <title>: Set the title of the plot
    xlabel <label>: Set the x-axis label
    yleftlabel/ylabel <label>: Set the left y-axis label
    yrightlabel <label>: Set the right y-axis label
    yticks <ticks> [<labels>]: Set the y-axis ticks and labels
    legend <loc>: Set the legend location
    save <path>: Save the plot to the path
    exit: Exit the configuration
Example:
    plot "results:cs_load:CS1" "CS1 Load" "blue" "-" "left"
    plot "results:cs_load:CS2" "CS2 Load" "red" "--" "left"
    title "CS1 & CS2 Load"
    xlabel "Time"
    yleftlabel "Load/kWh"
    legend
    save "test.png"
The series name should be in the format of "<results>:<attribute>:<instances>:<starting_time>", where
    "results" is the result folder, 
    "attribute" is the attribute to be plotted,
    "instances" is the instance name, such as 
        "CS1", "CS2", "<all>", "<fast>", "<slow>" for CS,
        "v1", "v2" for EV,
        "G1", "G2" for generator,
        "B1", "B2" for bus, 
        etc.,
    "starting_time" is the starting time of the series. "0" by default. This is optional.
You can load the commands from a file as an argument in the command prompt/terminal.
'''
    ADV_PLOT_NO_SERIES = "Series not provided"
    ADV_PLOT_NO_XLABEL = "X-axis label not provided"
    ADV_PLOT_NO_YLABEL = "Y-axis label not provided"
    ADV_PLOT_NO_TITLE = "Title not provided"
    ADV_PLOT_BAD_COMMAND = "Bad command: {}"

    PLOT_EV = "Electric Vehicle: {0}"
    PLOT_FCS_ACC_TITLE = "Fast Charging Station: Total Load"
    PLOT_SCS_ACC_TITLE = "Slow Charging Station: Total Load"
    PLOT_YLABEL_POWERKW = "Power (kW)"
    PLOT_YLABEL_POWERMW = "Power (MW or Mvar)"
    PLOT_YLABEL_COST = "Money ($)"
    PLOT_YLABEL_VOLTKV = "Voltage (kV)"
    PLOT_YLABEL_CURRENT = "Current (kA)"
    PLOT_YLABEL_COUNT = "Count"
    PLOT_YLABEL_SOC = "SoC"
    PLOT_YLABEL_CURTAIL = "Curtailment (%)"
    PLOT_YLABEL_STATUS = "Vehicle Status"
    PLOT_YLABEL_PRICE = "Price ($/kWh)"
    PLOT_XLABEL_TIME = "Time"
    PLOT_FCS_TITLE = "Fast Charging Station: {0}"
    PLOT_SCS_TITLE = "Slow Charging Station: {0}"
    PLOT_BUS_TOTAL = "Total Bus Load"
    PLOT_GEN_TOTAL = "Total Generator"
    PLOT_LINE = "Line: {0}"
    PLOT_GEN = "Generator: {0}"
    PLOT_BUS = "Bus: {0}"
    PLOT_PVW = "PV or Wind Turbine: {0}"
    PLOT_ESS = "ESS: {0}"

    @staticmethod
    def format(item:str, **kwargs):
        fmt = getattr(Lang, item)
        assert isinstance(fmt, str), f"Invalid item {item}"
        return fmt.format(**kwargs)

    @staticmethod
    def load(lang:str)->bool:
        if lang == "en":
            lc = en_Lang
        else:
            try:
                m = importlib.import_module(f"v2sim.locale.{lang}")
            except ImportError:
                return False
            if not hasattr(m, "_locale"): raise ValueError(f"Invalid language {lang}")
            lc = m._locale
        Lang.LANG_CODE = lang
        for key,val in lc.__dict__.items():
            assert isinstance(key,str)
            if key.startswith("__") and key.endswith("__"): continue
            if isinstance(val, str):
                if hasattr(Lang, key):
                    setattr(Lang, key, val)
                else:
                    print(f"Unknown key {key}")
        return True
    
    @staticmethod
    def get_lang_code():
        return Lang.LANG_CODE
    
    @staticmethod
    def save_lang_code(auto:bool = False):
        langf = Path(__file__).parent / "lang.txt"
        with langf.open("w") as f:
            if auto:
                f.write("<auto>")
            else:
                f.write(Lang.LANG_CODE)
    
    @staticmethod
    def load_default():
        langf = Path(__file__).parent / "lang.txt"
        if langf.exists():
            with langf.open("r") as f:
                locale_code = f.read().strip()
        else:
            with langf.open("w") as f:
                f.write("<auto>")
            locale_code = "<auto>"
        if locale_code == "<auto>":
            locale_code = str(locale.getdefaultlocale()[0])
        if "en" in locale_code:
            return
        if Lang.load(locale_code):
            return
        Lang.load(locale_code.split("_")[0])
        

class CustomLocaleLib:
    def __init__(self, supports_lang: List[str], default_lang:str=Lang.get_lang_code()):
        self.__supports = supports_lang
        assert len(supports_lang) > 0, Lang.ERROR_NO_SUPPORTED_LANG
        if default_lang not in supports_lang:
            self.__default = supports_lang[0]
        else:
            self.__default = default_lang
        self.__lib = {lang: {} for lang in supports_lang}
    
    @staticmethod
    def LoadFromFolder(folder:Union[str, Path]):
        p = folder if isinstance(folder, Path) else Path(folder)
        if not p.exists():
            raise FileNotFoundError(f"Folder {folder} not found.")
        if not p.is_dir():
            raise NotADirectoryError(f"{folder} is not a directory.")
        langs = []
        for pc in p.iterdir():
            if pc.is_file() and pc.suffix == ".lang":
                langs.append(pc.stem)
        lib = CustomLocaleLib(langs)
        for lang in langs:
            lib.LoadLanguageLib(lang, str(p / f"{lang}.lang"))
        return lib
    
    @property
    def SupportedLanguage(self):
        return self.__supports
    
    @property
    def DefaultLanguage(self):
        return self.__default
    @DefaultLanguage.setter
    def DefaultLanguage(self, lang:str):
        if lang == "<auto>":
            lang = str(locale.getdefaultlocale()[0])
        elif lang not in self.__supports:
            raise ValueError(Lang.ERROR_UNSUPPORTED_LANG.format(lang))
        Lang.load(lang)
        self.__default = lang
    
    def SetLanguageLib(self, lang:str, **kwargs):
        self.__lib[lang].clear()
        for key,val in kwargs.items():
            self.__lib[lang][key] = val
    
    def LoadLanguageLib(self, lang:str, path:str):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                key,val = line.split("=", 1)
                self.__lib[lang][key.strip()] = val.replace("\\n", "\n")
    
    def __setitem__(self, key, value):
        assert isinstance(key, tuple)
        assert len(key) == 2
        assert isinstance(key[0], str)
        assert isinstance(key[1], str)
        self.__lib[key[0]][key[1]] = value
    
    def __getitem__(self, key) -> str:
        assert isinstance(key, str)
        try:
            return self.__lib[Lang.get_lang_code()][key]
        except KeyError:
            return key
    
    def __call__(self, key) -> str:
        assert isinstance(key, str)
        try:
            return self.__lib[Lang.get_lang_code()][key]
        except KeyError:
            return key

en_Lang = copy.deepcopy(Lang)
Lang.load_default()