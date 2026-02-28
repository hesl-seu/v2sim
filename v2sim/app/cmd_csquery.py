from feasytools import ArgChecker
from v2sim import Lang
from v2sim.gen import StationQuery, AMAP_KEY_FILE


def main():
    args = ArgChecker()
    root = args.pop_str("d")
    new_loc = args.pop_str("p", "")
    ak = args.pop_str("key", "")
    allyes = args.pop_bool("y")
    mode = args.pop_str("m")
    assert mode in ["cs", "gs"], f"Only 'cs' and 'gs' modes are supported, but got '{mode}'"

    if ak == "" and AMAP_KEY_FILE.exists():
        with open(AMAP_KEY_FILE, "r") as f:
            ak = f.read().strip()
    
    if ak == "":
        print(Lang.CSQUERY_KEY_REQUIRED)
        exit()
    
    StationQuery(root, new_loc, ak, allyes, mode) # type: ignore


if __name__ == '__main__':
    main()