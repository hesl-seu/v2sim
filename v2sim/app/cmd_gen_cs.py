import sys
from feasytools import ArgChecker
from v2sim import Lang
from v2sim.gen import TrafficGenerator


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
    
    TrafficGenerator(root).StationFromArgs(params)


if __name__ == "__main__":
    main()