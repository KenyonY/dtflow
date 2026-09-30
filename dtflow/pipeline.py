"""
Pipeline: 用 YAML 把一串 dt 命令固化下来, 可复现地执行。

step 的 type 就是 CLI 命令名, 参数就是 CLI 选项名 (下划线形式), 一套语法两处用:

    version: "1.0"
    input: data.jsonl
    output: out.jsonl
    steps:
      - type: filter
        expr: "x.score > 0.5 and len(x.messages) >= 2"
      - type: select
        fields: "id,text,n=len(x.messages)"
      - type: clean
        strip: true
        drop_empty: "text"
      - type: dedupe
        key: text
      - type: transform
        preset: openai_chat
        params: {user_field: q, assistant_field: a}
      - type: split          # 只能是最后一步: 按 output 派生 out_train.jsonl / out_test.jsonl
        ratio: 0.9
        seed: 42

执行载体是 StreamingTransformer, 能惰性的步骤不落内存。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ops
from .expr import ExprSyntaxError, check_syntax
from .i18n import t
from .storage.io import load_data
from .streaming import StreamingTransformer, open_stream

PIPELINE_VERSION = "1.0"


def _load_yaml(filepath: str) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError:
        raise ImportError(
            t("PyYAML is required: pip install pyyaml", "需要安装 PyYAML: pip install pyyaml")
        ) from None
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(data: Dict[str, Any], filepath: str) -> None:
    try:
        import yaml
    except ImportError:
        raise ImportError(
            t("PyYAML is required: pip install pyyaml", "需要安装 PyYAML: pip install pyyaml")
        ) from None
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ============ 步骤执行器: (st, step) -> st ============


def _norm_step(step: Any) -> Any:
    """YAML 1.1 把裸 ``on:`` 解析成布尔 True; join 的 on 是最自然的写法, 不能让用户去加引号。"""
    if isinstance(step, dict) and True in step:
        step = dict(step)
        step["on"] = step.pop(True)
    return step


def _need(step: Dict[str, Any], key: str) -> Any:
    v = step.get(key)
    if v in (None, ""):
        typ = step.get("type")
        raise ValueError(t(f"{typ} step requires {key}", f"{typ} 步骤需要指定 {key}"))
    return v


def _s_filter(st, step):
    return ops.filter_rows(st, str(_need(step, "expr")), bool(step.get("strict")))


def _s_map(st, step):
    return ops.map_rows(st, str(_need(step, "code")), bool(step.get("strict")))


def _s_select(st, step):
    return ops.select_rows(st, str(_need(step, "fields")), bool(step.get("strict")))


def _s_explode(st, step):
    return ops.explode_rows(st, _need(step, "field"), step.get("as"), step.get("index_as"))


def _s_sort(st, step):
    return ops.sort_rows(
        st, str(_need(step, "by")), bool(step.get("desc")), bool(step.get("strict"))
    )


def _s_shuffle(st, step):
    return ops.shuffle_rows(st, step.get("seed"))


def _s_group(st, step):
    return ops.group_rows(
        st, str(_need(step, "by")), step.get("agg"), bool(step.get("strict")), step.get("top")
    )


def _s_join(st, step):
    right = _need(step, "right")
    if not (step.get("on") or (step.get("left_on") and step.get("right_on"))):
        raise ValueError(
            t(
                "join step requires on, or both left_on and right_on",
                "join 步骤需要 on, 或同时给 left_on 与 right_on",
            )
        )
    st, _dup = ops.join_rows(
        st,
        load_data(right),
        step.get("on"),
        step.get("left_on"),
        step.get("right_on"),
        bool(step.get("inner")),
        step.get("prefix"),
        anti=bool(step.get("anti")),
        strict=bool(step.get("strict")),
    )
    return st


def _s_dedupe(st, step):
    key = step.get("key")
    if isinstance(key, list):
        key = ",".join(key)
    return ops.dedupe_rows(st, key, step.get("similar"))


def _s_sample(st, step):
    return st.sample(int(step.get("num", 10)), seed=step.get("seed"))


def _s_head(st, step):
    return st.head(int(step.get("num", 10)))


def _s_tail(st, step):
    return st.tail(int(step.get("num", 10)))


def _s_transform(st, step):
    if not (step.get("preset") or step.get("config")):
        raise ValueError(
            t("transform step requires preset or config", "transform 步骤需要指定 preset 或 config")
        )
    return ops.transform_rows(
        st,
        step.get("preset"),
        step.get("params") or {},
        step.get("config"),
        bool(step.get("strict")),
    )


def _csv(v: Any) -> Optional[List[str]]:
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _field_n(v: Any) -> tuple:
    """ "text:10" → ("text", 10)"""
    if v is None:
        return None, None
    field, _, n = str(v).partition(":")
    if not n:
        raise ValueError(t(f"Expected field:count, got {v!r}", f"应为 字段:数量, 得到 {v!r}"))
    return field.strip(), int(n)


def _s_clean(st, step):
    """参数名 = dt clean 的选项名 (下划线)。"""
    min_len_f, min_len_v = _field_n(step.get("min_len"))
    max_len_f, max_len_v = _field_n(step.get("max_len"))
    min_tok_f, min_tok_v = _field_n(step.get("min_tokens"))
    max_tok_f, max_tok_v = _field_n(step.get("max_tokens"))
    drop_empty = step.get("drop_empty")
    if drop_empty is True:
        empty_fields: Optional[List[str]] = []
    else:
        empty_fields = _csv(drop_empty)
    rename = step.get("rename")
    promote = step.get("promote")
    keep = _csv(step.get("keep"))
    drop = _csv(step.get("drop"))
    return ops.clean_rows(
        st,
        strip=bool(step.get("strip")),
        empty_fields=empty_fields,
        min_len_field=min_len_f,
        min_len_value=min_len_v,
        max_len_field=max_len_f,
        max_len_value=max_len_v,
        keep_set=set(keep) if keep else None,
        drop_fields_set=set(drop) if drop else None,
        rename_map=rename if isinstance(rename, dict) else _kv(rename),
        promote_list=_promote(promote),
        add_field_map=(
            step.get("add_field")
            if isinstance(step.get("add_field"), dict)
            else _kv(step.get("add_field"))
        ),
        fill_map=step.get("fill") if isinstance(step.get("fill"), dict) else _kv(step.get("fill")),
        reorder_fields=_csv(step.get("reorder")),
        min_tokens_field=min_tok_f,
        min_tokens_value=min_tok_v,
        max_tokens_field=max_tok_f,
        max_tokens_value=max_tok_v,
        token_model=str(step.get("model", "cl100k_base")),
    )


def _kv(v: Any) -> Optional[Dict[str, str]]:
    """ "a:b,c:d" → {"a": "b", "c": "d"}"""
    if v is None:
        return None
    out = {}
    for pair in str(v).split(","):
        k, sep, val = pair.partition(":")
        if not sep or not k.strip():
            raise ValueError(
                t(f"Expected key:value, got {pair!r}", f"应为 key:value, 得到 {pair!r}")
            )
        out[k.strip()] = val.strip()
    return out


def _promote(v: Any) -> Optional[List[tuple]]:
    if v is None:
        return None
    items = v if isinstance(v, list) else str(v).split(",")
    out = []
    for item in items:
        src, sep, dst = str(item).strip().partition(":")
        if not sep:
            dst = src.rsplit(".", 1)[-1]
        out.append((src.strip(), dst.strip()))
    return out


STEP_EXECUTORS = {
    "filter": _s_filter,
    "map": _s_map,
    "select": _s_select,
    "explode": _s_explode,
    "sort": _s_sort,
    "shuffle": _s_shuffle,
    "group": _s_group,
    "join": _s_join,
    "dedupe": _s_dedupe,
    "sample": _s_sample,
    "head": _s_head,
    "tail": _s_tail,
    "clean": _s_clean,
    "transform": _s_transform,
}
TERMINAL_STEPS = {"split"}  # 产出多个文件, 只能在最后


# ============ 构建 / 执行 ============


def _check_steps(steps: List[Dict[str, Any]]) -> None:
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not step.get("type"):
            raise ValueError(t(f"Step {i} has no type", f"步骤 {i} 未指定 type"))
        typ = step["type"]
        if typ in TERMINAL_STEPS:
            if i != len(steps):
                raise ValueError(
                    t(f"Step {i}: {typ} must be the last step", f"步骤 {i}: {typ} 只能是最后一步")
                )
        elif typ not in STEP_EXECUTORS:
            available = ", ".join([*STEP_EXECUTORS, *TERMINAL_STEPS])
            raise ValueError(
                t(
                    f"Unknown step type: {typ}. Available: {available}",
                    f"未知步骤类型: {typ}。可用类型: {available}",
                )
            )


def build_pipeline(
    config: Dict[str, Any], input_path: str, verbose: bool = False
) -> StreamingTransformer:
    """把配置里全部非终态步骤挂到输入流上 (惰性), 返回数据流。"""
    steps = [_norm_step(s) for s in (config.get("steps", []) or [])]
    _check_steps(steps)
    if verbose:
        print(t(f"📂 Loading data: {input_path}", f"📂 加载数据: {input_path}"))
    st = open_stream(input_path)
    for i, step in enumerate(steps, 1):
        if step["type"] in TERMINAL_STEPS:
            break
        if verbose:
            desc = _format_step_description(step)
            print(t(f"🔄 Step {i}: {desc}", f"🔄 步骤 {i}: {desc}"))
        st = STEP_EXECUTORS[step["type"]](st, step)
    return st


def _split_paths(output_path: str, names: List[str]) -> List[str]:
    p = Path(output_path)
    suffixes = "".join(p.suffixes)
    stem = p.name[: -len(suffixes)] if suffixes else p.name
    return [str(p.parent / f"{stem}_{n}{suffixes or '.jsonl'}") for n in names]


def run_pipeline(
    config_path: str,
    input_file: Optional[str] = None,
    output_file: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    执行 Pipeline 配置文件并落盘。

    Returns:
        {"output": path, "rows": n}; 以 split 结尾时 {"splits": [{"name","path","rows"}], "rows": n}

    Examples:
        >>> run_pipeline("pipeline.yaml")
        >>> run_pipeline("pipeline.yaml", input_file="new_data.jsonl", output_file="out.jsonl")
    """
    config = _load_yaml(config_path)
    version = config.get("version", PIPELINE_VERSION)
    if version != PIPELINE_VERSION and verbose:
        print(
            t(
                f"⚠ Config version {version} differs from current version {PIPELINE_VERSION}",
                f"⚠ 配置版本 {version} 与当前版本 {PIPELINE_VERSION} 不一致",
            )
        )

    input_path = input_file or config.get("input")
    if not input_path:
        raise ValueError(
            t(
                "No input file: set input in the config or pass --input",
                "未指定输入文件，请在配置中设置 input 或使用 --input 参数",
            )
        )
    output_path = output_file or config.get("output")
    if not output_path or output_path == "-":
        raise ValueError(
            t(
                "No output file: set output in the config or pass --output (- means stdout in the CLI)",
                "未指定输出文件，请在配置中设置 output 或使用 --output 参数 (CLI 下 - 表示 stdout)",
            )
        )

    st = build_pipeline(config, str(input_path), verbose=verbose)
    steps = config.get("steps", []) or []
    last = steps[-1] if steps else None
    if last and last.get("type") == "split":
        ratios = ops.parse_ratio(last.get("ratio", 0.8))
        names = ops.split_names(len(ratios))
        parts = ops.split_rows(st.collect(), ratios, last.get("seed", config.get("seed")))
        paths = _split_paths(str(output_path), names)
        splits = []
        for name, part, path in zip(names, parts, paths, strict=False):
            StreamingTransformer(iter(part), None, total=len(part)).save(path, show_progress=False)
            splits.append({"name": name, "path": path, "rows": len(part)})
            if verbose:
                print(
                    t(
                        f"💾 {name}: {len(part)} rows -> {path}",
                        f"💾 {name}: {len(part)} 条 -> {path}",
                    )
                )
        return {"splits": splits, "rows": sum(len(p) for p in parts)}

    if verbose:
        print(t(f"💾 Saving to: {output_path}", f"💾 保存结果: {output_path}"))
    n = st.save(str(output_path), show_progress=verbose)
    if verbose:
        print(t(f"✅ Done! {n} rows", f"✅ 完成! 共 {n} 条数据"))
    return {"output": str(output_path), "rows": n}


