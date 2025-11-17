"""
主分析器模块 - 整合所有分析功能

提供统一的接口进行SFT数据集的完整分析
"""

import numpy as np
from typing import List, Dict, Any, Optional, Union
import json
import logging
from pathlib import Path
import time
from tqdm import tqdm
import pickle

from .embedding import BM25Vectorizer, HybridVectorizer
from .clustering import (
    KMeansClusterer,
    HDBSCANClusterer,
    LSHClusterer,
    HierarchicalClusterer,
    ClusteringResult
)
from .topic_modeling import TopicModeler, TopicEvolution
from .quality import QualityEvaluator, QualityMetrics
from .visualization import DataVisualizer

logger = logging.getLogger(__name__)


class SFTDataAnalyzer:
    """
    SFT数据集分析器

    整合向量化、聚类、主题建模、质量评估和可视化功能
    """

    def __init__(
        self,
        n_clusters: int = 100,
        min_cluster_size: int = 50,
        use_jieba: bool = True,
        output_dir: str = "./analysis_output",
        cache_dir: Optional[str] = "./cache"
    ):
        """
        初始化分析器

        Args:
            n_clusters: K-Means聚类数量
            min_cluster_size: HDBSCAN最小聚类大小
            use_jieba: 是否使用jieba分词
            output_dir: 输出目录
            cache_dir: 缓存目录（None表示不缓存）
        """
        self.n_clusters = n_clusters
        self.min_cluster_size = min_cluster_size
        self.use_jieba = use_jieba
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 初始化各个组件
        self.vectorizer = BM25Vectorizer(use_jieba=use_jieba, max_features=10000)
        self.kmeans_clusterer = KMeansClusterer(n_clusters=n_clusters)
        self.hdbscan_clusterer = HDBSCANClusterer(min_cluster_size=min_cluster_size)
        self.lsh_clusterer = LSHClusterer()
        self.hierarchical_clusterer = HierarchicalClusterer(
            coarse_clusterer=self.kmeans_clusterer,
            fine_clusterer=self.hdbscan_clusterer,
            dedup_clusterer=self.lsh_clusterer
        )
        self.topic_modeler = TopicModeler(use_jieba=use_jieba)
        self.quality_evaluator = QualityEvaluator()
        self.visualizer = DataVisualizer(output_dir=output_dir)

        # 存储分析结果
        self.results = {}

    def analyze(
        self,
        data: Union[List[Dict[str, str]], str],
        sample_size: Optional[int] = None,
        clustering_method: str = 'hierarchical',
        topic_method: str = 'tfidf',
        generate_report: bool = True,
        cache_embeddings: bool = True
    ) -> Dict[str, Any]:
        """
        执行完整的数据分析流程

        Args:
            data: SFT数据列表或数据文件路径
            sample_size: 采样大小（None表示使用全部数据）
            clustering_method: 聚类方法 ('kmeans', 'hdbscan', 'hierarchical')
            topic_method: 主题提取方法 ('tfidf', 'textrank', 'lda')
            generate_report: 是否生成分析报告
            cache_embeddings: 是否缓存向量化结果

        Returns:
            完整的分析结果字典
        """
        start_time = time.time()
        logger.info("="*50)
        logger.info("开始SFT数据集分析")
        logger.info("="*50)

        # 1. 加载数据
        logger.info("\n步骤1: 加载数据...")
        data = self._load_data(data)

        # 采样（如果需要）
        if sample_size and sample_size < len(data):
            logger.info(f"对数据进行采样：{sample_size}/{len(data)}")
            indices = np.random.choice(len(data), sample_size, replace=False)
            data = [data[i] for i in indices]

        self.results['n_samples'] = len(data)
        logger.info(f"数据加载完成，样本数：{len(data)}")

        # 2. 准备文本数据
        logger.info("\n步骤2: 准备文本数据...")
        texts = self._prepare_texts(data)

        # 3. 文本向量化
        logger.info("\n步骤3: 文本向量化...")
        embeddings = self._vectorize_texts(texts, cache_embeddings)
        logger.info(f"向量化完成，维度：{embeddings.shape}")

        # 4. 聚类分析
        logger.info(f"\n步骤4: 聚类分析（方法：{clustering_method}）...")
        clustering_results = self._perform_clustering(embeddings, method=clustering_method)
        self.results['clustering'] = clustering_results

        # 获取主要的聚类标签
        if clustering_method == 'hierarchical':
            cluster_labels = clustering_results['fine'].labels
        else:
            cluster_labels = clustering_results.labels

        # 5. 主题建模
        logger.info(f"\n步骤5: 主题建模（方法：{topic_method}）...")
        topics = self._extract_topics(texts, cluster_labels, method=topic_method)
        self.results['topics'] = topics

        # 6. 质量评估
        logger.info("\n步骤6: 质量评估...")
        quality_metrics = self._evaluate_quality(data, cluster_labels)
        self.results['quality'] = quality_metrics

        # 7. 生成可视化
        logger.info("\n步骤7: 生成可视化...")
        self._generate_visualizations(embeddings, cluster_labels, topics, quality_metrics)

        # 8. 生成分析报告
        if generate_report:
            logger.info("\n步骤8: 生成分析报告...")
            report_path = self.visualizer.generate_analysis_report(
                self.results,
                save_path="analysis_report.html"
            )
            self.results['report_path'] = report_path

        # 计算总时间
        elapsed_time = time.time() - start_time
        self.results['analysis_time'] = elapsed_time

        # 保存结果
        self._save_results()

        logger.info("="*50)
        logger.info(f"分析完成！总用时：{elapsed_time:.2f}秒")
        logger.info(f"结果保存在：{self.output_dir}")
        logger.info("="*50)

        # 打印摘要
        self._print_summary()

        return self.results

    def _load_data(self, data: Union[List[Dict], str]) -> List[Dict[str, str]]:
        """
        加载数据

        Args:
            data: 数据列表或文件路径

        Returns:
            数据列表
        """
        if isinstance(data, str):
            file_path = Path(data)
            if file_path.suffix == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            elif file_path.suffix == '.jsonl':
                data = []
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        data.append(json.loads(line))
            else:
                raise ValueError(f"不支持的文件格式：{file_path.suffix}")

        # 验证数据格式
        for item in data[:10]:  # 检查前10个样本
            if not isinstance(item, dict):
                raise ValueError("数据格式错误：每个样本应该是字典")
            if 'instruction' not in item or 'output' not in item:
                logger.warning("数据缺少instruction或output字段")

        return data

    def _prepare_texts(self, data: List[Dict[str, str]]) -> List[str]:
        """
        准备文本数据

        Args:
            data: 原始数据

        Returns:
            合并后的文本列表
        """
        texts = []
        for item in data:
            instruction = item.get('instruction', '')
            output = item.get('output', '')
            input_text = item.get('input', '')

            # 合并文本
            combined = f"{instruction} {input_text} {output}".strip()
            texts.append(combined)

        return texts

    def _vectorize_texts(
        self,
        texts: List[str],
        use_cache: bool = True
    ) -> np.ndarray:
        """
        文本向量化

        Args:
            texts: 文本列表
            use_cache: 是否使用缓存

        Returns:
            向量矩阵
        """
        cache_file = None
        if use_cache and self.cache_dir:
            cache_file = self.cache_dir / f"embeddings_{len(texts)}.pkl"
            if cache_file.exists():
                logger.info(f"从缓存加载向量：{cache_file}")
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)

        # 执行向量化
        embeddings = self.vectorizer.fit_transform(texts, batch_size=1000)

        # 保存到缓存
        if cache_file:
            with open(cache_file, 'wb') as f:
                pickle.dump(embeddings, f)
            logger.info(f"向量已缓存到：{cache_file}")

        return embeddings

    def _perform_clustering(
        self,
        embeddings: np.ndarray,
        method: str = 'hierarchical'
    ) -> Union[ClusteringResult, Dict[str, ClusteringResult]]:
        """
        执行聚类分析

        Args:
            embeddings: 向量矩阵
            method: 聚类方法

        Returns:
            聚类结果
        """
        if method == 'kmeans':
            return self.kmeans_clusterer.fit_predict(embeddings)
        elif method == 'hdbscan':
            return self.hdbscan_clusterer.fit_predict(embeddings)
        elif method == 'hierarchical':
            return self.hierarchical_clusterer.fit_predict(embeddings)
        else:
            raise ValueError(f"不支持的聚类方法：{method}")

    def _extract_topics(
        self,
        texts: List[str],
        cluster_labels: np.ndarray,
        method: str = 'tfidf'
    ) -> Dict[int, Dict]:
        """
        提取主题

        Args:
            texts: 文本列表
            cluster_labels: 聚类标签
            method: 主题提取方法

        Returns:
            主题字典
        """
        if method == 'lda':
            # 使用LDA
            lda_results = self.topic_modeler.fit_lda(texts, n_topics=20)
            return lda_results['topics']
        else:
            # 基于聚类提取主题
            return self.topic_modeler.extract_topics_from_clusters(
                texts, cluster_labels, method=method
            )

    def _evaluate_quality(
        self,
        data: List[Dict[str, str]],
        cluster_labels: np.ndarray
    ) -> Dict[str, Any]:
        """
        评估数据质量

        Args:
            data: 原始数据
            cluster_labels: 聚类标签

        Returns:
            质量评估结果
        """
        quality_metrics = self.quality_evaluator.evaluate(data, cluster_labels)

        # 转换为字典格式
        return {
            'length_stats': quality_metrics.length_stats,
            'diversity_scores': quality_metrics.diversity_scores,
            'complexity_scores': quality_metrics.complexity_scores,
            'duplication_stats': quality_metrics.duplication_stats,
            'format_quality': quality_metrics.format_quality,
            'overall_score': quality_metrics.overall_score,
            'warnings': quality_metrics.warnings,
            'recommendations': quality_metrics.recommendations
        }

    def _generate_visualizations(
        self,
        embeddings: np.ndarray,
        cluster_labels: np.ndarray,
        topics: Dict[int, Dict],
        quality_metrics: Dict[str, Any]
    ):
        """
        生成可视化图表

        Args:
            embeddings: 向量矩阵
            cluster_labels: 聚类标签
            topics: 主题信息
            quality_metrics: 质量指标
        """
        # 1. 聚类分布图
        if embeddings.shape[0] <= 50000:  # 对大数据集进行采样
            self.visualizer.visualize_clustering(
                embeddings.toarray() if hasattr(embeddings, 'toarray') else embeddings,
                cluster_labels,
                topics,
                method='umap',
                save_path=str(self.output_dir / "clustering_plot.html")
            )

        # 2. 主题分布图
        self.visualizer.visualize_topics(
            topics,
            save_path=str(self.output_dir / "topics_plot.html")
        )

        # 3. 质量指标图
        self.visualizer.visualize_quality_metrics(
            quality_metrics,
            save_path=str(self.output_dir / "quality_metrics.html")
        )

        # 4. 词云图（基于主题关键词）
        all_keywords = {}
        for topic_info in topics.values():
            for keyword, weight in topic_info['keywords']:
                all_keywords[keyword] = all_keywords.get(keyword, 0) + weight

        self.visualizer.create_word_cloud(
            all_keywords,
            save_path=str(self.output_dir / "wordcloud.png")
        )

    def _convert_to_serializable(self, obj):
        """递归转换对象为JSON可序列化格式"""
        from dataclasses import is_dataclass, asdict

        if isinstance(obj, dict):
            return {k: self._convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_to_serializable(item) for item in obj]
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        elif is_dataclass(obj):
            return asdict(obj)
        elif hasattr(obj, '__dict__') and not isinstance(obj, type):
            # 处理自定义类对象
            return {k: self._convert_to_serializable(v)
                   for k, v in obj.__dict__.items()
                   if not k.startswith('_')}
        else:
            return obj

    def _save_results(self):
        """保存分析结果"""
        results_file = self.output_dir / "analysis_results.json"

        try:
            # 转换为可序列化格式
            save_results = self._convert_to_serializable(self.results)

            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(save_results, f, ensure_ascii=False, indent=2)

            logger.info(f"结果已保存到：{results_file}")
        except Exception as e:
            logger.error(f"保存结果失败: {e}")
            # 不抛出异常，允许程序继续运行

    def _print_summary(self):
        """打印分析摘要"""
        print("\n" + "="*60)
        print("数据集分析摘要")
        print("="*60)

        print(f"\n📊 基本统计：")
        print(f"  • 样本总数：{self.results['n_samples']}")

        if 'clustering' in self.results:
            clustering = self.results['clustering']
            if isinstance(clustering, dict):
                if 'fine' in clustering:
                    print(f"  • 聚类数量：{clustering['fine'].n_clusters}")
                if 'dedup' in clustering:
                    dup_ratio = clustering['dedup'].scores.get('duplicate_ratio', 0)
                    print(f"  • 重复率：{dup_ratio:.2%}")
            else:
                print(f"  • 聚类数量：{clustering.n_clusters}")

        if 'quality' in self.results:
            quality = self.results['quality']
            print(f"\n📈 质量评估：")
            print(f"  • 总体质量分数：{quality['overall_score']:.1f}/100")
            print(f"  • 词汇多样性：{quality['diversity_scores'].get('vocabulary_diversity', 0):.3f}")
            print(f"  • 唯一样本比例：{quality['duplication_stats']['unique_sample_ratio']:.2%}")

            # 打印警告
            if quality['warnings']:
                print(f"\n⚠️ 质量警告：")
                for warning in quality['warnings'][:3]:
                    print(f"  {warning}")

            # 打印建议
            if quality['recommendations']:
                print(f"\n💡 改进建议：")
                for rec in quality['recommendations'][:3]:
                    print(f"  {rec}")

        print(f"\n⏱️ 分析用时：{self.results['analysis_time']:.2f}秒")
        print(f"📁 结果保存在：{self.output_dir}")
        print("="*60)

    def load_results(self, results_file: str) -> Dict[str, Any]:
        """
        加载之前的分析结果

        Args:
            results_file: 结果文件路径

        Returns:
            分析结果
        """
        with open(results_file, 'r', encoding='utf-8') as f:
            self.results = json.load(f)
        logger.info(f"结果已从{results_file}加载")
        return self.results