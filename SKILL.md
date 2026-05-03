# gamma_market_state_analyzer

**name:** gamma_market_state_analyzer  
**description:** 模拟高盛交易员逻辑，基于期权净伽马敞口（Net GEX）评估做市商对冲压力及其对市场波动的反作用。  
**owner_group:** 专家2组（指标）  
**domain:** risk  
**status:** active  
**version:** 1.1  

---

## 交易商伽马市场状态分析器

### 1. 适用范围

本 Skill 用于分析期权做市商（Market Maker）在特定标的（如 SPX 指数、个股）上的对冲行为如何平抑或放大市场波动。  

核心逻辑：做市商为维持风险中性，需根据股价变动反向或同向买卖正股。  

适用场景：财报季、期权到期日前后、波动率异常变动期。  

---

### 2. 输入材料要求

#### 2.1 必填输入

- 标的数据：当前价格 ($S$)、预期价格变动幅度  
- 期权链数据：每个行权价的持仓量（OI）、成交量（Volume）、隐含波动率 ($\sigma$)、剩余到期时间 ($T$)  
- 方向因子：散户买入期权（做市商 -1）或散户卖出期权（做市商 +1）  

#### 2.2 缺失处理

若缺少 $\sigma$ 或 $T$，必须输出：
- direction: neutral  
- needs_human_review: true  
并在 meta.uncertainties 中记录  

---

### 3. 量化逻辑参考

**Gamma 计算公式：**

$$
\Gamma = \frac{\phi(d_1)}{S \cdot \sigma \cdot \sqrt{T}}
$$

**总 GEX 计算：**

$$
\text{Total GEX} = \sum (\text{持仓量} \times \text{合约单位} \times \Gamma) \times \text{方向因子}
$$

---

### 4. 判断规则与证据链

#### 规则 1：敞口正负判断（Regime Identification）

**正伽马状态 (Long Gamma)：**

- 指标：Total GEX > 0（常见于散户卖出备兑看涨期权）  
- 行为：做市商“高抛低吸”（涨卖跌买）  
- 结论：direction = bullish 或 neutral，市场趋于震荡稳定  

**负伽马状态 (Short Gamma)：**

- 指标：Total GEX < 0（常见于散户大量买入期权）  
- 行为：做市商“追涨杀跌”（涨买跌卖）  
- 结论：direction = bearish，市场易出现单边行情  

---

#### 规则 2：对冲压力评估（Hedge Pressure）

- 对冲股数估算：

$$
\text{Hedge Shares} \approx \text{Total GEX} \times \Delta S
$$

- 阈值：若对冲量占标的日均成交量（ADV）20%以上 → risk_level = high  

---

#### 规则 3：行情形态验证

- Positive Gamma：横盘、缩量、波动率下降  
- Negative Gamma：单边走势、跳空、期权成交量激增  

---

### 5. 标准输出 (JSON)

```json
{
  "direction": "bullish | bearish | neutral",
  "confidence": 0.0,
  "reasoning": "结合GEX正负与做市商行为的详细推导",
  "signals": ["Long Gamma Regime", "Volatility Suppression"],
  "source": "gamma_market_state_analyzer",
  "signal_type": "risk",
  "stock_code": "",
  "meta": {
    "gamma_state": "positive | negative",
    "hedge_action": "Buy low sell high | Chase trend",
    "risk_level": "low | medium | high",
    "key_findings": ["阐述主要发现"],
    "evidence": ["列出支撑结论的期权持仓或波动率数据点"],
    "uncertainties": [],
    "needs_human_review": false
  }
}
```
