#!/usr/bin/env python3
"""
Analysis 模块性能测试脚本

在不同规模数据集上测试分析性能
"""

import json
import time
import psutil
import os
from pathlib import Path
from typing import Dict, List
import warnings

# 忽略警告
warnings.filterwarnings('ignore')

from data_transformer.analysis.analyzer import SFTDataAnalyzer


def load_data(file_path: str) -> List[dict]:
    """加载测试数据"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                # 转换为分析器需要的格式
                instruction = None
                output = None
                for msg in item['messages']:
                    if msg['role'] == 'user':
                        instruction = msg['content']
                    elif msg['role'] == 'assistant':
                        output = msg['content']
                if instruction and output:
                    data.append({'instruction': instruction, 'output': output})
    return data


def get_memory_usage() -> float:
    """获取当前进程内存使用量（MB）"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def run_analysis(data: List[dict], dataset_name: str, output_dir: str) -> Dict:
    """
    运行分析并记录性能指标

    Returns:
        性能指标字典
    """
    print(f"\n{'='*60}")
    print(f"测试数据集: {dataset_name}")
    print(f"数据量: {len(data)} 条")
    print(f"{'='*60}\n")

    # 记录初始内存
    mem_before = get_memory_usage()

    # 创建分析器
    analyzer = SFTDataAnalyzer(
        n_clusters=min(10, len(data) // 10),  # 动态调整聚类数
        output_dir=output_dir,
        cache_dir=None
    )

    # 运行分析
    start_time = time.time()

    try:
        results = analyzer.analyze(
            data,
            clustering_method='kmeans',
            topic_method='tfidf',
            generate_report=False,  # 不生成HTML报告以节省时间
            cache_embeddings=False
        )

        total_time = time.time() - start_time
        mem_after = get_memory_usage()
        mem_used = mem_after - mem_before

        # 提取关键指标（注意：quality和clustering可能是字典或对象）
        clustering = results['clustering']
        quality = results['quality']

        # 处理clustering（可能是对象或字典）
        if hasattr(clustering, 'n_clusters'):
            n_clusters = clustering.n_clusters
            silhouette = clustering.scores.get('silhouette', 0)
        else:
            n_clusters = clustering.get('n_clusters', 0)
            silhouette = clustering.get('scores', {}).get('silhouette', 0)

        # 处理quality（字典格式）
        if isinstance(quality, dict):
            overall_score = quality.get('overall_score', 0)
        else:
            overall_score = quality.overall_score

        metrics = {
            'dataset_name': dataset_name,
            'data_size': len(data),
            'total_time': round(total_time, 2),
            'memory_used_mb': round(mem_used, 2),
            'throughput': round(len(data) / total_time, 2),  # 条/秒
            'n_clusters': n_clusters,
            'overall_score': overall_score,
            'silhouette_score': silhouette,
            'n_topics': len(results['topics']),
            'success': True,
            'error': None
        }

        # 打印结果
        print(f"✓ 分析完成")
        print(f"  总耗时: {metrics['total_time']} 秒")
        print(f"  内存使用: {metrics['memory_used_mb']} MB")
        print(f"  吞吐量: {metrics['throughput']} 条/秒")
        print(f"  聚类数: {metrics['n_clusters']}")
        print(f"  主题数: {metrics['n_topics']}")
        print(f"  质量分数: {metrics['overall_score']}/100")
        print(f"  轮廓系数: {metrics['silhouette_score']:.4f}")

        return metrics

    except Exception as e:
        total_time = time.time() - start_time
        print(f"✗ 分析失败: {e}")

        return {
            'dataset_name': dataset_name,
            'data_size': len(data),
            'total_time': round(total_time, 2),
            'success': False,
            'error': str(e)
        }


def run_performance_tests(test_configs: List[tuple], output_dir: str = "performance_test_results"):
    """
    运行性能测试套件

    Args:
        test_configs: [(数据文件路径, 数据集名称), ...]
        output_dir: 结果输出目录
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_metrics = []

    for data_file, dataset_name in test_configs:
        # 加载数据
        print(f"\n加载数据: {data_file}")
        data = load_data(data_file)

        # 运行分析
        result_dir = output_path / dataset_name
        metrics = run_analysis(data, dataset_name, str(result_dir))
        all_metrics.append(metrics)

        # 短暂休息，让系统稳定
        time.sleep(2)

    # 保存所有结果
    results_file = output_path / "performance_metrics.json"
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print("性能测试完成")
    print(f"结果已保存到: {results_file}")
    print(f"{'='*60}\n")

    # 打印汇总表
    print_summary_table(all_metrics)

    return all_metrics


def print_summary_table(metrics: List[Dict]):
    """打印性能汇总表"""
    print("\n" + "="*80)
    print("性能测试汇总")
    print("="*80)

    # 表头
    header = f"{'数据集':<15} {'数据量':<10} {'耗时(s)':<10} {'内存(MB)':<12} {'吞吐量':<12} {'质量分数':<10}"
    print(header)
    print("-"*80)

    # 数据行
    for m in metrics:
        if m['success']:
            row = (f"{m['dataset_name']:<15} "
                  f"{m['data_size']:<10} "
                  f"{m['total_time']:<10} "
                  f"{m['memory_used_mb']:<12} "
                  f"{m['throughput']:<12} "
                  f"{m['overall_score']:<10}")
            print(row)
        else:
            print(f"{m['dataset_name']:<15} FAILED: {m['error']}")

    print("="*80)

    # 统计信息
    successful = [m for m in metrics if m['success']]
    if successful:
        avg_throughput = sum(m['throughput'] for m in successful) / len(successful)
        avg_quality = sum(m['overall_score'] for m in successful) / len(successful)

        print(f"\n统计信息:")
        print(f"  成功测试: {len(successful)}/{len(metrics)}")
        print(f"  平均吞吐量: {avg_throughput:.2f} 条/秒")
        print(f"  平均质量分数: {avg_quality:.2f}/100")

        # 线性度分析（检查是否随数据量线性增长）
        if len(successful) > 1:
            sorted_metrics = sorted(successful, key=lambda x: x['data_size'])
            time_ratio = sorted_metrics[-1]['total_time'] / sorted_metrics[0]['total_time']
            size_ratio = sorted_metrics[-1]['data_size'] / sorted_metrics[0]['data_size']
            linearity = time_ratio / size_ratio

            print(f"\n可扩展性分析:")
            print(f"  数据量增长倍数: {size_ratio:.2f}x")
            print(f"  时间增长倍数: {time_ratio:.2f}x")
            print(f"  线性度指标: {linearity:.2f} (接近1.0表示良好的线性可扩展性)")

            if linearity < 1.5:
                print(f"  ✓ 优秀的线性可扩展性")
            elif linearity < 2.5:
                print(f"  ○ 良好的可扩展性")
            else:
                print(f"  ✗ 可扩展性需要优化")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analysis模块性能测试")
    parser.add_argument("--small", action="store_true", help="运行小规模测试（100条）")
    parser.add_argument("--medium", action="store_true", help="运行中规模测试（500条）")
    parser.add_argument("--large", action="store_true", help="运行大规模测试（1000条）")
    parser.add_argument("--all", action="store_true", help="运行所有规模测试")
    parser.add_argument("-o", "--output", default="performance_test_results",
                       help="结果输出目录")

    args = parser.parse_args()

    # 确定要运行的测试
    test_configs = []

    if args.all or (not args.small and not args.medium and not args.large):
        # 默认运行所有测试
        test_configs = [
            ("tests/test_data/test_100.jsonl", "small_100"),
            ("tests/test_data/test_500.jsonl", "medium_500"),
            ("tests/test_data/test_1000.jsonl", "large_1000"),
        ]
    else:
        if args.small:
            test_configs.append(("tests/test_data/test_100.jsonl", "small_100"))
        if args.medium:
            test_configs.append(("tests/test_data/test_500.jsonl", "medium_500"))
        if args.large:
            test_configs.append(("tests/test_data/test_1000.jsonl", "large_1000"))

    # 运行测试
    print("\n" + "="*80)
    print("Analysis 模块性能测试")
    print("="*80)
    print(f"测试配置: {len(test_configs)} 个数据集")
    print(f"输出目录: {args.output}")

    run_performance_tests(test_configs, args.output)
