"""
LLM主题命名器 - 使用LLM为聚类主题生成高层次语义描述

支持Ollama本地服务
"""

import requests
import json
import logging
import numpy as np
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama API客户端"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        初始化Ollama客户端

        Args:
            base_url: Ollama服务地址
        """
        self.base_url = base_url.rstrip('/')
        self.generate_url = f"{self.base_url}/api/generate"
        self.embed_url = f"{self.base_url}/api/embeddings"

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> str:
        """
        生成文本

        Args:
            model: 模型名称
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大token数
            stream: 是否流式输出

        Returns:
            生成的文本
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": stream
        }

        if max_tokens:
            payload["options"] = {"num_predict": max_tokens}

        try:
            response = requests.post(
                self.generate_url,
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            if stream:
                # 流式输出处理
                result = ""
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        result += data.get("response", "")
                return result
            else:
                # 非流式输出
                data = response.json()
                return data.get("response", "")

        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API调用失败: {e}")
            raise

    def embeddings(
        self,
        model: str,
        text: str
    ) -> List[float]:
        """
        生成文本嵌入向量

        Args:
            model: 嵌入模型名称
            text: 输入文本

        Returns:
            嵌入向量
        """
        payload = {
            "model": model,
            "prompt": text
        }

        try:
            response = requests.post(
                self.embed_url,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding", [])

        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama Embeddings API调用失败: {e}")
            raise


class LLMTopicNamer:
    """
    LLM主题命名器

    使用LLM为聚类主题生成语义化的主题名称和描述
    """

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.3,
        max_samples_per_topic: int = 5,
        max_tokens_per_sample: int = 500,
        use_keywords: bool = True,
        sample_selection: str = 'closest'  # 'closest', 'random', 'diverse'
    ):
        """
        初始化LLM主题命名器

        Args:
            model: LLM模型名称
            base_url: Ollama服务地址
            temperature: 生成温度(越低越确定)
            max_samples_per_topic: 每个主题用于分析的最大样本数
            max_tokens_per_sample: 每个样本的最大token数(字符数约4倍)
            use_keywords: 是否在Prompt中包含关键词作为参考
            sample_selection: 样本选择策略 ('closest'最近, 'random'随机, 'diverse'多样性)
        """
        self.model = model
        self.temperature = temperature
        self.max_samples_per_topic = max_samples_per_topic
        self.max_tokens_per_sample = max_tokens_per_sample
        self.use_keywords = use_keywords
        self.sample_selection = sample_selection
        self.client = OllamaClient(base_url)

    def generate_topic_names(
        self,
        topics: Dict[int, Dict[str, Any]],
        sample_data: Optional[List[Dict]] = None,
        embeddings: Optional[np.ndarray] = None,
        cluster_labels: Optional[np.ndarray] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        为所有主题生成语义化名称

        Args:
            topics: 主题字典(来自TopicModeler)
            sample_data: 原始样本数据(必需,用于获取完整样本内容)
            embeddings: 样本的embedding向量(可选,用于选择代表性样本)
            cluster_labels: 聚类标签(可选,用于选择代表性样本)

        Returns:
            增强后的主题字典,包含LLM生成的语义描述
        """
        logger.info(f"开始使用LLM生成主题名称,共{len(topics)}个主题")

        enhanced_topics = {}

        for topic_id, topic_info in topics.items():
            logger.info(f"正在处理主题 {topic_id}...")

            keywords = topic_info.get('keywords', [])

            # 获取原始样本
            if sample_data and 'sample_indices' in topic_info:
                all_indices = topic_info['sample_indices']

                # 选择代表性样本
                selected_indices = self._select_representative_samples(
                    all_indices,
                    embeddings,
                    cluster_labels,
                    topic_id
                )

                # 格式化完整样本
                sample_docs = []
                for idx in selected_indices:
                    if idx < len(sample_data):
                        formatted = self._format_sample(sample_data[idx])
                        sample_docs.append(formatted)
            else:
                # 回退到使用sample_docs字段
                sample_docs = topic_info.get('sample_docs', [])
                logger.warning(f"主题 {topic_id} 缺少sample_indices,使用备用sample_docs")

            # 生成主题名称和描述
            try:
                topic_name, topic_description = self._generate_name_and_description(
                    sample_docs,
                    keywords
                )

                # 保留原有信息,添加LLM生成的内容
                enhanced_topics[topic_id] = {
                    **topic_info,
                    'llm_topic_name': topic_name,
                    'llm_topic_description': topic_description
                }

                logger.info(f"主题 {topic_id} 命名为: {topic_name}")

            except Exception as e:
                logger.error(f"生成主题 {topic_id} 名称失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # 保留原有信息
                enhanced_topics[topic_id] = {
                    **topic_info,
                    'llm_topic_name': topic_info.get('topic_summary', f"主题{topic_id}"),
                    'llm_topic_description': '生成失败'
                }

        logger.info("主题命名完成")
        return enhanced_topics

    def _select_representative_samples(
        self,
        sample_indices: List[int],
        embeddings: Optional[np.ndarray],
        cluster_labels: Optional[np.ndarray],
        topic_id: int
    ) -> List[int]:
        """
        选择代表性样本

        Args:
            sample_indices: 候选样本索引列表
            embeddings: embedding矩阵
            cluster_labels: 聚类标签
            topic_id: 主题ID

        Returns:
            选中的样本索引列表
        """
        import numpy as np

        n_select = min(self.max_samples_per_topic, len(sample_indices))

        # 如果没有embedding信息,随机采样
        if embeddings is None or cluster_labels is None:
            if self.sample_selection == 'random' or len(sample_indices) <= n_select:
                import random
                return random.sample(sample_indices, n_select) if len(sample_indices) > n_select else sample_indices
            return sample_indices[:n_select]

        # 获取该主题的所有样本的embedding
        cluster_mask = cluster_labels == topic_id
        cluster_indices = np.where(cluster_mask)[0]

        # 找到sample_indices在cluster_indices中的位置
        valid_indices = [idx for idx in sample_indices if idx in cluster_indices]
        if not valid_indices:
            # 如果没有匹配,回退到简单采样
            return sample_indices[:n_select]

        cluster_embeddings = embeddings[valid_indices]

        if self.sample_selection == 'closest':
            # 选择离聚类中心最近的样本
            centroid = np.mean(cluster_embeddings, axis=0)
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            closest_idx = np.argsort(distances)[:n_select]
            return [valid_indices[i] for i in closest_idx]

        elif self.sample_selection == 'diverse':
            # 多样性采样: 先选最近的,再选离已选样本较远的
            selected = []
            centroid = np.mean(cluster_embeddings, axis=0)

            # 先选离中心最近的
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            first_idx = np.argmin(distances)
            selected.append(first_idx)

            # 迭代选择与已选样本距离最大的
            for _ in range(n_select - 1):
                if len(selected) >= len(valid_indices):
                    break

                # 计算每个候选样本到已选样本的最小距离
                min_distances = []
                for i in range(len(cluster_embeddings)):
                    if i in selected:
                        min_distances.append(-1)  # 已选择
                    else:
                        dists = [np.linalg.norm(cluster_embeddings[i] - cluster_embeddings[j])
                                for j in selected]
                        min_distances.append(min(dists))

                # 选择距离最大的
                next_idx = np.argmax(min_distances)
                selected.append(next_idx)

            return [valid_indices[i] for i in selected]

        else:  # random
            import random
            return random.sample(valid_indices, n_select) if len(valid_indices) > n_select else valid_indices

    def _format_sample(self, sample: Dict) -> str:
        """
        格式化样本数据为文本

        Args:
            sample: 样本数据

        Returns:
            格式化的文本
        """
        if 'messages' in sample:
            # SFT格式 (ShareGPT)
            parts = []
            total_length = 0
            for msg in sample['messages']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '').strip()

                # 跳过system消息(通常是模板)
                if role == 'system':
                    continue

                # 控制每个消息的长度
                max_msg_len = self.max_tokens_per_sample // 2  # 一半给user,一半给assistant
                if len(content) > max_msg_len:
                    content = content[:max_msg_len] + "..."

                parts.append(f"[{role}]: {content}")
                total_length += len(content)

                # 总长度控制
                if total_length > self.max_tokens_per_sample:
                    break

            return '\n'.join(parts)

        elif 'instruction' in sample:
            # Instruction格式
            inst = sample.get('instruction', '').strip()
            out = sample.get('output', '').strip()

            # 动态分配长度
            half_len = self.max_tokens_per_sample // 2
            if len(inst) > half_len:
                inst = inst[:half_len] + "..."
            if len(out) > half_len:
                out = out[:half_len] + "..."

            return f"问题: {inst}\n回答: {out}"

        elif 'text' in sample:
            # 纯文本格式
            text = sample['text'].strip()
            if len(text) > self.max_tokens_per_sample:
                text = text[:self.max_tokens_per_sample] + "..."
            return text

        else:
            # 其他格式,尝试提取有用信息
            # 优先提取常见字段
            content_fields = ['content', 'query', 'response', 'question', 'answer']
            extracted = []

            for field in content_fields:
                if field in sample and sample[field]:
                    extracted.append(f"{field}: {str(sample[field])[:200]}")

            if extracted:
                text = '\n'.join(extracted)
            else:
                # 回退到JSON
                text = json.dumps(sample, ensure_ascii=False)

            if len(text) > self.max_tokens_per_sample:
                text = text[:self.max_tokens_per_sample] + "..."
            return text

    def _generate_name_and_description(
        self,
        sample_docs: List[str],
        keywords: List
    ) -> tuple[str, str]:
        """
        生成主题名称和描述

        Args:
            sample_docs: 样本文档列表
            keywords: 关键词列表

        Returns:
            (主题名称, 主题描述)
        """
        # 限制样本数量
        samples = sample_docs[:self.max_samples_per_topic]

        # 提取关键词文本
        keyword_texts = []
        for kw in keywords[:8]:
            if isinstance(kw, tuple):
                keyword_texts.append(kw[0])
            else:
                keyword_texts.append(str(kw))

        # 构建提示词
        prompt = self._build_prompt(samples, keyword_texts)

        # 调用LLM
        response = self.client.generate(
            model=self.model,
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=200
        )

        # 解析响应
        topic_name, topic_description = self._parse_response(response)

        return topic_name, topic_description

    def _build_prompt(
        self,
        samples: List[str],
        keywords: List[str]
    ) -> str:
        """
        构建提示词

        Args:
            samples: 样本文档
            keywords: 关键词

        Returns:
            提示词
        """
        # 格式化样本
        formatted_samples = []
        for i, sample in enumerate(samples, 1):
            formatted_samples.append(f"【样本{i}】\n{sample}")

        samples_text = "\n\n".join(formatted_samples)

        # 根据配置决定是否包含关键词
        if self.use_keywords and keywords:
            keyword_text = "参考关键词: " + ", ".join(keywords)
            keyword_section = f"\n\n{keyword_text}\n"
        else:
            keyword_section = "\n"

        prompt = f"""你是数据分析专家。请仔细阅读以下{len(samples)}个样本对话,总结这个数据主题的核心内容。

{samples_text}{keyword_section}
请生成简洁准确的主题名称和描述:
主题名称: [5-10字的简洁名称]
主题描述: [20-30字的一句话描述,说明这个主题的核心内容]
"""

        return prompt

    def _parse_response(self, response: str) -> tuple[str, str]:
        """
        解析LLM响应

        Args:
            response: LLM生成的文本

        Returns:
            (主题名称, 主题描述)
        """
        lines = response.strip().split('\n')

        topic_name = "未命名主题"
        topic_description = "暂无描述"

        for line in lines:
            line = line.strip()
            if line.startswith('主题名称:') or line.startswith('主题名称:'):
                topic_name = line.split(':', 1)[1].strip()
            elif line.startswith('主题描述:') or line.startswith('主题描述:'):
                topic_description = line.split(':', 1)[1].strip()

        # 清理可能的引号
        topic_name = topic_name.strip('"\'[]')
        topic_description = topic_description.strip('"\'[]')

        return topic_name, topic_description


class OllamaEmbedder:
    """
    Ollama嵌入向量生成器

    使用Ollama的embedding API生成文本向量
    """

    def __init__(
        self,
        model: str = "bge-m3:latest",
        base_url: str = "http://localhost:11434"
    ):
        """
        初始化Ollama嵌入器

        Args:
            model: 嵌入模型名称
            base_url: Ollama服务地址
        """
        self.model = model
        self.client = OllamaClient(base_url)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本嵌入向量

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表
        """
        embeddings = []

        logger.info(f"开始生成{len(texts)}个文本的嵌入向量")

        for i, text in enumerate(texts):
            try:
                embedding = self.client.embeddings(self.model, text)
                embeddings.append(embedding)

                if (i + 1) % 100 == 0:
                    logger.info(f"已生成 {i + 1}/{len(texts)} 个嵌入向量")

            except Exception as e:
                logger.error(f"生成第 {i} 个文本的嵌入向量失败: {e}")
                # 使用零向量作为占位符
                embeddings.append([])

        logger.info("嵌入向量生成完成")
        return embeddings

    def embed_single(self, text: str) -> List[float]:
        """
        生成单个文本的嵌入向量

        Args:
            text: 文本

        Returns:
            嵌入向量
        """
        try:
            return self.client.embeddings(self.model, text)
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}")
            return []
