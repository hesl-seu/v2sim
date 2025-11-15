from pathlib import Path
from feasytools import ArgChecker
from v2simux import csQuery
from feasytools import LangLib


_ = LangLib.LoadFor(__file__)
AMapKeyFile = Path.home() / ".v2simux" / "amap_key.txt"


def main():
    args = ArgChecker()
    root = args.pop_str("d")
    new_loc = args.pop_str("p", "")
    ak = args.pop_str("key", "")
    allyes = args.pop_bool("y")

    if ak == "" and AMapKeyFile.exists():
        with open(AMapKeyFile, "r") as f:
            ak = f.read().strip()
    
    if ak == "":
        print(_("DESC"))
        exit()
    
    csQuery(root, new_loc, ak, allyes)


if __name__ == '__main__':
    main()