"""
数据质量评估模块 - 评估SFT数据集的质量

包括长度分布、多样性、复杂度、重复性等指标
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
import re
import logging
from dataclasses import dataclass
import statistics

logger = logging.getLogger(__name__)


@dataclass
class QualityMetrics:
    """质量评估指标数据类"""
    length_stats: Dict[str, float]  # 长度统计
    diversity_scores: Dict[str, float]  # 多样性分数
    complexity_scores: Dict[str, float]  # 复杂度分数
    duplication_stats: Dict[str, float]  # 重复统计
    format_quality: Dict[str, float]  # 格式质量
    overall_score: float  # 总体质量分数
    warnings: List[str]  # 质量警告
    recommendations: List[str]  # 改进建议


class QualityEvaluator:
    """
    数据质量评估器

    评估SFT数据集的各项质量指标
    """

    def __init__(
        self,
        min_length: int = 10,
        max_length: int = 2000,
        target_diversity: float = 0.8
    ):
        """
        初始化质量评估器

        Args:
            min_length: 最小文本长度
            max_length: 最大文本长度
            target_diversity: 目标多样性分数
        """
        self.min_length = min_length
        self.max_length = max_length
        self.target_diversity = target_diversity

    def evaluate(
        self,
        data: List[Dict[str, str]],
        cluster_labels: Optional[np.ndarray] = None
    ) -> QualityMetrics:
        """
        评估数据集质量

        Args:
            data: SFT数据列表（包含instruction和output）
            cluster_labels: 聚类标签（可选）

        Returns:
            质量评估结果
        """
        logger.info(f"开始评估数据集质量，样本数：{len(data)}")

        # 提取指令和输出
        instructions = [item.get('instruction', '') for item in data]
        outputs = [item.get('output', '') for item in data]

        # 1. 长度统计
        length_stats = self._analyze_length_distribution(instructions, outputs)

        # 2. 多样性评估
        diversity_scores = self._evaluate_diversity(instructions, outputs, cluster_labels)

        # 3. 复杂度评估
        complexity_scores = self._evaluate_complexity(instructions, outputs)

        # 4. 重复性检测
        duplication_stats = self._detect_duplication(instructions, outputs)

        # 5. 格式质量检查
        format_quality = self._check_format_quality(data)

        # 6. 计算总体分数
        overall_score = self._calculate_overall_score(
            length_stats, diversity_scores, complexity_scores,
            duplication_stats, format_quality
        )

        # 7. 生成警告和建议
        warnings = self._generate_warnings(
            length_stats, diversity_scores, duplication_stats, format_quality
        )
        recommendations = self._generate_recommendations(
            length_stats, diversity_scores, complexity_scores, duplication_stats
        )

        return QualityMetrics(
            length_stats=length_stats,
            diversity_scores=diversity_scores,
            complexity_scores=complexity_scores,
            duplication_stats=duplication_stats,
            format_quality=format_quality,
            overall_score=overall_score,
            warnings=warnings,
            recommendations=recommendations
        )

    def _analyze_length_distribution(
        self,
        instructions: List[str],
        outputs: List[str]
    ) -> Dict[str, float]:
        """
        分析长度分布

        Args:
            instructions: 指令列表
            outputs: 输出列表

        Returns:
            长度统计信息
        """
        inst_lengths = [len(inst) for inst in instructions]
        out_lengths = [len(out) for out in outputs]
        total_lengths = [i + o for i, o in zip(inst_lengths, out_lengths)]

        stats = {
            'instruction_mean': np.mean(inst_lengths),
            'instruction_median': np.median(inst_lengths),
            'instruction_std': np.std(inst_lengths),
            'instruction_min': min(inst_lengths),
            'instruction_max': max(inst_lengths),
            'output_mean': np.mean(out_lengths),
            'output_median': np.median(out_lengths),
            'output_std': np.std(out_lengths),
            'output_min': min(out_lengths),
            'output_max': max(out_lengths),
            'total_mean': np.mean(total_lengths),
            'total_median': np.median(total_lengths),
            'too_short_ratio': sum(1 for l in total_lengths if l < self.min_length) / len(total_lengths),
            'too_long_ratio': sum(1 for l in total_lengths if l > self.max_length) / len(total_lengths)
        }

        # 计算长度分布的均匀性（使用变异系数）
        cv_instruction = stats['instruction_std'] / stats['instruction_mean'] if stats['instruction_mean'] > 0 else 0
        cv_output = stats['output_std'] / stats['output_mean'] if stats['output_mean'] > 0 else 0
        stats['length_uniformity'] = 1 / (1 + (cv_instruction + cv_output) / 2)

        return stats

    def _evaluate_diversity(
        self,
        instructions: List[str],
        outputs: List[str],
        cluster_labels: Optional[np.ndarray]
    ) -> Dict[str, float]:
        """
        评估多样性

        Args:
            instructions: 指令列表
            outputs: 输出列表
            cluster_labels: 聚类标签

        Returns:
            多样性分数
        """
        scores = {}

        # 1. 词汇多样性（Type-Token Ratio）
        all_inst_tokens = []
        all_out_tokens = []
        for inst, out in zip(instructions, outputs):
            inst_tokens = inst.lower().split()
            out_tokens = out.lower().split()
            all_inst_tokens.extend(inst_tokens)
            all_out_tokens.extend(out_tokens)

        inst_vocab_diversity = len(set(all_inst_tokens)) / len(all_inst_tokens) if all_inst_tokens else 0
        out_vocab_diversity = len(set(all_out_tokens)) / len(all_out_tokens) if all_out_tokens else 0
        scores['vocabulary_diversity'] = (inst_vocab_diversity + out_vocab_diversity) / 2

        # 2. N-gram多样性
        scores['bigram_diversity'] = self._calculate_ngram_diversity(instructions + outputs, n=2)
        scores['trigram_diversity'] = self._calculate_ngram_diversity(instructions + outputs, n=3)

        # 3. 聚类多样性（如果有聚类标签）
        if cluster_labels is not None:
            unique_clusters = len(np.unique(cluster_labels[cluster_labels >= 0]))
            scores['cluster_diversity'] = unique_clusters / len(cluster_labels)

            # 计算聚类熵
            cluster_counts = Counter(cluster_labels[cluster_labels >= 0])
            total = sum(cluster_counts.values())
            entropy = -sum(
                (count/total) * np.log2(count/total)
                for count in cluster_counts.values() if count > 0
            )
            max_entropy = np.log2(unique_clusters) if unique_clusters > 0 else 1
            scores['cluster_entropy'] = entropy / max_entropy if max_entropy > 0 else 0

        # 4. 模板多样性（检测是否有重复的模式）
        template_diversity = self._evaluate_template_diversity(instructions)
        scores['template_diversity'] = template_diversity

        return scores

    def _calculate_ngram_diversity(self, texts: List[str], n: int) -> float:
        """
        计算N-gram多样性

        Args:
            texts: 文本列表
            n: N-gram的N值

        Returns:
            多样性分数
        """
        all_ngrams = []
        for text in texts:
            tokens = text.lower().split()
            ngrams = [tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1)]
            all_ngrams.extend(ngrams)

        if not all_ngrams:
            return 0

        return len(set(all_ngrams)) / len(all_ngrams)

    def _evaluate_template_diversity(self, texts: List[str]) -> float:
        """
        评估模板多样性

        Args:
            texts: 文本列表

        Returns:
            模板多样性分数
        """
        # 将文本转换为简化的模板形式
        templates = []
        for text in texts[:1000]:  # 采样评估
            # 替换数字、URL等为占位符
            template = re.sub(r'\d+', '<NUM>', text)
            template = re.sub(r'https?://\S+', '<URL>', template)
            template = re.sub(r'\S+@\S+', '<EMAIL>', template)
            # 保留前50个字符作为模板
            template = template[:50]
            templates.append(template)

        # 计算模板的唯一性
        unique_templates = len(set(templates))
        total_templates = len(templates)

        return unique_templates / total_templates if total_templates > 0 else 0

    def _evaluate_complexity(
        self,
        instructions: List[str],
        outputs: List[str]
    ) -> Dict[str, float]:
        """
        评估文本复杂度

        Args:
            instructions: 指令列表
            outputs: 输出列表

        Returns:
            复杂度分数
        """
        scores = {}

        # 1. 平均句子长度
        inst_sent_lengths = []
        out_sent_lengths = []
        for inst, out in zip(instructions, outputs):
            inst_sents = re.split(r'[.!?。！？]', inst)
            out_sents = re.split(r'[.!?。！？]', out)
            inst_sent_lengths.extend([len(s.split()) for s in inst_sents if s.strip()])
            out_sent_lengths.extend([len(s.split()) for s in out_sents if s.strip()])

        scores['avg_sentence_length'] = np.mean(inst_sent_lengths + out_sent_lengths) if (inst_sent_lengths + out_sent_lengths) else 0

        # 2. 词汇复杂度（平均词长）
        all_words = []
        for text in instructions + outputs:
            words = re.findall(r'\b\w+\b', text.lower())
            all_words.extend(words)

        scores['avg_word_length'] = np.mean([len(w) for w in all_words]) if all_words else 0

        # 3. 标点符号密度
        punct_density = []
        for text in instructions + outputs:
            if len(text) > 0:
                punct_count = len(re.findall(r'[,.!?;:，。！？；：]', text))
                punct_density.append(punct_count / len(text))

        scores['punctuation_density'] = np.mean(punct_density) if punct_density else 0

        # 4. 代码/数学内容检测
        code_patterns = [r'```', r'def ', r'class ', r'import ', r'function', r'{\s*}', r'\$.*\$']
        code_count = 0
        for text in instructions + outputs:
            if any(re.search(pattern, text) for pattern in code_patterns):
                code_count += 1

        scores['code_content_ratio'] = code_count / len(instructions)

        # 5. 多语言检测
        chinese_count = sum(1 for text in instructions + outputs if re.search(r'[\u4e00-\u9fff]', text))
        scores['multilingual_ratio'] = chinese_count / (len(instructions) + len(outputs))

        return scores

    def _detect_duplication(
        self,
        instructions: List[str],
        outputs: List[str]
    ) -> Dict[str, float]:
        """
        检测重复内容

        Args:
            instructions: 指令列表
            outputs: 输出列表

        Returns:
            重复统计信息
        """
        stats = {}

        # 1. 完全重复的指令
        inst_counter = Counter(instructions)
        duplicate_insts = sum(1 for count in inst_counter.values() if count > 1)
        stats['duplicate_instruction_ratio'] = duplicate_insts / len(instructions)

        # 2. 完全重复的输出
        out_counter = Counter(outputs)
        duplicate_outs = sum(1 for count in out_counter.values() if count > 1)
        stats['duplicate_output_ratio'] = duplicate_outs / len(outputs)

        # 3. 近似重复（基于前缀）
        prefix_len = 50
        inst_prefixes = [inst[:prefix_len] for inst in instructions]
        prefix_counter = Counter(inst_prefixes)
        near_duplicate = sum(1 for count in prefix_counter.values() if count > 3)
        stats['near_duplicate_ratio'] = near_duplicate / len(instructions)

        # 4. 最大重复次数
        stats['max_duplication'] = max(inst_counter.values()) if inst_counter else 0

        # 5. 唯一样本比例
        unique_pairs = set(zip(instructions, outputs))
        stats['unique_sample_ratio'] = len(unique_pairs) / len(instructions)

        return stats

    def _check_format_quality(self, data: List[Dict[str, str]]) -> Dict[str, float]:
        """
        检查格式质量

        Args:
            data: 数据列表

        Returns:
            格式质量统计
        """
        quality = {
            'complete_samples': 0,  # 完整的样本
            'missing_instruction': 0,  # 缺少指令
            'missing_output': 0,  # 缺少输出
            'empty_instruction': 0,  # 空指令
            'empty_output': 0,  # 空输出
            'malformed': 0  # 格式错误
        }

        for item in data:
            if not isinstance(item, dict):
                quality['malformed'] += 1
                continue

            has_instruction = 'instruction' in item
            has_output = 'output' in item

            if has_instruction and has_output:
                if item['instruction'].strip() and item['output'].strip():
                    quality['complete_samples'] += 1
                else:
                    if not item['instruction'].strip():
                        quality['empty_instruction'] += 1
                    if not item['output'].strip():
                        quality['empty_output'] += 1
            else:
                if not has_instruction:
                    quality['missing_instruction'] += 1
                if not has_output:
                    quality['missing_output'] += 1

        # 转换为比例
        n_samples = len(data)
        for key in quality:
            quality[key] = quality[key] / n_samples if n_samples > 0 else 0

        return quality

    def _calculate_overall_score(
        self,
        length_stats: Dict[str, float],
        diversity_scores: Dict[str, float],
        complexity_scores: Dict[str, float],
        duplication_stats: Dict[str, float],
        format_quality: Dict[str, float]
    ) -> float:
        """
        计算总体质量分数

        Returns:
            总体分数（0-100）
        """
        scores = []
        weights = []

        # 长度质量（权重20%）
        length_score = (
            (1 - length_stats['too_short_ratio']) * 50 +
            (1 - length_stats['too_long_ratio']) * 30 +
            length_stats['length_uniformity'] * 20
        )
        scores.append(length_score)
        weights.append(0.2)

        # 多样性（权重30%）- 归一化到0-100
        diversity_score = (
            diversity_scores.get('vocabulary_diversity', 0) * 30 +
            diversity_scores.get('bigram_diversity', 0) * 30 +
            diversity_scores.get('template_diversity', 0) * 40
        )  # 已经是0-100范围，不需要再乘100
        scores.append(diversity_score)
        weights.append(0.3)

        # 复杂度（权重15%）- 归一化到0-100
        complexity_score = min(100, (
            min(complexity_scores['avg_sentence_length'] / 15, 1) * 50 +
            min(complexity_scores['avg_word_length'] / 6, 1) * 50
        ))  # 已经是0-100范围，不需要再乘100
        scores.append(complexity_score)
        weights.append(0.15)

        # 去重质量（权重25%）- 归一化到0-100
        dedup_score = (
            duplication_stats['unique_sample_ratio'] * 60 +
            (1 - duplication_stats['duplicate_instruction_ratio']) * 20 +
            (1 - duplication_stats['duplicate_output_ratio']) * 20
        )  # 已经是0-100范围，不需要再乘100
        scores.append(dedup_score)
        weights.append(0.25)

        # 格式质量（权重10%）- 归一化到0-100
        format_score = format_quality['complete_samples'] * 100
        scores.append(format_score)
        weights.append(0.1)

        # 加权平均
        overall = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        return round(overall, 2)

    def _generate_warnings(
        self,
        length_stats: Dict[str, float],
        diversity_scores: Dict[str, float],
        duplication_stats: Dict[str, float],
        format_quality: Dict[str, float]
    ) -> List[str]:
        """
        生成质量警告

        Returns:
            警告列表
        """
        warnings = []

        # 长度警告
        if length_stats['too_short_ratio'] > 0.1:
            warnings.append(f"⚠️ {length_stats['too_short_ratio']:.1%}的样本过短（<{self.min_length}字符）")
        if length_stats['too_long_ratio'] > 0.1:
            warnings.append(f"⚠️ {length_stats['too_long_ratio']:.1%}的样本过长（>{self.max_length}字符）")

        # 多样性警告
        if diversity_scores.get('vocabulary_diversity', 1) < 0.3:
            warnings.append("⚠️ 词汇多样性较低，可能存在大量重复表达")
        if diversity_scores.get('template_diversity', 1) < 0.5:
            warnings.append("⚠️ 模板多样性较低，数据可能过于模式化")

        # 重复警告
        if duplication_stats['duplicate_instruction_ratio'] > 0.05:
            warnings.append(f"⚠️ {duplication_stats['duplicate_instruction_ratio']:.1%}的指令完全重复")
        if duplication_stats['max_duplication'] > 10:
            warnings.append(f"⚠️ 存在重复超过{duplication_stats['max_duplication']}次的样本")

        # 格式警告
        if format_quality['complete_samples'] < 0.95:
            warnings.append(f"⚠️ 只有{format_quality['complete_samples']:.1%}的样本格式完整")

        return warnings

    def _generate_recommendations(
        self,
        length_stats: Dict[str, float],
        diversity_scores: Dict[str, float],
        complexity_scores: Dict[str, float],
        duplication_stats: Dict[str, float]
    ) -> List[str]:
        """
        生成改进建议

        Returns:
            建议列表
        """
        recommendations = []

        # 基于统计生成建议
        if length_stats['instruction_std'] > length_stats['instruction_mean'] * 0.5:
            recommendations.append("📝 建议：标准化指令长度，提高数据一致性")

        if diversity_scores.get('vocabulary_diversity', 1) < 0.4:
            recommendations.append("📝 建议：增加词汇多样性，引入更多不同表达方式")

        if duplication_stats['unique_sample_ratio'] < 0.95:
            recommendations.append("📝 建议：去除重复样本，保留唯一性高的数据")

        if complexity_scores['avg_sentence_length'] < 10:
            recommendations.append("📝 建议：增加句子复杂度，提供更丰富的训练信号")

        if not recommendations:
            recommendations.append("✅ 数据集质量良好，可以用于训练")

        return recommendations