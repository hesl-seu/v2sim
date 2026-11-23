from v2sim.gui.common import *

from dataclasses import dataclass
from itertools import chain
from copy import deepcopy
from math import hypot
from feasytools import SegFunc, ConstFunc, TimeFunc, RangeList
from fpowerkit import Bus, Line, Generator, PVWind, ESS, ESSPolicy, Grid as fGrid, PositionBase
from v2sim import RoadNet
from v2sim.net import Edge, Node
from v2sim.gui.network_render import RoadEdgeVisual, RoadNodeVisual, RoadScene
from .prope import PropertyPanel


GenLike = Union[Generator, PVWind, ESS]
PointList = List[Tuple[float, float]]
OESet = Optional[Set[str]]
OAfter = Optional[Callable[[], None]]
_L = LangLib.Load(__file__)

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
        if (item, cls) in self._rv:
            raise KeyError(f"Item {item} is already in BIDC")
        self._rv[(item, cls)] = id
    
    def pop(self, id:int):
        cls, item = self._mp.pop(id)
        self._rv.pop((item, cls))
    
    def remove(self, item:Any, cls:Optional[str]=None):
        if cls is None:
            keys = [key for key in self._rv if key[0] == item]
            if len(keys) != 1:
                raise KeyError(f"Item {item} is missing or ambiguous in BIDC")
            key = keys[0]
        else:
            key = (item, cls)
        id = self._rv.pop(key)
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
    
    def queryID(self, item:Any, cls:str):
        return self._rv[(item, cls)]

    def getID(self, item:Any, cls:str):
        return self._rv.get((item, cls))
    
