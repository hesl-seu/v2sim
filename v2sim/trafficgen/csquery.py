from typing import Any, Optional, Union, overload
from pathlib import Path
import time, json, requests
from ..traffic import CheckFile, DetectFiles, readXML


class CS:
    def __init__(self, id:str, name:str, lat:float, lng:float):
        self.id = id
        self.name = name
        self.lat = lat
        self.lng = lng

    def __str__(self):
        return f"CS<{self.id},{self.name},{self.lat},{self.lng}>"


class Rect:
    @overload
    def __init__(self, lu_lng:float, lu_lat:float, br_lng:float, br_lat:float): ...
    
    @overload
    def __init__(self, lu_lng:str): ...
    
    def __init__(self, lu_lng:Union[str,float], lu_lat:Optional[float]=None, br_lng:Optional[float]=None, br_lat:Optional[float]=None):
        if isinstance(lu_lng, str):
            s = lu_lng.split('|')
            lu = s[0].split(',')
            br = s[1].split(',')
            self.lu_lng = float(lu[0])
            self.lu_lat = float(lu[1])
            self.br_lng = float(br[0])
            self.br_lat = float(br[1])
        elif isinstance(lu_lng, float) and isinstance(lu_lat, float) and isinstance(br_lng, float) and isinstance(br_lat, float):
            self.lu_lng = lu_lng
            self.lu_lat = lu_lat
            self.br_lng = br_lng
            self.br_lat = br_lat
        else:
            raise Exception("Invalid arguments.")
    
    def __str__(self):
        return f"{self.lu_lng:.6f},{self.lu_lat:.6f}|{self.br_lng:.6f},{self.br_lat:.6f}"
    
    def split4(self)->'tuple[Rect,Rect,Rect,Rect]':
        mid_lng = (self.lu_lng + self.br_lng) / 2
        mid_lat = (self.lu_lat + self.br_lat) / 2
        return (
            Rect(self.lu_lng, self.lu_lat, mid_lng, mid_lat),
            Rect(mid_lng, self.lu_lat, self.br_lng, mid_lat),
            Rect(self.lu_lng, mid_lat, mid_lng, self.br_lat),
            Rect(mid_lng, mid_lat, self.br_lng, self.br_lat)
        )


class AMapPOIReader:
    def __init__(self, key:str, limit:int=100, allyes:bool=False):
        self.key = key
        self.offset = 25
        self.limit = limit
        self.all_yes = allyes

    def get(self, rect:Rect, keyword:str) -> tuple[list[CS], list[dict[str,Any]]]:
        raw = self.get_raw(rect, keyword)
        result = []
        for itm in raw:
            id = itm['id']
            name = itm['name']
            loc = itm['location'].split(',')
            lat = float(loc[1])
            lng = float(loc[0])
            result.append(CS(id, name, lat, lng))
        return result, raw
    
    def get_raw(self, rect:Rect, keyword:str) -> list[dict[str,Any]]:
        first_page = self.__get0(rect,keyword,1)
        if first_page['infocode'] == '10001':
            raise Exception('Invalid key.')
        if first_page['infocode'] == '10044':
            raise Exception('Usage reaches the limit. Please try again tomorrow.')
        page_count = int(first_page['count'])
        while page_count > 200:
            print(f"Too many results({page_count}). Splitting the region...")
            if not self.all_yes:
                cont = input("Continue?(Y/N) > ")
                if cont.lower() != 'y':
                    return []
            rect_list = rect.split4()
            result = []
            for rect in rect_list:
                result.extend(self.get_raw(rect, keyword))
            return result
        iterate_num = round(page_count / self.offset) + 1
        print(f"Total items: {page_count}. Queries needed: {iterate_num}")
        if not self.all_yes:
            cont = input("Continue?(Y/N) > ")
            if cont.lower() != 'y':
                return []
        final_result:list = first_page['pois']
        for i in range(2, iterate_num + 1):
            print(f"\rProgress: {i-1}/{iterate_num}",end="")
            temp_result = self.__get0(rect,keyword,i)
            final_result.extend(temp_result['pois'])
            time.sleep(0.2)
        print("\rFinished.               ")

        return final_result

    def __get0(self, rect:Rect, keyword:str, pagenum:int) -> dict[str,Any]:
        # 011100(充电站中类)|011102(充换电站)|011103(专用充电站)|073000(电动自行车充电站中类)|073001(电动自行车换电)|073002(电动自行车专用充电站)
        url = f'https://restapi.amap.com/v3/place/polygon?polygon={str(rect)}&keywords={keyword}&offset={self.offset}&page={pagenum}&key={self.key}&types=011100&extensions=all'
        response = requests.get(url)
        result = json.loads(response.text)
        return result


def csQuery(root:str, new_loc:str, ak:str, allyes:bool):
    detects = DetectFiles(root)
    tlbr = None
    if "net" in detects:
        loc_elem = readXML(detects["net"]).getroot().find("location")
        if loc_elem is not None:
            a,b,c,d = loc_elem.attrib["origBoundary"].split(",")
            tlbr = Rect(float(a),float(b),float(c),float(d))
    if new_loc != "":
        tlbr = Rect(new_loc)
    if tlbr is None:
        raise Exception("No location specified. It can be specified by -p or by the net file.")
    else:
        print(f"Location: {tlbr}")
    reader = AMapPOIReader(ak,allyes = allyes)
    cslist, results = reader.get(tlbr, "充电站")
    
    if len(cslist) == 0: return
    
    print("Saving json...")
    json_path = str(Path(root) / "cs.json")
    CheckFile(json_path)
    with open(json_path, 'w') as f:
        json.dump(results, f, ensure_ascii=False)
    
    print("Saving csv...")
    csv_path = str(Path(root) / "cs.csv")
    CheckFile(csv_path)
    with open(csv_path, 'w') as f:
        f.write("id,name,lat,lng\n")
        for itm in cslist:
            f.write(f"{itm.id},{itm.name},{itm.lat},{itm.lng}\n")
    