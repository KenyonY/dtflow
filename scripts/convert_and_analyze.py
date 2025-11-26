"""
转换 ShareGPT 格式数据到 SFT 格式并进行分析
"""
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_transformer.formats.sft import SFTFormatter
from data_transformer.analysis.analyzer import SFTDataAnalyzer


def convert_sharegpt_to_sft(input_file: str, output_file: str, style: str = 'simple'):
    """
    将 ShareGPT 格式转换为 SFT 格式

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        style: 转换风格 ('simple' 或 'messages')
    """
    print(f"正在转换文件: {input_file}")
    formatter = SFTFormatter()

    converted_count = 0
    with open(input_file, 'r', encoding='utf-8') as fin, \
         open(output_file, 'w', encoding='utf-8') as fout:

        for line in fin:
            item = json.loads(line)

            # 预处理：将 ShareGPT 格式的 role 映射为标准格式
            if 'conversations' in item:
                for turn in item['conversations']:
                    if 'from' in turn:
                        # 映射 ShareGPT 的 role
                        role_map = {'human': 'user', 'gpt': 'assistant'}
                        turn['from'] = role_map.get(turn['from'], turn['from'])

            # 如果是 simple 风格，需要先转为 messages 再转为 simple
            if style == 'simple' and 'conversations' in item:
                # 先转为 messages 格式
                item = formatter.format(item, style='messages')
            # 再转换为目标格式
            converted_item = formatter.format(item, style=style)
            fout.write(json.dumps(converted_item, ensure_ascii=False) + '\n')
            converted_count += 1

    print(f"转换完成! 已转换 {converted_count:,} 条数据")
    print(f"输出文件: {output_file}")


def analyze_sft_data(
    input_file: str,
    output_dir: str,
    sample_size: int = None,
    topic_method: str = 'ctfidf',
    auto_clusters: bool = True,
    n_clusters: int = 30
):
    """
    分析 SFT 数据集

    Args:
        input_file: SFT 格式的输入文件
        output_dir: 输出目录
        sample_size: 采样大小（None 表示使用全部数据）
        topic_method: 主题提取方法
        auto_clusters: 是否自动确定聚类数
        n_clusters: 固定聚类数（auto_clusters=False时使用）
    """
    print(f"\n开始分析数据集...")

    # 创建分析器
    analyzer = SFTDataAnalyzer(
        n_clusters=n_clusters,  # 初始聚类数量
        min_cluster_size=20,  # 最小聚类大小
        use_jieba=True,  # 使用中文分词
        output_dir=output_dir,
        cache_dir="./cache"
    )

    # 执行分析
    results = analyzer.analyze(
        data=input_file,
        sample_size=sample_size,
        clustering_method='kmeans',  # 使用 kmeans
        topic_method=topic_method,  # 支持多种主题方法
        generate_report=True,  # 启用报告生成
        cache_embeddings=True,
        auto_clusters=auto_clusters,  # 是否自动确定聚类数
        auto_cluster_method='combined'  # 使用综合方法
    )

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="转换 ShareGPT 格式并分析")
    parser.add_argument("--input", "-i", required=True, help="输入文件路径")
    parser.add_argument("--output-dir", "-o", default="./analysis_output", help="分析结果输出目录")
    parser.add_argument("--style", choices=['simple', 'messages'], default='simple',
                       help="SFT 转换风格 (默认: simple)")
    parser.add_argument("--sample-size", type=int, default=None,
                       help="采样大小（默认: 全部数据）")
    parser.add_argument("--skip-convert", action='store_true',
                       help="跳过转换步骤，直接分析（假设输入已是 SFT 格式）")

    # 新增参数
    parser.add_argument("--topic-method", choices=['tfidf', 'textrank', 'ctfidf', 'bertopic', 'lda', 'lda_enhanced'],
                       default='ctfidf',
                       help="主题提取方法 (默认: ctfidf - 推荐)")
    parser.add_argument("--auto-clusters", action='store_true', default=True,
                       help="自动确定最佳聚类数 (默认: 启用)")
    parser.add_argument("--n-clusters", type=int, default=30,
                       help="固定聚类数（仅在 --no-auto-clusters 时使用）")
    parser.add_argument("--no-auto-clusters", dest='auto_clusters', action='store_false',
                       help="禁用自动聚类数确定")

    args = parser.parse_args()

    # 转换格式
    if not args.skip_convert:
        converted_file = Path(args.input).parent / f"converted_{Path(args.input).stem}.jsonl"
        convert_sharegpt_to_sft(args.input, str(converted_file), args.style)
        input_file = str(converted_file)
    else:
        input_file = args.input

    # 分析数据
    analyze_sft_data(
        input_file,
        args.output_dir,
        args.sample_size,
        topic_method=args.topic_method,
        auto_clusters=args.auto_clusters,
        n_clusters=args.n_clusters
    )

    print("\n[完成] 全部完成!")