def _format_step_description(step: Dict[str, Any]) -> str:
    """ "filter (expr=x.a > 1)" 这种通用形态: 参数即 CLI 选项, 不必每种步骤各写一遍。"""
    params = ", ".join(f"{k}={v}" for k, v in step.items() if k != "type")
    return f"{step.get('type', '')} ({params})" if params else str(step.get("type", ""))


# ============ 模板 / 校验 ============


def generate_pipeline_template(
    input_file: str,
    output_file: str = "pipeline.yaml",
    preset: Optional[str] = None,
) -> str:
    """根据输入数据的字段生成一份可跑的 Pipeline 配置模板。"""
    data = load_data(input_file)
    if not data:
        raise ValueError(t("Input file is empty", "输入文件为空"))
    fields = list(data[0].keys())

    config: Dict[str, Any] = {
        "version": PIPELINE_VERSION,
        "seed": 42,
        "input": input_file,
        "output": Path(input_file).stem + "_output.jsonl",
        "steps": [],
    }
    if preset:
        config["steps"].append({"type": "transform", "preset": preset})
    else:
        config["steps"].append({"type": "filter", "expr": f"x.{fields[0]}"})
        if "messages" in fields:
            pass  # 已经是 messages 格式
        elif "q" in fields and "a" in fields:
            config["steps"].append(
                {
                    "type": "transform",
                    "preset": "openai_chat",
                    "params": {"user_field": "q", "assistant_field": "a"},
                }
            )
        elif "instruction" in fields and "output" in fields:
            config["steps"].append({"type": "transform", "preset": "alpaca"})
        config["steps"].append({"type": "dedupe", "key": fields[0] if fields else None})

    _save_yaml(config, output_file)
    return output_file


