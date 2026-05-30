from pathlib import Path
import shutil

from feasytools import ArgChecker
from v2sim.net import SplitCase

def main():
    args = ArgChecker()

    input_dir = args.get_str_or_none("i")
    output_dir = args.get_str_or_none("o")
    part_cnt = args.get_int("p", 2)

    if not input_dir or not output_dir:
        print("Usage: cmd_split.py -i <input_dir> -o <output_dir> [-p <partitions>]")
        return
    if part_cnt < 2:
        print("Partitions must be at least 2.")
        return
    
    if Path(output_dir).exists():
        print(f"Output directory {output_dir} already exists. Please remove it first.")
        return
    if Path(input_dir).resolve() != Path(output_dir).resolve():
        shutil.copytree(input_dir, output_dir, dirs_exist_ok=True)
    SplitCase(
        input_dir=input_dir,
        output_dir=output_dir,
        partitions=part_cnt
    )
    

if __name__ == "__main__":
    main()