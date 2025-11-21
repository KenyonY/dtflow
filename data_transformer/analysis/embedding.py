"""
文本向量化模块 - 支持BM25和Ollama嵌入向量

BM25是一种基于概率的信息检索模型，考虑了词频、逆文档频率和文档长度
同时支持Ollama的深度学习嵌入模型
"""

import numpy as np
from typing import List, Dict, Any, Optional, Union
import jieba
from collections import Counter
import math
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
import logging

logger = logging.getLogger(__name__)


class BM25Vectorizer:
    """
    BM25文本向量化器

    BM25算法实现，支持中英文文本，生成稀疏向量表示
    """

    def __init__(
        self,
        k1: float = 1.2,
        b: float = 0.75,
        min_df: int = 1,
        max_df: float = 0.98,
        max_features: Optional[int] = 10000,
        use_jieba: bool = True,
        stop_words: Optional[List[str]] = None
    ):
        """
        初始化BM25向量化器

        Args:
            k1: BM25参数，控制词频饱和度，默认1.2
            b: BM25参数，控制文档长度归一化，默认0.75
            min_df: 最小文档频率，默认2
            max_df: 最大文档频率比例，默认0.95
            max_features: 最大特征数，默认10000
            use_jieba: 是否使用jieba分词（中文），默认True
            stop_words: 停用词列表
        """
        self.k1 = k1
        self.b = b
        self.min_df = min_df
        self.max_df = max_df
        self.max_features = max_features
        self.use_jieba = use_jieba
        self.stop_words = stop_words or self._get_default_stop_words()

        # 文档相关统计
        self.doc_len = []
        self.avgdl = 0
        self.doc_freqs = {}
        self.idf = {}
        self.vocabulary = {}
        self.vocabulary_inv = {}
        self.n_docs = 0

        # TF-IDF向量化器（用于初始特征提取）
        self.tfidf_vectorizer = None

    def _get_default_stop_words(self) -> List[str]:
        """获取默认停用词"""
        # 基础停用词（可根据需要扩展）
        stop_words = [
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
            'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i',
            'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at'
        ]
        return stop_words

    def _tokenize(self, text: str) -> List[str]:
        """
        文本分词

        Args:
            text: 输入文本

        Returns:
            分词后的词列表
        """
        if self.use_jieba:
            # 使用jieba进行中文分词
            tokens = list(jieba.cut(text))
        else:
            # 简单的英文分词
            tokens = text.lower().split()

        # 过滤停用词和短词
        tokens = [t for t in tokens if t not in self.stop_words and len(t) > 1]
        return tokens

    def fit(self, documents: List[str], batch_size: int = 1000) -> 'BM25Vectorizer':
        """
        训练BM25模型

        Args:
            documents: 文档列表
            batch_size: 批处理大小

        Returns:
            self
        """
        self.n_docs = len(documents)
        logger.info(f"开始训练BM25模型，文档数量：{self.n_docs}")

        # 分批处理文档
        all_tokens = []
        for i in range(0, self.n_docs, batch_size):
            batch_docs = documents[i:i+batch_size]
            batch_tokens = [self._tokenize(doc) for doc in batch_docs]
            all_tokens.extend(batch_tokens)

            if (i + batch_size) % 10000 == 0:
                logger.info(f"已处理 {min(i + batch_size, self.n_docs)}/{self.n_docs} 文档")

        # 计算文档长度
        self.doc_len = [len(tokens) for tokens in all_tokens]
        self.avgdl = sum(self.doc_len) / len(self.doc_len)

        # 构建词汇表和文档频率
        word_counter = Counter()
        doc_freq_counter = Counter()

        for tokens in all_tokens:
            word_counter.update(tokens)
            doc_freq_counter.update(set(tokens))

        # 过滤词汇（根据min_df和max_df）
        max_doc_freq = int(self.max_df * self.n_docs)
        filtered_words = [
            word for word, freq in doc_freq_counter.items()
            if self.min_df <= freq <= max_doc_freq
        ]

        # 如果设置了max_features，只保留频率最高的词
        if self.max_features and len(filtered_words) > self.max_features:
            filtered_words = [
                word for word, _ in
                Counter({w: word_counter[w] for w in filtered_words})
                .most_common(self.max_features)
            ]

        # 构建词汇表
        self.vocabulary = {word: idx for idx, word in enumerate(filtered_words)}
        self.vocabulary_inv = {idx: word for word, idx in self.vocabulary.items()}

        # 计算IDF
        for word in self.vocabulary:
            df = doc_freq_counter.get(word, 0)
            self.idf[word] = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

        logger.info(f"BM25模型训练完成，词汇表大小：{len(self.vocabulary)}")
        return self

    def transform(self, documents: List[str], batch_size: int = 1000) -> csr_matrix:
        """
        将文档转换为BM25向量

        Args:
            documents: 文档列表
            batch_size: 批处理大小

        Returns:
            稀疏矩阵表示的BM25向量
        """
        n_docs = len(documents)
        n_features = len(self.vocabulary)

        # 初始化稀疏矩阵的数据结构
        data = []
        rows = []
        cols = []

        for doc_idx in range(0, n_docs, batch_size):
            batch_docs = documents[doc_idx:min(doc_idx + batch_size, n_docs)]

            for i, doc in enumerate(batch_docs):
                tokens = self._tokenize(doc)
                doc_len = len(tokens)

                # 计算每个词的BM25分数
                token_freqs = Counter(tokens)

                for token, freq in token_freqs.items():
                    if token in self.vocabulary:
                        # BM25公式
                        idf = self.idf.get(token, 0)
                        tf = (freq * (self.k1 + 1)) / (
                            freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                        )
                        score = idf * tf

                        data.append(score)
                        rows.append(doc_idx + i)
                        cols.append(self.vocabulary[token])

            if (doc_idx + batch_size) % 10000 == 0:
                logger.info(f"已向量化 {min(doc_idx + batch_size, n_docs)}/{n_docs} 文档")

        # 创建稀疏矩阵
        bm25_matrix = csr_matrix(
            (data, (rows, cols)),
            shape=(n_docs, n_features)
        )

        return bm25_matrix

    def fit_transform(self, documents: List[str], batch_size: int = 1000) -> csr_matrix:
        """
        训练并转换文档

        Args:
            documents: 文档列表
            batch_size: 批处理大小

        Returns:
            稀疏矩阵表示的BM25向量
        """
        self.fit(documents, batch_size)
        return self.transform(documents, batch_size)

    def get_feature_names(self) -> List[str]:
        """
        获取特征名称（词汇表）

        Returns:
            特征名称列表
        """
        return [self.vocabulary_inv[i] for i in range(len(self.vocabulary))]

    def save(self, filepath: str):
        """
        保存模型参数

        Args:
            filepath: 保存路径
        """
        import pickle
        model_data = {
            'k1': self.k1,
            'b': self.b,
            'vocabulary': self.vocabulary,
            'vocabulary_inv': self.vocabulary_inv,
            'idf': self.idf,
            'doc_len': self.doc_len,
            'avgdl': self.avgdl,
            'n_docs': self.n_docs
        }
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        logger.info(f"模型已保存到 {filepath}")

    def load(self, filepath: str):
        """
        加载模型参数

        Args:
            filepath: 模型文件路径
        """
        import pickle
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.k1 = model_data['k1']
        self.b = model_data['b']
        self.vocabulary = model_data['vocabulary']
        self.vocabulary_inv = model_data['vocabulary_inv']
        self.idf = model_data['idf']
        self.doc_len = model_data['doc_len']
        self.avgdl = model_data['avgdl']
        self.n_docs = model_data['n_docs']
        logger.info(f"模型已从 {filepath} 加载")


