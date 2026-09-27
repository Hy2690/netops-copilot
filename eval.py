"""eval.py — 自动化评估：批量注入故障，量化 Agent 的根因定位能力。

运行：python eval.py
输出：每个场景的关键词命中率、工具调用次数，以及总体准确率。

这是写进简历的关键：用数字说话，而不是"我做了一个 Agent"。
还可以用不同模型各跑一遍，得到模型横向对比数据：
    OLLAMA_MODEL=qwen38-gsq    python eval.py   # 默认主模型（Qwen3.8-27B GSQ-RCO-IQ3_S）
    OLLAMA_MODEL=gpt-oss:20b   python eval.py    # 速度优先备选
    OLLAMA_MODEL=qwen3.5:9b    python eval.py    # 轻量对照组
"""

import json
import os

import mock_network
from agent import diagnose

AUDIT_FILE = os.getenv("NETOPS_AUDIT", "audit.log")


def _readonly_call_count():
    """从审计日志统计只读工具调用次数（即 Agent 排查时执行了多少条命令）。"""
    if not os.path.exists(AUDIT_FILE):
        return 0
    count = 0
    with open(AUDIT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                if json.loads(line).get("action") == "readonly":
                    count += 1
            except json.JSONDecodeError:
                continue
    return count


def score(answer, expected_groups):
    """关键词分组命中：组间取平均（AND），组内任一命中即可（OR）。"""
    a = answer.lower()
    hits = sum(1 for g in expected_groups if any(k.lower() in a for k in g))
    return hits / len(expected_groups)


def main():
    model = os.getenv("OLLAMA_MODEL", "qwen38-gsq")
    results = []
    for name, fault in mock_network.FAULTS.items():
        before = _readonly_call_count()
        mock_network.inject_fault(name)
        print(f"\n### 场景: {fault['desc']}")
        answer = diagnose(fault["symptom"], trace=False)
        calls = _readonly_call_count() - before
        s = score(answer, fault["expected"])
        results.append((name, s, calls))
        print(f"  得分: {s:.0%} | 工具调用: {calls} 次 | 结论摘要: {answer[:80]}...")

    acc = sum(s for _, s, _ in results) / len(results)
    avg_calls = sum(c for _, _, c in results) / len(results)
    print("\n" + "=" * 60)
    print(f"模型: {model}")
    print(f"总体根因定位准确率: {acc:.0%}（{len(results)} 个场景）")
    print(f"平均每次诊断工具调用: {avg_calls:.1f} 次")


if __name__ == "__main__":
    main()
