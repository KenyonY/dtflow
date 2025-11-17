"""
主题建模模块 - 从聚类中提取主题和关键词

支持LDA、基于TF-IDF的主题提取等方法
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
import jieba
import jieba.analyse
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import logging

logger = logging.getLogger(__name__)


class TopicModeler:
    """
    主题建模器

    从文本数据和聚类结果中提取主题
    """

    def __init__(
        self,
        n_topics: int = 20,
        n_words_per_topic: int = 10,
        use_jieba: bool = True,
        max_features: int = 5000
    ):
        """
        初始化主题建模器

        Args:
            n_topics: 主题数量（用于LDA）
            n_words_per_topic: 每个主题的关键词数量
            use_jieba: 是否使用jieba分词
            max_features: 最大特征数
        """
        self.n_topics = n_topics
        self.n_words_per_topic = n_words_per_topic
        self.use_jieba = use_jieba
        self.max_features = max_features

        self.lda_model = None
        self.vectorizer = None
        self.feature_names = None

    def extract_topics_from_clusters(
        self,
        documents: List[str],
        cluster_labels: np.ndarray,
        method: str = 'tfidf'
    ) -> Dict[int, Dict[str, Any]]:
        """
        从聚类结果中提取主题

        Args:
            documents: 文档列表
            cluster_labels: 聚类标签
            method: 提取方法 ('tfidf', 'textrank', 'frequency')

        Returns:
            每个聚类的主题信息
        """
        logger.info(f"从聚类中提取主题，方法：{method}")

        topics = {}
        unique_labels = np.unique(cluster_labels)

        for label in unique_labels:
            if label == -1:  # 跳过噪声点
                continue

            # 获取该聚类的文档
            cluster_mask = cluster_labels == label
            cluster_docs = [documents[i] for i, mask in enumerate(cluster_mask) if mask]

            if not cluster_docs:
                continue

            # 提取主题关键词
            if method == 'tfidf':
                keywords = self._extract_tfidf_keywords(cluster_docs)
            elif method == 'textrank':
                keywords = self._extract_textrank_keywords(cluster_docs)
            elif method == 'frequency':
                keywords = self._extract_frequency_keywords(cluster_docs)
            else:
                raise ValueError(f"不支持的方法：{method}")

            # 生成主题描述（转换label为Python原生int以支持JSON序列化）
            topics[int(label)] = {
                'keywords': keywords[:self.n_words_per_topic],
                'size': len(cluster_docs),
                'sample_docs': cluster_docs[:3],  # 保存样例文档
                'topic_summary': self._generate_topic_summary(keywords[:5])
            }

        logger.info(f"成功提取{len(topics)}个主题")
        return topics

    def _extract_tfidf_keywords(self, documents: List[str]) -> List[Tuple[str, float]]:
        """
        使用TF-IDF提取关键词

        Args:
            documents: 文档列表

        Returns:
            关键词和权重列表
        """
        # 合并所有文档
        combined_text = ' '.join(documents)

        if self.use_jieba:
            # 使用jieba的TF-IDF提取
            keywords = jieba.analyse.extract_tags(
                combined_text,
                topK=self.n_words_per_topic * 2,
                withWeight=True
            )
        else:
            # 使用sklearn的TF-IDF
            vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                ngram_range=(1, 2)
            )
            tfidf_matrix = vectorizer.fit_transform(documents)
            feature_names = vectorizer.get_feature_names_out()

            # 计算平均TF-IDF分数
            avg_tfidf = np.mean(tfidf_matrix.toarray(), axis=0)
            top_indices = np.argsort(avg_tfidf)[::-1][:self.n_words_per_topic * 2]

            keywords = [(feature_names[i], avg_tfidf[i]) for i in top_indices]

        return keywords

    def _extract_textrank_keywords(self, documents: List[str]) -> List[Tuple[str, float]]:
        """
        使用TextRank提取关键词

        Args:
            documents: 文档列表

        Returns:
            关键词和权重列表
        """
        combined_text = ' '.join(documents)

        if self.use_jieba:
            keywords = jieba.analyse.textrank(
                combined_text,
                topK=self.n_words_per_topic * 2,
                withWeight=True
            )
        else:
            # 简单的词频统计作为备选
            return self._extract_frequency_keywords(documents)

        return keywords

    def _extract_frequency_keywords(self, documents: List[str]) -> List[Tuple[str, float]]:
        """
        使用词频提取关键词

        Args:
            documents: 文档列表

        Returns:
            关键词和频率列表
        """
        word_freq = Counter()

        for doc in documents:
            if self.use_jieba:
                words = jieba.cut(doc)
            else:
                words = doc.lower().split()

            # 过滤短词和停用词
            words = [w for w in words if len(w) > 1]
            word_freq.update(words)

        # 归一化频率
        total_count = sum(word_freq.values())
        keywords = [
            (word, count / total_count)
            for word, count in word_freq.most_common(self.n_words_per_topic * 2)
        ]

        return keywords

    def _generate_topic_summary(self, keywords: List[Tuple[str, float]]) -> str:
        """
        生成主题摘要

        Args:
            keywords: 关键词列表

        Returns:
            主题摘要字符串
        """
        if not keywords:
            return "未知主题"

        # 取前5个关键词生成摘要
        words = [word for word, _ in keywords[:5]]
        return " / ".join(words)

    def fit_lda(
        self,
        documents: List[str],
        n_topics: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        训练LDA主题模型

        Args:
            documents: 文档列表
            n_topics: 主题数量（覆盖初始化参数）

        Returns:
            LDA模型结果
        """
        logger.info("开始训练LDA模型")

        n_topics = n_topics or self.n_topics

        # 创建词袋向量化器
        self.vectorizer = CountVectorizer(
            max_features=self.max_features,
            min_df=2,
            max_df=0.95
        )

        # 如果使用jieba，先进行分词
        if self.use_jieba:
            tokenized_docs = [' '.join(jieba.cut(doc)) for doc in documents]
        else:
            tokenized_docs = documents

        # 创建词袋矩阵
        doc_term_matrix = self.vectorizer.fit_transform(tokenized_docs)
        self.feature_names = self.vectorizer.get_feature_names_out()

        # 训练LDA模型
        self.lda_model = LatentDirichletAllocation(
            n_components=n_topics,
            learning_method='online',
            random_state=42,
            n_jobs=-1
        )

        doc_topic_dist = self.lda_model.fit_transform(doc_term_matrix)

        # 提取主题
        topics = self._extract_lda_topics()

        # 计算主题连贯性分数
        coherence_score = self._calculate_coherence(doc_term_matrix, doc_topic_dist)

        logger.info(f"LDA模型训练完成，发现{n_topics}个主题")

        return {
            'topics': topics,
            'doc_topic_distribution': doc_topic_dist,
            'coherence_score': coherence_score,
            'perplexity': self.lda_model.perplexity(doc_term_matrix)
        }

    def _extract_lda_topics(self) -> Dict[int, Dict[str, Any]]:
        """
        从LDA模型中提取主题

        Returns:
            主题字典
        """
        if self.lda_model is None:
            raise ValueError("LDA模型尚未训练")

        topics = {}

        for topic_idx in range(self.lda_model.n_components):
            # 获取主题的词分布
            topic_dist = self.lda_model.components_[topic_idx]
            top_indices = np.argsort(topic_dist)[::-1][:self.n_words_per_topic]

            # 提取关键词和权重
            keywords = [
                (self.feature_names[i], topic_dist[i])
                for i in top_indices
            ]

            topics[topic_idx] = {
                'keywords': keywords,
                'topic_summary': self._generate_topic_summary(keywords)
            }

        return topics

    def _calculate_coherence(
        self,
        doc_term_matrix,
        doc_topic_dist: np.ndarray
    ) -> float:
        """
        计算主题连贯性分数

        Args:
            doc_term_matrix: 文档-词矩阵
            doc_topic_dist: 文档-主题分布

        Returns:
            连贯性分数
        """
        # 简化的连贯性计算（UMass coherence）
        coherence_scores = []

        for topic_idx in range(self.lda_model.n_components):
            topic_dist = self.lda_model.components_[topic_idx]
            top_indices = np.argsort(topic_dist)[::-1][:10]

            # 计算词对的共现
            coherence = 0
            for i in range(len(top_indices)):
                for j in range(i+1, len(top_indices)):
                    word_i = top_indices[i]
                    word_j = top_indices[j]

                    # 计算共现频率
                    co_occur = np.sum((doc_term_matrix[:, word_i] > 0) &
                                    (doc_term_matrix[:, word_j] > 0))
                    if co_occur > 0:
                        coherence += np.log((co_occur + 1) / doc_term_matrix.shape[0])

            coherence_scores.append(coherence)

        return np.mean(coherence_scores)

    def get_document_topics(
        self,
        documents: List[str],
        top_n: int = 3
    ) -> List[List[Tuple[int, float]]]:
        """
        获取文档的主题分布

        Args:
            documents: 文档列表
            top_n: 返回前N个主题

        Returns:
            每个文档的主题分布
        """
        if self.lda_model is None:
            raise ValueError("LDA模型尚未训练")

        # 转换文档
        if self.use_jieba:
            tokenized_docs = [' '.join(jieba.cut(doc)) for doc in documents]
        else:
            tokenized_docs = documents

        doc_term_matrix = self.vectorizer.transform(tokenized_docs)
        doc_topic_dist = self.lda_model.transform(doc_term_matrix)

        # 提取每个文档的主要主题
        document_topics = []
        for doc_dist in doc_topic_dist:
            top_topics_idx = np.argsort(doc_dist)[::-1][:top_n]
            top_topics = [(idx, doc_dist[idx]) for idx in top_topics_idx]
            document_topics.append(top_topics)

        return document_topics


