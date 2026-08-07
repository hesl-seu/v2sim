"""Generate a V2Sim/FPowerKit distribution-grid XML from a V2Sim RoadNet.

The primary API is ``generate_distribution_grid``.  Bus coordinates are copied
verbatim from RoadNet nodes, so later spatial coupling (charging stations,
loads, PV, etc.) uses the same coordinate system as the traffic network.

Example
-------
from v2sim.net import RoadNet
from v2sim_pdn_generator import GridGenerationConfig, generate_distribution_grid

roadnet = RoadNet.load("osm.net.xml")
result = generate_distribution_grid(
    roadnet,
    "wuxi_110kV.grid.xml",
    GridGenerationConfig(bus_count=99, feeder_count=3, base_voltage_kv=110.0),
)
print(result.bus_to_road_node)
"""

import argparse
from typing import Sequence
from v2sim.gen import GridGenerationConfig, generate_distribution_grid
from v2sim import RoadNet


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a V2Sim distribution-grid XML from a V2Sim road network."
    )
    parser.add_argument("roadnet", help="V2Sim raw/SUMO road-network XML")
    parser.add_argument("output", help="Output .grid.xml path")
    parser.add_argument("--buses", type=int, default=99, help="total bus count (default: 99)")
    parser.add_argument("--feeders", type=int, default=3, help="radial feeder count (default: 3)")
    parser.add_argument("--voltage-kv", type=float, default=110.0, help="base voltage")
    parser.add_argument("--power-mva", type=float, default=100.0, help="base apparent power")
    parser.add_argument(
        "--road-format", choices=("auto", "raw", "sumo"), default="auto",
        help="RoadNet.load format",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    roadnet = RoadNet.load(args.roadnet, fmt=args.road_format)
    config = GridGenerationConfig(
        bus_count=args.buses,
        feeder_count=args.feeders,
        base_voltage_kv=args.voltage_kv,
        base_power_mva=args.power_mva,
    )
    result = generate_distribution_grid(roadnet, args.output, config)
    print(
        f"Generated {result.output_path}: {result.bus_count} buses, "
        f"{result.line_count} lines, {result.generator_count} generators, "
        f"{result.feeder_count} feeders"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())