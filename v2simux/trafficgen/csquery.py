import time, json, requests
from dataclasses import dataclass
from typing import Any, Optional, TextIO, Union, overload, List, Dict, Tuple
from pathlib import Path
from ..traffic import CheckFile, DetectFiles, ReadXML, CONFIG_DIR


AMAP_KEY_FILE = CONFIG_DIR / "amap_key.txt"


class CSQueryError(Exception):
    def __init__(self, message:str, obj = None):
        if obj is not None:
            message += f"\nObject: {str(obj)}"
        super().__init__(message)
        self.obj = obj


@dataclass
class CS:
    id: str
    name: str
    lat: float
    lng: float
    
    @staticmethod
    def from_dict(d:Dict[str,Any]) -> 'CS':
        id = d.get('id', '')
        if id == '':
            raise CSQueryError("CS_from_dict: Invalid item id.", d)
        name = d.get('name', '')
        if name == '':
            raise CSQueryError("CS_from_dict: Invalid item name.", d)
        loc_str = d.get('location', '')
        if not isinstance(loc_str, str) or loc_str == '':
            raise CSQueryError("CS_from_dict: Invalid item location.", d)
        loc = loc_str.split(',')
        if len(loc) != 2:
            raise CSQueryError("CS_from_dict: Invalid item location.", d)
        try:
            lat = float(loc[1])
            lng = float(loc[0])
        except (ValueError, IndexError):
            raise CSQueryError("CS_from_dict: Invalid item location.", d)
        return CS(id, name, lat, lng)
    
    @staticmethod
    def from_dict_list(dl:List[Dict[str,Any]], lst:'List[CS]', fh:'Optional[TextIO]' = None):
        for d in dl:
            try:
                cs = CS.from_dict(d)
                lst.append(cs)
            except CSQueryError as e:
                print(e)
            if fh is not None:
                fh.write(f"{cs.id},{cs.name},{cs.lat},{cs.lng}\n")


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
            raise CSQueryError("Invalid Rect arguments.")
    
    def __str__(self):
        return f"{self.lu_lng:.6f},{self.lu_lat:.6f}|{self.br_lng:.6f},{self.br_lat:.6f}"
    
    def split4(self)->'Tuple[Rect,Rect,Rect,Rect]':
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
        self.buf = open("buf.csv","w", encoding='utf-8')

    def get_raw(self, rect:Rect, keyword:str) -> Tuple[List[Dict[str,Any]], List[CS]]:
        first_page = self.__get0(rect, keyword, 1)

        # Check info code
        infocode = first_page.get('infocode', None)
        if infocode is None:
            raise CSQueryError("AMapPOIReader_get_raw: No 'infocode' field in response.", first_page)
        if infocode == '10001':
            raise CSQueryError("AMapPOIReader_get_raw: Invalid AMap key.")
        if infocode == '10009':
            raise CSQueryError("AMapPOIReader_get_raw: AMap key does not match the platform.")
        if infocode == '10044':
            raise CSQueryError("AMapPOIReader_get_raw: AMap key usage has reached the limit.")

        # Check page count
        page_count_str = first_page.get('count', None)
        if page_count_str is None:
            raise CSQueryError("AMapPOIReader_get_raw: No 'count' field in response.", first_page)
        try:
            page_count = int(page_count_str)
        except ValueError:
            raise CSQueryError(f"AMapPOIReader_get_raw: Invalid count value: {page_count_str}")

        if page_count > 200:
            print(f"Too many results({page_count}). Splitting the region...")
            if not self.all_yes:
                cont = input("Continue?(Y/N) > ")
                if cont.lower() != 'y':
                    return [], []
            rect_list = rect.split4()
            raw_result = []; parsed_result = []
            for rect in rect_list:
                raw, parsed = self.get_raw(rect, keyword)
                raw_result.extend(raw)
                parsed_result.extend(parsed)
            return raw_result, parsed_result
        
        iterate_num = round(page_count / self.offset) + 1
        print(f"Total items: {page_count}. Queries needed: {iterate_num}")

        if not self.all_yes:
            cont = input("Continue?(Y/N) > ")
            if cont.lower() != 'y':
                return [], []
        
        pois:Optional[List[Dict[str, Any]]] = first_page.get('pois', None)
        if pois is None:
            raise CSQueryError("AMapPOIReader_get_raw: No 'pois' field in response.", first_page)
        raw_result = pois
        parsed_result = []
        CS.from_dict_list(pois, parsed_result, self.buf)

        for i in range(2, iterate_num + 1):
            print(f"\rProgress: {i-1}/{iterate_num}",end="")
            temp_result = self.__get0(rect, keyword, i)
            pois:Optional[List[Dict[str, Any]]] = temp_result.get('pois', None)
            if pois is None:
                continue
            raw_result.extend(pois)
            CS.from_dict_list(pois, parsed_result, self.buf)
            time.sleep(0.35)
        print("\rFinished.               ")

        return raw_result, parsed_result

    def __get0(self, rect:Rect, keyword:str, pagenum:int) -> Dict[str,Any]:
        # 011100(充电站中类)|011102(充换电站)|011103(专用充电站)|073000(电动自行车充电站中类)|073001(电动自行车换电)|073002(电动自行车专用充电站)
        url = f'https://restapi.amap.com/v3/place/polygon?polygon={str(rect)}&keywords={keyword}&offset={self.offset}&page={pagenum}&key={self.key}&types=011100&extensions=all'
        response = requests.get(url)
        response.encoding = 'utf-8'
        result = json.loads(response.text)
        return result


def csQuery(root:str, new_loc:str, ak:str, allyes:bool):
    detects = DetectFiles(root)
    tlbr = None
    if "net" in detects:
        tr = ReadXML(detects["net"]).getroot()
        if tr is None:
            raise RuntimeError(f"Failed to load net file {detects['net']}")
        loc_elem = tr.find("location")
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
    results, cslist = reader.get_raw(tlbr, "充电站")
    
    if len(cslist) == 0: return
    
    print("Saving csv...")
    csv_path = str(Path(root) / "cs.csv")
    CheckFile(csv_path)
    with open(csv_path, 'w', encoding="utf-8") as f:
        f.write("id,name,lat,lng\n")
        for itm in cslist:
            f.write(f"{itm.id},{itm.name},{itm.lat},{itm.lng}\n")

    print("Saving json...")
    json_path = str(Path(root) / "cs.json")
    CheckFile(json_path)
    with open(json_path, 'w', encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