class HybridVectorizer:
    """
    混合向量化器，支持BM25和其他向量化方法的组合
    """

    def __init__(
        self,
        bm25_weight: float = 0.5,
        tfidf_weight: float = 0.5,
        **kwargs
    ):
        """
        初始化混合向量化器

        Args:
            bm25_weight: BM25权重
            tfidf_weight: TF-IDF权重
            **kwargs: 传递给BM25Vectorizer的参数
        """
        self.bm25_weight = bm25_weight
        self.tfidf_weight = tfidf_weight

        self.bm25_vectorizer = BM25Vectorizer(**kwargs)
        self.tfidf_vectorizer = TfidfVectorizer(
            min_df=kwargs.get('min_df', 2),
            max_df=kwargs.get('max_df', 0.95),
            max_features=kwargs.get('max_features', 10000)
        )

    def fit_transform(self, documents: List[str]) -> csr_matrix:
        """
        训练并转换文档为混合向量

        Args:
            documents: 文档列表

        Returns:
            混合稀疏矩阵
        """
        # BM25向量
        bm25_matrix = self.bm25_vectorizer.fit_transform(documents)

        # TF-IDF向量
        tfidf_matrix = self.tfidf_vectorizer.fit_transform(documents)

        # 加权组合
        combined_matrix = (
            self.bm25_weight * bm25_matrix +
            self.tfidf_weight * tfidf_matrix
        )

        return combined_matrix


