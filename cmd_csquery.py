from pathlib import Path
from feasytools import ArgChecker
from ftrafficgen.csquery import csQuery


if __name__ == '__main__':
    args = ArgChecker()
    root = args.pop_str("d")
    new_loc = args.pop_str("p","")
    ak = args.pop_str("key","")
    allyes = args.pop_bool("y")
    if ak == "" and Path("amap_key.txt").exists():
        with open("amap_key.txt", "r") as f:
            ak = f.read().strip()
    if ak == "":
        print("Please provide an AMap key in command line.")
        exit()
    csQuery(root, new_loc, ak, allyes)
    