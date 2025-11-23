import numpy as np
from scipy.spatial import KDTree
from typing import Tuple
from numba import jit

class KDTreeSegmentSearch:
    """基于KDTree的线段快速搜索"""
    
    def __init__(self, segments: np.ndarray, leaf_size: int = 40, sample_points_per_segment: int = 5):
        """
        初始化线段搜索器
        
        参数:
            segments: shape (n, 4) 的numpy数组，每行 [x1, y1, x2, y2]
            leaf_size: KDTree叶子节点大小
            sample_points_per_segment: 每条线段采样的点数
        """
        self.segments = segments.astype(np.float64)
        self.n_segments = segments.shape[0]
        
        # 预计算线段信息
        self.vectors = self.segments[:, 2:] - self.segments[:, :2]
        self.lengths_sq = np.sum(self.vectors**2, axis=1)
        self.lengths = np.sqrt(self.lengths_sq)
        
        # 为每条线段采样多个点构建KDTree
        self.sample_points, self.sample_segment_indices = self._sample_segment_points(sample_points_per_segment)
        
        # 构建KDTree
        self.kdtree = KDTree(self.sample_points, leafsize=leaf_size)
        
        # 构建端点KDTree用于快速候选筛选
        endpoints = np.vstack([self.segments[:, :2], self.segments[:, 2:]])
        self.endpoint_tree = KDTree(endpoints, leafsize=leaf_size)
        
        # 预计算边界框
        self.bbox_min = np.minimum(self.segments[:, :2], self.segments[:, 2:])
        self.bbox_max = np.maximum(self.segments[:, :2], self.segments[:, 2:])
        
    
    def _sample_segment_points(self, n_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """为每条线段采样多个点"""
        if n_samples == 1:
            # 只采样中点
            mid_points = (self.segments[:, :2] + self.segments[:, 2:]) / 2
            return mid_points, np.arange(self.n_segments)
        
        # 为每条线段采样多个点
        t_values = np.linspace(0, 1, n_samples)
        all_points = []
        all_indices = []
        
        for i in range(self.n_segments):
            for t in t_values:
                point = self.segments[i, :2] + t * self.vectors[i]
                all_points.append(point)
                all_indices.append(i)
        
        return np.array(all_points), np.array(all_indices)
    
    def find_closest_candidates_kdtree(self, point: np.ndarray, n_candidates: int = 50) -> np.ndarray:
        """
        使用KDTree找到候选线段
        
        返回:
            候选线段的索引数组
        """
        point = np.array(point, dtype=np.float64).reshape(1, -1)
        
        # 在采样点KDTree中搜索最近点
        distances, indices = self.kdtree.query(point, k=min(n_candidates, len(self.sample_points)))
        
        # 获取对应的线段索引
        candidate_segment_indices = self.sample_segment_indices[indices]
        
        # 去重
        unique_candidates = np.unique(candidate_segment_indices)
        
        return unique_candidates
    
    def find_closest_candidates_endpoints(self, point: np.ndarray, n_candidates: int = 30) -> np.ndarray:
        """
        使用端点KDTree找到候选线段
        
        返回:
            候选线段的索引数组
        """
        point = np.array(point, dtype=np.float64).reshape(1, -1)
        
        # 在端点KDTree中搜索最近点
        distances, indices = self.endpoint_tree.query(point, k=min(n_candidates * 2, self.n_segments * 2))
        
        # 端点索引映射回线段索引
        segment_indices = indices % self.n_segments
        
        # 去重
        unique_candidates = np.unique(segment_indices)
        
        return unique_candidates
    
    def find_closest_candidates_combined(self, point: np.ndarray, n_candidates: int = 50) -> np.ndarray:
        """组合使用两种方法找到候选线段"""
        # 从采样点KDTree获取候选
        candidates1 = self.find_closest_candidates_kdtree(point, n_candidates // 2)
        
        # 从端点KDTree获取候选
        candidates2 = self.find_closest_candidates_endpoints(point, n_candidates // 2)
        
        # 合并并去重
        all_candidates = np.unique(np.concatenate([candidates1, candidates2]))
        
        # 如果候选太少，扩大搜索范围
        if len(all_candidates) < 10:
            candidates1 = self.find_closest_candidates_kdtree(point, n_candidates * 2)
            candidates2 = self.find_closest_candidates_endpoints(point, n_candidates * 2)
            all_candidates = np.unique(np.concatenate([candidates1, candidates2]))
        
        return all_candidates

    @staticmethod
    @jit(nopython=True, fastmath=True)
    def _distance_to_segment_numba(point: np.ndarray, segment: np.ndarray, 
                                 vector: np.ndarray, length_sq: float) -> Tuple[float, float]:
        """Numba加速的线段距离计算"""
        # 点到线段起点的向量
        point_to_start_x = point[0] - segment[0]
        point_to_start_y = point[1] - segment[1]
        
        # 计算投影参数 t
        dot_product = point_to_start_x * vector[0] + point_to_start_y * vector[1]
        
        if length_sq < 1e-10:  # 线段退化为点
            t = 0.0
        else:
            t = dot_product / length_sq
        
        # 限制t在[0,1]范围内
        t_clipped = max(0.0, min(1.0, t))
        
        # 计算投影点
        proj_x = segment[0] + t_clipped * vector[0]
        proj_y = segment[1] + t_clipped * vector[1]
        
        # 计算距离
        dx = point[0] - proj_x
        dy = point[1] - proj_y
        distance = np.sqrt(dx * dx + dy * dy)
        
        return distance, t_clipped

    def _compute_distances_to_candidates(self, point: np.ndarray, candidate_indices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算点到候选线段的距离"""
        n_candidates = len(candidate_indices)
        distances = np.zeros(n_candidates)
        t_values = np.zeros(n_candidates)
        
        for i, seg_idx in enumerate(candidate_indices):
            dist, t = self._distance_to_segment_numba(
                point, 
                self.segments[seg_idx], 
                self.vectors[seg_idx], 
                self.lengths_sq[seg_idx]
            )
            distances[i] = dist
            t_values[i] = t
        
        return distances, t_values

    def find_closest_segment(self, point: np.ndarray, n_candidates: int = 100) -> Tuple[int, float, np.ndarray]:
        """
        找到距离给定点最近的线段
        
        返回:
            segment_index: 线段索引
            distance: 最短距离
            closest_point: 线段上的最近点
        """
        point = np.array(point, dtype=np.float64)
        
        # 步骤1: 使用KDTree找到候选线段
        candidate_indices = self.find_closest_candidates_combined(point, n_candidates)
        
        # 步骤2: 在候选线段中精确计算距离
        distances, t_values = self._compute_distances_to_candidates(point, candidate_indices)
        
        # 步骤3: 找到最小距离
        min_idx = np.argmin(distances)
        best_segment_idx = candidate_indices[min_idx]
        min_distance = distances[min_idx]
        best_t = t_values[min_idx]
        
        # 步骤4: 计算最近点坐标
        closest_point = self.segments[best_segment_idx, :2] + best_t * self.vectors[best_segment_idx]
        
        return best_segment_idx, min_distance, closest_point

    def batch_find_closest_segments(self, points: np.ndarray, n_candidates: int = 100, 
                                  batch_size: int = 1000) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        批量处理多个点
        
        参数:
            points: shape (m, 2) 的点数组
            n_candidates: 每个点的候选线段数量
            batch_size: 批处理大小
            
        返回:
            indices: 每个点对应的最近线段索引
            distances: 每个点的最小距离
            closest_points: 每个点在线段上的最近点
        """
        n_points = points.shape[0]
        indices = np.zeros(n_points, dtype=int)
        distances = np.zeros(n_points)
        closest_points = np.zeros((n_points, 2))
        
        # 分批处理以避免内存问题
        for i in range(0, n_points, batch_size):
            end_idx = min(i + batch_size, n_points)
            batch_points = points[i:end_idx]
            batch_size_current = batch_points.shape[0]
            
            print(f"处理点 {i} 到 {end_idx-1}...")
            
            for j in range(batch_size_current):
                idx, dist, closest_pt = self.find_closest_segment(batch_points[j], n_candidates)
                indices[i + j] = idx
                distances[i + j] = dist
                closest_points[i + j] = closest_pt
        
        return indices, distances, closest_points