_REQUIRED = {
    "filter": ("expr",),
    "map": ("code",),
    "select": ("fields",),
    "explode": ("field",),
    "sort": ("by",),
    "group": ("by",),
    "join": ("right",),
}
# 每种 step 认得的键 (= CLI 选项名): 拼错的键静默忽略等于假装执行了, 必须报出来
_ALLOWED = {
    "filter": {"expr", "strict"},
    "map": {"code", "strict"},
    "select": {"fields", "strict"},
    "explode": {"field", "as", "index_as"},
    "sort": {"by", "desc", "strict"},
    "shuffle": {"seed"},
    "group": {"by", "agg", "strict", "top"},
    "join": {"right", "on", "left_on", "right_on", "inner", "prefix", "anti", "strict"},
    "dedupe": {"key", "similar"},
    "sample": {"num", "seed"},
    "head": {"num"},
    "tail": {"num"},
    "clean": {
        "strip",
        "drop_empty",
        "min_len",
        "max_len",
        "keep",
        "drop",
        "rename",
        "promote",
        "add_field",
        "fill",
        "reorder",
        "min_tokens",
        "max_tokens",
        "model",
    },
    "transform": {"preset", "params", "config", "strict"},
    "split": {"ratio", "seed"},
}
_EXPR_KEYS = {"filter": "expr", "sort": "by", "group": "by", "select": None, "map": None}


