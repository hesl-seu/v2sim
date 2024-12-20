from v2sim import DetectFiles, ELGraph, plot_graph
from feasytools import ArgChecker
import libsumo

if __name__ == "__main__":
    args = ArgChecker()
    input_dir = args.pop_str("d")
    locate_edgestr = args.pop_str("l","")
    route_edgestr = args.pop_str("r","")
    files = DetectFiles(input_dir)
    if not files.net or not files.fcs:
        print("No net.xml file found in the directory")
        exit(1)

    if not files.fcs:
        print("No fcs.xml file found in the directory")
        exit(1)
    
    print("Loading graph...")
    elg = ELGraph(files.net, files.fcs)
    
    print("Checking SCC...")
    elg.checkBadCS()
    elg.checkSCCSize()
    print("FCS edges:",elg.cs_names)
    
    locate_edges = list(map(lambda x: x.strip(),locate_edgestr.split(",")))
    if len(locate_edges)>=1 and locate_edges[0]!="":
        print("Edges to locate:",locate_edges)

    route_edges = list(map(lambda x: x.strip(),route_edgestr.split(",")))
    mid_edges = []
    if len(route_edges)>=1 and route_edges[0]!="":
        assert len(route_edges)>=2, "Route must have at least 2 edges"
        print("Edges to route:",route_edges)
        libsumo.simulation.load(["-n",files.net])
        for i in range(len(route_edges)-1):
            stage = libsumo.simulation.findRoute(route_edges[i],route_edges[i+1])
            edges:list[str] = stage.edges
            mid_edges.extend(edges)
    
    plot_graph(input_dir, elg, locate_edges, route_edges, mid_edges)