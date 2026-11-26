import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
from shapely.geometry import Point

# 1. 读取 CSV（假设文件名为 cs.csv，与脚本同目录）
df = pd.read_csv('cs.csv')

# 2. 创建 GeoDataFrame，指定 WGS84 坐标系 (EPSG:4326)
geometry = [Point(xy) for xy in zip(df['lng'], df['lat'])]
gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

# 3. 投影到 Web 墨卡托 (EPSG:3857)，用于 contextily 底图
gdf_web = gdf.to_crs(epsg=3857)

# 4. 绘图
fig, ax = plt.subplots(figsize=(12, 10))

# 绘制底图（自动根据数据范围获取切片）
ax = gdf_web.plot(ax=ax, marker='o', color='red', markersize=20, alpha=0.7, label='加油站')
custom_headers = {
    'user-agent': 'SEU Charging Station Display/1.0'
}

ctx.add_basemap(
    ax, 
    crs=gdf_web.crs, 
    source=ctx.providers.OpenStreetMap.Mapnik,
    zoom=13,
    headers=custom_headers  # 传入自定义的 User-Agent
)

plt.tight_layout()
plt.savefig('stations_map.png', dpi=300)  # 保存图片
plt.show()