def validate_pipeline(config_path: str) -> List[str]:
    """校验配置: 步骤类型、必填参数、表达式语法 (提前到执行前报错)。返回错误列表。"""
    errors: List[str] = []
    try:
        config = _load_yaml(config_path)
    except Exception as e:
        return [t(f"Cannot parse config file: {e}", f"无法解析配置文件: {e}")]

    if "steps" not in config:
        errors.append(t("Missing steps field", "缺少 steps 字段"))
    steps = [_norm_step(s) for s in (config.get("steps", []) or [])]
    all_types = [*STEP_EXECUTORS, *TERMINAL_STEPS]
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or "type" not in step:
            errors.append(t(f"Step {i} is missing type", f"步骤 {i} 缺少 type 字段"))
            continue
        typ = step["type"]
        if typ not in all_types:
            errors.append(
                t(
                    f"Step {i}: unknown type '{typ}', available: {', '.join(all_types)}",
                    f"步骤 {i}: 未知类型 '{typ}'，可用: {', '.join(all_types)}",
                )
            )
            continue
        if typ in TERMINAL_STEPS and i != len(steps):
            errors.append(
                t(f"Step {i}: {typ} must be the last step", f"步骤 {i}: {typ} 只能是最后一步")
            )
        unknown = sorted(str(k) for k in step if k not in _ALLOWED[typ] | {"type", "name"})
        if unknown:
            unknown_s, allowed_s = ", ".join(unknown), ", ".join(sorted(_ALLOWED[typ]))
            errors.append(
                t(
                    f"Step {i}: {typ} does not accept {unknown_s}; available: {allowed_s}",
                    f"步骤 {i}: {typ} 不认识参数 {unknown_s}; 可用: {allowed_s}",
                )
            )
        for key in _REQUIRED.get(typ, ()):
            if step.get(key) in (None, ""):
                errors.append(
                    t(f"Step {i}: {typ} requires {key}", f"步骤 {i}: {typ} 需要指定 {key}")
                )
        if typ == "transform" and not (step.get("preset") or step.get("config")):
            errors.append(
                t(
                    f"Step {i}: transform requires preset or config",
                    f"步骤 {i}: transform 需要指定 preset 或 config",
                )
            )
        if typ == "join" and not (step.get("on") or (step.get("left_on") and step.get("right_on"))):
            errors.append(
                t(
                    f"Step {i}: join requires on, or both left_on and right_on",
                    f"步骤 {i}: join 需要 on, 或同时给 left_on 与 right_on",
                )
            )
        if typ == "join" and step.get("on") and (step.get("left_on") or step.get("right_on")):
            errors.append(
                t(
                    f"Step {i}: join takes either on or left_on/right_on, not both",
                    f"步骤 {i}: join 的 on 与 left_on/right_on 只能二选一",
                )
            )
        # 表达式语法
        exprs = []
        if typ in ("filter", "sort", "group") and step.get(_EXPR_KEYS[typ]):
            exprs.append((str(step[_EXPR_KEYS[typ]]), "eval"))
        if typ == "map" and step.get("code"):
            exprs.append((str(step["code"]), "exec"))
        if typ == "join":
            for k in ("on", "left_on", "right_on"):
                if step.get(k):
                    exprs.append((str(step[k]), "eval"))
        for expr, mode in exprs:
            try:
                check_syntax(expr, mode)
            except ExprSyntaxError as e:
                import textwrap

                caret = textwrap.indent(e.caret(), "  ")
                errors.append(t(f"Step {i}: {typ} {e}\n{caret}", f"步骤 {i}: {typ} {e}\n{caret}"))
        if typ == "group" and step.get("agg"):
            try:
                for _name, e in ops.parse_spec(str(step["agg"])):
                    if e:
                        check_syntax(e, allowed=ops._AGG_ALLOWED)
            except (ValueError, ExprSyntaxError) as e:
                errors.append(t(f"Step {i}: group agg {e}", f"步骤 {i}: group agg {e}"))
        if typ in ("select",) and step.get("fields"):
            try:
                for _name, e in ops.parse_spec(str(step["fields"])):
                    if e:
                        check_syntax(e)
            except (ValueError, ExprSyntaxError) as e:
                errors.append(t(f"Step {i}: select {e}", f"步骤 {i}: select {e}"))
    return errors
