"""
SFT数据集分析示例

展示如何使用data_transformer的analysis模块分析大规模SFT数据集
"""

import json
import argparse
from pathlib import Path
import logging
from typing import List, Dict

# 导入分析器
from data_transformer.analysis import SFTDataAnalyzer


def generate_sample_data(n_samples: int = 1000) -> List[Dict[str, str]]:
    """
    生成示例SFT数据

    Args:
        n_samples: 样本数量

    Returns:
        SFT数据列表
    """
    import random

    # 示例指令模板
    instruction_templates = [
        "请解释{concept}的概念",
        "如何实现{task}？",
        "请比较{item1}和{item2}的区别",
        "写一个关于{topic}的{type}",
        "将以下{source_lang}翻译成{target_lang}",
        "请分析{subject}的{aspect}",
        "生成一个{domain}领域的{content_type}",
        "解决这个{problem_type}问题",
        "优化以下{code_type}代码",
        "总结{document_type}的要点"
    ]

    # 示例输出模板
    output_templates = [
        "{concept}是一个重要的概念，它指的是...",
        "要实现{task}，您需要按照以下步骤：1. 准备... 2. 执行... 3. 验证...",
        "{item1}和{item2}的主要区别在于：首先，{item1}更注重...而{item2}强调...",
        "这是一个关于{topic}的{type}示例，包含了详细的说明和实现方法...",
        "翻译结果如下：[翻译内容]。这个翻译保持了原文的语义和风格...",
        "通过分析{subject}的{aspect}，我们可以发现以下几个关键点...",
        "根据您的需求，我生成了以下{domain}领域的{content_type}...",
        "针对这个{problem_type}问题，解决方案如下：首先分析问题的本质...",
        "优化后的{code_type}代码如下，主要改进了性能和可读性...",
        "{document_type}的主要要点包括：1. 核心观点... 2. 支撑论据... 3. 结论..."
    ]

    # 参数值
    concepts = ["机器学习", "深度学习", "自然语言处理", "计算机视觉", "强化学习"]
    tasks = ["数据预处理", "模型训练", "特征工程", "超参数调优", "模型部署"]
    items = ["Python", "Java", "神经网络", "决策树", "SVM", "LSTM", "Transformer"]
    topics = ["人工智能", "数据科学", "软件工程", "云计算", "网络安全"]
    types = ["教程", "案例", "报告", "分析", "总结"]
    languages = ["中文", "英文", "日文", "法文", "德文"]
    domains = ["医疗", "金融", "教育", "零售", "制造"]
    problem_types = ["算法", "系统设计", "数据结构", "优化", "调试"]

    data = []
    for i in range(n_samples):
        # 随机选择模板
        inst_template = random.choice(instruction_templates)
        out_template = random.choice(output_templates)

        # 填充参数
        params = {
            'concept': random.choice(concepts),
            'task': random.choice(tasks),
            'item1': random.choice(items),
            'item2': random.choice(items),
            'topic': random.choice(topics),
            'type': random.choice(types),
            'source_lang': random.choice(languages),
            'target_lang': random.choice(languages),
            'subject': random.choice(topics),
            'aspect': random.choice(['优势', '劣势', '应用', '原理', '发展']),
            'domain': random.choice(domains),
            'content_type': random.choice(['方案', '报告', '代码', '文档']),
            'problem_type': random.choice(problem_types),
            'code_type': random.choice(['Python', 'JavaScript', 'Java']),
            'document_type': random.choice(['论文', '报告', '文章', '书籍'])
        }

        # 生成指令和输出
        instruction = inst_template.format(**params)
        output = out_template.format(**params)

        # 添加一些变化
        if random.random() > 0.7:
            instruction += " 请详细说明。"
        if random.random() > 0.8:
            output += " 这是一个非常重要的概念，需要深入理解。"

        # 有时添加输入字段
        input_text = ""
        if random.random() > 0.7:
            input_text = f"相关背景信息：{random.choice(['这是一个常见问题', '需要考虑实际应用', '注意边界情况'])}"

        data.append({
            'instruction': instruction,
            'input': input_text,
            'output': output
        })

    return data


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='分析SFT数据集')
    parser.add_argument(
        '--data_file',
        type=str,
        help='数据文件路径（JSON或JSONL格式）'
    )
    parser.add_argument(
        '--sample_size',
        type=int,
        default=None,
        help='采样大小（用于大数据集的快速分析）'
    )
    parser.add_argument(
        '--n_clusters',
        type=int,
        default=50,
        help='聚类数量'
    )
    parser.add_argument(
        '--clustering_method',
        type=str,
        default='hierarchical',
        choices=['kmeans', 'hdbscan', 'hierarchical'],
        help='聚类方法'
    )
    parser.add_argument(
        '--topic_method',
        type=str,
        default='tfidf',
        choices=['tfidf', 'textrank', 'lda'],
        help='主题提取方法'
    )
    parser.add_argument(
        '--output_dir',
        type=str,
        default='./analysis_output',
        help='输出目录'
    )
    parser.add_argument(
        '--use_sample_data',
        action='store_true',
        help='使用生成的示例数据进行测试'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='显示详细日志'
    )

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 准备数据
    if args.use_sample_data:
        print("生成示例数据...")
        data = generate_sample_data(n_samples=1000)
        print(f"生成了{len(data)}条示例数据")
    elif args.data_file:
        print(f"从文件加载数据：{args.data_file}")
        data = args.data_file
    else:
        print("错误：请指定数据文件或使用--use_sample_data选项")
        return

    # 创建分析器
    analyzer = SFTDataAnalyzer(
        n_clusters=args.n_clusters,
        use_jieba=True,
        output_dir=args.output_dir
    )

    # 执行分析
    print("\n开始分析数据集...")
    print("="*60)

    results = analyzer.analyze(
        data=data,
        sample_size=args.sample_size,
        clustering_method=args.clustering_method,
        topic_method=args.topic_method,
        generate_report=True,
        cache_embeddings=True
    )

    # 打印主要结果
    print("\n分析结果摘要：")
    print("-"*60)
    print(f"样本总数：{results['n_samples']}")

    if 'quality' in results:
        quality = results['quality']
        print(f"总体质量分数：{quality['overall_score']:.1f}/100")
        print(f"词汇多样性：{quality['diversity_scores'].get('vocabulary_diversity', 0):.3f}")

    if 'topics' in results:
        print(f"\n发现的主要主题（前5个）：")
        for i, (topic_id, topic_info) in enumerate(list(results['topics'].items())[:5]):
            keywords = [kw[0] for kw in topic_info['keywords'][:5]]
            print(f"  主题{topic_id}: {', '.join(keywords)} (样本数: {topic_info['size']})")

    print(f"\n详细报告已保存到：{args.output_dir}/analysis_report.html")
    print("="*60)


if __name__ == '__main__':
    main()