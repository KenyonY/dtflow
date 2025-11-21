#!/usr/bin/env python3
"""
主题样本查看工具

根据分析结果查看特定主题的样本
"""

import json
import argparse
import sys
from pathlib import Path
from typing import List, Dict


def load_analysis_results(analysis_dir: str) -> Dict:
    """加载分析结果"""
    results_file = Path(analysis_dir) / "analysis_results.json"

    if not results_file.exists():
        print(f"错误：找不到分析结果文件: {results_file}")
        sys.exit(1)

    with open(results_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_original_data(data_file: str) -> List[Dict]:
    """加载原始数据"""
    data = []

    if not Path(data_file).exists():
        print(f"错误：找不到数据文件: {data_file}")
        sys.exit(1)

    with open(data_file, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line))

    return data


def list_topics(results: Dict):
    """列出所有主题"""
    if 'topics' not in results:
        print("错误：分析结果中没有主题信息")
        return

    topics = results['topics']

    print("\n" + "="*80)
    print("主题列表")
    print("="*80)
    print(f"{'ID':<6} {'样本数':<10} {'LLM主题名称':<30} {'关键词':<30}")
    print("-"*80)

    for topic_id, topic_info in sorted(topics.items(), key=lambda x: int(x[0])):
        keywords = [kw[0] if isinstance(kw, list) else kw for kw in topic_info['keywords'][:5]]
        keywords_str = ', '.join(keywords)
        llm_name = topic_info.get('llm_topic_name', '')
        if len(llm_name) > 28:
            llm_name = llm_name[:28] + ".."
        print(f"{topic_id:<6} {topic_info['size']:<10} {llm_name:<30} {keywords_str:<30}")

    print("="*80)
    print(f"总计: {len(topics)} 个主题")


def view_topic_samples(
    topic_id: int,
    results: Dict,
    data: List[Dict],
    limit: int = 10,
    export_file: str = None
):
    """查看特定主题的样本"""
    if 'topics' not in results:
        print("错误：分析结果中没有主题信息")
        return

    topics = results['topics']
    topic_id_str = str(topic_id)

    if topic_id_str not in topics:
        print(f"错误：主题 {topic_id} 不存在")
        print(f"可用主题ID: {', '.join(sorted(topics.keys()))}")
        return

    topic_info = topics[topic_id_str]

    # 显示主题信息
    print("\n" + "="*80)
    print(f"主题 {topic_id} 详情")
    print("="*80)

    # 显示LLM生成的主题名称和描述(如果有)
    llm_name = topic_info.get('llm_topic_name', '')
    llm_desc = topic_info.get('llm_topic_description', '')
    if llm_name:
        print(f"主题名称 (LLM): {llm_name}")
    if llm_desc:
        print(f"主题描述 (LLM): {llm_desc}")

    keywords = [kw[0] if isinstance(kw, list) else kw for kw in topic_info['keywords'][:8]]
    print(f"关键词: {', '.join(keywords)}")
    print(f"样本数: {topic_info['size']}")
    print(f"主题摘要: {topic_info.get('topic_summary', 'N/A')}")

    # 获取样本索引
    sample_indices = topic_info.get('sample_indices', [])

    if not sample_indices:
        print("\n警告：该主题没有保存样本索引")
        return

    # 限制显示数量
    display_indices = sample_indices[:limit]

    print("\n" + "-"*80)
    print(f"样本列表 (显示前 {len(display_indices)}/{len(sample_indices)} 条)")
    print("-"*80)

    samples_to_export = []

    for i, idx in enumerate(display_indices, 1):
        if idx >= len(data):
            print(f"\n警告：索引 {idx} 超出数据范围")
            continue

        sample = data[idx]

        print(f"\n【样本 {i}】 (索引: {idx})")

        # 显示样本内容
        if 'messages' in sample:
            # SFT 格式
            for msg in sample['messages']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                # 限制显示长度
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"  [{role}]: {content}")
        elif 'instruction' in sample:
            # Instruction-Output 格式
            inst = sample.get('instruction', '')
            out = sample.get('output', '')
            if len(inst) > 200:
                inst = inst[:200] + "..."
            if len(out) > 200:
                out = out[:200] + "..."
            print(f"  [instruction]: {inst}")
            print(f"  [output]: {out}")
        else:
            # 其他格式
            print(f"  {sample}")

        samples_to_export.append(sample)

    # 导出功能
    if export_file:
        export_path = Path(export_file)
        export_path.parent.mkdir(parents=True, exist_ok=True)

        # 导出所有样本（不限制数量）
        all_samples = [data[idx] for idx in sample_indices if idx < len(data)]

        with open(export_path, 'w', encoding='utf-8') as f:
            for sample in all_samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')

        print(f"\n✓ 已导出 {len(all_samples)} 条样本到: {export_file}")


def main():
    parser = argparse.ArgumentParser(
        description='主题样本查看工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出所有主题
  python scripts/view_topic_samples.py --list

  # 查看主题4的样本
  python scripts/view_topic_samples.py --topic 4 --data data/sample_2k.jsonl

  # 查看主题4的前20条样本
  python scripts/view_topic_samples.py --topic 4 --data data/sample_2k.jsonl --limit 20

  # 导出主题4的所有样本
  python scripts/view_topic_samples.py --topic 4 --data data/sample_2k.jsonl --export topic_4_samples.jsonl
        """
    )

    parser.add_argument('--analysis-dir', default='analysis_results',
                       help='分析结果目录 (默认: analysis_results)')
    parser.add_argument('--list', action='store_true',
                       help='列出所有主题')
    parser.add_argument('--topic', type=int,
                       help='要查看的主题ID')
    parser.add_argument('--data',
                       help='原始数据文件路径')
    parser.add_argument('--limit', type=int, default=10,
                       help='显示样本数量 (默认: 10)')
    parser.add_argument('--export',
                       help='导出样本到文件 (JSONL格式)')

    args = parser.parse_args()

    # 加载分析结果
    results = load_analysis_results(args.analysis_dir)

    # 列出主题
    if args.list:
        list_topics(results)
        return

    # 查看特定主题
    if args.topic is not None:
        if not args.data:
            print("错误：需要提供原始数据文件路径 (--data)")
            sys.exit(1)

        data = load_original_data(args.data)
        view_topic_samples(args.topic, results, data, args.limit, args.export)
        return

    # 默认显示帮助
    parser.print_help()


if __name__ == '__main__':
    main()
