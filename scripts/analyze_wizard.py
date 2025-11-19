#!/usr/bin/env python3
"""
DataTransformer 交互式分析向导

完全交互式的数据分析配置和执行工具
"""

import json
import sys
from pathlib import Path
from typing import Optional
import warnings
warnings.filterwarnings('ignore')


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """打印标题"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.END}\n")


def print_step(step: int, total: int, text: str):
    """打印步骤"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}📍 步骤 {step}/{total}: {text}{Colors.END}")
    print(f"{Colors.CYAN}{'─'*70}{Colors.END}")


def print_success(text: str):
    """打印成功信息"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    """打印错误信息"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_warning(text: str):
    """打印警告信息"""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")


def print_info(text: str):
    """打印信息"""
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")


def ask_question(question: str, default: Optional[str] = None) -> str:
    """询问问题"""
    if default:
        prompt = f"{Colors.BOLD}{question}{Colors.END} [{default}]: "
    else:
        prompt = f"{Colors.BOLD}{question}{Colors.END}: "

    response = input(prompt).strip()
    return response if response else (default or "")


def ask_yes_no(question: str, default: bool = True) -> bool:
    """询问是/否问题"""
    default_str = "Y/n" if default else "y/N"
    response = ask_question(f"{question} ({default_str})", "")

    if not response:
        return default

    return response.lower() in ['y', 'yes', '是']


def select_option(question: str, options: list, default: int = 0) -> int:
    """选择选项"""
    print(f"\n{Colors.BOLD}{question}{Colors.END}")
    for i, option in enumerate(options, 1):
        prefix = "→" if i == default + 1 else " "
        print(f"  {prefix} {i}. {option}")

    while True:
        choice = ask_question("请选择", str(default + 1))
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
            else:
                print_error(f"请输入 1-{len(options)} 之间的数字")
        except ValueError:
            print_error("请输入有效的数字")


def detect_file_format(file_path: str) -> dict:
    """检测文件格式"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if not first_line:
                return {'valid': False, 'error': '文件为空'}

            data = json.loads(first_line)

            # 检测格式
            if 'messages' in data:
                format_type = 'sft'
                format_name = 'SFT消息格式'
            elif 'instruction' in data and 'output' in data:
                format_type = 'instruction-output'
                format_name = 'Instruction-Output格式'
            elif 'prompt' in data and 'completion' in data:
                format_type = 'prompt-completion'
                format_name = 'Prompt-Completion格式'
            elif 'question' in data and 'answer' in data:
                format_type = 'qa'
                format_name = 'Question-Answer格式'
            else:
                format_type = 'custom'
                format_name = '自定义格式'

            # 计算行数
            with open(file_path, 'r', encoding='utf-8') as f:
                line_count = sum(1 for line in f if line.strip())

            return {
                'valid': True,
                'format_type': format_type,
                'format_name': format_name,
                'sample': data,
                'line_count': line_count
            }

    except json.JSONDecodeError as e:
        return {'valid': False, 'error': f'JSON解析错误: {e}'}
    except Exception as e:
        return {'valid': False, 'error': f'读取文件失败: {e}'}


def show_format_examples():
    """显示格式示例"""
    print("\n支持的数据格式示例：\n")

    examples = [
        ("SFT消息格式（推荐）", {
            "messages": [
                {"role": "user", "content": "什么是机器学习？"},
                {"role": "assistant", "content": "机器学习是..."}
            ]
        }),
        ("Instruction-Output格式", {
            "instruction": "什么是机器学习？",
            "output": "机器学习是..."
        }),
        ("Prompt-Completion格式", {
            "prompt": "什么是机器学习？",
            "completion": "机器学习是..."
        }),
        ("Question-Answer格式", {
            "question": "什么是机器学习？",
            "answer": "机器学习是..."
        }),
    ]

    for name, example in examples:
        print(f"{Colors.BOLD}{name}:{Colors.END}")
        print(json.dumps(example, ensure_ascii=False, indent=2))
        print()


def run_wizard():
    """运行向导"""
    # 欢迎界面
    print_header("DataTransformer 交互式分析向导")

    print(f"""
{Colors.CYAN}欢迎使用 DataTransformer！{Colors.END}

这个向导将帮助你：
  1. 检测和验证你的数据格式
  2. 配置分析参数
  3. 运行完整的数据分析
  4. 生成可视化报告

