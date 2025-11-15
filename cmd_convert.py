from feasytools import ArgChecker
from v2simux import ConvertCase, Lang


def main():
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
        print(Lang.CONVERT_ERROR_MISSING_PATHS)
        exit(1)
    
    ConvertCase(input_dir, output_dir, part_cnt, auto_partition,
            non_passenger_links, non_scc_links)

if __name__ == "__main__":
    main()