import sys
from feasytools import ArgChecker
from v2sim import Lang
from v2sim.gen import TrafficGenerator, StationFilterConfig


def print_help(err:str = ""):
    if err != "":
        print(err)
    print(Lang.CSGEN_HELP_STR.format(sys.argv[0]))
    sys.exit()
    
    
def main():
    params = ArgChecker()
    if params.pop_bool("h") or params.pop_bool("help"):
        print_help()

    try:
        root = params.pop_str("d")
    except:
        print_help(Lang.ERROR_CMD_NOT_SPECIFIED.format("d"))
    
    silent = params.pop_bool("silent")
    if "name-case-sensitive" in params or "name-start-with" in params or "name-end-with" in params or "name-not-start-with" in params or "name-not-end-with" in params:
        name_case_sensitive = params.pop_bool("name-case-sensitive")
        name_start_with = params.pop_str("name-start-with", "")
        name_end_with = params.pop_str("name-end-with", "")
        name_not_start_with = params.pop_str("name-not-start-with", "")
        name_not_end_with = params.pop_str("name-not-end-with", "")
        filter_config = StationFilterConfig(
            case_sensitive=name_case_sensitive,
            start_with=name_start_with,
            end_with=name_end_with,
            not_start_with=name_not_start_with,
            not_end_with=name_not_end_with
        )
    else:
        filter_config = None
    TrafficGenerator(
        root, silent, 
        fcs_filter_config=filter_config, 
        scs_filter_config=filter_config, 
        gs_filter_config=filter_config
    ).StationFromArgs(params)


if __name__ == "__main__":
    main()