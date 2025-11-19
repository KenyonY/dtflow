#!/usr/bin/env python3
"""
数据格式转换工具

将各种常见格式转换为JSONL格式，用于DataTransformer分析

支持的输入格式：
- CSV
- TSV
- Excel (.xlsx, .xls)
- JSON数组
- 纯文本对话（txt）
"""

import argparse
import json
import csv
import sys
from pathlib import Path
from typing import List, Dict


def detect_input_format(file_path: str) -> str:
    """检测输入文件格式"""
    suffix = Path(file_path).suffix.lower()

    format_map = {
        '.csv': 'csv',
        '.tsv': 'tsv',
        '.txt': 'txt',
        '.json': 'json',
        '.jsonl': 'jsonl',
        '.xlsx': 'excel',
        '.xls': 'excel'
    }

    return format_map.get(suffix, 'unknown')


def convert_csv(input_file: str, output_file: str,
                question_col: str, answer_col: str,
                delimiter: str = ',', encoding: str = 'utf-8'):
    """转换CSV文件"""
    print(f"📄 正在读取CSV文件: {input_file}")

    data = []
    with open(input_file, 'r', encoding=encoding) as f:
        reader = csv.DictReader(f, delimiter=delimiter)

        # 验证列名
        if question_col not in reader.fieldnames:
            raise ValueError(f"找不到问题列: {question_col}\n可用列: {reader.fieldnames}")
        if answer_col not in reader.fieldnames:
            raise ValueError(f"找不到答案列: {answer_col}\n可用列: {reader.fieldnames}")

        for i, row in enumerate(reader, 1):
            question = row.get(question_col, '').strip()
            answer = row.get(answer_col, '').strip()

            if question and answer:
                data.append({
                    "instruction": question,
                    "output": answer
                })

    print(f"✓ 读取了 {len(data)} 条有效数据")
    write_jsonl(data, output_file)


def convert_excel(input_file: str, output_file: str,
                  question_col: str, answer_col: str,
                  sheet_name: str = 0):
    """转换Excel文件"""
    try:
        import pandas as pd
    except ImportError:
        print("❌ 需要安装pandas库")
        print("安装命令: pip install pandas openpyxl")
        sys.exit(1)

    print(f"📊 正在读取Excel文件: {input_file}")

    df = pd.read_excel(input_file, sheet_name=sheet_name)

    # 验证列名
    if question_col not in df.columns:
        raise ValueError(f"找不到问题列: {question_col}\n可用列: {list(df.columns)}")
    if answer_col not in df.columns:
        raise ValueError(f"找不到答案列: {answer_col}\n可用列: {list(df.columns)}")

    data = []
    for _, row in df.iterrows():
        question = str(row[question_col]).strip() if pd.notna(row[question_col]) else ''
        answer = str(row[answer_col]).strip() if pd.notna(row[answer_col]) else ''

        if question and answer:
            data.append({
                "instruction": question,
                "output": answer
            })

    print(f"✓ 读取了 {len(data)} 条有效数据")
    write_jsonl(data, output_file)


def convert_json_array(input_file: str, output_file: str,
                       question_key: str, answer_key: str):
    """转换JSON数组文件"""
    print(f"📦 正在读取JSON文件: {input_file}")

    with open(input_file, 'r', encoding='utf-8') as f:
        items = json.load(f)

    if not isinstance(items, list):
        raise ValueError("JSON文件必须是数组格式: [{...}, {...}, ...]")

    data = []
    for item in items:
        question = item.get(question_key, '').strip()
        answer = item.get(answer_key, '').strip()

        if question and answer:
            data.append({
                "instruction": question,
                "output": answer
            })

    print(f"✓ 读取了 {len(data)} 条有效数据")
    write_jsonl(data, output_file)


def convert_txt_dialog(input_file: str, output_file: str,
                       separator: str = '\n---\n'):
    """转换纯文本对话文件"""
    print(f"📝 正在读取文本文件: {input_file}")

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 分割对话
    dialogs = content.split(separator)
    data = []

    for dialog in dialogs:
        lines = [l.strip() for l in dialog.strip().split('\n') if l.strip()]

        if len(lines) >= 2:
            # 假设第一行是问题，后面的是答案
            question = lines[0]
            answer = '\n'.join(lines[1:])

            if question and answer:
                data.append({
                    "instruction": question,
                    "output": answer
                })

    print(f"✓ 读取了 {len(data)} 条有效数据")
    write_jsonl(data, output_file)