class TopicEvolution:
    """
    主题演化分析

    跟踪主题随时间的变化
    """

    def __init__(self, time_window: str = 'monthly'):
        """
        初始化主题演化分析器

        Args:
            time_window: 时间窗口 ('daily', 'weekly', 'monthly')
        """
        self.time_window = time_window
        self.topic_timeline = {}

    def analyze_evolution(
        self,
        documents: List[str],
        timestamps: List[str],
        cluster_labels: np.ndarray
    ) -> Dict[str, Any]:
        """
        分析主题演化

        Args:
            documents: 文档列表
            timestamps: 时间戳列表
            cluster_labels: 聚类标签

        Returns:
            主题演化分析结果
        """
        # 按时间窗口分组
        time_groups = self._group_by_time(documents, timestamps, cluster_labels)

        # 分析每个时间窗口的主题分布
        evolution_data = {}
        for time_key, group_data in time_groups.items():
            topic_dist = Counter(group_data['labels'])
            evolution_data[time_key] = {
                'topic_distribution': dict(topic_dist),
                'dominant_topic': topic_dist.most_common(1)[0][0] if topic_dist else None,
                'n_documents': len(group_data['documents'])
            }

        return {
            'timeline': evolution_data,
            'trending_topics': self._identify_trending_topics(evolution_data),
            'stable_topics': self._identify_stable_topics(evolution_data)
        }

    def _group_by_time(
        self,
        documents: List[str],
        timestamps: List[str],
        cluster_labels: np.ndarray
    ) -> Dict[str, Dict]:
        """
        按时间窗口分组文档
        """
        # 简化实现：按月份分组
        time_groups = {}

        for doc, ts, label in zip(documents, timestamps, cluster_labels):
            # 提取月份作为时间键（假设时间戳格式为YYYY-MM-DD）
            time_key = ts[:7] if len(ts) >= 7 else 'unknown'

            if time_key not in time_groups:
                time_groups[time_key] = {
                    'documents': [],
                    'labels': []
                }

            time_groups[time_key]['documents'].append(doc)
            time_groups[time_key]['labels'].append(label)

        return time_groups

    def _identify_trending_topics(
        self,
        evolution_data: Dict[str, Dict]
    ) -> List[int]:
        """
        识别趋势上升的主题
        """
        # 简化实现：计算主题频率的增长
        topic_trends = {}
        sorted_times = sorted(evolution_data.keys())

        if len(sorted_times) < 2:
            return []

        # 比较最后两个时间窗口
        recent = evolution_data[sorted_times[-1]].get('topic_distribution', {})
        previous = evolution_data[sorted_times[-2]].get('topic_distribution', {})

        trending = []
        for topic_id in recent:
            recent_count = recent.get(topic_id, 0)
            prev_count = previous.get(topic_id, 0)

            if prev_count > 0:
                growth_rate = (recent_count - prev_count) / prev_count
                if growth_rate > 0.5:  # 增长超过50%
                    trending.append(topic_id)

        return trending

    def _identify_stable_topics(
        self,
        evolution_data: Dict[str, Dict]
    ) -> List[int]:
        """
        识别稳定的主题
        """
        # 统计每个主题出现的时间窗口数
        topic_presence = Counter()

        for time_data in evolution_data.values():
            for topic_id in time_data.get('topic_distribution', {}).keys():
                topic_presence[topic_id] += 1

        # 在超过80%的时间窗口中出现的主题视为稳定
        n_windows = len(evolution_data)
        stable = [
            topic_id for topic_id, count in topic_presence.items()
            if count >= 0.8 * n_windows
        ]

        return stable