class NetworkPanel(Frame):
    ROAD_EDGE_CANVAS_LIMIT = 8000
    ROAD_NODE_CANVAS_LIMIT = 2000
    VIEWPORT_RENDER_DELAY_MS = 50

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
        self._Q.register("road_scene_ready", self._on_road_scene_ready)
        
        self._item_editing = None
        self._item_editing_id = -1
        self._property_values = None
        self._tool_mode = StringVar(self, value='select')
        self._connect_start = None
        self._preview_id = None
        self._undo_stack = []
        self._redo_stack = []
        self._revision = self._next_revision = self._saved_revision = 0

        self._toolbar = Frame(self)
        self._toolbar.pack(side='top', fill=X)
        # Two toolbar rows keep every action accessible on narrower windows.
        self._primary_tools = Frame(self._toolbar)
        self._primary_tools.pack(side='top', fill=X)
        self._secondary_tools = Frame(self._toolbar)
        self._secondary_tools.pack(side='top', fill=X)
        self._btn_select = Radiobutton(self._primary_tools, text=_L['NET_SELECT'],
            variable=self._tool_mode, value='select', style='Toolbutton',
            command=self._on_tool_changed)
        self._btn_grid_link = Radiobutton(self._primary_tools, text=_L['NET_GRID_LINE'],
            variable=self._tool_mode, value='grid', style='Toolbutton',
            command=self._on_tool_changed)
        self._btn_road_link = Radiobutton(self._primary_tools, text=_L['NET_UX_ROAD'],
            variable=self._tool_mode, value='road', style='Toolbutton',
            command=self._on_tool_changed)
        # A PV and a wind turbine are PVWind with different type tags.
        self._device_buttons = {}
        for mode, title in (
            ('gen', 'NET_ADD_GEN'), ('pv', 'NET_ADD_PV'),
            ('wind', 'NET_ADD_WIND'), ('ess', 'NET_ADD_ESS'),
        ):
            self._device_buttons[mode] = Radiobutton(
                self._secondary_tools, text=_L[title], variable=self._tool_mode,
                value=mode, style='Toolbutton', command=self._on_tool_changed)
        for btn in (self._btn_select, self._btn_grid_link, self._btn_road_link):
            btn.pack(side='left', padx=(4, 0), pady=3)
        for btn in self._device_buttons.values():
            btn.pack(side='left', padx=(4, 0), pady=3)
        self._btn_undo = Button(self._secondary_tools, text=_L['NET_UNDO'], command=self.undo)
        self._btn_redo = Button(self._secondary_tools, text=_L['NET_REDO'], command=self.redo)
        self._btn_undo.pack(side='left', padx=(14, 2))
        self._btn_redo.pack(side='left', padx=2)
        # Keep the hint on its own row so adding equipment doesn't hide tools.
        self._hint = Label(self, text=_L['NET_SELECT_HINT'])
        self._hint.pack(side='top', fill=X, padx=8, pady=(0, 2))

        self._cv = Canvas(self, bg='white', takefocus=True)
        self._cv.pack(side='left',anchor='center',fill=BOTH, expand=1)
        self._cv.bind("<MouseWheel>", self._onMouseWheel)
        self._cv.bind("<Button-1>", self._onLClick)
        self._cv.bind("<Button-3>", self._onRClick)
        self._cv.bind("<B1-Motion>", self._onMotion)
        self._cv.bind("<B3-Motion>", self._onMotion)
        self._cv.bind("<Motion>", self._onPreviewMotion)
        self._cv.bind("<Escape>", self._cancel_connection)
        self._cv.bind("<ButtonRelease-1>", self._onRelease)
        self._cv.bind("<ButtonRelease-3>", self._onRelease)
        self._cv.bind("<Configure>", self._onCanvasConfigure)

        self._pr = PropertyPanel(self, {}, ConfigItemDict())
        self._pr.tree.AfterFunc = self.__finish_edit
        self._pr.set_delete_handler(self.delete_selected)
        self._pr.pack(side='right',anchor='e',fill=Y, expand=0)
        # Only keys originating inside this panel are intercepted. Entry and
        # combobox text editing retains its own native undo shortcuts.
        self.bind_all('<Control-z>', self._on_undo_key, add='+')
        self.bind_all('<Control-y>', self._on_redo_key, add='+')
        self.bind_all('<Control-Z>', self._on_undo_key, add='+')
        self.bind_all('<Control-Y>', self._on_redo_key, add='+')
        self.__rnet_editable = False
        self.clear()

        if roadnet is not None:
            self.setRoadNet(roadnet)
        
        if grid is not None:
            self.setGrid(grid)
        
        self.save_callback = save_callback
        self.__saved = True
    
    def check_pos(self, b: PositionBase):
        assert self._r is not None
        if self._r.hasGeoProj():
            name0, desc0 = "Longitude", "Longitude of the bus"
            name1, desc1 = "Latitude", "Latitude of the bus"
            pos = b.LonLat
        else:
            name0, desc0 = "X", "X coordinate of the bus"
            name1, desc1 = "Y", "Y coordinate of the bus"
            pos = b.position
        return name0, desc0, name1, desc1, pos

    def savefig(self, save_to:str):
        if save_to.lower().endswith(".eps"):
            if self._road_scene is None:
                self._cv.postscript(file = save_to)
                return
            old_limits = self._max_visible_road_edges, self._max_visible_road_nodes
            try:
                self._max_visible_road_edges = len(self._road_scene.edges)
                self._max_visible_road_nodes = len(self._road_scene.nodes)
                self._render_viewport()
                self._cv.postscript(file = save_to)
            finally:
                self._max_visible_road_edges, self._max_visible_road_nodes = old_limits
                self._schedule_viewport_render(0)
            return
        raise RuntimeError("Only .eps format is supported")
    
    def scale(self, x:float, y:float, s:float, item = 'all'):
        self._cv.scale(item, x, y, s, s)
        if item == 'all':
            self._scale['k'] *= s
            self._scale['x'] = (1 - s) * x + self._scale['x'] * s
            self._scale['y'] = (1 - s) * y + self._scale['y'] * s
            self._schedule_viewport_render()
    
    def move(self, dx:float, dy:float, item = 'all'):
        self._cv.move(item, dx, dy)
        if item == 'all':
            self._scale['x'] += dx
            self._scale['y'] += dy
            self._schedule_viewport_render()
    
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
        self._cancel_connection()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._revision = self._next_revision = self._saved_revision = 0
        self._item_editing = None
        self._item_editing_id = -1
        self._property_values = None
        self._pr.setDataEmpty()
        self._pr.enable_delete(False)
        self._update_history_buttons()
        self._tool_mode.set('select')
        self._on_tool_changed()
        self.__saved = True
        pending = getattr(self, '_viewport_after_id', None)
        if pending is not None:
            try: self.after_cancel(pending)
            except: pass
        self._cv.delete('all')
        self._scale_cnt = 0
        self._items:BIDC = BIDC(["bus", "bustext", "gen", "gentext", "genconn", "line", "edge", "node"])
        self._Redges:Dict[str, int] = {}
        self._located_edges:Set[str] = set()
        self._drag = {'item': None,'x': 0,'y': 0}
        self._scale = {'k':1.0, 'x':0, 'y':0}
        self._r:Optional[RoadNet] = None
        self._g = None
        self._update_tool_permissions()
        self.__en = False
        self._world_colors = None
        self._road_scene:Optional[RoadScene] = None
        self._scene_generation = getattr(self, '_scene_generation', 0) + 1
        self._draw_callbacks:List[Callable[[], None]] = []
        self._viewport_after_id = None
        self._last_canvas_size = (0, 0)
        # Tk Canvas remains responsive with this bounded number of road items.
        self._max_visible_road_edges = self.ROAD_EDGE_CANVAS_LIMIT
        self._max_visible_road_nodes = self.ROAD_NODE_CANVAS_LIMIT
        self._node_radius = 3.0
    
    def setRoadNet(self, roadnet:RoadNet, repaint:bool=True, after:OAfter=None):
        '''
        Set the road network to be displayed
            roadnet: ELGraph, the road network to be displayed
            repaint: bool, whether to repaint the network.
            after: Optional[Callable[[], None]], the function to be called after the network is repainted.
                If after is None, this repaint operation will block the main thread!
                If after is not None, this repaint operation will be done asynchronously.
        '''
        if self._r is not roadnet:
            self._reset_history()
        self._r = roadnet
        # SUMO road geometry is read-only; UXsim geometry is editable.
        # Set the policy before asynchronously rendering the new network.
        self.__rnet_editable = not roadnet.is_from_sumo()
        self._update_tool_permissions()
        self._world_colors = self._r.create_color_map()
        if repaint:
            self._draw_async(after=after, rebuild_road=True)
    
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
        if self._g is not grid:
            self._reset_history()
        self._g = grid
        self._update_tool_permissions()
        if repaint: 
            self._draw_async(rebuild_road=self._road_scene is None)
    
    # --- Editing tools and per-operation history (GUI only) ---
    def _reset_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._revision = self._next_revision = self._saved_revision = 0
        self._update_history_buttons()

    def _update_history_buttons(self):
        self._btn_undo.configure(state='normal' if self._undo_stack else 'disabled')
        self._btn_redo.configure(state='normal' if self._redo_stack else 'disabled')

    def _update_tool_permissions(self):
        grid_ok = self._g is not None
        road_ok = self._r is not None and self.__rnet_editable
        self._btn_grid_link.configure(state='normal' if grid_ok else 'disabled')
        self._btn_road_link.configure(state='normal' if road_ok else 'disabled')
        for btn in self._device_buttons.values():
            btn.configure(state='normal' if grid_ok else 'disabled')
        if ((self._tool_mode.get() == 'road' and not road_ok) or
                (self._tool_mode.get() in ('grid', 'gen', 'pv', 'wind', 'ess')
                 and not grid_ok)):
            self._tool_mode.set('select')
        self._on_tool_changed()
        self._pr.enable_delete(self._item_editing is not None and
            (not isinstance(self._item_editing, (Node, Edge)) or road_ok))

    def _on_tool_changed(self):
        self._cancel_connection()
        mode = self._tool_mode.get()
        self._hint.configure(text={
            'select': _L['NET_SELECT_HINT'],
            'grid': _L['NET_GRID_HINT'],
            'road': _L['NET_ROAD_HINT'],
            'gen': _L['NET_ADD_GEN_HINT'],
            'pv': _L['NET_ADD_PV_HINT'],
            'wind': _L['NET_ADD_WIND_HINT'],
            'ess': _L['NET_ADD_ESS_HINT'],
        }[mode])
        self._cv.configure(cursor='crosshair' if mode != 'select' else '')

    def _cancel_connection(self, event=None):
        self._connect_start = None
        if getattr(self, '_preview_id', None) is not None:
            self._cv.delete(self._preview_id)
            self._preview_id = None
        if event is not None:
            return 'break'

    def _onPreviewMotion(self, event):
        if not self.__en or self._connect_start is None:
            return
        _, (x0, y0) = self._connect_start
        px, py = self.convRealXY2PlotXY(x0, y0)
        if self._preview_id is None:
            self._preview_id = self._cv.create_line(px, py, event.x, event.y,
                fill='darkorange', width=2, dash=(5, 4), tags=('preview',))
        else:
            self._cv.coords(self._preview_id, px, py, event.x, event.y)

    @staticmethod
    def _unique_name(existing, prefix):
        i = 1
        used = set(existing)
        while f'{prefix}{i}' in used:
            i += 1
        return f'{prefix}{i}'

    def _hit_endpoint(self, x, y, kind):
        """Canvas hit test for the *correct* layer, never a nearby road/line."""
        wanted = ('bus', 'bustext') if kind == 'grid' else ('node',)
        candidates = self._cv.find_overlapping(x-7, y-7, x+7, y+7)
        for cid in reversed(candidates):
            if cid not in self._items._mp:
                continue
            itm = self._items[cid]
            if itm.type in wanted:
                if itm.type == 'bustext':
                    return _removesuffix(itm.desc, '.text')
                return itm.desc
        return None

    def _connection_click(self, event):
        kind = self._tool_mode.get()
        if kind in ('gen', 'pv', 'wind', 'ess'):
            self._create_grid_equipment_click(event, kind)
            return
        if kind not in ('grid', 'road'):
            return
        if kind == 'grid' and self._g is None:
            return
        if kind == 'road' and (self._r is None or not self.__rnet_editable):
            return
        xy = self.convPlotXY2RealXY(event.x, event.y)
        endpoint = (self._hit_endpoint(event.x, event.y, kind), xy)
        if self._connect_start is None:
            self._connect_start = endpoint
            return
        start = self._connect_start
        self._cancel_connection()
        if start[0] is not None and start[0] == endpoint[0]:
            return
        if start[0] is None and endpoint[0] is None and hypot(
                start[1][0]-endpoint[1][0], start[1][1]-endpoint[1][1]) < 1e-9:
            return
        before = self._snapshot(kind)
        try:
            if kind == 'grid':
                self._create_grid_link(start, endpoint)
            else:
                self._create_road_link(start, endpoint)
        except Exception as exc:
            self._restore_snapshot(kind, before)
            MB.showerror(_L['ERROR'], str(exc))
            return
        self._record_change(kind, before)
        self._clear_selection()
        self._redraw_after_change(kind)

    def _create_grid_equipment_click(self, event, kind):
        """Place a grid device with one undo entry (including an auto bus)."""
        if self._g is None or self._r is None:
            return
        # Commit an unfinished property edit before capturing this transaction.
        self._pr.tree.tree_item_edit_done(None)
        before = self._snapshot('grid')
        try:
            bus_id = self._hit_endpoint(event.x, event.y, 'grid')
            x, y = self.convPlotXY2RealXY(event.x, event.y)
            gap = 42.0 / max(self._scale['k'], 1e-6)
            if bus_id is None:
                # The clicked point represents the device; put the new bus
                # left of it so both symbols and their wire remain visible.
                bus_id = self._unique_name(self._g.BusNames, 'B')
                self._g.AddBus(Bus(bus_id, 0.0, 0.0, x - gap, y,
                    min_v_pu=0.8, max_v_pu=1.2))
                # FPowerKit 0.5.1 AddBus omits ESS adjacency initialization.
                if hasattr(self._g, '_eatb'):
                    self._g._eatb.setdefault(bus_id, [])
            else:
                # The bus is the attachment target. Offset equipment from it
                # and cycle placement so repeated additions don't overlap.
                bus = self._g.Bus(bus_id)
                count = sum(item.BusID == bus_id for item in
                            chain(self._g.Gens, self._g.PVWinds, self._g.ESSs))
                direction = ((1, 0), (0, 1), (-1, 0), (0, -1),
                             (1, 1), (-1, 1), (-1, -1), (1, -1))[count % 8]
                ring = 1 + count // 8
                x = bus.x + direction[0] * gap * ring
                y = bus.y + direction[1] * gap * ring

            if kind == 'gen':
                name = self._unique_name((g.ID for g in self._g.Gens), 'G')
                device = Generator(name, bus_id, 0.0, 0.0, 0.0, x, y,
                    pmin_pu=0.0, pmax_pu=1.0,
                    qmin_pu=-1.0, qmax_pu=1.0)
                self._g.AddGen(device)
            elif kind in ('pv', 'wind'):
                tag, prefix = ('PV', 'PV') if kind == 'pv' else ('Wind', 'W')
                name = self._unique_name((g.ID for g in self._g.PVWinds), prefix)
                device = PVWind(name, bus_id, 0.0, 1.0, 0.0, tag, x, y)
                self._g.AddPVWind(device)
            elif kind == 'ess':
                name = self._unique_name((g.ID for g in self._g.ESSs), 'ESS')
                capacity = 1.0 / self._g.Sb_MVA   # 1 MWh
                max_power = 100.0 / self._g.Sb_kVA  # 100 kW
                device = ESS(name, bus_id, capacity, 0.95, 0.95,
                    max_power, max_power, 1.0, ESSPolicy.Manual, x, y,
                    init_elec_puh=capacity * 0.5)
                self._g.AddESS(device)
            else:
                raise ValueError(kind)
        except Exception as exc:
            self._restore_snapshot('grid', before)
            MB.showerror(_L['ERROR'], str(exc))
            return
        self._record_change('grid', before)
        self._clear_selection()
        self._redraw_after_change('grid')
        # Return to selection so the newly-created device can be edited or
        # dragged immediately; a new click on its tool permits another add.
        self._tool_mode.set('select')
        self._on_tool_changed()
        px, py = self.convRealXY2PlotXY(x, y)
        self._onLClick(type('Click', (), {'x': round(px), 'y': round(py)})())

    def _create_grid_link(self, start, end):
        assert self._g is not None
        ids = []
        for bus_id, (x, y) in (start, end):
            if bus_id is None:
                bus_id = self._unique_name(self._g.BusNames, 'B')
                self._g.AddBus(Bus(bus_id, 0.0, 0.0, x, y,
                    min_v_pu=0.8, max_v_pu=1.2))
                # Some FPowerKit releases omit ESS adjacency initialization
                # from AddBus; support ESS on newly created buses as well.
                if hasattr(self._g, '_eatb'):
                    self._g._eatb.setdefault(bus_id, [])
            ids.append(bus_id)
        pos1 = self._g.Bus(ids[0]).pos
        pos2 = self._g.Bus(ids[1]).pos
        length_km = hypot(pos1[0]-pos2[0], pos1[1]-pos2[1])/1000.0
        line_id = self._unique_name((line.ID for line in self._g.Lines), 'L')
        # Editable initial impedance; no calculation or solver is invoked here.
        self._g.AddLine(Line(line_id, ids[0], ids[1], 0.001, 0.001,
            length_km=length_km))

    def _create_road_link(self, start, end):
        assert self._r is not None and self.__rnet_editable
        ids = []
        for node_id, (x, y) in (start, end):
            if node_id is None:
                node_id = self._unique_name(self._r.node_ids, 'N')
                self._r.add_node(node_id, x, y)
            ids.append(node_id)
        n1, n2 = self._r.nodes[ids[0]], self._r.nodes[ids[1]]
        length_m = max(hypot(n1.x-n2.x, n1.y-n2.y), 1.0)
        edge_id = self._unique_name(self._r.edge_ids, 'E')
        self._r.add_edge(edge_id, ids[0], ids[1], length_m, 1, 13.89)

    @staticmethod
    def _road_snapshot(roadnet):
        """Lightweight records avoid copying optional scipy/SUMO caches."""
        return (
            [(n.name, n.x, n.y, deepcopy(n.attrs)) for n in roadnet.nodes.values()],
            [(e.name, e.from_node.name, e.to_node.name, e.length, e.lanes,
              e.speed_limit, e.world_id, e.nickname, deepcopy(e.attrs))
             for e in roadnet.edges.values()],
            tuple(roadnet.convBoundary),
        )

    def _snapshot(self, kind):
        if kind == 'grid':
            return deepcopy(self._g)
        if kind == 'road':
            if self._r is None or not self.__rnet_editable:
                raise RuntimeError('SUMO road geometry is read-only.')
            return self._road_snapshot(self._r)
        raise ValueError(kind)

    def _restore_snapshot(self, kind, state):
        self._clear_selection()
        if kind == 'grid':
            self._g = deepcopy(state)
        elif kind == 'road':
            assert self._r is not None and self.__rnet_editable
            old = self._r
            restored = RoadNet()
            # Keep map metadata and projector; reconstruct only UXsim geometry.
            for attr in ('netOffset', 'convBoundary', 'origBoundary',
                         'projParameter', '_proj'):
                setattr(restored, attr, getattr(old, attr))
            nodes, edges, boundary = state
            restored.convBoundary = boundary
            for name, x, y, attrs in nodes:
                restored.add_node(name, x, y, deepcopy(attrs))
            for (name, src, dst, length, lanes, speed, world_id,
                 nickname, attrs) in edges:
                edge = restored.add_edge(name, src, dst, length, lanes,
                    speed, world_id, nickname)
                edge.attrs = deepcopy(attrs)
            self._r = restored
            self._world_colors = self._r.create_color_map()
        else:
            raise ValueError(kind)
        self._update_tool_permissions()
        self._redraw_after_change(kind)

    def _refresh_ux_boundary(self):
        if self._r is None or not self.__rnet_editable:
            return
        nodes = tuple(self._r.nodes.values())
        if not nodes:
            self._r.convBoundary = (0., 0., 0., 0.)
        else:
            self._r.convBoundary = (
                min(n.x for n in nodes), min(n.y for n in nodes),
                max(n.x for n in nodes), max(n.y for n in nodes),
            )
        # Moving nodes invalidates any nearest-node index already constructed.
        if hasattr(self._r, '_RoadNet__kdt'):
            self._r._RoadNet__kdt = None

    def _record_change(self, kind, before):
        if kind == 'road':
            self._refresh_ux_boundary()
        self._undo_stack.append((kind, before, self._revision))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._next_revision += 1
        self._revision = self._next_revision
        self.saved = self._revision == self._saved_revision
        self._update_history_buttons()

    def undo(self):
        if not self.__en or not self._undo_stack:
            return
        self._cancel_connection()
        self._pr.tree.tree_item_edit_done(None)
        if not self._undo_stack:
            return
        kind, before, rev = self._undo_stack.pop()
        current = self._snapshot(kind)
        self._redo_stack.append((kind, current, self._revision))
        self._revision = rev
        self._restore_snapshot(kind, before)
        self.saved = self._revision == self._saved_revision
        self._update_history_buttons()

    def redo(self):
        if not self.__en or not self._redo_stack:
            return
        self._cancel_connection()
        self._pr.tree.tree_item_edit_done(None)
        if not self._redo_stack:
            return
        kind, after, rev = self._redo_stack.pop()
        current = self._snapshot(kind)
        self._undo_stack.append((kind, current, self._revision))
        self._revision = rev
        self._restore_snapshot(kind, after)
        self.saved = self._revision == self._saved_revision
        self._update_history_buttons()

    def _key_targets_network(self, widget):
        # Never consume shortcuts in a property entry/combobox or other tab.
        if isinstance(widget, (Entry, Text, Spinbox, Combobox)):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _on_undo_key(self, event):
        if self._key_targets_network(event.widget):
            self.undo()
            return 'break'

    def _on_redo_key(self, event):
        if self._key_targets_network(event.widget):
            self.redo()
            return 'break'

    def _clear_selection(self):
        self._item_editing = None
        self._item_editing_id = -1
        self._property_values = None
        self._drag['item'] = None
        self._pr.setDataEmpty()
        self._pr.enable_delete(False)
        self.UnlocateAllEdges()

    def _redraw_after_change(self, kind):
        self._draw_async(center=False, rebuild_road=(kind == 'road'))

    def delete_selected(self):
        e = self._item_editing
        if e is None:
            return
        if isinstance(e, (Node, Edge)) and not self.__rnet_editable:
            return
        kind = 'road' if isinstance(e, (Node, Edge)) else 'grid'
        name = getattr(e, 'name', getattr(e, 'ID', ''))
        detail = ''
        if isinstance(e, Bus):
            detail = '\n' + _L['NET_DELETE_BUS_WARNING']
        elif isinstance(e, Node):
            detail = '\n' + _L['NET_DELETE_NODE_WARNING']
        if not MB.askyesno(_L['DELETE'], _L['NET_DELETE_CONFIRM'].format(name) + detail):
            return
        before = self._snapshot(kind)
        try:
            if isinstance(e, Bus):
                # Explicitly remove connected elements first, since DelBus in
                # FPowerKit doesn't clear all opposite adjacency collections.
                for line in list(self._g.Lines):
                    if e.ID in (line.fBus, line.tBus):
                        self._g.DelLine(line.ID)
                for gen in list(self._g.Gens):
                    if gen.BusID == e.ID: self._g.DelGen(gen.ID)
                for pvw in list(self._g.PVWinds):
                    if pvw.BusID == e.ID: self._g.DelPVWind(pvw.ID)
                for ess in list(self._g.ESSs):
                    if ess.BusID == e.ID: self._delete_grid_ess(ess)
                self._g.DelBus(e.ID)
                if hasattr(self._g, '_eatb'):
                    self._g._eatb.pop(e.ID, None)
            elif isinstance(e, Line): self._g.DelLine(e.ID)
            elif isinstance(e, Generator): self._g.DelGen(e.ID)
            elif isinstance(e, PVWind): self._g.DelPVWind(e.ID)
            elif isinstance(e, ESS): self._delete_grid_ess(e)
            elif isinstance(e, Edge): self._remove_ux_edge(e)
            elif isinstance(e, Node):
                for edge in list(self._r.edges.values()):
                    if e.name in (edge.from_node.name, edge.to_node.name):
                        self._remove_ux_edge(edge)
                self._r.remove_node(e.name)
            else: return
        except Exception as exc:
            self._restore_snapshot(kind, before)
            MB.showerror(_L['ERROR'], str(exc))
            return
        self._record_change(kind, before)
        self._clear_selection()
        self._redraw_after_change(kind)

    def _delete_grid_ess(self, ess):
        """Compatibility with FPowerKit releases lacking a DelESS method."""
        if hasattr(self._g, 'DelESS'):
            self._g.DelESS(ess.ID)
        else:
            self._g._esss.pop(ess.ID)
            attached = self._g._eatb.get(ess.BusID, [])
            if ess in attached:
                attached.remove(ess)

    def _remove_ux_edge(self, edge):
        # RoadNet.remove_edge removes the lookup entry but doesn't unlink the
        # Node adjacency lists; keep both sides consistent in the editor.
        if edge in edge.from_node.outgoing_edges:
            edge.from_node.outgoing_edges.remove(edge)
        if edge in edge.to_node.incoming_edges:
            edge.to_node.incoming_edges.remove(edge)
        self._r.remove_edge(edge.name)

    def _onLClick(self, event):
        if not self.__en: return
        self._cv.focus_set()
        if self._tool_mode.get() != 'select':
            self._connection_click(event)
            return
        # Commit any active property cell before changing selected object.
        self._pr.tree.tree_item_edit_done(None)
        # Do not retain an editable object from the previous selection when a
        # read-only SUMO road element (or empty canvas area) is selected.
        self._item_editing = None
        self._item_editing_id = -1
        self._property_values = None
        self._pr.enable_delete(False)
        self._drag['item'] = None
        self._drag['moved'] = False
        def _edit_id(typename:str, clicked_item:int) -> int:
            if typename.endswith("conn"): return clicked_item + 1
            elif typename.endswith("text"): return clicked_item + 2
            else: return clicked_item
        def _EMW(x):
            return x if self.__rnet_editable else EditMode.DISABLED
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
                    (e.name, ConfigItem("Name", _EMW(EditMode.ENTRY), "Name of the edge")),
                    (e.from_node.name, ConfigItem("From", _EMW(EditMode.COMBO), "From node", combo_values=node_ids)),
                    (e.to_node.name, ConfigItem("To", _EMW(EditMode.COMBO), "To node", combo_values=node_ids)),
                    (e.length, ConfigItem("Length", _EMW(EditMode.ENTRY), "Length in meter\nMay not be the same as the euclidean distance.")),
                    (e.lanes, ConfigItem("Lanes", _EMW(EditMode.SPIN), "Number of lanes", spin_range=(1,100))),
                    (e.speed_limit, ConfigItem("Speed limit", _EMW(EditMode.ENTRY), "Speed limit in m/s"))
                )
                self.LocateEdge(itm.desc, 'purple')
                if self.__rnet_editable:
                    self._item_editing = e
                    self._item_editing_id = clicked_item
            elif itm.type == "node":
                n = self._r.nodes[itm.desc]
                if self._r.hasGeoProj():
                    lon, lat = self._r.convertXY2LonLat(n.x, n.y)
                    self._pr.setData2(
                        (n.name, ConfigItem("Name", _EMW(EditMode.ENTRY), "Name of the node")),
                        (lon, ConfigItem("Longitude", _EMW(EditMode.ENTRY), "Longitude of the node")),
                        (lat, ConfigItem("Latitude", _EMW(EditMode.ENTRY), "Latitude of the node")),
                    )
                else:
                    self._pr.setData2(
                        (n.name, ConfigItem("Name", _EMW(EditMode.ENTRY), "Name of the node")),
                        (n.x, ConfigItem("X", _EMW(EditMode.ENTRY), "X coordinate of the node")),
                        (n.y, ConfigItem("Y", _EMW(EditMode.ENTRY), "Y coordinate of the node")),
                    )
                if self.__rnet_editable:
                    self._item_editing = n
                    self._item_editing_id = clicked_item
            elif itm.type in ("bus", "bustext"):
                if itm.type == 'bustext':
                    b = self._g.Bus(_removesuffix(itm.desc,".text"))
                else:
                    b = self._g.Bus(itm.desc)
                name0, desc0, name1, desc1, pos = self.check_pos(b)
                self._pr.setData2(
                    (b.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the bus")),
                    (pos[0], ConfigItem(name0, EditMode.ENTRY, desc0)),
                    (pos[1], ConfigItem(name1, EditMode.ENTRY, desc1)),
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
                name0, desc0, name1, desc1, pos = self.check_pos(g)
                self._pr.setData({
                    "Name":g.ID,        "Bus":g.BusID,
                    name0:pos[0],       name1:pos[1],
                    "P/pu":g.P,         "Q/pu":g.Q,
                    "Pmax/pu":g.Pmax,   "Pmin/pu":g.Pmin,
                    "Qmax/pu":g.Qmax,   "Qmin/pu":g.Qmin,
                    "CostA":g.CostA,    "CostB":g.CostB,        "CostC":g.CostC
                }, ConfigItemDict((
                    ConfigItem("Name", EditMode.ENTRY, "Name of the generator"),
                    ConfigItem("Bus", EditMode.COMBO, "Bus to which the generator is connected", combo_values=self._g.BusNames),
                    ConfigItem(name0, EditMode.ENTRY, desc0),
                    ConfigItem(name1, EditMode.ENTRY, desc1),
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
                name0, desc0, name1, desc1, pos = self.check_pos(p)
                self._pr.setData2(
                    (p.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the PV/Wind generator")),
                    (p.BusID, ConfigItem("Bus", EditMode.COMBO, "Bus to which the PV/Wind generator is connected", combo_values=self._g.BusNames)),
                    (pos[0], ConfigItem(name0, EditMode.ENTRY, desc0)),
                    (pos[1], ConfigItem(name1, EditMode.ENTRY, desc1)),
                    (p.P, ConfigItem("P/pu", EditMode.SEGFUNC, "Active power output of the PV/Wind generator")),
                    (p.PF, ConfigItem("Power Factor", EditMode.ENTRY, "Power Factor should be 0.0~1.0")),
                    (p._tag, ConfigItem("Tag", EditMode.COMBO, "Tag should be 'PV' or 'Wind'", combo_values=['PV', 'Wind'])),
                    (p.CC, ConfigItem("Curtail Cost", EditMode.ENTRY, "Unit = $/(pu pwr·h)")),
                )
                self._item_editing = p
                self._item_editing_id = _edit_id(itm.type, clicked_item)
            elif itm.type in ('ess', 'esstext', 'essconn'):
                e = self._g.ESS(_removesuffix(_removesuffix(itm.desc,".text"),".conn"))
                name0, desc0, name1, desc1, pos = self.check_pos(e)
                cp = e._cprice
                if cp is not None: cp /= self._g.Sb_kVA
                dp = e._dprice
                if dp is not None: dp /= self._g.Sb_kVA
                self._pr.setData2(
                    (e.ID, ConfigItem("Name", EditMode.ENTRY, "Name of the ESS")),
                    (e.BusID, ConfigItem("Bus", EditMode.COMBO, "Bus to which the ESS is connected", combo_values=self._g.BusNames)),
                    (pos[0], ConfigItem(name0, EditMode.ENTRY, desc0)),
                    (pos[1], ConfigItem(name1, EditMode.ENTRY, desc1)),
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
            if self._item_editing is not None:
                self._property_values = self._pr.getAllData()
                self._pr.enable_delete(True)
            if itm.type in ('bus', 'gen', 'pvw', 'ess') or (itm.type == 'node' and self.__rnet_editable):
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
    
    def __move_gen(self, i:int, e:GenLike, newLL:Tuple[float, float] = (-1, -1), newPlotXY:Tuple[float, float] = (0, 0), move_gen:bool=True):
        x0, y0 = self.convRealXY2PlotXY(e.x, e.y)
        if newLL != (-1, -1):
            newPlotXY = self.convLL2PlotXY(*newLL)
        x1, y1 = newPlotXY
        e.x, e.y = self.convPlotXY2RealXY(*newPlotXY)
        dx, dy = x1 - x0, y1 - y0
        if move_gen: self._cv.move(i, dx, dy)
        self._cv.move(i-2, dx, dy)
        assert self._g is not None
        self.__replot_genline(i-1, e, self._g.Bus(e.BusID))
    
    def __replot_genline(self, i:int, e:GenLike, b:Bus):
        x0, y0 = self.convRealXY2PlotXY(e.x, e.y)
        x1, y1 = self.convRealXY2PlotXY(b.x, b.y)
        self._cv.coords(i, x0, y0, x1, y1)
    
    def __move_line(self, i:int, e:Line):
        assert self._g is not None
        x_from, y_from = self._g.Bus(e.fBus).pos
        p_from = self.convRealXY2PlotXY(x_from, y_from)
        x_to, y_to = self._g.Bus(e.tBus).pos
        p_to = self.convRealXY2PlotXY(x_to, y_to)
        self._cv.coords(i, p_from[0], p_from[1], p_to[0], p_to[1])
    
    def __move_edge(self, i:int, e:Edge):
        assert self._r is not None
        (x0, y0), (x1, y1) = self._r.get_offset_shape(e.name)
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
            lid = self._items.getID(l.name, "edge")
            if lid is not None:
                self.__move_edge(lid, l)

    def __move_bus(self, i:int, e:Bus, newLL:Tuple[float, float] = (-1, -1), newPlotXY:Tuple[float, float] = (0, 0), move_bus:bool=True):
        assert self._r is not None
        x0, y0 = self.convRealXY2PlotXY(e.x, e.y)
        if newLL != (-1, -1):
            x1, y1 = self.convLL2PlotXY(*newLL)
            e.x, e.y = self.convPlotXY2RealXY(x1, y1)
        else:
            x1, y1 = newPlotXY
            e.x, e.y = self.convPlotXY2RealXY(x1, y1)
        
        dx, dy = x1 - x0, y1 - y0
        if move_bus:
            self._cv.move(i, dx, dy)
        self._cv.move(i-1, dx, dy)
        assert self._g is not None
        for g in self._g.GensAtBus(e.ID):
            gid = self._items.queryID(g.ID, "gen")
            self.__replot_genline(gid-1, g, e)
        for l in chain(self._g._ladjfb[e.ID], self._g._ladjtb[e.ID]):
            lid = self._items.queryID(l.ID, "line")
            self.__move_line(lid, l)

    @staticmethod
    def __chk(s:str):
        s = s.strip().lower()
        if s == "" or s == "none": return None
        else: return s
    
    def __finish_edit(self):
        """One completed property change is one undoable transaction."""
        e = self._item_editing
        if e is None or (isinstance(e, (Edge, Node)) and not self.__rnet_editable):
            return
        values = self._pr.getAllData()
        if values == self._property_values:
            return
        kind = 'road' if isinstance(e, (Edge, Node)) else 'grid'
        before = self._snapshot(kind)
        try:
            ok = self._apply_property_edit()
        except Exception as exc:
            self._restore_snapshot(kind, before)
            MB.showerror(_L['ERROR'], str(exc))
            return
        if not ok:
            # Validation must not leave a partially edited model behind.
            self._restore_snapshot(kind, before)
            return
        self._record_change(kind, before)
        self._property_values = values

    def _apply_property_edit(self):
        e = self._item_editing
        # Property changes to a SUMO node/edge must never mutate the road net.
        # This guard does not affect editing the electrical grid.
        if isinstance(e, (Edge, Node)) and not self.__rnet_editable:
            return False
        if e is None:
            return False
        ret = self._pr.getAllData()
        i = self._item_editing_id
        road_geometry_changed = False
        
        if isinstance(e, Edge):
            assert self._r is not None
            if ret['Name'] != e.name and ret['Name'] in self._r.edge_ids:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return False
            e.length = float(ret['Length'])
            e.lanes = int(ret['Lanes'])
            e.speed_limit = float(ret['Speed limit'])
            if e.name != ret['Name']:
                old_name = e.name
                self.UnlocateEdge(old_name)
                self._Redges.pop(old_name, None)
                self._r.rename_edge(old_name, ret['Name'])
                self._items.set_desc(i, ret['Name'])
                self._Redges[e.name] = i
                self.LocateEdge(e.name, 'purple')
                road_geometry_changed = True
            if ret["From"] != e.from_node.name or ret["To"] != e.to_node.name:
                node_ids = set(self._r.node_ids)
                if ret["From"] not in node_ids:
                    MB.showerror("Error", f"Node {ret['From']} does not exist.")
                    return False
                if ret["To"] not in node_ids:
                    MB.showerror("Error", f"Node {ret['To']} does not exist.")
                    return False
                self._r.update_edge(e.name, ret["From"], ret["To"])
                self.__move_edge(i, e)
                road_geometry_changed = True
        elif isinstance(e, Node):
            assert self._r is not None
            if ret['Name'] != e.name and ret['Name'] in self._r.node_ids:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return False
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret['Latitude'])
                plotX, plotY = self.convLL2PlotXY(nLon, nLat)
            else:
                x, y = float(ret['X']), float(ret['Y'])
                plotX, plotY = self.convRealXY2PlotXY(x, y)
            self.__move_node(i, e, plotX, plotY)
            road_geometry_changed = True
            if e.name != ret['Name']:
                self._r.update_node(e.name, ret['Name'])
                self._items.set_desc(i, ret['Name'])
        elif isinstance(e, Bus):
            assert self._g is not None and self._r is not None
            if ret['Name'] != e.ID and ret['Name'] in self._g.BusNames:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return False
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
                self.__move_bus(i, e, newPlotXY=(x, y))
            old_bus_id = e.ID
            self._g.ChangeBusID(old_bus_id, ret['Name'])
            if old_bus_id != ret['Name']:
                # In FPowerKit versions where ChangeBusID updates only lines
                # and conventional generators, keep the other GUI-managed
                # equipment references consistent as well.
                for relation in ('_patb', '_eatb'):
                    mapping = getattr(self._g, relation, None)
                    if mapping is not None and old_bus_id in mapping:
                        mapping[ret['Name']] = mapping.pop(old_bus_id)
                for equipment in chain(self._g.PVWinds, self._g.ESSs):
                    if equipment.BusID == old_bus_id:
                        equipment._bus = ret['Name']
            self._items.set_desc(i, ret['Name'])
            self._cv.itemconfig(i-1, text = e.ID)
        elif isinstance(e, Generator):
            assert self._g is not None and self._r is not None
            e.CostA = self._float2func(ret['CostA'])
            e.CostB = self._float2func(ret['CostB'])
            e.CostC = self._float2func(ret['CostC'])
            self._g.ChangeGenBus(e.ID, ret['Bus'])
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret["Latitude"])
                self.__move_gen(i, e, newLL=(nLon, nLat))
            else:
                x = float(ret['X'])
                y = float(ret['Y'])
                self.__move_gen(i, e, newPlotXY=(x, y))
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
            assert self._g is not None and self._r is not None
            self._g.ChangePVWindBus(e.ID, ret['Bus'])
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret["Latitude"])
                self.__move_gen(i, e, newLL=(nLon, nLat))
            else:
                x = float(ret['X'])
                y = float(ret['Y'])
                self.__move_gen(i, e, newPlotXY=(x, y))
            p = self.__chk(ret['P/pu'])
            e.P = self._float2func(p) if p is not None else 0
            pf = float(ret['Power Factor'])
            if not 0.0 < pf <= 1.0:
                raise ValueError('Power Factor must be in (0, 1].')
            e.PF = pf
            if ret['Tag'] not in ('PV', 'Wind'):
                raise ValueError('Tag must be PV or Wind.')
            e.Tag = ret['Tag']
            e.CC = float(ret['Curtail Cost'])
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
            assert self._g is not None and self._r is not None
            if self._r.hasGeoProj():
                nLon = float(ret['Longitude'])
                nLat = float(ret["Latitude"])
                self.__move_gen(i, e, newLL=(nLon, nLat))
            else:
                x = float(ret['X'])
                y = float(ret['Y'])
                self.__move_gen(i, e, newPlotXY=(x, y))
            e.Cap = float(ret['Capacity/MWh']) / self._g.Sb_MVA
            e._elec = float(ret['SOC']) * e.Cap
            e.EC = float(ret['Ec'])
            e.ED = float(ret['Ed'])
            e.MaxPc = float(ret['Max Pc/kW']) / self._g.Sb_kVA
            e.MaxPd = float(ret['Max Pd/kW']) / self._g.Sb_kVA
            e._policy = ESSPolicy(ret['Policy'])
            # Newly placed manual ESS has no time ranges (None). Preserve
            # that valid optional value when editing any other ESS property.
            ctime, dtime = self.__chk(ret['CTime']), self.__chk(ret['DTime'])
            e._ctime = RangeList(eval(ctime)) if ctime is not None else None
            e._dtime = RangeList(eval(dtime)) if dtime is not None else None
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
        if road_geometry_changed:
            self._draw_async(center=False, rebuild_road=True)
        return True

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
            if isinstance(self._drag["item"], int) and (dx or dy):
                self._drag['moved'] = True
    
    def _onRelease(self, event):
        if not self.__en: return
        i = self._drag["item"]
        if isinstance(i,int) and self._drag.get('moved'):
            item_type = self._items[i].type
            kind = 'road' if item_type == 'node' else 'grid'
            before = self._snapshot(kind)
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
                self.__move_gen(i, e, newLL = (nLon, nLat), move_gen = False)
            elif self._items[i].type == 'pvw':
                assert self._g is not None
                e = self._g.PVWind(self._items[i].desc)
                self.__move_gen(i, e, newLL = (nLon, nLat), move_gen = False)
            elif self._items[i].type == 'ess':
                assert self._g is not None
                e = self._g.ESS(self._items[i].desc)
                self.__move_gen(i, e, newLL = (nLon, nLat), move_gen = False)
            elif self._items[i].type == 'node':
                assert self._r is not None
                e = self._r.nodes[self._items[i].desc]
                self.__move_node(i, e, cx, cy, False)
                self._draw_async(center=False, rebuild_road=True)
            self._record_change(kind, before)
            if kind == 'grid':
                # Click selection refreshes the property panel at the new position.
                self._onLClick(event)
            else:
                self._clear_selection()
        elif i == 'all':
            self._schedule_viewport_render(0)
        self._drag["item"] = None
        self._drag['moved'] = False
        
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

    def _onCanvasConfigure(self, event):
        size = (event.width, event.height)
        if size != self._last_canvas_size:
            self._last_canvas_size = size
            self._schedule_viewport_render(40)

    def _schedule_viewport_render(self, delay_ms:Optional[int]=None):
        if self._road_scene is None:
            return
        if delay_ms is None:
            delay_ms = self.VIEWPORT_RENDER_DELAY_MS
        if self._viewport_after_id is not None:
            try: self.after_cancel(self._viewport_after_id)
            except: pass
        self._viewport_after_id = self.after(delay_ms, self._render_viewport)

    def _viewport_bbox(self):
        k = max(self._scale['k'], 1e-12)
        width = max(self._cv.winfo_width(), 1)
        height = max(self._cv.winfo_height(), 1)
        pad = 12.0 / k
        x0 = (0.0 - self._scale['x']) / k - pad
        y0 = (0.0 - self._scale['y']) / k - pad
        x1 = (width - self._scale['x']) / k + pad
        y1 = (height - self._scale['y']) / k + pad
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def _content_bounds(self):
        if self._road_scene is None:
            return None
        minx, miny, maxx, maxy = self._road_scene.bounds
        if self._g is not None:
            positions = [(b.x, -b.y) for b in self._g.Buses]
            positions.extend((g.x, -g.y) for g in chain(self._g.Gens, self._g.PVWinds, self._g.ESSs))
            if positions:
                minx = min(minx, min(p[0] for p in positions))
                miny = min(miny, min(p[1] for p in positions))
                maxx = max(maxx, max(p[0] for p in positions))
                maxy = max(maxy, max(p[1] for p in positions))
        return minx, miny, maxx, maxy
    
    def _center(self):
        bbox = self._content_bounds()
        if bbox is None: return
        minx, miny, maxx, maxy = bbox
        cw = max(maxx - minx, 1.0)
        ch = max(maxy - miny, 1.0)
        ww = max(self._cv.winfo_width(), 100)
        wh = max(self._cv.winfo_height(), 100)
        k = min(max(ww - 50, 100) / cw, max(wh - 50, 100) / ch)
        self._scale['k'] = k
        self._scale['x'] = (ww - (minx + maxx) * k) / 2
        self._scale['y'] = (wh - (miny + maxy) * k) / 2
        self._scale_cnt = 0
        self._render_viewport()
    
    def LocateEdge(self, edge:str, color:str='red'):
        '''Locate an edge by highlighting it in given color, red by default'''
        self._located_edges.add(edge)
        if edge not in self._Redges and self._road_scene is not None:
            visual = self._road_scene.edge_by_name.get(edge)
            if visual is not None:
                pid = self._draw_road_edge_visual(visual, color=color, width=5)
                self._Redges[edge] = pid
        if edge in self._Redges:
            pid = self._Redges[edge]
            self._cv.itemconfig(pid, fill=color, width=5)
    
    def LocateEdges(self, edges:Iterable[str], color:str='red'):
        '''Locate a set of edges by highlighting them in given color, red by default'''
        for edge in edges:
            self.LocateEdge(edge, color)
    
    def UnlocateAllEdges(self):
        '''Unlocate all edges that are located'''
        for edge in tuple(self._located_edges):
            self.UnlocateEdge(edge)
        self._located_edges.clear()
    
    def UnlocateEdge(self, edge:str):
        '''Unlocate an edge by restoring its color'''
        self._located_edges.discard(edge)
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

    def _draw_road_node_visual(self, node:RoadNodeVisual, radius:float):
        x = node.x * self._scale['k'] + self._scale['x']
        y = node.y * self._scale['k'] + self._scale['y']
        pid = self._cv.create_oval(
            x-radius, y-radius, x+radius, y+radius,
            fill='gray', width=1, tags=('road', 'road-node')
        )
        self._items[pid] = itemdesc("node", node.name)
        return pid

    def _draw_road_edge_visual(
            self, edge:RoadEdgeVisual, color:Optional[str]=None,
            width:Optional[float]=None):
        k = self._scale['k']; ox = self._scale['x']; oy = self._scale['y']
        pid = self._cv.create_line(
            edge.x0*k+ox, edge.y0*k+oy, edge.x1*k+ox, edge.y1*k+oy,
            fill=color or edge.color, width=width or edge.width,
            tags=('road', 'road-edge')
        )
        self._items[pid] = itemdesc("edge", edge.name)
        self._Redges[edge.name] = pid
        return pid

    @staticmethod
    def _prepare_road_scene(generation:int, roadnet:RoadNet,
            world_colors, center:bool):
        return generation, RoadScene.build(roadnet, world_colors), center

    def _draw_async(self, scale:float=1.0, dx:float=0.0, dy:float=0.0,
            center:bool=True, after:OAfter=None, rebuild_road:bool=True):
        if self._r is None:
            if after: after()
            return
        if after:
            self._draw_callbacks.append(after)
        if not rebuild_road and self._road_scene is not None:
            if center: self._center()
            else: self._render_viewport()
            self.__en = True
            callbacks, self._draw_callbacks = self._draw_callbacks, []
            for callback in callbacks: callback()
            return
        self.__en = False
        self._scene_generation += 1
        generation = self._scene_generation
        self._Q.submit(
            "road_scene_ready", self._prepare_road_scene,
            generation, self._r, self._world_colors, center
        )

    def _on_road_scene_ready(self, generation:int, scene:RoadScene, center:bool):
        if generation != self._scene_generation:
            return
        self._road_scene = scene
        span = max(scene.bounds[2] - scene.bounds[0], scene.bounds[3] - scene.bounds[1])
        self._node_radius = max(span / 200.0, 1.0)
        if center:
            self._center()
        else:
            self._render_viewport()
        self.__en = True
        callbacks, self._draw_callbacks = self._draw_callbacks, []
        for callback in callbacks:
            callback()
    
    def _draw_line(self,x1,y1,x2,y2,color,lw,name):
        self._items[self._cv.create_line(
            x1,y1,x2,y2,width=lw,fill=color,tags=('grid', 'grid-line')
        )] = itemdesc('line', name)
    
    def _draw_gen(self,x,y,r,color,lw,name,xb,yb,tp):
        assert tp in ('gen', 'pvw', 'ess')
        self._items[self._cv.create_text(
            x+1.8*r,y+1.8*r,text=name,tags=('grid', 'grid-label')
        )] = itemdesc(tp+'text', name+".text")
        self._items[self._cv.create_line(
            x, y, xb, yb, width=lw,tags=('grid', 'grid-connection')
        )] = itemdesc(tp+"conn", name+".conn")
        if tp == 'gen':
            self._items[self._cv.create_oval(
                x-r, y-r, x+r, y+r, fill=color, width=lw,tags=('grid', 'grid-generator')
            )] = itemdesc(tp, name)
        elif tp == 'pvw':
            self._items[self._cv.create_polygon(
                x, y-r, x-r, y+r, x+r, y+r, fill=color,
                outline='black', width=lw,tags=('grid', 'grid-pvw')
            )] = itemdesc(tp, name)
        else:
            self._items[self._cv.create_rectangle(
                x-r, y-r, x+r, y+r, fill=color, width=lw,tags=('grid', 'grid-ess')
            )] = itemdesc(tp, name)

    def _draw_bus(self,x,y,r,color,lw,name):
        self._items[self._cv.create_text(
            x+1.8*r,y+1.8*r,text=name,tags=('grid', 'grid-label')
        )] = itemdesc('bustext', name+".text")
        self._items[self._cv.create_rectangle(
            x-0.5*r, y-r, x+0.5*r, y+r,
            fill=color, width=lw,tags=('grid', 'grid-bus')
        )] = itemdesc("bus", name)

    def _refresh_editing_canvas_id(self):
        editing = self._item_editing
        if editing is None:
            return
        if isinstance(editing, Edge): cls, name = 'edge', editing.name
        elif isinstance(editing, Node): cls, name = 'node', editing.name
        elif isinstance(editing, Bus): cls, name = 'bus', editing.ID
        elif isinstance(editing, Generator): cls, name = 'gen', editing.ID
        elif isinstance(editing, PVWind): cls, name = 'pvw', editing.ID
        elif isinstance(editing, ESS): cls, name = 'ess', editing.ID
        elif isinstance(editing, Line): cls, name = 'line', editing.ID
        else: return
        canvas_id = self._items.getID(name, cls)
        if canvas_id is not None:
            self._item_editing_id = canvas_id

    def _render_viewport(self):
        self._viewport_after_id = None
        if self._road_scene is None:
            return
        self._cv.delete('all')
        self._preview_id = None
        self._items = BIDC(["bus", "bustext", "gen", "gentext", "genconn", "line", "edge", "node"])
        self._Redges = {}
        road_edges, road_nodes = self._road_scene.select(
            self._viewport_bbox(),
            self._max_visible_road_edges,
            self._max_visible_road_nodes,
            self._located_edges,
        )
        if isinstance(self._item_editing, Node):
            selected_node = self._road_scene.node_by_name.get(self._item_editing.name)
            if selected_node is not None and all(n.name != selected_node.name for n in road_nodes):
                road_nodes = list(road_nodes) + [selected_node]
        for edge in road_edges:
            if edge.name in self._located_edges:
                self._draw_road_edge_visual(edge, color='purple', width=5)
            else:
                self._draw_road_edge_visual(edge)
        node_radius = max(1.0, min(6.0, self._node_radius * self._scale['k'] / 2))
        for node in road_nodes:
            self._draw_road_node_visual(node, node_radius)

        r = max(3.0, min(30.0, self._node_radius * self._scale['k']))
        if self._g is not None:
            for line in self._g.Lines:
                x1, y1 = self.convRealXY2PlotXY(*self._g.Bus(line.fBus).pos)
                x2, y2 = self.convRealXY2PlotXY(*self._g.Bus(line.tBus).pos)
                self._draw_line(x1, y1, x2, y2, 'black', 2, line.ID)
            
            for g in chain(self._g.Gens, self._g.PVWinds, self._g.ESSs):
                tp = g.__class__.__name__.lower()[:3]
                xb, yb = self.convRealXY2PlotXY(*self._g.Bus(g.BusID).pos)
                x, y = self.convRealXY2PlotXY(g.x, g.y)
                self._draw_gen(x, y, r, 'white', 2, g.ID, xb, yb, tp)

            for b in self._g.Buses:
                x, y = self.convRealXY2PlotXY(b.x, b.y)
                self._draw_bus(x, y, r, 'white', 2, b.ID)
        self._refresh_editing_canvas_id()

    def _draw(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True):
        """Synchronous compatibility entry point used by older integrations."""
        if self._r is None: return
        self._road_scene = RoadScene.build(self._r, self._world_colors)
        self._scale = {'k':scale, 'x':dx, 'y':dy}
        if center: self._center()
        else: self._render_viewport()
    
    def save(self, grid_path:str, net_path:str):
        '''Save the current network to files'''
        if self._g:
            self._g.saveFileXML(grid_path)
        if self._r and not self._r.is_from_sumo():
            self._r.save(net_path)
        self._saved_revision = self._revision
        self.saved = True

__all__ = ["NetworkPanel", "itemdesc", "BIDC", "GenLike", "PointList", "OAfter", "OESet"]
