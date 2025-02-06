from dataclasses import dataclass
from itertools import chain
from queue import Queue
import queue
import threading
from tkinter import messagebox as MB
from feasytools import SegFunc, ConstFunc, TimeFunc
from typing import Any, Callable, Iterable, Optional, Union
from v2sim import ELGraph, Edge
from fpowerkit import Bus, Line, Generator
from fpowerkit import Grid as fGrid
from .controls import EditMode, PropertyPanel
from .view import *


PointList = list[tuple[float, float]]
OESet = Optional[set[str]]
OAfter = Optional[Callable[[], None]]

@dataclass
class itemdesc:
    type:str
    desc:Any

class BIDC:
    def __init__(self, categories:Iterable[str]):
        self._cls = list(categories)
        self._mp:dict[int, tuple[str, Any]] = {}
        self._rv:dict[Any, int] = {}
    
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
    
    def __getitem__(self, id:int):
        return itemdesc(*self._mp[id])
    
    def __setitem__(self, id:int, val:Union[itemdesc,tuple[str, Any]]):
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
    def __init__(self, master, roadnet:Optional[ELGraph]=None, grid:Optional[Grid]=None, **kwargs):
        super().__init__(master, **kwargs)

        self._cv = Canvas(self, bg='white')
        self._cv.pack(side='left',anchor='center',fill=BOTH, expand=1)
        self._cv.bind("<MouseWheel>", self._onMouseWheel)
        self._cv.bind("<Button-1>", self._onLClick)
        self._cv.bind("<Button-3>", self._onRClick)
        self._cv.bind("<B1-Motion>", self._onMotion)
        self._cv.bind("<B3-Motion>", self._onMotion)
        self._cv.bind("<ButtonRelease-1>", self._onRelease)
        self._cv.bind("<ButtonRelease-3>", self._onRelease)

        self._pr = PropertyPanel(self, {})
        self._pr.tree.AfterFunc = self.__finish_edit
        self._pr.pack(side='right',anchor='e',fill=Y, expand=0)
        self.clear()

        if roadnet is not None:
            self.setRoadNet(roadnet)
        
        if grid is not None:
            self.setGrid(grid)
    
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
    
    def convLL2XY(self, lon:float, lat:float) -> tuple[float, float]:
        '''Convert longitude and latitude to canvas coordinates'''
        if self._r:
            try:
                x, y = self._r.Net.convertLonLat2XY(lon, lat)
            except:
                x, y = lon, lat
        else:
            x, y = lon, lat
        return x * self._scale['k'] + self._scale['x'], y * self._scale['k'] + self._scale['y']
    
    def convXY2LL(self, x:float, y:float) -> tuple[float, float]:
        '''Convert canvas coordinates to longitude and latitude'''
        x = (x - self._scale['x'])/self._scale['k']
        y = (y - self._scale['y'])/self._scale['k']
        if self._r is None: return (x, y)
        try:
            return self._r.Net.convertXY2LonLat(x, y)
        except:
            return (x, y)
    
    def clear(self):
        self._cv.delete('all')
        self._scale_cnt = 0
        self._items:BIDC = BIDC(["bus", "bustext", "gen", "gentext", "genconn", "line", "edge"])
        self._Redges:dict[str, int] = {}
        self._located_edges:set[str] = set()
        self._drag = {'item': None,'x': 0,'y': 0}
        self._scale = {'k':1.0, 'x':0, 'y':0}
        self._r = None
        self._g = None
        self.__en = False
    
    @property
    def RoadNet(self) -> Optional[ELGraph]:
        return self._r
    
    def setRoadNet(self, roadnet:ELGraph, repaint:bool=True, async_:bool=False, after:OAfter=None):
        '''
        Set the road network to be displayed
            roadnet: ELGraph, the road network to be displayed
            repaint: bool, whether to repaint the network.
            async_: bool, whether to repaint the network asynchronously.
            after: Optional[Callable[[], None]], the function to be called after the network is repainted.
                If after is None, this repaint operation will block the main thread!
                If after is not None, this repaint operation will be done asynchronously.
        '''
        assert isinstance(roadnet, ELGraph)
        self._r = roadnet
        if repaint: 
            if async_:
                self._draw_async(after=after)
            else:
                self._draw()
                after and after()
    
    @property
    def Enabled(self) -> bool:
        return self.__en

    @Enabled.setter
    def Enabled(self, v:bool):
        self.__en = v
    
    @property
    def Grid(self) -> Optional[fGrid]:
        return self._g
    
    def setGrid(self, grid:fGrid, repaint:bool=True, async_:bool=False):
        '''
        Set the power grid to be displayed
            grid: ELGraph, the road network to be displayed
            repaint: bool, whether to repaint the network.
                This repaint operation will block the main thread!
        '''
        assert isinstance(grid, fGrid)
        self._g = grid
        if repaint: 
            if async_:
                self._draw_async()
            else:
                self._draw()
    
    def _onLClick(self, event):
        if not self.__en: return
        x, y = event.x, event.y
        nr_item = self._cv.find_closest(x, y)
        ovl_item = self._cv.find_overlapping(x-5, y-5, x+5, y+5)
        if nr_item and nr_item[0] in ovl_item:
            clicked_item = nr_item[0]
            self.UnlocateAllEdges()
            itm = self._items[clicked_item]
            if itm.type == 'bus':
                self._drag['item'] = clicked_item
                self._drag["x"] = event.x
                self._drag["y"] = event.y
            if itm.type == "edge":
                self._pr.setData({
                    "Name":itm.desc, 
                    "Has FCS": itm.desc in self._r.FCSNames,
                    "Has SCS": itm.desc in self._r.SCSNames,
                }, default_edit_mode=EditMode.DISABLED)
                self.LocateEdge(itm.desc, 'purple')
            elif itm.type in ("bus", "bustext"):
                if itm.type == 'bustext':
                    b = self._g.Bus(itm.desc.removesuffix(".text"))
                else:
                    b = self._g.Bus(itm.desc)
                self._pr.setData({
                    "Name":b.ID,
                    "Longitude":b.Lon,
                    "Latitude":b.Lat,
                    "Pd/pu":b.Pd,
                    "Qd/pu":b.Qd,
                }, default_edit_mode=EditMode.ENTRY,
                edit_modes={
                    "Pd/pu":EditMode.SEGFUNC,
                    "Qd/pu":EditMode.SEGFUNC,
                })
                self._item_editing = b
                self._item_editing_id = clicked_item if itm.type == 'bus' else clicked_item + 1
            elif itm.type == "line":
                l = self._g.Line(itm.desc)
                self._pr.setData({
                    "Name":l.ID,
                    "From Bus":l.fBus,
                    "To Bus":l.tBus,
                    "R/pu":l.R,
                    "X/pu":l.X,
                }, default_edit_mode=EditMode.ENTRY,
                edit_modes={
                    "From Bus":EditMode.COMBO,
                    "To Bus":EditMode.COMBO
                }, edit_modes_kwargs={
                    "From Bus": {"combo_values":self._g.BusNames},
                    "To Bus": {"combo_values":self._g.BusNames}
                })
                self._item_editing = l
                self._item_editing_id = clicked_item
            elif itm.type in ("gen", "gentext", "genconn"):
                if itm.type == 'gentext':
                    g = self._g.Gen(itm.desc.removesuffix(".text"))
                elif itm.type == 'genconn':
                    g = self._g.Gen(itm.desc.removesuffix(".conn"))
                else:
                    g = self._g.Gen(itm.desc)
                self._pr.setData({
                    "Name":g.ID,
                    "Bus":g.BusID,
                    "Pmax/pu":g.Pmax,
                    "Pmin/pu":g.Pmin,
                    "Qmax/pu":g.Qmax,
                    "Qmin/pu":g.Qmin,
                    "CostA":g.CostA,
                    "CostB":g.CostB,
                    "CostC":g.CostC
                }, default_edit_mode=EditMode.SEGFUNC, desc={
                    "CostA": "Unit = $/(pu pwr·h)^2",
                    "CostB": "Unit = $/(pu pwr·h)",
                    "CostC": "Unit = $"
                }, edit_modes={
                    "Name":EditMode.ENTRY,
                    "Bus":EditMode.COMBO
                }, edit_modes_kwargs={
                    "Bus": {"combo_values":self._g.BusNames}
                })
                self._item_editing = g
                if itm.type == "gen":
                    self._item_editing_id = clicked_item
                elif itm.type == "genconn":
                    self._item_editing_id = clicked_item + 1
                else:
                    self._item_editing_id = clicked_item + 2
            else:
                self._pr.setData({})
            self._pr.tree.show_title(f"Type: {itm.type} (ID = {clicked_item})")

    @staticmethod
    def _float2func(v: str):
        v = eval(v)
        if isinstance(v, (float, int)):
            return ConstFunc(v)
        elif isinstance(v, TimeFunc):
            return v
        else:
            return SegFunc(v)

    def __move_gen(self, i:int, p_old:tuple[float,float], p_new:tuple[float, float]):
        x0, y0 = self.convLL2XY(*p_old)
        x1, y1 = self.convLL2XY(*p_new)
        dx, dy = x1 - x0, y1 - y0
        self.__move_gen2(i, dx, dy)
    
    def __move_gen2(self, i:int, dx:float,dy:float):
        self._cv.move(i, dx, dy)
        self._cv.move(i-1, dx, dy)
        self._cv.move(i-2, dx, dy)
    
    def __move_line(self, i:int, e:Line):
        latf1, lonf1 = self._g.Bus(e.fBus).position
        pf1 = self.convLL2XY(lonf1,latf1)
        latt1, lont1 = self._g.Bus(e.tBus).position
        pt1 = self.convLL2XY(lont1,latt1)
        self._cv.coords(i, pf1[0], pf1[1], pt1[0], pt1[1])
    
    def __move_bus(self, i:int, e:Bus, nLon:float, nLat:float, move_bus:bool=True):
        x0, y0 = self.convLL2XY(e.Lon, e.Lat)
        x1, y1 = self.convLL2XY(nLon, nLat)
        e.Lon = nLon
        e.Lat = nLat
        dx, dy = x1-x0, y1-y0
        if move_bus:
            self._cv.move(i, dx, dy)
        else:
            x2, y2, x3, y3 = self._cv.coords(i)
            self._cv.moveto(i, x1-(x3-x2)/2, y1-(y3-y2)/2)
        self._cv.move(i-1, dx, dy)
        for g in self._g.GensAtBus(e.ID):
            gid = self._items.queryID(g.ID)
            self.__move_gen2(gid, dx, dy)
        for l in chain(self._g._ladjfb[e.ID], self._g._ladjtb[e.ID]):
            lid = self._items.queryID(l.ID)
            self.__move_line(lid, l)

    def __finish_edit(self):
        ret = self._pr.getAllData()
        e = self._item_editing
        i = self._item_editing_id
        if isinstance(e, Bus):
            if ret['Name'] != e.ID and ret['Name'] in self._g.BusNames:
                MB.showerror("Error", f"New name duplicated: {ret['Name']}")
                return
            nLon = float(ret['Longitude'])
            nLat = float(ret["Latitude"])
            e.Pd = self._float2func(ret['Pd/pu'])
            e.Qd = self._float2func(ret['Qd/pu'])
            self.__move_bus(i, e, nLon, nLat)
            self._g.ChangeBusID(e.ID, ret['Name'])
            e.ID = ret['Name']
            self._cv.itemconfig(i-1, text = e.ID)
        
        elif isinstance(e, Generator):
            e.CostA = ret['CostA']
            e.CostB = ret['CostB']
            e.CostC = ret['CostC']
            b = self._g.Bus(e.BusID)
            p0 = (b.Lon, b.Lat)
            self._g.ChangeGenBus(e.ID, ret['Bus'])
            b = self._g.Bus(e.BusID)
            p1 = (b.Lon, b.Lat)
            self.__move_gen(i, p0, p1)
            e.Pmax = ret['Pmax/pu']
            e.Qmax = ret['Qmax/pu']
            e.Pmin = ret['Pmin/pu']
            e.Qmin = ret['Qmin/pu']
            self._g.ChangeGenID(e.ID, ret['Name'])
            e.ID = ret['Name']
        elif isinstance(e, Line):
            self._g.ChangeLineFromBus(e.ID, ret['From Bus'])
            self._g.ChangeLineToBus(e.ID, ret['To Bus'])
            e.R = ret['R/pu']
            e.X = ret['X/pu']
            self.__move_line(i, e)
            self._g.ChangeLineID(e.ID, ret['Name'])
            e.ID = ret['Name']

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
    
    def _onRelease(self, event):
        if not self.__en: return
        i = self._drag["item"]
        self._drag["item"] = None
        if isinstance(i,int) and self._items[i].type == 'bus':
            nLon, nLat = self.convXY2LL(event.x, event.y)
            e = self._g.Bus(self._items[i].desc)
            self.__move_bus(i, e, nLon, nLat, False)        
    
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
        
    def __get_edge_prop(self, edge:str) -> tuple[str, float]:
        if edge in self._r.FCSNames:
            return ("darkblue",3) if edge in self._r.EdgeIDSet else ("darkgray",3)
        elif edge in self._r.SCSNames:
            return ("blue",2) if edge in self._r.EdgeIDSet else ("gray",2)
        else:
            return ("blue",1) if edge in self._r.EdgeIDSet else ("gray",1)
    
    def __update_gui(self):
        LIMIT = 50
        try:
            cnt = 0
            while cnt < LIMIT:
                cnt += 1
                t, x = self.__q.get_nowait()
                if t == 'c':
                    self._center()
                elif t == 'r':
                    self._draw_edge(*x)
                elif t == 'b':
                    self._draw_bus(*x)
                elif t == 'l':
                    self._draw_line(*x)
                elif t == 'g':
                    self._draw_gen(*x)
                elif t == 'a':
                    x and x()
                    self.__en = True
        except queue.Empty:
            pass
        if not self.__q_closed or cnt >= LIMIT:
            self._cv.after('idle', self.__update_gui)

    def _draw_edge(self, shape:PointList, color:str, lw:float, ename:str):
        pid = self._cv.create_line(shape, fill=color, width=lw)
        self._items[pid] = itemdesc("edge", ename)
        self._Redges[ename] = pid
    
    def _draw_async(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True, after:OAfter=None):
        self.__q = Queue()
        self.__q_closed = False
        threading.Thread(target=self._draw, args=(scale,dx,dy,center,True,after), daemon=True).start()
        self._cv.after(10, self.__update_gui)
    
    def _draw_line(self,x1,y1,x2,y2,color,lw,name):
        self._items[self._cv.create_line(x1,y1,x2,y2,width=lw,fill=color)] = itemdesc('line', name)
    
    def _draw_gen(self,x,y,r,color,lw,name):
        self._items[self._cv.create_text(x+5*r,y+1.5*r,text=name)] = itemdesc('gentext', name+".text")
        self._items[self._cv.create_line(x, y, x+3*r, y, width=lw)] = itemdesc("genconn", name+".conn")
        self._items[self._cv.create_oval(x+2*r, y-r, x+4*r, y+r, fill=color, width=lw)] = itemdesc("gen", name)

    def _draw_bus(self,x,y,r,color,lw,name):
        self._items[self._cv.create_text(x+1.5*r,y+1.5*r,text=name)] = itemdesc('bustext', name+".text")
        self._items[self._cv.create_rectangle(x-r, y-r, x+r, y+r, fill=color, width=lw)] = itemdesc("bus", name)
    
    def _draw(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True, async_:bool=False, after:OAfter=None):
        if self._r is None: return
        self.__en = False
        self._cv.delete('all')
        minx, miny, maxx, maxy = 1e100, 1e100, -1e100, -1e100

        if self._r.Net is not None:
            minx, miny, maxx, maxy = self._r.Net.getBoundary()
            edges = self._r.Net.getEdges()
            for e in edges:
                e: Edge
                ename:str = e.getID()
                shape = e.getShape()
                if shape is None:
                    raise ValueError(f"Edge {ename} has no shape")
                shape:PointList
                c, lw = self.__get_edge_prop(ename)
                shape = [(p[0]*scale+dx,p[1]*scale+dy) for p in shape]
                t = (shape, c, lw, ename)
                if async_:
                    self.__q.put(('r',t))
                else:
                    self._draw_edge(*t)
            
        if self._g is not None:
            if minx > maxx or miny > maxy:
                r = 5
                cx, cy = 0
            else:
                r = max(maxx-minx, maxy-miny)/100
                cx = minx
                cy = miny
            locless = 0
            for b in self._g.Buses:
                if b.Lon is None or b.Lat is None:
                    x,y = cx+(locless//20)*7*r, cy+(locless%20)*7*r
                    locless += 1
                    b.Lon, b.Lat = self.convXY2LL(x,y)
                    print(f"Bus {b.ID} has no location, set to Lon, Lat = ({b.Lon:.6f},{b.Lat:.6f})")
            for line in self._g.Lines:
                lat1, lon1 = self._g.Bus(line.fBus).position
                lat2, lon2 = self._g.Bus(line.tBus).position
                x1, y1 = self.convLL2XY(lon1, lat1)
                x2, y2 = self.convLL2XY(lon2, lat2)
                t = (x1, y1, x2, y2, 'black', 2, line.ID)
                if async_:
                    self.__q.put(('l',t))
                else:
                    self._draw_line(*t)
            for g in self._g.Gens:
                b = self._g.Bus(g.BusID)
                x, y = self.convLL2XY(b.Lon, b.Lat)
                t = (x, y, r, 'white', 2, g.ID)
                if async_:
                    self.__q.put(('g',t))
                else:
                    self._draw_gen(*t)
            for b in self._g.Buses:
                x, y = self.convLL2XY(b.Lon, b.Lat)
                t = (x, y, r, 'white', 2, b.ID)
                if async_:
                    self.__q.put(('b',t))
                else:
                    self._draw_bus(*t)
                    
        if async_:
            self.__q.put(('c', None))
            self.__q.put(('a', after))
            self.__q_closed = True
        else:
            if center: self._center()
            after and after()
            self.__en = True
    
    def saveGrid(self, path:str):
        '''Save the current grid to a file'''
        if self._g:
            self._g.saveFileXML(path)