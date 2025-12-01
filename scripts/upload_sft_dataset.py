#!/usr/bin/env python3
"""
SFT 数据集上传工具

使用方法:
    python upload_sft_dataset.py --file data.jsonl --name "我的数据集"
    python upload_sft_dataset.py --file data.jsonl --name "我的数据集" --validate-only
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple
import requests


class SFTDatasetUploader:
    """SFT 数据集上传器"""

    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.session = requests.Session()

    def validate_message(self, message: Dict[str, Any], line_num: int, msg_idx: int) -> List[str]:
        """验证单条消息格式"""
        errors = []

        # 检查 role 字段
        if 'role' not in message:
            errors.append(f"第 {line_num} 行，消息 {msg_idx}: 缺少 'role' 字段")
        elif message['role'] not in ['system', 'user', 'assistant']:
            errors.append(
                f"第 {line_num} 行，消息 {msg_idx}: 无效的 role '{message['role']}'"
                f"（必须是 'system', 'user', 或 'assistant'）"
            )

        # 检查 content 字段
        if 'content' not in message:
            errors.append(f"第 {line_num} 行，消息 {msg_idx}: 缺少 'content' 字段")
        else:
            content = message['content']
            # content 可以是字符串或数组
            if isinstance(content, str):
                if not content.strip():
                    errors.append(f"第 {line_num} 行，消息 {msg_idx}: 'content' 不能为空")
            elif isinstance(content, list):
                # 验证多模态内容
                for content_idx, item in enumerate(content):
                    if not isinstance(item, dict):
                        errors.append(
                            f"第 {line_num} 行，消息 {msg_idx}，内容项 {content_idx}: "
                            f"必须是对象"
                        )
                        continue

                    item_type = item.get('type')
                    if item_type == 'text':
                        if 'text' not in item or not item['text'].strip():
                            errors.append(
                                f"第 {line_num} 行，消息 {msg_idx}，内容项 {content_idx}: "
                                f"文本内容不能为空"
                            )
                    elif item_type == 'image_url':
                        if 'image_url' not in item or 'url' not in item['image_url']:
                            errors.append(
                                f"第 {line_num} 行，消息 {msg_idx}，内容项 {content_idx}: "
                                f"缺少 'image_url.url' 字段"
                            )
                    else:
                        errors.append(
                            f"第 {line_num} 行，消息 {msg_idx}，内容项 {content_idx}: "
                            f"未知的类型 '{item_type}'（应为 'text' 或 'image_url'）"
                        )
            else:
                errors.append(
                    f"第 {line_num} 行，消息 {msg_idx}: "
                    f"'content' 必须是字符串或数组"
                )

        return errors

    def validate_data(self, filepath: Path) -> Tuple[bool, List[str], int]:
        """
        验证 SFT 数据格式

        Returns:
            (is_valid, errors, line_count)
        """
        errors = []
        line_count = 0

        if not filepath.exists():
            return False, [f"文件不存在: {filepath}"], 0

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line_count = line_num
                    line = line.strip()

                    if not line:  # 跳过空行
                        continue

                    try:
                        data = json.loads(line)

                        # 检查必需字段
                        if 'messages' not in data:
                            errors.append(f"第 {line_num} 行: 缺少 'messages' 字段")
                            continue

                        messages = data['messages']
                        if not isinstance(messages, list):
                            errors.append(f"第 {line_num} 行: 'messages' 必须是数组")
                            continue

                        if not messages:
                            errors.append(f"第 {line_num} 行: 'messages' 不能为空")
                            continue

                        # 检查每条消息
                        for msg_idx, msg in enumerate(messages):
                            if not isinstance(msg, dict):
                                errors.append(
                                    f"第 {line_num} 行，消息 {msg_idx}: 必须是对象"
                                )
                                continue

                            msg_errors = self.validate_message(msg, line_num, msg_idx)
                            errors.extend(msg_errors)

                    except json.JSONDecodeError as e:
                        errors.append(f"第 {line_num} 行: JSON 格式错误 - {str(e)}")

        except Exception as e:
            return False, [f"读取文件时出错: {str(e)}"], 0

        return len(errors) == 0, errors, line_count

    def create_dataset(
        self,
        name: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """创建数据集"""
        try:
            response = self.session.post(
                f"{self.api_base}/api/datasets",
                json={
                    "name": name,
                    "type": "sft",
                    "description": description
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"创建数据集失败: {str(e)}")

    def upload_file(
        self,
        dataset_id: str,
        filepath: Path,
        source_format: str = None
    ) -> Dict[str, Any]:
        """上传文件到数据集"""
        try:
            with open(filepath, 'rb') as f:
                files = {'file': (filepath.name, f)}
                url = f"{self.api_base}/api/datasets/{dataset_id}/upload"
                if source_format:
                    url += f"?source_format={source_format}"

                response = self.session.post(
                    url,
                    files=files,
                    timeout=120
                )
                response.raise_for_status()
                return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"上传文件失败: {str(e)}")

    def get_dataset_stats(self, dataset_id: str) -> Dict[str, Any]:
        """获取数据集统计信息"""
        try:
            response = self.session.get(
                f"{self.api_base}/api/datasets/{dataset_id}/stats",
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"获取统计信息失败: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description='SFT 数据集上传工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 验证数据格式
  python upload_sft_dataset.py --file data.jsonl --validate-only

  # 创建数据集并上传
  python upload_sft_dataset.py --file data.jsonl --name "医疗问答数据集"

  # 指定 API 地址
  python upload_sft_dataset.py --file data.jsonl --name "数据集" --api http://example.com:8000
        """
    )

    parser.add_argument(
        '--file', '-f',
        type=str,
        required=True,
        help='数据文件路径（JSONL 格式）'
    )
    parser.add_argument(
        '--name', '-n',
        type=str,
        help='数据集名称'
    )
    parser.add_argument(
        '--description', '-d',
        type=str,
        default='',
        help='数据集描述（可选）'
    )
    parser.add_argument(
        '--api',
        type=str,
        default='http://localhost:8000',
        help='API 服务器地址（默认: http://localhost:8000）'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='仅验证数据格式，不上传'
    )
    parser.add_argument(
        '--source-format',
        type=str,
        choices=['sft', 'rlhf', 'pretrain'],
        help='源数据格式（如果需要转换）'
    )

    args = parser.parse_args()

    # 验证文件路径
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"❌ 错误: 文件不存在 '{filepath}'")
        sys.exit(1)

    print(f"📁 正在处理文件: {filepath}")
    print(f"{'=' * 60}")

    # 创建上传器
    uploader = SFTDatasetUploader(api_base=args.api)

    # 验证数据
    print("🔍 验证数据格式...")
    is_valid, errors, line_count = uploader.validate_data(filepath)

    if not is_valid:
        print(f"\n❌ 发现 {len(errors)} 个错误:\n")
        for error in errors[:20]:  # 只显示前20个错误
            print(f"  • {error}")
        if len(errors) > 20:
            print(f"\n  ... 还有 {len(errors) - 20} 个错误")
        sys.exit(1)

    print(f"✅ 数据格式验证通过！共 {line_count} 条数据")

    # 如果只是验证，则退出
    if args.validate_only:
        print("\n✅ 验证完成（未上传）")
        sys.exit(0)

    # 检查是否提供了数据集名称
    if not args.name:
        print("\n❌ 错误: 请提供数据集名称（--name）")
        sys.exit(1)

    # 创建数据集
    print(f"\n📦 创建数据集: {args.name}")
    try:
        dataset = uploader.create_dataset(
            name=args.name,
            description=args.description
        )
        dataset_id = dataset['id']
        print(f"✅ 数据集创建成功！ID: {dataset_id}")
    except Exception as e:
        print(f"❌ {str(e)}")
        sys.exit(1)

    # 上传文件
    print(f"\n⬆️  上传数据文件...")
    try:
        result = uploader.upload_file(
            dataset_id=dataset_id,
            filepath=filepath,
            source_format=args.source_format
        )
        print(f"✅ {result.get('message', '上传成功')}")
    except Exception as e:
        print(f"❌ {str(e)}")
        sys.exit(1)

    # 获取统计信息
    print(f"\n📊 获取数据集统计...")
    try:
        stats = uploader.get_dataset_stats(dataset_id)
        print(f"✅ 统计信息:")
        print(f"   • 总数: {stats.get('total', 0)}")
        print(f"   • 已标注: {stats.get('annotated', 0)}")
        print(f"   • 待标注: {stats.get('pending', 0)}")
    except Exception as e:
        print(f"⚠️  获取统计信息失败: {str(e)}")

    print(f"\n{'=' * 60}")
    print("🎉 数据集上传完成！")
    print(f"\n访问 Web 界面开始标注:")
    print(f"  http://localhost:5173/datasets")
    print(f"\n或直接开始标注:")
    print(f"  http://localhost:5173/annotate/sft/{dataset_id}")


if __name__ == '__main__':
    main()
