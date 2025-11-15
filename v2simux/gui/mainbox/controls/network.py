from v2simux.gui.common import *

from dataclasses import dataclass
from itertools import chain
from feasytools import SegFunc, ConstFunc, TimeFunc, RangeList
from fpowerkit import Bus, Line, Generator, PVWind, ESS, ESSPolicy, Grid as fGrid
from v2simux import RoadNet
from v2simux.traffic.net import Edge, Node
from .prope import PropertyPanel


GenLike = Union[Generator, PVWind, ESS]
PointList = List[Tuple[float, float]]
OESet = Optional[Set[str]]
OAfter = Optional[Callable[[], None]]

def _removesuffix(s:str, suffix:str) -> str:
    if s.endswith(suffix):
        return s[:-len(suffix)]
    return s

@dataclass
class itemdesc:
    type:str
    desc:Any

class BIDC:
    def __init__(self, categories:Iterable[str]):
        self._cls = list(categories)
        self._mp:Dict[int, Tuple[str, Any]] = {}
        self._rv:Dict[Any, int] = {}
    
    @property
    def classes(self):
        return self._cls
    
    def add(self, id:int, cls:str, item:Any):
        if id in self._mp: raise KeyError(f"{id} is already in BIDC")
        self._mp[id] = (cls, item)
        self._rv[item] = id
    
    def pop(self, id:int):
        item = self._mp.pop(id)[1]
        self._rv.pop(item)
    
    def remove(self, item:Any):
        id = self._rv.pop(item)
        self._mp.pop(id)
    
    def get(self, id:int):
        return self._mp[id]
    
    def set_desc(self, id:int, desc:Any):
        cls, _ = self._mp[id]
        self._mp[id] = (cls, desc)
    
    def __getitem__(self, id:int):
        return itemdesc(*self._mp[id])
    
    def __setitem__(self, id:int, val:Union[itemdesc,Tuple[str, Any]]):
        if id in self._mp: self.pop(id)
        if isinstance(val, itemdesc):
            self.add(id, val.type, val.desc)
        elif isinstance(val, tuple):
            assert isinstance(val[0], str)
            self.add(id, val[0], val[1])
        else:
            raise TypeError(f"Invalid val: {val}")
    
    def queryID(self, item:Any):
        return self._rv[item]
    
    def queryIDandCls(self, item:Any):
        id = self._rv[item]
        return id, self._mp[id][0]
    
    def queryCls(self, item:Any):
        id = self._rv[item]
        return self._mp[id][0]
    
