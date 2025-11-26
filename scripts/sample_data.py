"""
数据采样脚本 - 从大数据集中随机采样指定数量的数据
"""
import json
import random
from pathlib import Path


def sample_jsonl(input_file: str, output_file: str, sample_size: int, random_seed: int = 42):
    """
    从 JSONL 文件中随机采样数据

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        sample_size: 采样数量
        random_seed: 随机种子，保证可重复性
    """
    random.seed(random_seed)

    # 读取所有数据
    print(f"正在读取文件: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total_count = len(lines)
    print(f"文件总行数: {total_count:,}")

    # 采样
    if sample_size >= total_count:
        print(f"警告: 采样数量 ({sample_size}) 大于等于总数据量 ({total_count})，将使用全部数据")
        sampled_lines = lines
    else:
        print(f"正在随机采样 {sample_size:,} 条数据...")
        sampled_lines = random.sample(lines, sample_size)

    # 保存采样数据
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"正在保存到: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(sampled_lines)

    print(f"采样完成! 已保存 {len(sampled_lines):,} 条数据")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从 JSONL 文件中随机采样数据")
    parser.add_argument("--input", "-i", required=True, help="输入文件路径")
    parser.add_argument("--output", "-o", required=True, help="输出文件路径")
    parser.add_argument("--size", "-s", type=int, required=True, help="采样数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (默认: 42)")

    args = parser.parse_args()

    sample_jsonl(args.input, args.output, args.size, args.seed)
