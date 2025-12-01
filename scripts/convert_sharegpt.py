#!/usr/bin/env python3
"""
ShareGPT 格式转换工具

将 ShareGPT 格式数据转换为标准 SFT messages 格式
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List


def convert_sharegpt_to_sft(item: Dict) -> Dict:
    """
    转换单条 ShareGPT 数据到 SFT 格式

    Args:
        item: ShareGPT 格式的数据项

    Returns:
        SFT messages 格式的数据项
    """
    role_map = {
        'human': 'user',
        'gpt': 'assistant',
        'system': 'system'
    }

    messages = []

    # 添加 system 消息（如果存在）
    if 'system' in item and item['system']:
        messages.append({
            'role': 'system',
            'content': item['system']
        })

    # 转换对话
    if 'conversations' in item:
        for conv in item['conversations']:
            role = role_map.get(conv['from'], conv['from'])
            messages.append({
                'role': role,
                'content': conv['value']
            })

    return {'messages': messages}


def convert_file(
    input_file: str,
    output_file: str,
    show_progress: bool = True,
    progress_interval: int = 10000
) -> Dict[str, int]:
    """
    转换整个文件

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        show_progress: 是否显示进度
        progress_interval: 进度显示间隔

    Returns:
        统计信息字典
    """
    stats = {
        'total': 0,
        'success': 0,
        'error': 0
    }

    print(f"开始转换: {input_file}")
    print(f"输出文件: {output_file}")
    print()

    # 创建输出目录
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with open(input_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'w', encoding='utf-8') as f_out:

        for line_num, line in enumerate(f_in, 1):
            stats['total'] += 1

            try:
                item = json.loads(line.strip())
                sft_item = convert_sharegpt_to_sft(item)
                f_out.write(json.dumps(sft_item, ensure_ascii=False) + '\n')
                stats['success'] += 1

                # 显示进度
                if show_progress and stats['success'] % progress_interval == 0:
                    print(f"已转换: {stats['success']:,} 条 "
                          f"(错误: {stats['error']})")

            except Exception as e:
                stats['error'] += 1
                if stats['error'] <= 5:  # 只打印前5个错误
                    print(f"第 {line_num} 行转换失败: {e}", file=sys.stderr)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='ShareGPT 格式转换工具',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('input', help='输入文件路径（ShareGPT格式）')
    parser.add_argument('output', help='输出文件路径（SFT格式）')
    parser.add_argument('--no-progress', action='store_true',
                       help='不显示进度信息')
    parser.add_argument('--interval', type=int, default=10000,
                       help='进度显示间隔（默认: 10000）')

    args = parser.parse_args()

    # 检查输入文件
    if not Path(args.input).exists():
        print(f"错误：文件不存在: {args.input}")
        sys.exit(1)

    # 转换
    try:
        stats = convert_file(
            args.input,
            args.output,
            show_progress=not args.no_progress,
            progress_interval=args.interval
        )

        print()
        print("="*60)
        print("转换完成！")
        print("="*60)
        print(f"总计:   {stats['total']:,} 条")
        print(f"成功:   {stats['success']:,} 条")
        print(f"失败:   {stats['error']:,} 条")
        print(f"成功率: {stats['success']/stats['total']*100:.2f}%")
        print()
        print(f"输出文件: {args.output}")

    except Exception as e:
        print(f"\n转换失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
