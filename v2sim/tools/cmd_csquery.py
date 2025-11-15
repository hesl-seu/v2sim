from feasytools import ArgChecker
from v2sim import csQuery, AMAP_KEY_FILE, Lang


def main():
    args = ArgChecker()
    root = args.pop_str("d")
    new_loc = args.pop_str("p", "")
    ak = args.pop_str("key", "")
    allyes = args.pop_bool("y")

    if ak == "" and AMAP_KEY_FILE.exists():
        with open(AMAP_KEY_FILE, "r") as f:
            ak = f.read().strip()
    
    if ak == "":
        print(Lang.CSQUERY_KEY_REQUIRED)
        exit()
    
    csQuery(root, new_loc, ak, allyes)


if __name__ == '__main__':
    main()