class OllamaEmbeddingVectorizer:
    """
    Ollama嵌入向量化器

    使用Ollama服务的embedding API进行文本向量化
    """

    def __init__(
        self,
        model: str = "bge-m3:latest",
        base_url: str = "http://localhost:11434",
        batch_size: int = 32
    ):
        """
        初始化Ollama嵌入向量化器

        Args:
            model: 嵌入模型名称
            base_url: Ollama服务地址
            batch_size: 批处理大小
        """
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.batch_size = batch_size
        self.embed_url = f"{self.base_url}/api/embeddings"

    def _get_embedding(self, text: str, max_retries: int = 3, expected_dim: Optional[int] = None) -> Optional[np.ndarray]:
        """
        获取单个文本的嵌入向量（带重试机制）

        Args:
            text: 输入文本
            max_retries: 最大重试次数
            expected_dim: 期望的向量维度（用于验证）

        Returns:
            嵌入向量，失败返回None
        """
        import requests
        import time

        payload = {
            "model": self.model,
            "prompt": text
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.embed_url,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding", [])

                # 验证嵌入向量
                if not embedding:
                    logger.warning(f"第{attempt + 1}次尝试：返回空向量")
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))  # 指数退避
                        continue
                    else:
                        return None

                embedding_array = np.array(embedding)

                # 验证维度
                if expected_dim is not None and len(embedding_array) != expected_dim:
                    logger.warning(f"第{attempt + 1}次尝试：向量维度不匹配 (期望{expected_dim}, 实际{len(embedding_array)})")
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    else:
                        return None

                # 成功返回
                return embedding_array

            except Exception as e:
                logger.warning(f"第{attempt + 1}次尝试失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))  # 指数退避
                else:
                    logger.error(f"获取嵌入向量失败（已重试{max_retries}次）")
                    return None

        return None

    def fit_transform(self, documents: List[str]) -> np.ndarray:
        """
        将文档转换为嵌入向量矩阵

        Args:
            documents: 文档列表

        Returns:
            嵌入向量矩阵 (n_documents, embedding_dim)
        """
        logger.info(f"开始使用Ollama模型 {self.model} 生成嵌入向量")

        embeddings = []
        n_docs = len(documents)
        expected_dim = None
        failed_count = 0

        for i in range(0, n_docs, self.batch_size):
            batch_docs = documents[i:min(i + self.batch_size, n_docs)]

            for doc_idx, doc in enumerate(batch_docs):
                # 获取嵌入向量（带重试）
                embedding = self._get_embedding(doc, max_retries=3, expected_dim=expected_dim)

                if embedding is None:
                    # 重试3次后仍然失败
                    failed_count += 1
                    if expected_dim is not None:
                        # 使用零向量作为占位符
                        embedding = np.zeros(expected_dim)
                        logger.warning(f"文档 {i + doc_idx} 嵌入失败，使用零向量")
                    else:
                        # 首个文档失败，无法确定维度
                        logger.error("首个文档嵌入失败，无法确定向量维度")
                        raise ValueError("首个文档嵌入失败，无法确定向量维度")
                else:
                    # 成功获取嵌入
                    if expected_dim is None:
                        expected_dim = len(embedding)
                        logger.info(f"检测到嵌入向量维度: {expected_dim}")

                embeddings.append(embedding)

            logger.info(f"已处理 {min(i + self.batch_size, n_docs)}/{n_docs} 文档 (失败: {failed_count})")

        embedding_matrix = np.array(embeddings)
        logger.info(f"嵌入向量生成完成,形状: {embedding_matrix.shape}")

        if failed_count > 0:
            logger.warning(f"共有 {failed_count}/{n_docs} 个文档嵌入失败 (成功率: {(n_docs - failed_count) / n_docs * 100:.2f}%)")

        return embedding_matrix

    def transform(self, documents: List[str]) -> np.ndarray:
        """
        转换文档为嵌入向量(与fit_transform相同)

        Args:
            documents: 文档列表

        Returns:
            嵌入向量矩阵
        """
        return self.fit_transform(documents)