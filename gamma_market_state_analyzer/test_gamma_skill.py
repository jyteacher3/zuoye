#!/usr/bin/env python3
"""
gamma_market_state_analyzer Skill — 独立测试脚本

运行方式：
    python test_gamma_skill.py            # 测试 SPY / QQQ / AAPL
    python test_gamma_skill.py TSLA     # 测试指定标的

说明：
    - 需要 yfinance（pip install yfinance）
    - 限流时自动切换演示模式，无需任何 API Key
    - 输出格式兼容 AI Renaissance Signal 规范
"""

import sys
import logging
from pathlib import Path

# 将 skill 目录加入路径，直接 import gamma_engine
SKILL_DIR = Path(__file__).parent
sys.path.insert(0, str(SKILL_DIR))

from gamma_engine import analyze_gamma, judge_regime, judge_direction

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)


def print_result(ticker: str, result: dict):
    """格式化打印分析结果"""
    meta = result.get("meta", {})
    print(f"\n{'=' * 50}")
    print(f"标的：{ticker}")
    print(f"  direction : {result['direction']}")
    print(f"  confidence: {result['confidence']:.2f}")
    print(f"  reasoning : {result['reasoning']}")
    print(f"  signals   : {result.get('signals', [])}")
    print(f"  Total GEX: ${meta.get('total_gex', 0):,.0f}")
    print(f"  gamma_state: {meta.get('gamma_state', 'N/A')}")
    print(f"  risk_level : {meta.get('risk_level', 'N/A')}")
    print(f"  demo_mode  : {meta.get('demo_mode', False)}")
    if meta.get("warnings"):
        print(f"  warnings  : {meta['warnings']}")


def main():
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["SPY", "QQQ", "AAPL"]

    print("=" * 50)
    print("  gamma_market_state_analyzer — GEX 分析测试")
    print("=" * 50)

    for ticker in tickers:
        try:
            result = analyze_gamma(ticker)
            print_result(ticker, result)
        except Exception as e:
            logging.exception(f"分析 {ticker} 失败: {e}")

    print(f"\n{'=' * 50}")
    print("  测试完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
