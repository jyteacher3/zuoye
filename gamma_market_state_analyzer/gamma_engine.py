"""
gamma_market_state_analyzer — GEX 计算引擎（可独立运行）

基于期权持仓量（OI）和 Black-Scholes Gamma 公式，
计算标的总 Gamma 敞口（Net GEX），判断做市商对冲压力及市场状态。

## 快速开始

```bash
pip install yfinance
python test_gamma_skill.py
```

## 设计说明

- 含完整 Black-Scholes Gamma 计算
- 支持 yfinance 获取真实期权链（美股/ETF）
- 限流或数据缺失时自动切换演示模式
- 输出与 AI Renaissance Signal 规范兼容的字典

作者：专家7组（风险）
依赖：yfinance（免费，无需 API Key）
"""

import math
import time
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

logger = logging.getLogger(__name__)

# ── Black-Scholes 辅助函数 ───────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """标准正态分布累积函数"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _calc_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def black_scholes_gamma(
    S: float,
    K: float,
    T: float,
    r: float = 0.05,
    sigma: float = 0.3,
) -> float:
    """
    计算单张期权的 Gamma（Black-Scholes）

    Args:
        S: 当前价格
        K: 行权价
        T: 剩余到期时间（年）
        r: 无风险利率（默认 5%）
        sigma: 隐含波动率（默认 30%）

    Returns:
        Gamma 值（每张合约，未乘合约乘数）
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0

    d1 = _calc_d1(S, K, T, r, sigma)
    gamma = _norm_cdf(d1) / (S * sigma * math.sqrt(T))
    return gamma


# ── GEX 计算核心 ───────────────────────────────────────────────────

CONTRACT_SIZE = 100   # 美股期权每张合约对应股数


def calc_option_gex(
    oi: int,
    gamma: float,
    direction: int,
    contract_size: int = CONTRACT_SIZE,
) -> float:
    """
    计算单张期权合约的 GEX 贡献

    Args:
        oi: 持仓量（张）
        gamma: 单张合约 Gamma
        direction: 方向因子
            +1 = 做市商净多头（散户卖出）
            -1 = 做市商净空头（散户买入）
        contract_size: 合约乘数（美股=100）

    Returns:
        该合约的 GEX 贡献（$/1% 价格变动）
    """
    return oi * contract_size * gamma * direction


def calc_total_gex(
    options_chain: List[Dict],
    S: float,
    T: float,
    r: float = 0.05,
    direction: int = -1,
) -> Tuple[float, int, List[Dict]]:
    """
    计算标的总 GEX

    Args:
        options_chain: 期权链数据列表，每项含 {strike, oi_call, oi_put, iv_call, iv_put}
        S: 当前价格
        T: 到期时间（年）
        r: 无风险利率
        direction: 方向因子（默认 -1 = 散户净买入）

    Returns:
        (total_gex, valid_contracts, detail_list)
    """
    total_gex = 0.0
    valid = 0
    details = []

    for opt in options_chain:
        K = opt["strike"]
        oi_c = opt.get("oi_call", 0)
        oi_p = opt.get("oi_put", 0)
        iv_c = opt.get("iv_call", 0.3)
        iv_p = opt.get("iv_put", 0.3)

        # Call Gamma
        if oi_c > 0:
            g_c = black_scholes_gamma(S, K, T, r, iv_c)
            gex_c = calc_option_gex(oi_c, g_c, direction, CONTRACT_SIZE)
            total_gex += gex_c
            valid += 1
            details.append({
                "strike": K,
                "type": "C",
                "oi": oi_c,
                "gamma": g_c,
                "gex": gex_c,
            })

        # Put Gamma
        if oi_p > 0:
            g_p = black_scholes_gamma(S, K, T, r, iv_p)
            gex_p = calc_option_gex(oi_p, g_p, -direction, CONTRACT_SIZE)
            total_gex += gex_p
            valid += 1
            details.append({
                "strike": K,
                "type": "P",
                "oi": oi_p,
                "gamma": g_p,
                "gex": gex_p,
            })

    return total_gex, valid, details


# ── 状态判断 ─────────────────────────────────────────────────────

def judge_regime(total_gex: float) -> str:
    """判断 Gamma Regime"""
    if total_gex > 0:
        return "positive"
    elif total_gex < 0:
        return "negative"
    else:
        return "neutral"


def judge_direction(total_gex: float, gex_threshold: float = 5e4) -> str:
    """
    根据 Total GEX 判断方向信号

    Positive GEX → 做市商高抛低吸 → 震荡稳定 → bullish/neutral
    Negative GEX → 做市商追涨杀跌 → 单边放大 → bearish
    """
    if total_gex > gex_threshold:
        return "bullish"
    elif total_gex < -gex_threshold:
        return "bearish"
    else:
        return "neutral"


def calc_hedge_pressure(total_gex: float, adv: float) -> Tuple[float, str]:
    """
    计算对冲压力

    Returns:
        (hedge_ratio, risk_level)
    """
    if adv <= 0:
        return 0.0, "low"

    hedge_shares = abs(total_gex) / 100.0  # 简化估算
    hedge_ratio = hedge_shares / adv

    if hedge_ratio >= 0.2:
        risk_level = "high"
    elif hedge_ratio >= 0.1:
        risk_level = "medium"
    else:
        risk_level = "low"

    return hedge_ratio, risk_level


# ── 数据获取（yfinance，含重试） ────────────────────────────────

def _yf_get_with_retry(ticker_obj, attr: str, expr: str = None,
                       max_retries: int = 3, delay: float = 2.0):
    """带重试的 yfinance 属性获取，处理限流"""
    for attempt in range(max_retries):
        try:
            if attr == "info":
                return ticker_obj.info
            elif attr == "options":
                return list(ticker_obj.options)
            elif attr == "option_chain":
                return ticker_obj.option_chain(expr)
        except Exception as e:
            msg = str(e).lower()
            if "rate" in msg or "too many" in msg or "429" in msg:
                if attempt < max_retries - 1:
                    wait = delay * (2 ** attempt)
                    logger.warning(f"限流，等待 {wait}s 后重试...")
                    time.sleep(wait)
                    continue
            if attempt == max_retries - 1:
                raise
    return None


def fetch_option_chain_yf(
    ticker: str,
    max_expiry: int = 4,
) -> Tuple[List[Dict], float, List[str]]:
    """
    使用 yfinance 获取期权链数据（含重试逻辑）

    Args:
        ticker: 股票代码（如 'SPY', 'AAPL'）
        max_expiry: 最多取最近 N 个到期日

    Returns:
        (options_chain, current_price, warnings)
    """
    if not HAS_YFINANCE:
        raise ImportError("yfinance 未安装，请运行 pip install yfinance")

    warnings = []
    S = 0.0

    try:
        t = yf.Ticker(ticker)
        info = _yf_get_with_retry(t, "info")
        if info:
            S = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        if S <= 0:
            warnings.append(f"无法获取 {ticker} 当前价格")
    except Exception as e:
        warnings.append(f"获取 {ticker} 价格失败: {e}")
        return [], 0.0, warnings

    options_chain = []

    try:
        exprs = _yf_get_with_retry(t, "options")
        if not exprs:
            warnings.append(f"{ticker} 无期权数据（可能非期权标的）")
            return options_chain, S, warnings
        expirations = exprs[:max_expiry]
    except Exception as e:
        warnings.append(f"获取 {ticker} 到期日失败: {e}")
        return options_chain, S, warnings

    for expr in expirations:
        try:
            chain = _yf_get_with_retry(t, "option_chain", expr=expr)
            if chain is None:
                warnings.append(f"获取 {ticker} {expr} 期权链失败")
                continue

            calls = chain.calls
            puts = chain.puts

            for _, row in calls.iterrows():
                strike = row.get("strike", 0)
                oi = row.get("openInterest", 0)
                iv = row.get("impliedVolatility", 0.3)
                if oi > 0:
                    options_chain.append({
                        "strike": strike,
                        "oi_call": int(oi),
                        "oi_put": 0,
                        "iv_call": iv,
                        "iv_put": 0.3,
                        "expiry": expr,
                    })

            for _, row in puts.iterrows():
                strike = row.get("strike", 0)
                oi = row.get("openInterest", 0)
                iv = row.get("impliedVolatility", 0.3)
                existing = next((o for o in options_chain if o["strike"] == strike), None)
                if existing:
                    existing["oi_put"] = int(oi)
                    existing["iv_put"] = iv
                elif oi > 0:
                    options_chain.append({
                        "strike": strike,
                        "oi_call": 0,
                        "oi_put": int(oi),
                        "iv_call": 0.3,
                        "iv_put": iv,
                        "expiry": expr,
                    })
        except Exception as e:
            warnings.append(f"处理 {ticker} 到期日 {expr} 失败: {e}")

    return options_chain, S, warnings


# ── 演示模式（限流时自动切换） ──────────────────────────────────

def _get_demo_data(ticker: str) -> Tuple[float, List[Dict]]:
    """
    演示模式：返回模拟的期权链数据

    基于历史典型状态生成合理的 GEX 近似值，
    仅用于演示流水线跑通，不用于实盘决策。
    """
    demo_config = {
        "SPY":   {"price": 580.0, "gex_state": "positive", "iv": 0.18},
        "QQQ":   {"price": 480.0, "gex_state": "negative", "iv": 0.25},
        "AAPL":  {"price": 195.0, "gex_state": "positive", "iv": 0.28},
        "TSLA":  {"price": 250.0, "gex_state": "negative", "iv": 0.45},
        "NVDA":  {"price": 880.0, "gex_state": "negative", "iv": 0.40},
    }
    cfg = demo_config.get(ticker.upper(), {"price": 100.0, "gex_state": "neutral", "iv": 0.30})
    S = cfg["price"]
    iv = cfg["iv"]
    gex_sign = {"positive": 1, "negative": -1, "neutral": 0}[cfg["gex_state"]]

    chain: List[Dict] = []
    for i in range(-10, 11):
        strike = round(S + i * 5, 1)
        if strike <= 0:
            continue
        dist = abs(strike - S)
        oi_base = max(0, int(5000 * (1 - dist / 50)))
        oi_call = oi_base if gex_sign >= 0 else int(oi_base * 0.6)
        oi_put  = oi_base if gex_sign <= 0 else int(oi_base * 0.6)
        chain.append({
            "strike": strike,
            "oi_call": oi_call,
            "oi_put": oi_put,
            "iv_call": iv,
            "iv_put": iv + 0.02,
            "expiry": "demo",
        })
    return S, chain


# ── 主分析函数 ────────────────────────────────────────────────────

def analyze_gamma(
    ticker: str,
    spot_price: Optional[float] = None,
    days_to_expiry: int = 7,
    direction_factor: int = -1,
    adv: float = 1e8,
    max_expiry: int = 4,
) -> Dict:
    """
    完整的 Gamma 市场状态分析

    Args:
        ticker: 标的代码（如 'SPY', 'QQQ', 'AAPL'）
        spot_price: 当前价格（None 则自动获取）
        days_to_expiry: 分析到期时间（天）
        direction_factor: 散户方向
            -1 = 散户净买入期权（做市商 Short Gamma，最常见）
            +1 = 散户净卖出期权（做市商 Long Gamma）
        adv: 标的平均日成交量（股）
        max_expiry: 最多取最近 N 个到期日

    Returns:
        结果字典，含 direction / confidence / reasoning / meta
    """
    warnings = []

    # 1. 获取数据（失败则切换演示模式）
    options_chain, fetched_price, fetch_warnings = fetch_option_chain_yf(ticker, max_expiry)
    warnings.extend(fetch_warnings)

    # 2. 确定 S（价格）
    if spot_price is not None:
        S = spot_price
    else:
        S = fetched_price

    # 3. 限流或数据为空时切换演示模式
    demo_mode = (S <= 0 or not options_chain)
    if demo_mode:
        warnings.append(f"yfinance 不可用，切换演示模式（模拟数据）")
        demo_price, demo_chain = _get_demo_data(ticker)
        if S <= 0:
            S = demo_price
        options_chain = demo_chain
        warnings.append(f"演示模式：使用 {ticker} 的历史模拟数据，GEX 值为近似值")

    if S <= 0:
        return _build_result(
            direction="neutral",
            confidence=0.1,
            reasoning=f"无法获取 {ticker} 价格，GEX 分析终止",
            signals=[],
            meta={"warnings": warnings + ["价格数据缺失"]},
            needs_human_review=True,
        )

    if not options_chain:
        return _build_result(
            direction="neutral",
            confidence=0.1,
            reasoning=f"{ticker} 未获取到期权链数据（可能无期权）",
            signals=[],
            meta={"warnings": warnings + ["期权链数据为空"]},
            needs_human_review=True,
        )

    # 4. 计算 T（到期时间，年）
    T = max(days_to_expiry / 365.0, 1 / 365.0)

    # 5. 计算 Total GEX
    total_gex, valid_contracts, details = calc_total_gex(
        options_chain, S, T, r=0.05, direction=direction_factor,
    )

    # 6. 判断状态
    gamma_state = judge_regime(total_gex)
    direction = judge_direction(total_gex)

    # 7. 对冲压力
    hedge_ratio, risk_level = calc_hedge_pressure(total_gex, adv)

    # 8. 置信度
    confidence = _calc_confidence(valid_contracts, hedge_ratio, gamma_state)

    # 9. 构建 reasoning
    reasoning = (
        f"{ticker} 总 GEX = ${total_gex:,.0f}，"
        f"Gamma 状态：{gamma_state}，"
        f"做市商对冲行为：{'高抛低吸（稳定）' if gamma_state == 'positive' else '追涨杀跌（放大波动）'}，"
        f"对冲压力占 ADV 约 {hedge_ratio:.1%}，"
        f"风险等级：{risk_level}。"
    )

    signals = []
    if gamma_state == "positive":
        signals.append("Long Gamma Regime")
        signals.append("Volatility Suppression")
    else:
        signals.append("Short Gamma Regime")
        signals.append("Volatility Expansion Risk")

    meta = {
        "gamma_state": gamma_state,
        "total_gex": total_gex,
        "hedge_ratio": hedge_ratio,
        "risk_level": risk_level,
        "valid_contracts": valid_contracts,
        "spot_price": S,
        "t_days": days_to_expiry,
        "direction_factor": direction_factor,
        "warnings": warnings,
        "demo_mode": demo_mode,
    }

    return _build_result(
        direction=direction,
        confidence=confidence,
        reasoning=reasoning,
        signals=signals,
        meta=meta,
        needs_human_review=(confidence < 0.4 or not options_chain),
    )


def _calc_confidence(valid_contracts: int, hedge_ratio: float, gamma_state: str) -> float:
    """计算置信度"""
    base = 0.3
    if valid_contracts >= 50:
        base += 0.3
    elif valid_contracts >= 20:
        base += 0.2
    elif valid_contracts >= 10:
        base += 0.1

    if hedge_ratio >= 0.15:
        base += 0.2
    elif hedge_ratio >= 0.05:
        base += 0.1

    if gamma_state != "neutral":
        base += 0.1

    return min(round(base, 2), 0.85)


def _build_result(
    direction: str,
    confidence: float,
    reasoning: str,
    signals: List[str],
    meta: Dict,
    needs_human_review: bool,
) -> Dict:
    return {
        "direction": direction,
        "confidence": confidence,
        "reasoning": reasoning,
        "signals": signals,
        "meta": {
            **meta,
            "needs_human_review": needs_human_review,
        },
    }


# ── 命令行直接运行 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    test_tickers = ["SPY", "QQQ", "AAPL"]
    if len(sys.argv) > 1:
        test_tickers = sys.argv[1:]

    for ticker in test_tickers:
        print(f"\n{'=' * 50}")
        print(f"分析标的：{ticker}")
        result = analyze_gamma(ticker)
        print(f"direction   : {result['direction']}")
        print(f"confidence  : {result['confidence']:.2f}")
        print(f"reasoning   : {result['reasoning']}")
        print(f"signals     : {result['signals']}")
        gex = result.get("meta", {}).get("total_gex", 0)
        print(f"Total GEX   : ${gex:,.0f}")
        print(f"risk_level  : {result.get('meta', {}).get('risk_level', 'N/A')}")
        print(f"gamma_state : {result.get('meta', {}).get('gamma_state', 'N/A')}")
        print(f"demo_mode   : {result.get('meta', {}).get('demo_mode', False)}")
