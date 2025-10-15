import os
import shutil
from pathlib import Path
from feasytools import ArgChecker
from v2sim import RoadNet, DetectFiles

if __name__ == "__main__":
    args = ArgChecker()

    # Input path
    input_dir = args.get_str("i", "")

    # Output path
    output_dir = args.get_str("o", "")

    # Partition count
    part_cnt = args.get_int("p", 1)

    # Whether to auto determine partition count
    auto_partition = args.get_bool("auto-partition")

    # Whether to include non-passenger links
    non_passenger_links = args.get_bool("non-passenger-links")

    # Whether to include links and edges not in the largest SCC
    non_scc_links = args.get_bool("non-scc-items")

    if input_dir == "" or output_dir == "":
        print("Please provide input and output directory paths by -i and -o")
        exit(1)
    files = DetectFiles(input_dir)
    converted = False
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if files.net:
        print("Found SUMO network file:", files.net)
        r = RoadNet.load_sumo(files.net, only_passenger=not non_passenger_links)
        if not non_scc_links:
            print("Extracting largest strongly connected component...")
            r.remove_items_outside_max_scc()
        if auto_partition:
            part_cnt = min(32, os.cpu_count() or 1, r.node_count // 40)
            print(f"Auto partition count determined: {part_cnt}")
        if part_cnt > 1:
            print(f"Partitioning network into {part_cnt} parts...")
            r.partition_roadnet(part_cnt)
        r.save(str(out_dir / Path(files.net).name))
        converted = True
    if files.poly:
        print("Found POLY file:", files.poly)
        shutil.copy(files.poly, str(out_dir / Path(files.poly).name))
        converted = True
    if files.cscsv:
        print("Found charging station CSV file:", files.cscsv)
        shutil.copy(files.cscsv, str(out_dir / Path(files.cscsv).name))
        converted = True
    if files.osm:
        print("Found OSM file:", files.osm)
        shutil.copy(files.osm, str(out_dir / Path(files.osm).name))
        converted = True
    if files.grid:
        print("Found power grid file:", files.grid)
        shutil.copy(files.grid, str(out_dir / Path(files.grid).name))
        converted = True
    if files.py:
        print("Found vehicle Python file:", files.py)
        shutil.copy(files.py, str(out_dir / Path(files.py).name))
        converted = True
    if files.pref:
        print("Found vehicle preference file:", files.pref)
        shutil.copy(files.pref, str(out_dir / Path(files.pref).name))
        converted = True
    if files.plg:
        print("Found plugin file:", files.plg)
        shutil.copy(files.plg, str(out_dir / Path(files.plg).name))
        converted = True
    if not converted:
        print("No supported files found in the input directory.")