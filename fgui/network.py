from dataclasses import dataclass
from typing import Any, Iterable, Optional
from v2sim import ELGraph, Edge
from .controls import EditMode, PropertyPanel
from .view import *

PointList = list[tuple[float, float]]
OESet = Optional[set[str]]

@dataclass
class itemdesc:
    type:str
    desc:Any

class NetworkPanel(Frame):
    def __init__(self, master, roadnet:Optional[ELGraph]=None, **kwargs):
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
            self.RoadNet = roadnet
    
    def clear(self):
        self._cv.delete('all')
        self._scale_cnt = 0
        self._items:dict[int, itemdesc] = {}
        self._Redges:dict[str, int] = {}
        self._located_edges:set[str] = set()
        self._drag = {'item': None,'x': 0,'y': 0}
        self._r = None
    
    @property
    def RoadNet(self) -> Optional[ELGraph]:
        return self._r
    
    def setRoadNet(self, roadnet:ELGraph, repaint:bool=True):
        assert isinstance(roadnet, ELGraph)
        self._r = roadnet
        if repaint: self._draw()
    
    def _onLClick(self, event):
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
                if itm.desc in self._r.cs_names:
                    self._pr.setData({"Name":itm.desc, "Type": "Fast CS"}, default_edit_mode=EditMode.DISABLED)
                else:
                    self._pr.setData({"Name":itm.desc, "Type": "Normal Edge"}, default_edit_mode=EditMode.DISABLED)
            else:
                self._pr.setData({})

    def _onRClick(self, event):
        self._drag['item'] = 'all'
        self._drag["x"] = event.x
        self._drag["y"] = event.y
    
    def _onRMotion(self, event):
        if self._drag["item"]:
            x, y = event.x, event.y
            dx = x - self._drag["x"]
            dy = y - self._drag["y"]
            self._cv.move(self._drag["item"], dx, dy)
            self._drag["x"] = x
            self._drag["y"] = y
    
    def _onRRelease(self, event):
        self._drag["item"] = None
    
    def _onMouseWheel(self, event):
        if event.delta > 0 and self._scale_cnt < 50:
            s = 1.1
            self._scale_cnt += 1
        elif event.delta < 0 and self._scale_cnt > -50:
            s = 1 / 1.1
            self._scale_cnt -= 1
        else:
            s = 1
        self._cv.scale('all', event.x, event.y, s, s)
    
    def _center(self):
        bbox = self._cv.bbox("all")
        if not bbox: return
        cw = bbox[2] - bbox[0]
        ch = bbox[3] - bbox[1]
        ww = self._cv.winfo_width()
        wh = self._cv.winfo_height()
        dx = (ww - cw) / 2 - bbox[0]
        dy = (wh - ch) / 2 - bbox[1]
        self._cv.move("all", dx, dy)
        s = min(max(ww-50, 100)/cw, max(wh-50, 100)/ch)
        self._cv.scale('all', ww//2, wh//2, s, s)
    
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
        if edge in self._r.cs_names:
            return ("darkblue",3) if edge in self._r.EdgeIDSet else ("darkgray",3)
        else:
            return ("blue",1) if edge in self._r.EdgeIDSet else ("gray",1)
        
    def _draw(self, scale:float=1.0, dx:float=0.0, dy:float=0.0, center:bool=True):
        if self._r is None: return
        self._cv.delete('all')
        for e in self._r.net.getEdges():
            e: Edge
            ename:str = e.getID()
            shape = e.getShape()
            if shape is None:
                raise ValueError(f"Edge {ename} has no shape")
            shape:PointList
            c, lw = self.__get_edge_prop(ename)
            pid = self._cv.create_line([
                (p[0]*scale+dx,p[1]*scale+dy) for p in shape
            ], fill=c, width=lw)
            self._items[pid] = itemdesc("edge", ename)
            self._Redges[ename] = pid
        if center: self._center()