{Colors.BOLD}整个过程只需要几分钟！{Colors.END}
""")

    if not ask_yes_no("准备好开始了吗？"):
        print("\n👋 下次再见！")
        return

    # 步骤1: 选择数据文件
    print_step(1, 5, "选择数据文件")

    while True:
        file_path = ask_question("请输入数据文件路径", "data/sft_dataset_example.jsonl")

        if not Path(file_path).exists():
            print_error(f"文件不存在: {file_path}")
            if not ask_yes_no("要重新输入吗？"):
                print("\n❌ 已取消")
                return
            continue

        # 检测格式
        print(f"\n🔍 正在检测文件格式...")
        file_info = detect_file_format(file_path)

        if not file_info['valid']:
            print_error(file_info['error'])
            print_info("数据文件必须是JSONL格式（每行一个JSON对象）")

            if ask_yes_no("要查看格式示例吗？"):
                show_format_examples()

            if not ask_yes_no("要重新输入文件路径吗？"):
                print("\n❌ 已取消")
                return
            continue

        # 显示检测结果
        print_success(f"文件格式: {file_info['format_name']}")
        print_success(f"数据量: {file_info['line_count']} 条")

        print(f"\n{Colors.BOLD}数据示例:{Colors.END}")
        print(json.dumps(file_info['sample'], ensure_ascii=False, indent=2))

        if ask_yes_no("\n这个数据文件正确吗？"):
            break

    # 步骤2: 配置输出目录
    print_step(2, 5, "配置输出目录")

    output_dir = ask_question("输出目录", "analysis_results")
    print_success(f"结果将保存到: {output_dir}/")

    # 步骤3: 配置分析参数
    print_step(3, 5, "配置分析参数")

    print("\n💡 聚类数量决定了将数据分成几个主题组")
    print("   建议值: 数据量的1/10到1/20")

    default_clusters = max(5, min(20, file_info['line_count'] // 10))
    clusters_str = ask_question(f"聚类数量", str(default_clusters))

    try:
        n_clusters = int(clusters_str)
    except ValueError:
        print_warning(f"无效的数字，使用默认值: {default_clusters}")
        n_clusters = default_clusters

    generate_report = ask_yes_no("\n要生成HTML可视化报告吗？", True)

    # 步骤4: 确认配置
    print_step(4, 5, "确认配置")

    print(f"""
{Colors.BOLD}分析配置摘要:{Colors.END}

  数据文件: {file_path}
  数据格式: {file_info['format_name']}
  数据量: {file_info['line_count']} 条
  输出目录: {output_dir}/
  聚类数量: {n_clusters}
  生成报告: {'是' if generate_report else '否'}
""")

    if not ask_yes_no("确认开始分析吗？"):
        print("\n❌ 已取消")
        return

    # 步骤5: 运行分析
    print_step(5, 5, "运行分析")

    try:
        # 导入库
        print("\n📦 正在加载分析模块...")
        from data_transformer.analysis.analyzer import SFTDataAnalyzer

        # 加载数据
        print("📥 正在加载数据...")
        data = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)

                # 转换为统一格式
                if file_info['format_type'] == 'sft':
                    inst = out = None
                    for msg in item.get('messages', []):
                        if msg.get('role') == 'user':
                            inst = msg.get('content')
                        elif msg.get('role') == 'assistant':
                            out = msg.get('content')
                    if inst and out:
                        data.append({'instruction': inst, 'output': out})

                elif file_info['format_type'] in ['instruction-output', 'prompt-completion', 'qa']:
                    key_map = {
                        'instruction-output': ('instruction', 'output'),
                        'prompt-completion': ('prompt', 'completion'),
                        'qa': ('question', 'answer')
                    }
                    inst_key, out_key = key_map[file_info['format_type']]
                    data.append({
                        'instruction': item.get(inst_key, ''),
                        'output': item.get(out_key, '')
                    })

        print_success(f"已加载 {len(data)} 条数据")

        # 创建分析器
        print("\n🔧 正在初始化分析器...")
        analyzer = SFTDataAnalyzer(
            n_clusters=n_clusters,
            output_dir=output_dir
        )
        print_success("分析器初始化完成")

        # 运行分析
        print("\n📊 正在运行分析（这可能需要几秒到几分钟）...")
        print("    请耐心等待...\n")

        results = analyzer.analyze(
            data,
            generate_report=generate_report,
            cache_embeddings=False
        )

        # 显示结果
        print_header("分析完成！")

        quality = results['quality']
        clustering = results.get('clustering', {})

        if isinstance(clustering, dict):
            n_clusters_result = clustering.get('n_clusters', n_clusters)
        else:
            n_clusters_result = clustering.n_clusters

        print(f"""
{Colors.GREEN}{Colors.BOLD}✨ 分析成功完成！{Colors.END}

{Colors.BOLD}📈 关键指标:{Colors.END}

  数据量: {len(data)} 条
  聚类数: {n_clusters_result}
  质量分数: {quality.get('overall_score', 0):.1f}/100
  词汇多样性: {quality.get('diversity_scores', {}).get('vocabulary_diversity', 0):.3f}
  唯一样本率: {quality.get('duplication_stats', {}).get('unique_sample_ratio', 0):.1%}

{Colors.BOLD}📁 输出文件:{Colors.END}

  • {output_dir}/analysis_results.json
    完整的分析数据（JSON格式）
""")

        if generate_report:
            print(f"""  • {output_dir}/analysis_report.html
    可视化分析报告（用浏览器打开）
""")

        print(f"""  • {output_dir}/*.png
    可视化图表

{Colors.BOLD}💡 下一步建议:{Colors.END}
""")

        if generate_report:
            print(f"""  1. 用浏览器打开: {output_dir}/analysis_report.html
     查看完整的可视化报告
""")

        print(f"""  2. 查看质量警告和改进建议
     根据分析结果优化你的数据集

  3. 如果质量分数较低，考虑:
     - 去除重复数据
     - 增加数据多样性
     - 提高文本复杂度

{Colors.GREEN}{Colors.BOLD}✨ 感谢使用 DataTransformer！{Colors.END}
""")

    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}⚠️  分析已取消{Colors.END}")
        return
    except Exception as e:
        print_error(f"分析失败: {e}")
        print("\n💡 可能的原因:")
        print("  1. 数据格式不正确")
        print("  2. 内存不足")
        print("  3. 缺少必要的依赖包")
        print("\n建议查看详细错误信息或寻求帮助")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    try:
        run_wizard()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}👋 再见！{Colors.END}")
        sys.exit(0)