class NetworkPanel(Frame):
    def _draw_done_center(self):
        self._center()
        self.__en = True
    
    def __init__(self, master, roadnet:Optional[RoadNet]=None, 
            grid:Optional[fGrid]=None, save_callback:Optional[Callable[[bool],None]]=None, **kwargs):
        super().__init__(master, **kwargs)

        self._Q = EventQueue(self)
        self._Q.register("draw_done", lambda: None)
        self._Q.register("draw_done_center", self._draw_done_center)
        self._Q.register("loaded", lambda: None)
        
        self._item_editing = None
        self._item_editing_id = -1
        self._cv = Canvas(self, bg='white')
        self._cv.pack(side='left',anchor='center',fill=BOTH, expand=1)
        self._cv.bind("<MouseWheel>", self._onMouseWheel)
        self._cv.bind("<Button-1>", self._onLClick)
        self._cv.bind("<Button-3>", self._onRClick)
        self._cv.bind("<B1-Motion>", self._onMotion)
        self._cv.bind("<B3-Motion>", self._onMotion)
        self._cv.bind("<ButtonRelease-1>", self._onRelease)
        self._cv.bind("<ButtonRelease-3>", self._onRelease)

        self._pr = PropertyPanel(self, {}, ConfigItemDict())
        self._pr.tree.AfterFunc = self.__finish_edit
        self._pr.pack(side='right',anchor='e',fill=Y, expand=0)
        self.clear()

        if roadnet is not None:
            self.setRoadNet(roadnet)
        
        if grid is not None:
            self.setGrid(grid)
        
        self.save_callback = save_callback
        self.__saved = True
    
    def savefig(self, save_to:str):
        if save_to.lower().endswith(".eps"):
            self._cv.postscript(file = save_to)
            return
        raise RuntimeError("Only .eps format is supported")
    
    def scale(self, x:float, y:float, s:float, item = 'all'):
        self._cv.scale(item, x, y, s, s)
        self._scale['k'] *= s
        self._scale['x'] = (1 - s) * x + self._scale['x'] * s
        self._scale['y'] = (1 - s) * y + self._scale['y'] * s
    
    def move(self, dx:float, dy:float, item = 'all'):
        self._cv.move(item, dx, dy)
        if item == 'all':
            self._scale['x'] += dx
            self._scale['y'] += dy
    
    def convRealXY2PlotXY(self, realX:float, realY:float):
        return realX * self._scale['k'] + self._scale['x'], (-realY) * self._scale['k'] + self._scale['y']
    
    def convPlotXY2RealXY(self, plotX:float, plotY:float):
        x = (plotX - self._scale['x'])/self._scale['k']
        y = -(plotY - self._scale['y'])/self._scale['k']
        return x, y

    def convLL2PlotXY(self, lon:Optional[float], lat:Optional[float]) -> Tuple[float, float]:
        '''Convert longitude and latitude to canvas coordinates'''
        if lon is None: lon = 0
        if lat is None: lat = 0
        if self._r and self._r.hasGeoProj():
            x, y = self._r.convertLonLat2XY(lon, lat)
        else:
            x, y = lon, lat
        y = -y
        return x * self._scale['k'] + self._scale['x'], y * self._scale['k'] + self._scale['y']
    
    def convPlotXY2LL(self, x:float, y:float) -> Tuple[float, float]:
        '''Convert canvas coordinates to longitude and latitude'''
        x = (x - self._scale['x'])/self._scale['k']
        y = -(y - self._scale['y'])/self._scale['k']
        if self._r is None: return (x, y)
        try:
            return self._r.convertXY2LonLat(x, y)
        except:
            return (x, y)
    
    def clear(self):
        self._cv.delete('all')
        self._scale_cnt = 0
        self._items:BIDC = BIDC(["bus", "bustext", "gen", "gentext", "genconn", "line", "edge", "node"])
        self._Redges:Dict[str, int] = {}
        self._located_edges:Set[str] = set()
        self._drag = {'item': None,'x': 0,'y': 0}
        self._scale = {'k':1.0, 'x':0, 'y':0}
        self._r:Optional[RoadNet] = None
        self._g = None
        self.__en = False
        self._world_colors = None
    
    def setRoadNet(self, roadnet:RoadNet, repaint:bool=True, after:OAfter=None):
        '''
        Set the road network to be displayed
            roadnet: ELGraph, the road network to be displayed
            repaint: bool, whether to repaint the network.
            after: Optional[Callable[[], None]], the function to be called after the network is repainted.
                If after is None, this repaint operation will block the main thread!
                If after is not None, this repaint operation will be done asynchronously.
        '''
        self._r = roadnet
        self._world_colors = self._r.create_color_map()
        if repaint: 
            self._draw_async(after=after)
    
    @property
    def Enabled(self) -> bool:
        return self.__en

    @Enabled.setter
    def Enabled(self, v:bool):
        self.__en = v
    
    @property
    def Grid(self) -> Optional[fGrid]:
        return self._g
    
    def setGrid(self, grid:fGrid, repaint:bool=True):
        '''
        Set the power grid to be displayed
            grid: ELGraph, the road network to be displayed
            repaint: bool, whether to repaint the network.
                This repaint operation will block the main thread!
        '''
        assert isinstance(grid, fGrid)
        self._g = grid
        if repaint: 
            self._draw_async()
    
    def _onLClick(self, event):
        if not self.__en: return
        def _edit_id(typename:str, clicked_item:int) -> int:
            if typename.endswith("conn"): return clicked_item + 1
            elif typename.endswith("text"): return clicked_item + 2
            else: return clicked_item
        x, y = event.x, event.y
        nr_item = self._cv.find_closest(x, y)
        ovl_item = self._cv.find_overlapping(x-5, y-5, x+5, y+5)
        if nr_item and nr_item[0] in ovl_item:
            clicked_item = nr_item[0]
            self.UnlocateAllEdges()
            itm = self._items[clicked_item]
            assert self._r is not None
            assert self._g is not None
            if itm.type == "edge":
                e = self._r.edges[itm.desc]
                node_ids = self._r.node_ids
                self._pr.setData2(
                    (e.id, ConfigItem("Name", EditMode.ENTRY, "Name of the edge")),
                    (e.from_node.id, ConfigItem("From", EditMode.COMBO, "From node", combo_values=node_ids)),
                    (e.to_node.id, ConfigItem("To", EditMode.COMBO, "To node", combo_values=node_ids)),
                    (e.length, ConfigItem("Length", EditMode.ENTRY, "Length in meter\nMay not be the same as the euclidean distance.")),
                    (e.lanes, ConfigItem("Lanes", EditMode.SPIN, "Number of lanes", spin_range=(1,100))),
                    (e.speed_limit, ConfigItem("Speed limit", EditMode.ENTRY, "Speed limit in m/s"))
                )
                self.LocateEdge(itm.desc, 'purple')
                self._item_editing = e
                self._item_editing_id = clicked_item
            elif itm.type == "node":
                n = self._r.nodes[itm.desc]
                if self._r.hasGeoProj():
                    lon, lat = self._r.convertXY2LonLat(n.x, n.y)
                    self._pr.setData2(
                        (n.id, ConfigItem("Name", EditMode.ENTRY, "Name of the node")),
                        (lon, ConfigItem("Longitude", EditMode.ENTRY, "Longitude of the node")),
                        (lat, ConfigItem("Latitude", EditMode.ENTRY, "Latitude of the node")),
                    )
                else:
                    self._pr.setData2(
                        (n.id, ConfigItem("Name", EditMode.ENTRY, "Name of the node")),
                        (n.x, ConfigItem("X", EditMode.ENTRY, "X coordinate of the node")),
                        (n.y, ConfigItem("Y", EditMode.ENTRY, "Y coordinate of the node")),
                    )
                self._item_editing = n
                self._item_editing_id = clicked_item
            elif itm.type in ("bus", "bustext"):
                if itm.type == 'bustext':
                    b = self._g.Bus(_removesuffix(itm.desc,".text"))
                else:
                    b = self._g.Bus(itm.desc)
                if self._r.hasGeoProj():
                    name0, desc0 = "Longitude", "Longitude of the bus"
                    name1, desc1 = "Latitude", "Latitude of the bus"
                else:
                    name0, desc0 = "X", "X coordinate of the bus"
                    name1, desc1 = "Y", "Y coordinate of the bus"
                self._pr.setData2(
                    (b.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the bus")),
                    (b.Lon, ConfigItem(name0, EditMode.ENTRY, desc0)),
                    (b.Lat, ConfigItem(name1, EditMode.ENTRY, desc1)),
                    (b.V, ConfigItem("V/pu", EditMode.ENTRY, "Voltage magnitude in per unit.\nSet to None if not fixed")),
                    (b.MinV, ConfigItem("Vmin/pu", EditMode.ENTRY, "Minimum voltage magnitude in per unit")),
                    (b.MaxV, ConfigItem("Vmax/pu", EditMode.ENTRY, "Maximum voltage magnitude in per unit")),
                    (b.Pd, ConfigItem("Pd/pu", EditMode.SEGFUNC, "Active power demand in per unit")),
                    (b.Qd, ConfigItem("Qd/pu", EditMode.SEGFUNC, "Reactive power demand in per unit")),
                )
                self._item_editing = b
                self._item_editing_id = clicked_item if itm.type == 'bus' else clicked_item + 1
            elif itm.type == "line":
                l = self._g.Line(itm.desc)
                self._pr.setData({
                    "Name":l.ID,"From Bus":l.fBus,"To Bus":l.tBus,
                    "R/pu":l.R,"X/pu":l.X,"MaxI/kA":l.max_I,"Length/km":l.L
                }, ConfigItemDict((
                    ConfigItem("Name", EditMode.ENTRY, "Name of the line"),
                    ConfigItem("From Bus", EditMode.COMBO, "Sending-end bus of the line", combo_values=self._g.BusNames),
                    ConfigItem("To Bus", EditMode.COMBO, "Receiving-end bus of the line", combo_values=self._g.BusNames),
                    ConfigItem("R/pu", EditMode.ENTRY, "Resistance of the line in per unit"),
                    ConfigItem("X/pu", EditMode.ENTRY, "Reactance of the line in per unit"),
                    ConfigItem("MaxI/kA", EditMode.ENTRY, "Thermal limit of the line in kA"),
                    ConfigItem("Length/km", EditMode.ENTRY, "Length of the line in km"),
                )))
                self._item_editing = l
                self._item_editing_id = clicked_item
            elif itm.type in ("gen", "gentext", "genconn"):
                g = self._g.Gen(_removesuffix(_removesuffix(itm.desc,".text"),".conn"))
                self._pr.setData({
                    "Name":g.ID,"Bus":g.BusID,
                    "Longitude":g.Lon,"Latitude":g.Lat,
                    "P/pu":g.P,"Q/pu":g.Q,
                    "Pmax/pu":g.Pmax,"Pmin/pu":g.Pmin,
                    "Qmax/pu":g.Qmax,"Qmin/pu":g.Qmin,
                    "CostA":g.CostA,"CostB":g.CostB,"CostC":g.CostC
                }, ConfigItemDict((
                    ConfigItem("Name", EditMode.ENTRY, "Name of the generator"),
                    ConfigItem("Bus", EditMode.COMBO, "Bus to which the generator is connected", combo_values=self._g.BusNames),
                    ConfigItem("Longitude", EditMode.ENTRY, "Longitude of the generator.\nIf longtitude not available, set it to an X coordinate"),
                    ConfigItem("Latitude", EditMode.ENTRY, "Latitude of the generator.\nIf latitude not available, set it to a Y coordinate"),
                    ConfigItem("P/pu", EditMode.ENTRY, "Active power output in per unit.\nSet to None if not fixed"),
                    ConfigItem("Q/pu", EditMode.ENTRY, "Reactive power output in per unit.\nSet to None if not fixed"),
                    ConfigItem("Pmax/pu", EditMode.SEGFUNC, "Maximum active power output in per unit"),
                    ConfigItem("Pmin/pu", EditMode.SEGFUNC, "Minimum active power output in per unit"),
                    ConfigItem("Qmax/pu", EditMode.SEGFUNC, "Maximum reactive power output in per unit"),
                    ConfigItem("Qmin/pu", EditMode.SEGFUNC, "Minimum reactive power output in per unit"),
                    ConfigItem("CostA", EditMode.SEGFUNC, "Quadratic cost coefficient A in $/(pu pwr·h)^2"),
                    ConfigItem("CostB", EditMode.SEGFUNC, "Quadratic cost coefficient B in $/(pu pwr·h)"),
                    ConfigItem("CostC", EditMode.SEGFUNC, "Quadratic cost coefficient C in $"),
                )))
                self._item_editing = g
                self._item_editing_id = _edit_id(itm.type, clicked_item)
            elif itm.type in ("pvw", "pvwtext", "pvwconn"):
                p = self._g.PVWind(_removesuffix(_removesuffix(itm.desc,".text"), ".conn"))
                self._pr.setData2(
                    (p.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the PV/Wind generator")),
                    (p.BusID, ConfigItem("Bus", EditMode.COMBO, "Bus to which the PV/Wind generator is connected", combo_values=self._g.BusNames)),
                    (p.Lon, ConfigItem("Longitude", EditMode.ENTRY, "Longitude of the PV/Wind generator.\nIf longtitude not available, set it to an X coordinate")),
                    (p.Lat, ConfigItem("Latitude", EditMode.ENTRY, "Latitude of the PV/Wind generator.\nIf latitude not available, set it to a Y coordinate")),
                    (p.P, ConfigItem("P/pu", EditMode.SEGFUNC, "Active power output of the PV/Wind generator")),
                    (p.PF, ConfigItem("Power Factor", EditMode.ENTRY, "Power Factor should be 0.0~1.0")),
                    (p._tag, ConfigItem("Tag", EditMode.COMBO, "Tag should be 'PV' or 'Wind'", combo_values=['PV', 'Wind'])),
                    (p.CC, ConfigItem("Curtail Cost", EditMode.ENTRY, "Unit = $/(pu pwr·h)")),
                )
                self._item_editing = p
                self._item_editing_id = _edit_id(itm.type, clicked_item)
            elif itm.type in ('ess', 'esstext', 'essconn'):
                e = self._g.ESS(_removesuffix(_removesuffix(itm.desc,".text"),".conn"))
                cp = e._cprice
                if cp is not None: cp /= self._g.Sb_kVA
                dp = e._dprice
                if dp is not None: dp /= self._g.Sb_kVA
                self._pr.setData2(
                    (e.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the ESS")),
                    (e.BusID, ConfigItem("Bus", EditMode.COMBO, "Bus to which the ESS is connected", combo_values=self._g.BusNames)),
                    (e.Lon, ConfigItem("Longitude", EditMode.ENTRY, "Longitude of the ESS.\nIf longtitude not available, set it to an X coordinate")),
                    (e.Lat, ConfigItem("Latitude", EditMode.ENTRY, "Latitude of the ESS.\nIf latitude not available, set it to a Y coordinate")),
                    (e.Cap * self._g.Sb_MVA, ConfigItem("Capacity/MWh", EditMode.ENTRY, "Maximum active power output of the ESS")),
                    (e.SOC, ConfigItem("SOC", EditMode.ENTRY, "State of Charge of the ESS, 0~1")),
                    (e.EC, ConfigItem("Ec", EditMode.ENTRY, "Charging Efficiency of the ESS")),
                    (e.ED, ConfigItem("Ed", EditMode.ENTRY, "Discharging Efficiency of the ESS")),
                    (e.MaxPc * self._g.Sb_kVA, ConfigItem("Max Pc/kW", EditMode.ENTRY, "Maximum Charging Power, kW")),
                    (e.MaxPd * self._g.Sb_kVA, ConfigItem("Max Pd/kW", EditMode.ENTRY, "Maximum Discharging Power, kW")),
                    (e.PF, ConfigItem("Power factor", EditMode.ENTRY, "Power factor")),
                    (e._policy.value, ConfigItem("Policy", EditMode.COMBO, "Charging and discharging policy", combo_values=[ESSPolicy.Manual.value,ESSPolicy.Price.value,ESSPolicy.Time.value])),
                    (str(e._ctime), ConfigItem("CTime", EditMode.RANGELIST, "Charging time if policy is time-based")),
                    (str(e._dtime), ConfigItem("DTime", EditMode.RANGELIST, "Discharging time if policy is time-based")),
                    (cp if cp is not None else "None", ConfigItem("CPrice/$/kWh", EditMode.ENTRY, "Charging if price is strictly below than this given price under price-based policy")),
                    (dp if dp is not None else "None", ConfigItem("DPrice/$/kWh", EditMode.ENTRY, "Discharging if price is strictly greater than this given price under price-based policy")),
                )
                self._item_editing = e
                self._item_editing_id = _edit_id(itm.type, clicked_item)
            else:
                self._pr.setDataEmpty()
            self._pr.tree.show_title(f"Type: {itm.type} (ID = {clicked_item})")
            if itm.type in ('bus', 'gen', 'pvw', 'ess', 'node'):
                self._drag['item'] = clicked_item
                self._drag["x"] = event.x
                self._drag["y"] = event.y

    @staticmethod
    def _float2func(v: str):
        v = eval(v)
        if isinstance(v, (float, int)):
            return ConstFunc(v)
        elif isinstance(v, TimeFunc):
            return v
        else:
            return SegFunc(v) # type: ignore

    @property
    def saved(self) -> bool:
        return self.__saved
    @saved.setter
    def saved(self, v:bool):
        if self.save_callback: self.save_callback(v)
        self.__saved = v
    
    def __move_gen(self, i:int, e:GenLike, nLon:float, nLat:float, move_gen:bool=True):
        assert e.Lon is not None and e.Lat is not None
        x0, y0 = self.convLL2PlotXY(e.Lon, e.Lat)
        x1, y1 = self.convLL2PlotXY(nLon, nLat)
        e.Lon = nLon
        e.Lat = nLat
        dx, dy = x1 - x0, y1 - y0
        if move_gen: self._cv.move(i, dx, dy)
        self._cv.move(i-2, dx, dy)
        assert self._g is not None
        self.__replot_genline(i-1, e, self._g.Bus(e.BusID))
    
    def __replot_genline(self, i:int, e:GenLike, b:Bus):
        assert e.Lon is not None and e.Lat is not None
        assert b.Lon is not None and b.Lat is not None
        x0, y0 = self.convLL2PlotXY(e.Lon, e.Lat)
        x1, y1 = self.convLL2PlotXY(b.Lon, b.Lat)
        self._cv.coords(i, x0, y0, x1, y1)
    
    def __move_line(self, i:int, e:Line):
        assert self._g is not None
        latf1, lonf1 = self._g.Bus(e.fBus).position
        assert latf1 is not None and lonf1 is not None
        pf1 = self.convLL2PlotXY(lonf1,latf1)
        latt1, lont1 = self._g.Bus(e.tBus).position
        assert latt1 is not None and lont1 is not None
        pt1 = self.convLL2PlotXY(lont1,latt1)
        self._cv.coords(i, pf1[0], pf1[1], pt1[0], pt1[1])
    
    def __move_edge(self, i:int, e:Edge):
        assert self._r is not None
        (x0, y0), (x1, y1) = self._r.get_offset_shape(e.id)
        (x0, y0) = self.convRealXY2PlotXY(x0, y0)
        (x1, y1) = self.convRealXY2PlotXY(x1, y1)
        self._cv.coords(i, x0, y0, x1, y1)

    def __move_node(self, i:int, e:Node, newPlotX:float, newPlotY:float, move_node:bool=True):
        oldPlotX, oldPlotY = self.convRealXY2PlotXY(e.x, e.y)
        dx, dy = newPlotX - oldPlotX, newPlotY - oldPlotY
        e.x, e.y = self.convPlotXY2RealXY(newPlotX, newPlotY)
        if move_node:
            self._cv.move(i, dx, dy)
        assert self._r is not None
        for l in chain(e.incoming_edges, e.outgoing_edges):
            lid = self._items.queryID(l.id)
            self.__move_edge(lid, l)

    def __move_bus(self, i:int, e:Bus, newLL:Tuple[float, float] = (-1, -1), newXY:Tuple[float, float] = (0, 0), move_bus:bool=True):
        assert e.Lon is not None and e.Lat is not None and self._r is not None
        x0, y0 = self.convLL2PlotXY(e.Lon, e.Lat)
        if newLL != (-1, -1):
            x1, y1 = self.convLL2PlotXY(*newLL)
            e.Lon, e.Lat = newLL
        else:
            x1, y1 = newXY
            e.Lon, e.Lat = self.convPlotXY2LL(x1, y1)
        
        dx, dy = x1 - x0, y1 - y0
        if move_bus:
            self._cv.move(i, dx, dy)
        self._cv.move(i-1, dx, dy)
        assert self._g is not None
        for g in self._g.GensAtBus(e.ID):
            gid = self._items.queryID(g.ID)
            self.__replot_genline(gid-1, g, e)
        for l in chain(self._g._ladjfb[e.ID], self._g._ladjtb[e.ID]):
            lid = self._items.queryID(l.ID)
            self.__move_line(lid, l)

    @staticmethod
    def __chk(s:str):
        s = s.strip().lower()
        if s == "" or s == "none": return None
        else: return s
    
    def __finish_edit(self):
        ret = self._pr.getAllData()
        e = self._item_editing
        i = self._item_editing_id
        
        if isinstance(e, Edge):
            assert self._r is not None
            if ret['Name'] != e.id and ret['Name'] in self._r.edge_ids:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return
            e.length = float(ret['Length'])
            e.lanes = int(ret['Lanes'])
            e.speed_limit = float(ret['Speed limit'])
            if e.id != ret['Name']:
                self.UnlocateEdge(e.id)
                self._Redges.pop(e.id)
                self._r.rename_edge(e.id, ret['Name'])
                self._items.set_desc(i, ret['Name'])
                self._Redges[e.id] = i
                self.LocateEdge(e.id, 'purple')
            if ret["From"] != e.from_node.id or ret["To"] != e.to_node.id:
                node_ids = set(self._r.node_ids)
                if ret["From"] not in node_ids:
                    MB.showerror("Error", f"Node {ret['From']} does not exist.")
                    return
                if ret["To"] not in node_ids:
                    MB.showerror("Error", f"Node {ret['To']} does not exist.")
                    return
                self._r.update_edge(e.id, ret["From"], ret["To"])
                self.__move_edge(i, e)
        elif isinstance(e, Node):
            assert self._r is not None
            if ret['Name'] != e.id and ret['Name'] in self._r.node_ids:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret['Latitude'])
                plotX, plotY = self.convLL2PlotXY(nLon, nLat)
            else:
                x, y = float(ret['X']), float(ret['Y'])
                plotX, plotY = self.convRealXY2PlotXY(x, y)
            self.__move_node(i, e, plotX, plotY)
            if e.id != ret['Name']:
                self._r.update_node(e.id, ret['Name'])
                self._items.set_desc(i, ret['Name'])
        elif isinstance(e, Bus):
            assert self._g is not None and self._r is not None
            if ret['Name'] != e.ID and ret['Name'] in self._g.BusNames:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return
            e.Pd = self._float2func(ret['Pd/pu'])
            e.Qd = self._float2func(ret['Qd/pu'])
            v = self.__chk(ret['V/pu'])
            if v is not None:
                e.fixV(float(v))
            else:
                e.unfixV()
            e.MinV = float(ret['Vmin/pu'])
            e.MaxV = float(ret['Vmax/pu'])
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret["Latitude"])
                self.__move_bus(i, e, newLL=(nLon, nLat))
            else:
                x = float(ret['X'])
                y = float(ret['Y'])
                self.__move_bus(i, e, newXY=(x, y))
            self._g.ChangeBusID(e.ID, ret['Name'])
            self._items.set_desc(i, ret['Name'])
            # e._id = ret['Name']
            self._cv.itemconfig(i-1, text = e.ID)
        elif isinstance(e, Generator):
            assert self._g is not None
            nLon = float(ret['Longitude'])
            nLat = float(ret["Latitude"])
            e.CostA = self._float2func(ret['CostA'])
            e.CostB = self._float2func(ret['CostB'])
            e.CostC = self._float2func(ret['CostC'])
            self._g.ChangeGenBus(e.ID, ret['Bus'])
            self.__move_gen(i, e, nLon, nLat)
            p = self.__chk(ret['P/pu'])
            q = self.__chk(ret['Q/pu'])
            if p is not None:
                e.fixP(eval(p))
            else:
                e.unfixP()
            if q is not None:
                e.fixQ(eval(q))
            else:
                e.unfixQ()
            e.Pmax = self._float2func(ret['Pmax/pu'])
            e.Qmax = self._float2func(ret['Qmax/pu'])
            e.Pmin = self._float2func(ret['Pmin/pu'])
            e.Qmin = self._float2func(ret['Qmin/pu'])
            self._g.ChangeGenID(e.ID, ret['Name'])
            self._items.set_desc(i, ret['Name'])
            # e._id = ret['Name']
        elif isinstance(e, PVWind):
            assert self._g is not None
            nLon = float(ret['Longitude'])
            nLat = float(ret["Latitude"])
            self._g.ChangePVWindBus(e.ID, ret['Bus'])
            self.__move_gen(i, e, nLon, nLat)
            p = self.__chk(ret['P/pu'])
            e.P = self._float2func(p) if p is not None else 0
            self._g.ChangePVWindID(e.ID, ret['Name'])
            self._items.set_desc(i, ret['Name'])
            # e._id = ret['Name']
        elif isinstance(e, Line):
            assert self._g is not None
            self._g.ChangeLineFromBus(e.ID, ret['From Bus'])
            self._g.ChangeLineToBus(e.ID, ret['To Bus'])
            e.R = float(ret['R/pu'])
            e.X = float(ret['X/pu'])
            e.L = float(ret['Length/km'])
            e.max_I = float(ret['MaxI/kA'])
            self.__move_line(i, e)
            self._g.ChangeLineID(e.ID, ret['Name'])
            self._items.set_desc(i, ret['Name'])
            # e._id = ret['Name']
        elif isinstance(e, ESS):
            assert self._g is not None
            nLon = float(ret['Longitude'])
            nLat = float(ret["Latitude"])
            e.Cap = float(ret['Capacity/MWh']) / self._g.Sb_MVA
            e._elec = float(ret['SOC']) * e.Cap
            e.EC = float(ret['Ec'])
            e.ED = float(ret['Ed'])
            e.MaxPc = float(ret['Max Pc/kW']) / self._g.Sb_kVA
            e.MaxPd = float(ret['Max Pd/kW']) / self._g.Sb_kVA
            e._policy = ESSPolicy(ret['Policy'])
            e._ctime = RangeList(eval(ret["CTime"]))
            e._dtime = RangeList(eval(ret["DTime"]))
            cp = ret["CPrice/$/kWh"]
            if cp.lower() == "none": e._cprice = None
            else: e._cprice = float(cp) * self._g.Sb_kVA
            dp = ret["DPrice/$/kWh"]
            if dp.lower() == "none": e._dprice = None
            else: e._dprice = float(dp) * self._g.Sb_kVA
            e.PF = float(ret['Power factor'])
            self._g.ChangeESSBus(e.ID, ret['Bus'])
            self._g.ChangeESSID(e.ID, ret['Name'])
            self._items.set_desc(i, ret['Name'])
            # e._id = ret['Name']
        self.saved = False

    def _onRClick(self, event):
        if not self.__en: return
        self._drag['item'] = 'all'
        self._drag["x"] = event.x
        self._drag["y"] = event.y
    
    def _onMotion(self, event):
        if not self.__en: return
        if self._drag["item"]:
            x, y = event.x, event.y
            dx = x - self._drag["x"]
            dy = y - self._drag["y"]
            self.move(dx, dy, self._drag["item"])
            self._drag["x"] = x
            self._drag["y"] = y
        if isinstance(self._drag["item"],int):
            self.saved = False
    
    def _onRelease(self, event):
        if not self.__en: return
        i = self._drag["item"]
        if isinstance(i,int):
            self.saved = False
            co = self._cv.coords(i)
            if len(co) == 4: 
                x1,y1,x2,y2 = co
                cx = (x1+x2)/2
                cy = (y1+y2)/2
            elif len(co) == 6: # PVW
                x1, y1, x2, y2, x3, y3 = co
                cx = x1
                cy = (y1+y2)/2
            else:
                raise RuntimeError("Invalid item")
            nLon, nLat = self.convPlotXY2LL(cx, cy)
            if self._items[i].type == 'bus':
                assert self._g is not None
                e = self._g.Bus(self._items[i].desc)
                self.__move_bus(i, e, newLL = (nLon, nLat), move_bus = False)
            elif self._items[i].type == 'gen':
                assert self._g is not None
                e = self._g.Gen(self._items[i].desc)
                self.__move_gen(i, e, nLon, nLat, False)
            elif self._items[i].type == 'pvw':
                assert self._g is not None
                e = self._g.PVWind(self._items[i].desc)
                self.__move_gen(i, e, nLon, nLat, False)
            elif self._items[i].type == 'ess':
                assert self._g is not None
                e = self._g.ESS(self._items[i].desc)
                self.__move_gen(i, e, nLon, nLat, False)
            elif self._items[i].type == 'node':
                assert self._r is not None
                e = self._r.nodes[self._items[i].desc]
                self.__move_node(i, e, cx, cy, False)
            self._onLClick(event)
        self._drag["item"] = None
        
    def _onMouseWheel(self, event):
        if not self.__en: return
        if event.delta > 0 and self._scale_cnt < 50:
            s = 1.1
            self._scale_cnt += 1
        elif event.delta < 0 and self._scale_cnt > -50:
            s = 1 / 1.1
            self._scale_cnt -= 1
        else:
            s = 1
        self.scale(event.x, event.y, s)
    
    def _center(self):
        bbox = self._cv.bbox("all")
        if not bbox: return
        cw = bbox[2] - bbox[0]
        ch = bbox[3] - bbox[1]
        ww = self._cv.winfo_width()
        wh = self._cv.winfo_height()
        dx = (ww - cw) / 2 - bbox[0]
        dy = (wh - ch) / 2 - bbox[1]
        self.move(dx, dy)
        s = min(max(ww-50, 100)/cw, max(wh-50, 100)/ch)
        self.scale(ww//2, wh//2, s)
    
    def LocateEdge(self, edge:str, color:str='red'):
        '''Locate an edge by highlighting it in given color, red by default'''
        if edge in self._Redges:
            pid = self._Redges[edge]
            self._cv.itemconfig(pid, fill=color, width=5)
            self._located_edges.add(edge)
    
    def LocateEdges(self, edges:Iterable[str], color:str='red'):
        '''Locate a set of edges by highlighting them in given color, red by default'''
        for edge in edges:
            self.LocateEdge(edge, color)
    
    def UnlocateAllEdges(self):
        '''Unlocate all edges that are located'''
        for edge in self._located_edges:
            self.UnlocateEdge(edge)
        self._located_edges.clear()
    
    def UnlocateEdge(self, edge:str):
        '''Unlocate an edge by restoring its color'''
        if edge in self._Redges:
            pid = self._Redges[edge]
            c, lw = self.__get_edge_prop(edge)
            self._cv.itemconfig(pid, fill=c, width=lw)
        
    def __get_edge_prop(self, edge:str) -> Tuple[Any, float]:
        assert self._r is not None
        # Get the edge properties from the road network
        e = self._r.edges[edge]
        if self._world_colors and e.world_id in self._world_colors:
            return self._world_colors[e.world_id], 2
        return ("blue", 2)

    def _draw_node(self, x:float, y:float, r, color, name:str):
        pid = self._cv.create_oval(x-r, y-r, x+r, y+r, fill=color, width=1)
        self._items[pid] = itemdesc("node", name)

    def _draw_edge(self, shape:PointList, color:str, lw:float, ename:str):
        shape = [(p[0], -p[1]) for p in shape]
        pid = self._cv.create_line(shape, fill=color, width=lw)
        self._items[pid] = itemdesc("edge", ename)
        self._Redges[ename] = pid
    
    def _draw_async(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True, after:OAfter=None):
        if after:
            self._Q.setcallback("draw_done", after)
        self._Q.submit("draw_done", self._draw, scale, dx, dy, center)
    
    def _draw_line(self,x1,y1,x2,y2,color,lw,name):
        self._items[self._cv.create_line(x1,y1,x2,y2,width=lw,fill=color)] = itemdesc('line', name)
    
    def _draw_gen(self,x,y,r,color,lw,name,xb,yb,tp):
        assert tp in ('gen', 'pvw', 'ess')
        self._items[self._cv.create_text(x+1.8*r,y+1.8*r,text=name)] = itemdesc(tp+'text', name+".text")
        self._items[self._cv.create_line(x, y, xb, yb, width=lw)] = itemdesc(tp+"conn", name+".conn")
        if tp == 'gen':
            self._items[self._cv.create_oval(x-r, y-r, x+r, y+r, fill=color, width=lw)] = itemdesc(tp, name)
        elif tp == 'pvw':
            self._items[self._cv.create_polygon(x, y-r, x-r, y+r, x+r, y+r, fill=color, outline='black', width=lw)] = itemdesc(tp, name)
        else:
            self._items[self._cv.create_rectangle(x-r, y-r, x+r, y+r, fill=color, width=lw)] = itemdesc(tp, name)

    def _draw_bus(self,x,y,r,color,lw,name):
        self._items[self._cv.create_text(x+1.8*r,y+1.8*r,text=name)] = itemdesc('bustext', name+".text")
        self._items[self._cv.create_rectangle(x-0.5*r, y-r, x+0.5*r, y+r, fill=color, width=lw)] = itemdesc("bus", name)
    
    def _draw(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True):
        if self._r is None: return
        self.__en = False
        self._cv.delete('all')

        minx, miny, maxx, maxy = self._r.getBoundary()
        if minx > maxx or miny > maxy:
            r = 5
            cx, cy = 0, 0
        else:
            r = max(maxx-minx, maxy-miny)/200
            cx = minx
            cy = miny
            
        for ename in self._r.edges.keys():
            shape = self._r.get_offset_shape(ename)
            c, lw = self.__get_edge_prop(ename)
            shape = [(p[0] * scale + dx, p[1] * scale + dy) for p in shape]
            self._Q.delegate(self._draw_edge, shape, c, lw, ename)
        
        for nd in self._r.nodes.values():
            x, y = nd.get_coord()
            x = x * scale + dx
            y = -y * scale + dy
            self._Q.delegate(self._draw_node, x, y, r/2, 'gray', nd.id)
            
        if self._g is not None:
            locless = 0
            for b in self._g.Buses:
                if b.Lon is None or b.Lat is None:
                    x,y = cx+(locless//20)*7*r, cy+(locless%20)*7*r
                    locless += 1
                    b.Lon, b.Lat = self.convPlotXY2LL(x,y)
                    print(f"Bus {b.ID} has no location, set to Lon, Lat = ({b.Lon:.6f},{b.Lat:.6f})")
            for line in self._g.Lines:
                x1, y1 = self.convLL2PlotXY(*self._g.Bus(line.fBus).LonLat)
                x2, y2 = self.convLL2PlotXY(*self._g.Bus(line.tBus).LonLat)
                self._Q.delegate(self._draw_line, x1, y1, x2, y2, 'black', 2, line.ID)
            
            for g in chain(self._g.Gens, self._g.PVWinds, self._g.ESSs):
                tp = g.__class__.__name__.lower()[:3]
                xb, yb = self.convLL2PlotXY(*self._g.Bus(g.BusID).LonLat)
                if g.Lon is None or g.Lat is None:
                    x,y = xb, yb+3*r
                    locless += 1
                    g.Lon, g.Lat = self.convPlotXY2LL(x,y)
                    t = g.__class__.__name__
                    print(f"{t} {g.ID} has no location, set to Lon, Lat = ({b.Lon:.6f},{b.Lat:.6f})")
                x, y = self.convLL2PlotXY(g.Lon, g.Lat)
                self._Q.delegate(self._draw_gen, x, y, r, 'white', 2, g.ID, xb, yb, tp)

            for b in self._g.Buses:
                x, y = self.convLL2PlotXY(b.Lon, b.Lat)
                self._Q.delegate(self._draw_bus, x, y, r, 'white', 2, b.ID)
        
        if center: self._Q.trigger("draw_done_center")
    
    def save(self, grid_path:str, net_path:str):
        '''Save the current network to files'''
        if self._g:
            self._g.saveFileXML(grid_path)
        if self._r:
            self._r.save(net_path)
        self.saved = True

__all__ = ["NetworkPanel", "itemdesc", "BIDC", "GenLike", "PointList", "OAfter", "OESet"]