"""TTL/RDF 单文件提取 — BreachPoint。

直接调用 parse_ttl 解析器，无 LLM 调用。

公开 API:
    extract(path) -> dict   — {nodes, edges, input_tokens, output_tokens}
"""
from __future__ import annotations
from pathlib import Path

TTL_EXTENSIONS: frozenset[str] = frozenset({".ttl", ".turtle", ".n3"})


def extract(path: str | Path, client=None, *, model: str = "", schema=None) -> dict:
    """解析 TTL/RDF 文件，返回 {nodes, edges, input_tokens, output_tokens}。

    client / model / schema 参数保留仅为接口兼容，实际不使用。

    Raises:
        ValueError: 若文件不是支持的 TTL 格式。
    """
    path = Path(path)
    if path.suffix.lower() not in TTL_EXTENSIONS:
        raise ValueError(
            f"不支持的文件格式：{path.suffix}。breachpoint 当前仅支持 TTL/RDF 文件。"
        )

    from .parse_ttl import parse_ttl
    result = parse_ttl(path)
    return {
        "nodes": result["nodes"],
        "edges": result["edges"],
        "input_tokens": 0,
        "output_tokens": 0,
    }
