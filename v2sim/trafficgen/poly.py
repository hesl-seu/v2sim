import random
from typing import Optional
from xml.etree.ElementTree import Element
from ..traffic import Point, readXML

class Polygon:
    def __init__(self, elem:Element):
        self.ID = elem.attrib["id"]
        self.type = elem.attrib.get("type", "building.yes")
        self.points:list[Point] = []
        shape = elem.attrib["shape"]
        for p in shape.split(' '):
            x,y = p.split(',')
            self.points.append(Point(float(x), float(y)))
    
    def getConvertedType(self) -> Optional[str]:
        """
        Convert the functional area type of the POLY mode to the functional area type of the TAZ mode
        """
        poly_type = self.type.lower()
        if ("residential" in poly_type or "building" in poly_type or 
            "apartments" in poly_type or "house" in poly_type):
            return "Home"
        elif ("industrial" in poly_type or "office" in poly_type or 
            "school" in poly_type or "gov" in poly_type):
            return "Work"
        elif ("shop" in poly_type or "commercial" in poly_type or
            "amenity" in poly_type or "historic" in poly_type or 
            "tourism" in poly_type or "leisure" in poly_type or 
            "sport" in poly_type or "park" in poly_type):
            return "Relax"
        elif ("building" in poly_type):
            if random.randint(0,99)<70:
                return "Work"
            else:
                return "Relax"
        elif ("natural" not in poly_type):
            return "Other"
        else:
            return None
    
    def center(self) -> Point:
        x = sum([p.x for p in self.points]) / len(self.points)
        y = sum([p.y for p in self.points]) / len(self.points)
        return Point(x, y)
    
    def __iter__(self):
        return iter(self.points)
    
class PolygonMan:
    def __init__(self, file:str):
        self.polygons:list[Polygon] = []
        rt = readXML(file).getroot()
        if rt is None:
            raise RuntimeError(f"Failed to load polygon file {file}")
        for elem in rt:
            if elem.tag != 'poly': continue
            self.polygons.append(Polygon(elem))
    
    def __iter__(self):
        return iter(self.polygons)
    
    def __getitem__(self, idx):
        return self.polygons[idx]
    
    def __len__(self):
        return len(self.polygons)