"""
CLI 数据清洗和去重相关命令
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import DataTransformer
from ..storage.io import save_data
from ..streaming import load_stream
from ..utils.field_path import get_field_with_spec
from .common import (
    _check_file_format,
    _get_value_len,
    _is_empty_value,
    _is_streaming_supported,
    _parse_field_list,
)


def dedupe(
    filename: str,
    key: Optional[str] = None,
    similar: Optional[float] = None,
    output: Optional[str] = None,
) -> None:
    """
    数据去重。

    支持两种模式：
    1. 精确去重（默认）：完全相同的数据才去重
    2. 相似度去重：使用 MinHash+LSH 算法，相似度超过阈值则去重

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        key: 去重依据字段，支持嵌套路径语法：
            - meta.source        嵌套字段
            - messages[0].role   数组索引
            - messages[-1].content  负索引
            - messages.#         数组长度
            - messages[*].role:join  展开所有元素
            多个字段用逗号分隔。不指定则全量去重
        similar: 相似度阈值（0-1），指定后启用相似度去重模式，需要指定 --key
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt dedupe data.jsonl                       # 全量精确去重
        dt dedupe data.jsonl --key=text            # 按 text 字段精确去重
        dt dedupe data.jsonl --key=user,timestamp  # 按多字段组合精确去重
        dt dedupe data.jsonl --key=meta.id         # 按嵌套字段去重
        dt dedupe data.jsonl --key=messages[0].content   # 按第一条消息内容去重
        dt dedupe data.jsonl --key=text --similar=0.8    # 相似度去重
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 相似度去重模式必须指定 key
    if similar is not None and not key:
        print("错误: 相似度去重需要指定 --key 参数")
        return

    if similar is not None and (similar <= 0 or similar > 1):
        print("错误: --similar 参数必须在 0-1 之间")
        return

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    original_count = len(dt)
    print(f"   共 {original_count} 条数据")

    # 执行去重
    if similar is not None:
        # 相似度去重模式
        print(f"🔑 相似度去重: 字段={key}, 阈值={similar}")
        print("🔄 执行去重（MinHash+LSH）...")
        try:
            result = dt.dedupe_similar(key, threshold=similar)
        except ImportError as e:
            print(f"错误: {e}")
            return
    else:
        # 精确去重模式
        dedupe_key: Any = None
        if key:
            keys = [k.strip() for k in key.split(",")]
            if len(keys) == 1:
                dedupe_key = keys[0]
                print(f"🔑 按字段精确去重: {dedupe_key}")
            else:
                dedupe_key = keys
                print(f"🔑 按多字段组合精确去重: {', '.join(dedupe_key)}")
        else:
            print("🔑 全量精确去重")

        print("🔄 执行去重...")
        result = dt.dedupe(dedupe_key)

    dedupe_count = len(result)
    removed_count = original_count - dedupe_count

    # 保存结果
    output_path = output or str(filepath)
    print(f"💾 保存结果: {output_path}")
    try:
        result.save(output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    print(f"\n✅ 完成! 去除 {removed_count} 条重复数据，剩余 {dedupe_count} 条")


def clean(
    filename: str,
    drop_empty: Optional[str] = None,
    min_len: Optional[str] = None,
    max_len: Optional[str] = None,
    keep: Optional[str] = None,
    drop: Optional[str] = None,
    rename: Optional[str] = None,
    promote: Optional[str] = None,
    add_field: Optional[str] = None,
    fill: Optional[str] = None,
    reorder: Optional[str] = None,
    strip: bool = False,
    min_tokens: Optional[str] = None,
    max_tokens: Optional[str] = None,
    model: str = "cl100k_base",
    output: Optional[str] = None,
) -> None:
    """
    数据清洗（默认流式处理）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        drop_empty: 删除空值记录，支持嵌套路径语法
            - 不带值：删除任意字段为空的记录
            - 指定字段：删除指定字段为空的记录（逗号分隔）
        min_len: 最小长度过滤，格式 "字段:长度"，字段支持嵌套路径
        max_len: 最大长度过滤，格式 "字段:长度"，字段支持嵌套路径
        keep: 只保留指定字段（逗号分隔，仅支持顶层字段）
        drop: 删除指定字段（逗号分隔，仅支持顶层字段）
        rename: 重命名字段，格式 "old:new" 或 "old1:new1,old2:new2"
        promote: 提升嵌套字段到顶层，格式 "path" 或 "path:name"（逗号分隔多个）
        add_field: 添加常量字段，格式 "key:value"（逗号分隔多个）
        fill: 填充空值，格式 "field:default_value"（逗号分隔多个）
        reorder: 控制字段顺序（逗号分隔），未列出的字段追加在后面
        strip: 去除所有字符串字段的首尾空白
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt clean data.jsonl --drop-empty                    # 删除任意空值记录
        dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
        dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
        dt clean data.jsonl --keep=question,answer          # 只保留这些字段
        dt clean data.jsonl --drop=metadata,timestamp       # 删除这些字段
        dt clean data.jsonl --rename=question:instruction   # 重命名字段
        dt clean data.jsonl --promote=meta.label            # 提升嵌套字段到顶层
        dt clean data.jsonl --promote=meta.label:tag        # 提升并自定义名称
        dt clean data.jsonl --add-field=source:web          # 添加常量字段
        dt clean data.jsonl --fill=label:unknown            # 填充空值
        dt clean data.jsonl --reorder=id,text,label         # 控制字段顺序
        dt clean data.jsonl --strip                         # 去除字符串首尾空白
        dt clean data.jsonl --min-tokens=content:10            # content 字段最少 10 tokens
        dt clean data.jsonl --max-tokens=content:1000          # content 字段最多 1000 tokens
        dt clean data.jsonl --min-tokens=text:50 --model=gpt-4 # 使用 gpt-4 分词器
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 解析参数
    min_len_field, min_len_value = _parse_len_param(min_len) if min_len else (None, None)
    max_len_field, max_len_value = _parse_len_param(max_len) if max_len else (None, None)
    min_tokens_field, min_tokens_value = (
        _parse_len_param(min_tokens) if min_tokens else (None, None)
    )
    max_tokens_field, max_tokens_value = (
        _parse_len_param(max_tokens) if max_tokens else (None, None)
    )
    token_model = model
    keep_fields = _parse_field_list(keep) if keep else None
    drop_fields_set = set(_parse_field_list(drop)) if drop else None
    rename_map = _parse_rename_param(rename) if rename else None
    promote_list = _parse_promote_param(promote) if promote else None
    add_field_map = _parse_kv_param(add_field, "add-field") if add_field else None
    fill_map = _parse_kv_param(fill, "fill") if fill else None
    reorder_fields = _parse_field_list(reorder) if reorder else None
    keep_set = set(keep_fields) if keep_fields else None

    # 构建清洗配置
    empty_fields = None
    if drop_empty is not None:
        if drop_empty == "" or drop_empty is True:
            print("🔄 删除任意字段为空的记录...")
            empty_fields = []
        else:
            empty_fields = _parse_field_list(drop_empty)
            print(f"🔄 删除字段为空的记录: {', '.join(empty_fields)}")

    if strip:
        print("🔄 去除字符串首尾空白...")
    if min_len_field:
        print(f"🔄 过滤 {min_len_field} 长度 < {min_len_value} 的记录...")
    if max_len_field:
        print(f"🔄 过滤 {max_len_field} 长度 > {max_len_value} 的记录...")
    if keep_fields:
        print(f"🔄 只保留字段: {', '.join(keep_fields)}")
    if drop_fields_set:
        print(f"🔄 删除字段: {', '.join(drop_fields_set)}")
    if rename_map:
        rename_desc = ", ".join(f"{k} → {v}" for k, v in rename_map.items())
        print(f"🔄 重命名字段: {rename_desc}")
    if promote_list:
        promote_desc = ", ".join(f"{src} → {dst}" for src, dst in promote_list)
        print(f"🔄 提升字段: {promote_desc}")
    if add_field_map:
        add_desc = ", ".join(f"{k}={v}" for k, v in add_field_map.items())
        print(f"🔄 添加字段: {add_desc}")
    if fill_map:
        fill_desc = ", ".join(f"{k}={v}" for k, v in fill_map.items())
        print(f"🔄 填充空值: {fill_desc}")
    if reorder_fields:
        print(f"🔄 字段排序: {', '.join(reorder_fields)}")
    if min_tokens_field:
        print(
            f"🔄 过滤 {min_tokens_field} tokens < {min_tokens_value} 的记录 (model={token_model})..."
        )
    if max_tokens_field:
        print(
            f"🔄 过滤 {max_tokens_field} tokens > {max_tokens_value} 的记录 (model={token_model})..."
        )

    output_path = output or str(filepath)

    # 检查输入输出是否相同（流式处理需要临时文件）
    input_resolved = filepath.resolve()
    output_resolved = Path(output_path).resolve()
    use_temp_file = input_resolved == output_resolved

    # 对于 JSONL 文件使用流式处理
    if _is_streaming_supported(filepath):
        print(f"📊 流式加载: {filepath}")

        # 如果输入输出相同，使用临时文件
        if use_temp_file:
            print("⚠ 检测到输出文件与输入文件相同，将使用临时文件")
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=output_resolved.suffix,
                prefix=".tmp_",
                dir=output_resolved.parent,
            )
            os.close(temp_fd)
            actual_output = temp_path
        else:
            actual_output = output_path

        try:
            count = _clean_streaming(
                str(filepath),
                actual_output,
                strip=strip,
                empty_fields=empty_fields,
                min_len_field=min_len_field,
                min_len_value=min_len_value,
                max_len_field=max_len_field,
                max_len_value=max_len_value,
                keep_set=keep_set,
                drop_fields_set=drop_fields_set,
                rename_map=rename_map,
                promote_list=promote_list,
                add_field_map=add_field_map,
                fill_map=fill_map,
                reorder_fields=reorder_fields,
                min_tokens_field=min_tokens_field,
                min_tokens_value=min_tokens_value,
                max_tokens_field=max_tokens_field,
                max_tokens_value=max_tokens_value,
                token_model=token_model,
            )

            # 如果使用了临时文件，移动到目标位置
            if use_temp_file:
                shutil.move(temp_path, output_path)

            print(f"💾 保存结果: {output_path}")
            print(f"\n✅ 完成! 清洗后 {count} 条数据")
        except Exception as e:
            # 清理临时文件
            if use_temp_file and os.path.exists(temp_path):
                os.unlink(temp_path)
            print(f"错误: 清洗失败 - {e}")
            import traceback

            traceback.print_exc()
        return

    # 非 JSONL 文件使用传统方式
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    original_count = len(dt)
    print(f"   共 {original_count} 条数据")

    # 单次遍历执行所有清洗操作
    data, step_stats = _clean_data_single_pass(
        dt.data,
        strip=strip,
        empty_fields=empty_fields,
        min_len_field=min_len_field,
        min_len_value=min_len_value,
        max_len_field=max_len_field,
        max_len_value=max_len_value,
        keep_fields=keep_fields,
        drop_fields=drop_fields_set,
        rename_map=rename_map,
        promote_list=promote_list,
        add_field_map=add_field_map,
        fill_map=fill_map,
        reorder_fields=reorder_fields,
        min_tokens_field=min_tokens_field,
        min_tokens_value=min_tokens_value,
        max_tokens_field=max_tokens_field,
        max_tokens_value=max_tokens_value,
        token_model=token_model,
    )

    # 保存结果
    final_count = len(data)
    print(f"💾 保存结果: {output_path}")

    try:
        save_data(data, output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    # 打印统计
    removed_count = original_count - final_count
    print("\n✅ 完成!")
    print(f"   原始: {original_count} 条 -> 清洗后: {final_count} 条 (删除 {removed_count} 条)")
    if step_stats:
        print(f"   步骤: {' | '.join(step_stats)}")


def _parse_rename_param(param: str) -> Dict[str, str]:
    """解析重命名参数，格式 'old:new' 或 'old1:new1,old2:new2'"""
    rename_map = {}
    for pair in param.split(","):
        pair = pair.strip()
        if ":" not in pair:
            raise ValueError(f"重命名参数格式错误: {pair}，应为 'old:new'")
        old, new = pair.split(":", 1)
        old, new = old.strip(), new.strip()
        if not old or not new:
            raise ValueError(f"重命名参数格式错误: {pair}，字段名不能为空")
        rename_map[old] = new
    return rename_map


def _parse_promote_param(param: str) -> List[tuple]:
    """
    解析提升参数，格式 'path' 或 'path:name'（逗号分隔多个）。

    Returns:
        [(source_path, target_name), ...]
    """
    result = []
    for item in param.split(","):
        item = item.strip()
        if ":" in item:
            src, dst = item.split(":", 1)
            src, dst = src.strip(), dst.strip()
        else:
            src = item
            # 默认用路径最后一段作为目标名
            dst = src.rsplit(".", 1)[-1] if "." in src else src
        if not src or not dst:
            raise ValueError(f"promote 参数格式错误: {item}")
        result.append((src, dst))
    return result


def _parse_kv_param(param: str, param_name: str) -> Dict[str, str]:
    """解析 key:value 格式参数（通用），用于 --add-field 和 --fill"""
    kv_map = {}
    for pair in param.split(","):
        pair = pair.strip()
        if ":" not in pair:
            raise ValueError(f"{param_name} 参数格式错误: {pair}，应为 'key:value'")
        key, value = pair.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            raise ValueError(f"{param_name} 参数格式错误: {pair}，key 不能为空")
        kv_map[key] = value
    return kv_map


def _rename_item(item: Dict, rename_map: Dict[str, str]) -> Dict:
    """重命名字段，保持字段顺序"""
    return {rename_map.get(k, k): v for k, v in item.items()}


def _promote_fields(item: Dict, promote_list: List[tuple]) -> Dict:
    """提升嵌套字段到顶层（始终添加字段，即使值为 None）"""
    item = dict(item)
    for src_path, dst_name in promote_list:
        item[dst_name] = get_field_with_spec(item, src_path)
    return item


def _add_fields(item: Dict, add_field_map: Dict[str, str]) -> Dict:
    """添加常量字段"""
    item = dict(item)
    item.update(add_field_map)
    return item


def _fill_empty(item: Dict, fill_map: Dict[str, str]) -> Dict:
    """填充空值（字段不存在时也会添加）"""
    item = dict(item)
    for field, default in fill_map.items():
        if field not in item or _is_empty_value(item[field]):
            item[field] = default
    return item


def _reorder_item(item: Dict, reorder_fields: List[str]) -> Dict:
    """按指定顺序重排字段，未列出的字段追加在后面"""
    ordered = {}
    for f in reorder_fields:
        if f in item:
            ordered[f] = item[f]
    for k, v in item.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _parse_len_param(param: str) -> tuple:
    """解析长度参数，格式 'field:length'"""
    if ":" not in param:
        raise ValueError(f"长度参数格式错误: {param}，应为 '字段:长度'")
    parts = param.split(":", 1)
    field = parts[0].strip()
    try:
        length = int(parts[1].strip())
    except ValueError as e:
        raise ValueError(f"长度必须是整数: {parts[1]}") from e
    return field, length


def _clean_data_single_pass(
    data: List[Dict],
    strip: bool = False,
    empty_fields: Optional[List[str]] = None,
    min_len_field: Optional[str] = None,
    min_len_value: Optional[int] = None,
    max_len_field: Optional[str] = None,
    max_len_value: Optional[int] = None,
    keep_fields: Optional[List[str]] = None,
    drop_fields: Optional[set] = None,
    rename_map: Optional[Dict[str, str]] = None,
    promote_list: Optional[List[tuple]] = None,
    add_field_map: Optional[Dict[str, str]] = None,
    fill_map: Optional[Dict[str, str]] = None,
    reorder_fields: Optional[List[str]] = None,
    min_tokens_field: Optional[str] = None,
    min_tokens_value: Optional[int] = None,
    max_tokens_field: Optional[str] = None,
    max_tokens_value: Optional[int] = None,
    token_model: str = "cl100k_base",
) -> tuple:
    """
    单次遍历执行所有清洗操作。

    Args:
        data: 原始数据列表
        strip: 是否去除字符串首尾空白
        empty_fields: 检查空值的字段列表（支持嵌套路径），空列表表示检查所有字段，None 表示不检查
        min_len_field: 最小长度检查的字段（支持嵌套路径）
        min_len_value: 最小长度值
        max_len_field: 最大长度检查的字段（支持嵌套路径）
        max_len_value: 最大长度值
        keep_fields: 只保留的字段列表（仅支持顶层字段）
        drop_fields: 要删除的字段集合（仅支持顶层字段）

    Returns:
        (清洗后的数据, 统计信息列表)
    """
    # 延迟导入 count_tokens（仅在需要时）
    _count_tokens = None
    if min_tokens_field is not None or max_tokens_field is not None:
        from ..tokenizers import count_tokens as _count_tokens

    result = []
    stats = {
        "drop_empty": 0,
        "min_len": 0,
        "max_len": 0,
        "min_tokens": 0,
        "max_tokens": 0,
    }

    # 预先计算 keep_fields 集合（如果有的话）
    keep_set = set(keep_fields) if keep_fields else None

    for item in data:
        # 1. strip 处理（在过滤前执行，这样空值检测更准确）
        if strip:
            item = {k: v.strip() if isinstance(v, str) else v for k, v in item.items()}

        # 2. 空值过滤
        if empty_fields is not None:
            if len(empty_fields) == 0:
                # 检查所有字段
                if any(_is_empty_value(v) for v in item.values()):
                    stats["drop_empty"] += 1
                    continue
            else:
                # 检查指定字段（支持嵌套路径）
                if any(_is_empty_value(get_field_with_spec(item, f)) for f in empty_fields):
                    stats["drop_empty"] += 1
                    continue

        # 3. 最小长度过滤（支持嵌套路径）
        if min_len_field is not None:
            if _get_value_len(get_field_with_spec(item, min_len_field, default="")) < min_len_value:
                stats["min_len"] += 1
                continue

        # 4. 最大长度过滤（支持嵌套路径）
        if max_len_field is not None:
            if _get_value_len(get_field_with_spec(item, max_len_field, default="")) > max_len_value:
                stats["max_len"] += 1
                continue

        # 4.5 最小 token 数过滤
        if min_tokens_field is not None:
            value = get_field_with_spec(item, min_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) < min_tokens_value:
                stats["min_tokens"] += 1
                continue

        # 4.6 最大 token 数过滤
        if max_tokens_field is not None:
            value = get_field_with_spec(item, max_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) > max_tokens_value:
                stats["max_tokens"] += 1
                continue

        # 5. 提升嵌套字段（在 drop 之前，否则父字段被删后无法提取）
        if promote_list is not None:
            item = _promote_fields(item, promote_list)

        # 6. 字段管理（keep/drop）
        if keep_set is not None:
            item = {k: v for k, v in item.items() if k in keep_set}
        elif drop_fields is not None:
            item = {k: v for k, v in item.items() if k not in drop_fields}

        # 7. 字段重命名
        if rename_map is not None:
            item = _rename_item(item, rename_map)

        # 8. 添加常量字段
        if add_field_map is not None:
            item = _add_fields(item, add_field_map)

        # 9. 填充空值
        if fill_map is not None:
            item = _fill_empty(item, fill_map)

        # 10. 字段排序（最后执行）
        if reorder_fields is not None:
            item = _reorder_item(item, reorder_fields)

        result.append(item)

    # 构建统计信息字符串列表
    step_stats = []
    if strip:
        step_stats.append("strip")
    if stats["drop_empty"] > 0:
        step_stats.append(f"drop-empty: -{stats['drop_empty']}")
    if stats["min_len"] > 0:
        step_stats.append(f"min-len: -{stats['min_len']}")
    if stats["max_len"] > 0:
        step_stats.append(f"max-len: -{stats['max_len']}")
    if stats["min_tokens"] > 0:
        step_stats.append(f"min-tokens: -{stats['min_tokens']}")
    if stats["max_tokens"] > 0:
        step_stats.append(f"max-tokens: -{stats['max_tokens']}")
    if keep_fields:
        step_stats.append(f"keep: {len(keep_fields)} 字段")
    if drop_fields:
        step_stats.append(f"drop: {len(drop_fields)} 字段")
    if rename_map:
        step_stats.append(f"rename: {len(rename_map)} 字段")
    if promote_list:
        step_stats.append(f"promote: {len(promote_list)} 字段")
    if add_field_map:
        step_stats.append(f"add-field: {len(add_field_map)} 字段")
    if fill_map:
        step_stats.append(f"fill: {len(fill_map)} 字段")
    if reorder_fields:
        step_stats.append("reorder")

    return result, step_stats


def _clean_streaming(
    input_path: str,
    output_path: str,
    strip: bool = False,
    empty_fields: Optional[List[str]] = None,
    min_len_field: Optional[str] = None,
    min_len_value: Optional[int] = None,
    max_len_field: Optional[str] = None,
    max_len_value: Optional[int] = None,
    keep_set: Optional[set] = None,
    drop_fields_set: Optional[set] = None,
    rename_map: Optional[Dict[str, str]] = None,
    promote_list: Optional[List[tuple]] = None,
    add_field_map: Optional[Dict[str, str]] = None,
    fill_map: Optional[Dict[str, str]] = None,
    reorder_fields: Optional[List[str]] = None,
    min_tokens_field: Optional[str] = None,
    min_tokens_value: Optional[int] = None,
    max_tokens_field: Optional[str] = None,
    max_tokens_value: Optional[int] = None,
    token_model: str = "cl100k_base",
) -> int:
    """
    流式清洗数据。

    Returns:
        处理后的数据条数
    """

    # 延迟导入 count_tokens（仅在需要时）
    _count_tokens = None
    if min_tokens_field is not None or max_tokens_field is not None:
        from ..tokenizers import count_tokens as _count_tokens

    def clean_filter(item: Dict) -> bool:
        """过滤函数：返回 True 保留，False 过滤（支持嵌套路径）"""
        # 空值过滤
        if empty_fields is not None:
            if len(empty_fields) == 0:
                if any(_is_empty_value(v) for v in item.values()):
                    return False
            else:
                # 支持嵌套路径
                if any(_is_empty_value(get_field_with_spec(item, f)) for f in empty_fields):
                    return False

        # 最小长度过滤（支持嵌套路径）
        if min_len_field is not None:
            if _get_value_len(get_field_with_spec(item, min_len_field, default="")) < min_len_value:
                return False

        # 最大长度过滤（支持嵌套路径）
        if max_len_field is not None:
            if _get_value_len(get_field_with_spec(item, max_len_field, default="")) > max_len_value:
                return False

        # 最小 token 数过滤
        if min_tokens_field is not None:
            value = get_field_with_spec(item, min_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) < min_tokens_value:
                return False

        # 最大 token 数过滤
        if max_tokens_field is not None:
            value = get_field_with_spec(item, max_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) > max_tokens_value:
                return False

        return True

    def clean_transform(item: Dict) -> Dict:
        """转换函数：strip + 字段管理"""
        # strip 处理
        if strip:
            item = {k: v.strip() if isinstance(v, str) else v for k, v in item.items()}

        # 字段管理
        if keep_set is not None:
            item = {k: v for k, v in item.items() if k in keep_set}
        elif drop_fields_set is not None:
            item = {k: v for k, v in item.items() if k not in drop_fields_set}

        return item

    # 构建流式处理链
    st = load_stream(input_path)

    # 如果需要 strip，先执行 strip 转换（在过滤之前，这样空值检测更准确）
    if strip:
        st = st.transform(
            lambda x: {k: v.strip() if isinstance(v, str) else v for k, v in x.items()}
        )

    # 执行过滤
    if (
        empty_fields is not None
        or min_len_field is not None
        or max_len_field is not None
        or min_tokens_field is not None
        or max_tokens_field is not None
    ):
        st = st.filter(clean_filter)

    # 提升嵌套字段（在 drop 之前，否则父字段被删后无法提取）
    if promote_list is not None:
        st = st.transform(lambda item: _promote_fields(item, promote_list))

    # 执行字段管理（keep/drop）
    if keep_set is not None or drop_fields_set is not None:

        def field_transform(item):
            if keep_set is not None:
                return {k: v for k, v in item.items() if k in keep_set}
            elif drop_fields_set is not None:
                return {k: v for k, v in item.items() if k not in drop_fields_set}
            return item

        st = st.transform(field_transform)

    # 执行字段重命名
    if rename_map is not None:
        st = st.transform(lambda item: _rename_item(item, rename_map))

    # 添加常量字段
    if add_field_map is not None:
        st = st.transform(lambda item: _add_fields(item, add_field_map))

    # 填充空值
    if fill_map is not None:
        st = st.transform(lambda item: _fill_empty(item, fill_map))

    # 字段排序（最后执行）
    if reorder_fields is not None:
        st = st.transform(lambda item: _reorder_item(item, reorder_fields))

    return st.save(output_path)
