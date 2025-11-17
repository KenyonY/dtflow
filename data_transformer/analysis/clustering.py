"""
聚类分析模块 - 多层次聚类算法实现

包含K-Means、HDBSCAN、LSH等聚类算法，支持大规模数据处理
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from sklearn.cluster import MiniBatchKMeans, KMeans
from sklearn.metrics import silhouette_score, calinski_harabasz_score
from scipy.sparse import csr_matrix, issparse
import logging
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)


@dataclass
class ClusteringResult:
    """聚类结果数据类"""
    labels: np.ndarray  # 聚类标签
    n_clusters: int  # 聚类数量
    centers: Optional[np.ndarray] = None  # 聚类中心
    scores: Dict[str, float] = None  # 评估分数
    noise_points: Optional[np.ndarray] = None  # 噪声点索引
    metadata: Dict[str, Any] = None  # 其他元数据


class KMeansClusterer:
    """
    K-Means聚类器

    使用MiniBatchKMeans处理大规模数据
    """

    def __init__(
        self,
        n_clusters: int = 100,
        batch_size: int = 10000,
        max_iter: int = 100,
        random_state: int = 42,
        use_minibatch: bool = True
    ):
        """
        初始化K-Means聚类器

        Args:
            n_clusters: 聚类数量
            batch_size: MiniBatch大小
            max_iter: 最大迭代次数
            random_state: 随机种子
            use_minibatch: 是否使用MiniBatchKMeans
        """
        self.n_clusters = n_clusters
        self.batch_size = batch_size
        self.max_iter = max_iter
        self.random_state = random_state
        self.use_minibatch = use_minibatch
        self.model = None
        self.labels_ = None
        self.cluster_centers_ = None

    def fit_predict(self, X: Union[np.ndarray, csr_matrix]) -> ClusteringResult:
        """
        训练并预测聚类

        Args:
            X: 输入特征矩阵

        Returns:
            聚类结果
        """
        logger.info(f"开始K-Means聚类，目标聚类数：{self.n_clusters}")
        start_time = time.time()

        # 选择合适的K-Means算法
        if self.use_minibatch and X.shape[0] > 10000:
            self.model = MiniBatchKMeans(
                n_clusters=self.n_clusters,
                batch_size=self.batch_size,
                max_iter=self.max_iter,
                random_state=self.random_state,
                n_init='auto'
            )
        else:
            self.model = KMeans(
                n_clusters=self.n_clusters,
                max_iter=self.max_iter,
                random_state=self.random_state,
                n_init='auto'
            )

        # 训练模型
        self.labels_ = self.model.fit_predict(X)
        self.cluster_centers_ = self.model.cluster_centers_

        # 计算评估指标
        scores = {}
        try:
            # 对于大数据集，使用采样计算轮廓系数
            if X.shape[0] > 50000:
                sample_size = min(10000, X.shape[0])
                sample_idx = np.random.choice(X.shape[0], sample_size, replace=False)
                X_sample = X[sample_idx]
                labels_sample = self.labels_[sample_idx]
                scores['silhouette'] = silhouette_score(X_sample, labels_sample)
            else:
                scores['silhouette'] = silhouette_score(X, self.labels_)

            scores['calinski_harabasz'] = calinski_harabasz_score(X, self.labels_)
            scores['inertia'] = self.model.inertia_
        except Exception as e:
            logger.warning(f"评估指标计算失败：{e}")

        elapsed_time = time.time() - start_time
        logger.info(f"K-Means聚类完成，用时：{elapsed_time:.2f}秒")

        # 统计每个簇的大小（转换为Python原生类型以支持JSON序列化）
        unique_labels, counts = np.unique(self.labels_, return_counts=True)
        cluster_sizes = {int(label): int(count) for label, count in zip(unique_labels, counts)}

        return ClusteringResult(
            labels=self.labels_,
            n_clusters=self.n_clusters,
            centers=self.cluster_centers_,
            scores=scores,
            metadata={
                'algorithm': 'KMeans',
                'batch_size': self.batch_size if self.use_minibatch else None,
                'elapsed_time': elapsed_time,
                'cluster_sizes': cluster_sizes
            }
        )

    def predict(self, X: Union[np.ndarray, csr_matrix]) -> np.ndarray:
        """
        预测新数据的聚类标签

        Args:
            X: 输入特征矩阵

        Returns:
            聚类标签
        """
        if self.model is None:
            raise ValueError("模型尚未训练，请先调用fit_predict")
        return self.model.predict(X)


class HDBSCANClusterer:
    """
    HDBSCAN密度聚类器

    适用于发现任意形状的聚类和识别异常点
    """

    def __init__(
        self,
        min_cluster_size: int = 50,
        min_samples: int = 5,
        metric: str = 'euclidean',
        cluster_selection_method: str = 'eom',
        prediction_data: bool = True
    ):
        """
        初始化HDBSCAN聚类器

        Args:
            min_cluster_size: 最小聚类大小
            min_samples: 核心点的最小样本数
            metric: 距离度量
            cluster_selection_method: 聚类选择方法 ('eom' 或 'leaf')
            prediction_data: 是否生成预测数据
        """
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.metric = metric
        self.cluster_selection_method = cluster_selection_method
        self.prediction_data = prediction_data
        self.model = None
        self.labels_ = None

    def fit_predict(self, X: Union[np.ndarray, csr_matrix]) -> ClusteringResult:
        """
        训练并预测聚类

        Args:
            X: 输入特征矩阵

        Returns:
            聚类结果
        """
        logger.info("开始HDBSCAN密度聚类")
        start_time = time.time()

        try:
            import hdbscan
        except ImportError:
            logger.error("HDBSCAN未安装，请运行: pip install hdbscan")
            raise

        # 如果是稀疏矩阵，可能需要转换为密集矩阵（取决于数据大小）
        if issparse(X) and X.shape[0] < 50000:
            X = X.toarray()

        # 创建HDBSCAN模型
        self.model = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric=self.metric,
            cluster_selection_method=self.cluster_selection_method,
            prediction_data=self.prediction_data,
            core_dist_n_jobs=-1
        )

        # 训练模型
        self.labels_ = self.model.fit_predict(X)

        # 统计聚类信息
        unique_labels = np.unique(self.labels_)
        n_clusters = len([l for l in unique_labels if l >= 0])
        noise_mask = self.labels_ == -1
        n_noise = np.sum(noise_mask)
        noise_ratio = n_noise / len(self.labels_)

        # 获取聚类概率
        cluster_probs = self.model.probabilities_ if hasattr(self.model, 'probabilities_') else None

        # 计算评估指标
        scores = {}
        if n_clusters > 1:
            # 只对非噪声点计算评估指标
            non_noise_mask = ~noise_mask
            if np.sum(non_noise_mask) > 0:
                try:
                    X_non_noise = X[non_noise_mask]
                    labels_non_noise = self.labels_[non_noise_mask]
                    scores['silhouette'] = silhouette_score(X_non_noise, labels_non_noise)
                    scores['calinski_harabasz'] = calinski_harabasz_score(X_non_noise, labels_non_noise)
                except Exception as e:
                    logger.warning(f"评估指标计算失败：{e}")

        scores['noise_ratio'] = noise_ratio

        elapsed_time = time.time() - start_time
        logger.info(f"HDBSCAN聚类完成，发现{n_clusters}个聚类，噪声点比例：{noise_ratio:.2%}，用时：{elapsed_time:.2f}秒")

        # 统计每个簇的大小（转换为Python原生类型以支持JSON序列化）
        cluster_sizes = {}
        for label in unique_labels:
            if label >= 0:
                cluster_sizes[int(label)] = int(np.sum(self.labels_ == label))

        return ClusteringResult(
            labels=self.labels_,
            n_clusters=n_clusters,
            scores=scores,
            noise_points=np.where(noise_mask)[0],
            metadata={
                'algorithm': 'HDBSCAN',
                'n_noise': n_noise,
                'noise_ratio': noise_ratio,
                'cluster_probs': cluster_probs,
                'elapsed_time': elapsed_time,
                'cluster_sizes': cluster_sizes
            }
        )


class LSHClusterer:
    """
    局部敏感哈希(LSH)聚类器

    用于快速相似度搜索和去重
    """

    def __init__(
        self,
        n_bands: int = 20,
        n_rows: int = 5,
        threshold: float = 0.8
    ):
        """
        初始化LSH聚类器

        Args:
            n_bands: 哈希带数量
            n_rows: 每个带的行数
            threshold: 相似度阈值
        """
        self.n_bands = n_bands
        self.n_rows = n_rows
        self.threshold = threshold
        self.hash_tables = None
        self.labels_ = None

    def _hash_signature(self, signature: np.ndarray, band_idx: int) -> str:
        """
        计算签名的哈希值

        Args:
            signature: MinHash签名
            band_idx: 带索引

        Returns:
            哈希字符串
        """
        start = band_idx * self.n_rows
        end = start + self.n_rows
        return hash(tuple(signature[start:end]))

    def fit_predict(self, X: Union[np.ndarray, csr_matrix]) -> ClusteringResult:
        """
        使用LSH进行聚类（主要用于去重）

        Args:
            X: 输入特征矩阵

        Returns:
            聚类结果
        """
        logger.info("开始LSH聚类分析")
        start_time = time.time()

        try:
            from datasketch import MinHash, MinHashLSH
        except ImportError:
            logger.error("datasketch未安装，请运行: pip install datasketch")
            raise

        n_samples = X.shape[0]

        # 创建MinHash LSH
        lsh = MinHashLSH(threshold=self.threshold, num_perm=self.n_bands * self.n_rows)

        # 为每个文档创建MinHash
        minhashes = []
        for i in range(n_samples):
            # 获取文档的非零特征
            if issparse(X):
                row = X.getrow(i)
                indices = row.indices
            else:
                row = X[i]
                indices = np.where(row > 0)[0]

            # 创建MinHash
            m = MinHash(num_perm=self.n_bands * self.n_rows)
            for idx in indices:
                m.update(str(idx).encode('utf8'))

            minhashes.append(m)
            lsh.insert(f"doc_{i}", m)

        # 查找相似文档组
        similar_groups = []
        processed = set()

        for i in range(n_samples):
            if i in processed:
                continue

            # 查找相似文档
            result = lsh.query(minhashes[i])
            group = set([int(r.split('_')[1]) for r in result])

            if len(group) > 1:
                similar_groups.append(group)
                processed.update(group)

        # 分配聚类标签
        self.labels_ = np.full(n_samples, -1)
        for group_idx, group in enumerate(similar_groups):
            for doc_idx in group:
                self.labels_[doc_idx] = group_idx

        # 统计结果
        n_clusters = len(similar_groups)
        n_duplicates = sum(len(g) - 1 for g in similar_groups)
        duplicate_ratio = n_duplicates / n_samples if n_samples > 0 else 0

        elapsed_time = time.time() - start_time
        logger.info(f"LSH分析完成，发现{n_clusters}组相似文档，重复率：{duplicate_ratio:.2%}，用时：{elapsed_time:.2f}秒")

        return ClusteringResult(
            labels=self.labels_,
            n_clusters=n_clusters,
            scores={'duplicate_ratio': duplicate_ratio},
            metadata={
                'algorithm': 'LSH',
                'similar_groups': similar_groups,
                'n_duplicates': n_duplicates,
                'elapsed_time': elapsed_time
            }
        )


class HierarchicalClusterer:
    """
    层次化聚类器

    组合多种聚类算法进行多层次分析
    """

    def __init__(
        self,
        coarse_clusterer: Optional[KMeansClusterer] = None,
        fine_clusterer: Optional[HDBSCANClusterer] = None,
        dedup_clusterer: Optional[LSHClusterer] = None
    ):
        """
        初始化层次化聚类器

        Args:
            coarse_clusterer: 粗粒度聚类器
            fine_clusterer: 细粒度聚类器
            dedup_clusterer: 去重聚类器
        """
        self.coarse_clusterer = coarse_clusterer or KMeansClusterer(n_clusters=100)
        self.fine_clusterer = fine_clusterer or HDBSCANClusterer(min_cluster_size=30)
        self.dedup_clusterer = dedup_clusterer or LSHClusterer()
        self.hierarchical_labels_ = None

    def fit_predict(self, X: Union[np.ndarray, csr_matrix]) -> Dict[str, ClusteringResult]:
        """
        执行层次化聚类

        Args:
            X: 输入特征矩阵

        Returns:
            各层次的聚类结果字典
        """
        logger.info("开始层次化聚类分析")
        results = {}

        # 第一步：粗粒度聚类
        logger.info("执行粗粒度K-Means聚类...")
        coarse_result = self.coarse_clusterer.fit_predict(X)
        results['coarse'] = coarse_result

        # 第二步：在每个粗粒度簇内进行细粒度聚类
        logger.info("执行细粒度HDBSCAN聚类...")
        fine_labels = np.full(X.shape[0], -1)
        fine_label_counter = 0

        for cluster_id in range(coarse_result.n_clusters):
            cluster_mask = coarse_result.labels == cluster_id
            cluster_size = np.sum(cluster_mask)

            if cluster_size < self.fine_clusterer.min_cluster_size * 2:
                # 簇太小，不再细分
                fine_labels[cluster_mask] = fine_label_counter
                fine_label_counter += 1
            else:
                # 对簇内数据进行细粒度聚类
                X_cluster = X[cluster_mask]
                fine_result = self.fine_clusterer.fit_predict(X_cluster)

                # 映射细粒度标签
                cluster_indices = np.where(cluster_mask)[0]
                for local_label in np.unique(fine_result.labels):
                    if local_label >= 0:  # 忽略噪声点
                        local_mask = fine_result.labels == local_label
                        fine_labels[cluster_indices[local_mask]] = fine_label_counter
                        fine_label_counter += 1

        results['fine'] = ClusteringResult(
            labels=fine_labels,
            n_clusters=fine_label_counter,
            metadata={'algorithm': 'Hierarchical-Fine'}
        )

        # 第三步：去重分析
        logger.info("执行LSH去重分析...")
        dedup_result = self.dedup_clusterer.fit_predict(X)
        results['dedup'] = dedup_result

        # 创建层次化标签
        self.hierarchical_labels_ = np.column_stack([
            coarse_result.labels,
            fine_labels
        ])

        logger.info("层次化聚类分析完成")
        return results

    def get_cluster_hierarchy(self) -> Dict[int, List[int]]:
        """
        获取聚类层次结构

        Returns:
            粗粒度簇到细粒度簇的映射
        """
        if self.hierarchical_labels_ is None:
            raise ValueError("尚未执行聚类，请先调用fit_predict")

        hierarchy = {}
        for coarse, fine in self.hierarchical_labels_:
            if coarse not in hierarchy:
                hierarchy[coarse] = set()
            hierarchy[coarse].add(fine)

        return {k: list(v) for k, v in hierarchy.items()}