def write_jsonl(data: List[Dict], output_file: str):
    """写入JSONL文件"""
    print(f"\n💾 正在写入JSONL文件: {output_file}")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"✓ 成功写入 {len(data)} 条数据")
    print(f"\n✨ 转换完成！")
    print(f"\n下一步: 运行分析")
    print(f"  python scripts/analyze {output_file}")


def print_help_examples():
    """打印帮助示例"""
    print("""
数据格式转换工具

示例用法:

1. CSV转JSONL:
   python scripts/convert_to_jsonl.py \\
     --input data.csv \\
     --output data.jsonl \\
     --question-col "问题" \\
     --answer-col "答案"

2. Excel转JSONL:
   python scripts/convert_to_jsonl.py \\
     --input data.xlsx \\
     --output data.jsonl \\
     --question-col "Question" \\
     --answer-col "Answer"

3. JSON数组转JSONL:
   python scripts/convert_to_jsonl.py \\
     --input data.json \\
     --output data.jsonl \\
     --question-key "prompt" \\
     --answer-key "completion"

4. 纯文本对话转JSONL:
   python scripts/convert_to_jsonl.py \\
     --input dialog.txt \\
     --output data.jsonl \\
     --format txt

支持的输入格式: CSV, TSV, Excel, JSON, TXT
    """)


def main():
    parser = argparse.ArgumentParser(
        description='将各种格式转换为JSONL',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('-i', '--input', required=True,
                       help='输入文件路径')
    parser.add_argument('-o', '--output', required=True,
                       help='输出JSONL文件路径')
    parser.add_argument('--format', choices=['csv', 'tsv', 'excel', 'json', 'txt', 'auto'],
                       default='auto',
                       help='输入格式（默认自动检测）')
    parser.add_argument('--question-col', '--question-key',
                       help='问题列名/键名（CSV/Excel/JSON）')
    parser.add_argument('--answer-col', '--answer-key',
                       help='答案列名/键名（CSV/Excel/JSON）')
    parser.add_argument('--sheet', default=0,
                       help='Excel工作表名或索引（默认第一个）')
    parser.add_argument('--separator', default='\n---\n',
                       help='文本对话分隔符（仅用于txt格式）')
    parser.add_argument('--encoding', default='utf-8',
                       help='文件编码（默认utf-8）')
    parser.add_argument('--examples', action='store_true',
                       help='显示使用示例')

    args = parser.parse_args()

    if args.examples:
        print_help_examples()
        return

    # 检查输入文件
    if not Path(args.input).exists():
        print(f"❌ 错误：文件不存在: {args.input}")
        sys.exit(1)

    # 检测格式
    if args.format == 'auto':
        args.format = detect_input_format(args.input)
        if args.format == 'unknown':
            print(f"❌ 无法识别文件格式: {args.input}")
            print("💡 请使用 --format 参数指定格式")
            sys.exit(1)
        print(f"🔍 检测到格式: {args.format.upper()}")

    # 转换
    try:
        if args.format in ['csv', 'tsv']:
            if not args.question_col or not args.answer_col:
                print("❌ CSV/TSV格式需要指定 --question-col 和 --answer-col")
                sys.exit(1)

            delimiter = '\t' if args.format == 'tsv' else ','
            convert_csv(args.input, args.output,
                       args.question_col, args.answer_col,
                       delimiter=delimiter, encoding=args.encoding)

        elif args.format == 'excel':
            if not args.question_col or not args.answer_col:
                print("❌ Excel格式需要指定 --question-col 和 --answer-col")
                sys.exit(1)

            convert_excel(args.input, args.output,
                         args.question_col, args.answer_col,
                         sheet_name=args.sheet)

        elif args.format == 'json':
            if not args.question_col or not args.answer_col:
                print("❌ JSON格式需要指定 --question-key 和 --answer-key")
                sys.exit(1)

            convert_json_array(args.input, args.output,
                              args.question_col, args.answer_col)

        elif args.format == 'txt':
            convert_txt_dialog(args.input, args.output,
                              separator=args.separator)

        elif args.format == 'jsonl':
            print("⚠️  输入文件已经是JSONL格式，无需转换")
            print(f"可以直接运行: python scripts/analyze {args.input}")

        else:
            print(f"❌ 不支持的格式: {args.format}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 转换失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
