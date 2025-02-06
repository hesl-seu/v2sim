from dataclasses import dataclass
from queue import Queue
import queue
import threading
import time
from typing import Any, Callable, Iterable, Optional
from v2sim import ELGraph, Edge
from fpowerkit import Bus, Line, PDNCases
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

class NetworkPanel(Frame):
    def __init__(self, master, roadnet:Optional[ELGraph]=None, grid:Optional[Grid]=None, **kwargs):
        super().__init__(master, **kwargs)

        self._cv = Canvas(self, bg='white')
        self._cv.pack(side='left',anchor='center',fill=BOTH, expand=1)
        self._cv.bind("<MouseWheel>", self._onMouseWheel)
        self._cv.bind("<Button-1>", self._onLClick)
        self._cv.bind("<Button-3>", self._onRClick)
        self._cv.bind("<B3-Motion>", self._onRMotion)
        self._cv.bind("<ButtonRelease-3>", self._onRRelease)

        self._pr = PropertyPanel(self, {})
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
        self._scale['x'] += dx
        self._scale['y'] += dy
    
    def convLL2XY(self, lon:float, lat:float) -> tuple[float, float]:
        '''Convert longitude and latitude to canvas coordinates'''
        if self._r is None: return (lon, lat)
        x, y = self._r.Net.convertLonLat2XY(lon, lat)
        return x * self._scale['k'] + self._scale['x'], y * self._scale['k'] + self._scale['y']
    
    def convXY2LL(self, x:float, y:float) -> tuple[float, float]:
        '''Convert canvas coordinates to longitude and latitude'''
        x = (x - self._scale['x'])/self._scale['k']
        y = (y - self._scale['y'])/self._scale['k']
        if self._r is None: return (x, y)
        return self._r.Net.convertXY2LonLat(x, y)
    
    def clear(self):
        self._cv.delete('all')
        self._scale_cnt = 0
        self._items:dict[int, itemdesc] = {}
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
    def Grid(self) -> Optional[Grid]:
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
            self.LocateEdge(self._items[clicked_item].desc, 'purple')
            itm = self._items[clicked_item]
            self._pr.tree.show_title(f"Type: {itm.type} (ID = {clicked_item})")
            if itm.type == "edge":
                self._pr.setData({
                    "Name":itm.desc, 
                    "Has FCS": itm.desc in self._r.FCSNames,
                    "Has SCS": itm.desc in self._r.SCSNames,
                }, default_edit_mode=EditMode.DISABLED)
            else:
                self._pr.setData({})

    def _onRClick(self, event):
        if not self.__en: return
        self._drag['item'] = 'all'
        self._drag["x"] = event.x
        self._drag["y"] = event.y
    
    def _onRMotion(self, event):
        if not self.__en: return
        if self._drag["item"]:
            x, y = event.x, event.y
            dx = x - self._drag["x"]
            dy = y - self._drag["y"]
            self.move(dx, dy, self._drag["item"])
            self._drag["x"] = x
            self._drag["y"] = y
    
    def _onRRelease(self, event):
        if not self.__en: return
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
                elif t == 'l':
                    shape, c, lw, ename = x
                    pid = self._cv.create_line(shape, fill=c, width=lw)
                    self._items[pid] = itemdesc("edge", ename)
                    self._Redges[ename] = pid
                elif t == 'a':
                    x and x()
                    self.__en = True
        except queue.Empty:
            pass
        if not self.__q_closed or cnt >= LIMIT:
            self._cv.after('idle', self.__update_gui)

    def _draw_async(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True, after:OAfter=None):
        self.__q = Queue()
        self.__q_closed = False
        threading.Thread(target=self._draw, args=(scale,dx,dy,center,True,after), daemon=True).start()
        self._cv.after(10, self.__update_gui)
    
    def _draw(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True, async_:bool=False, after:OAfter=None):
        if self._r is None: return
        self.__en = False
        self._cv.delete('all')            
        for e in self._r.Net.getEdges():
            e: Edge
            ename:str = e.getID()
            shape = e.getShape()
            if shape is None:
                raise ValueError(f"Edge {ename} has no shape")
            shape:PointList
            c, lw = self.__get_edge_prop(ename)
            shape = [(p[0]*scale+dx,p[1]*scale+dy) for p in shape]
            if async_: # Draw the line asynchronously. ID will be put into the queue to be joined
                self.__q.put(('l',(shape, c, lw, ename)))
            else:
                pid = self._cv.create_line(shape, fill=c, width=lw)
                self._items[pid] = itemdesc("edge", ename)
                self._Redges[ename] = pid
        if async_:
            self.__q.put(('c', None))
            self.__q.put(('a', after))
            self.__q_closed = True
        else:
            if center: self._center()
            after and after()
            self.__en = True