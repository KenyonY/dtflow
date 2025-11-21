#!/usr/bin/env python3
"""
使用LLM主题命名的SFT数据集分析脚本

该脚本演示如何使用Ollama的embedding和LLM模型进行数据集分析
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_transformer.analysis.analyzer import SFTDataAnalyzer


def main():
    parser = argparse.ArgumentParser(
        description='使用LLM主题命名的SFT数据集分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用Ollama embedding和LLM主题命名分析数据集
  python scripts/analyze_with_llm.py \\
    --input data/sample_10k.jsonl \\
    --output analysis_results_llm \\
    --use-ollama-embedding \\
    --ollama-embed-model bge-m3:latest \\
    --ollama-llm-model gemma2:4b

  # 只使用LLM主题命名,不使用Ollama embedding
  python scripts/analyze_with_llm.py \\
    --input data/sample_10k.jsonl \\
    --output analysis_results_llm

  # 指定采样大小
  python scripts/analyze_with_llm.py \\
    --input data/large_dataset.jsonl \\
    --sample-size 5000 \\
    --output analysis_results_llm

注意:
  - 需要先启动Ollama服务: ollama serve
  - 需要下载模型: ollama pull bge-m3:latest && ollama pull gemma2:4b
        """
    )

    parser.add_argument(
        '--input',
        required=True,
        help='输入数据文件路径 (JSONL格式)'
    )
    parser.add_argument(
        '--output',
        default='./analysis_results_llm',
        help='输出目录 (默认: ./analysis_results_llm)'
    )
    parser.add_argument(
        '--sample-size',
        type=int,
        help='采样大小 (默认: 使用全部数据)'
    )
    parser.add_argument(
        '--use-ollama-embedding',
        action='store_true',
        help='使用Ollama embedding模型 (默认: 使用BM25)'
    )
    parser.add_argument(
        '--ollama-embed-model',
        default='bge-m3:latest',
        help='Ollama embedding模型名称 (默认: bge-m3:latest)'
    )
    parser.add_argument(
        '--ollama-llm-model',
        default='gemma3:4b',
        help='Ollama LLM模型名称 (默认: gemma3:4b)'
    )
    parser.add_argument(
        '--ollama-url',
        default='http://localhost:11434',
        help='Ollama服务地址 (默认: http://localhost:11434)'
    )
    parser.add_argument(
        '--n-clusters',
        type=int,
        default=100,
        help='K-Means聚类数量 (默认: 100)'
    )
    parser.add_argument(
        '--min-cluster-size',
        type=int,
        default=50,
        help='HDBSCAN最小聚类大小 (默认: 50)'
    )
    parser.add_argument(
        '--clustering-method',
        choices=['kmeans', 'hdbscan', 'hierarchical'],
        default='hierarchical',
        help='聚类方法 (默认: hierarchical)'
    )
    parser.add_argument(
        '--topic-method',
        choices=['tfidf', 'textrank', 'lda'],
        default='tfidf',
        help='主题提取方法 (默认: tfidf)'
    )
    parser.add_argument(
        '--no-llm-naming',
        action='store_true',
        help='禁用LLM主题命名'
    )
    parser.add_argument(
        '--no-report',
        action='store_true',
        help='不生成HTML报告'
    )
    parser.add_argument(
        '--analyze-by-role',
        action='store_true',
        help='分别对user和assistant进行聚类分析'
    )

    args = parser.parse_args()

    # 验证输入文件
    input_file = Path(args.input)
    if not input_file.exists():
        print(f"错误: 输入文件不存在: {input_file}")
        sys.exit(1)

    print("="*60)
    print("SFT数据集分析 (使用LLM主题命名)")
    print("="*60)
    print(f"输入文件: {args.input}")
    print(f"输出目录: {args.output}")
    print(f"Embedding模型: {'Ollama-' + args.ollama_embed_model if args.use_ollama_embedding else 'BM25'}")
    print(f"LLM模型: {args.ollama_llm_model if not args.no_llm_naming else '禁用'}")
    print(f"聚类方法: {args.clustering_method}")
    print(f"主题提取: {args.topic_method}")
    print("="*60)

    # 初始化分析器
    analyzer = SFTDataAnalyzer(
        n_clusters=args.n_clusters,
        min_cluster_size=args.min_cluster_size,
        use_jieba=True,
        output_dir=args.output,
        use_ollama_embedding=args.use_ollama_embedding,
        ollama_embed_model=args.ollama_embed_model,
        ollama_llm_model=args.ollama_llm_model,
        ollama_base_url=args.ollama_url
    )

    # 执行分析
    try:
        results = analyzer.analyze(
            data=args.input,
            sample_size=args.sample_size,
            clustering_method=args.clustering_method,
            topic_method=args.topic_method,
            generate_report=not args.no_report,
            cache_embeddings=True,
            use_llm_topic_naming=not args.no_llm_naming,
            analyze_by_role=args.analyze_by_role
        )

        print("\n✓ 分析完成!")
        print(f"\n查看结果:")
        print(f"  • 分析报告: {args.output}/analysis_report.html")
        print(f"  • 聚类可视化: {args.output}/clustering_plot.html")
        print(f"  • 主题分布: {args.output}/topics_plot.html")
        print(f"  • 质量指标: {args.output}/quality_metrics.html")
        print(f"  • 词云: {args.output}/wordcloud.png")
        print(f"\n查看主题列表:")
        print(f"  python scripts/view_topic_samples.py --list --analysis-dir {args.output}")
        print(f"\n查看特定主题样本:")
        print(f"  python scripts/view_topic_samples.py --topic 0 --data {args.input} --analysis-dir {args.output}")

    except Exception as e:
        print(f"\n✗ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
