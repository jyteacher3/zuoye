# gamma_market_state_analyzer Skill 提交包

## 文件清单

```
gamma_market_state_analyzer/
├── SKILL.md              ← 原始设计文档（未改动）
├── gamma_engine.py        ← GEX 计算引擎（可执行）
├── test_gamma_skill.py  ← 独立测试脚本（老师可直接运行）
└── README.md             ← 使用说明
```

## 快速验证

```bash
# 安装依赖
pip install yfinance

# 运行测试（会自动切换演示模式，无需 API Key）
python test_gamma_skill.py
```

## 设计说明

- **SKILL.md**：基于 Black-Scholes 的 Gamma 敞口分析框架，定义判断规则与输出规范
- **gamma_engine.py**：完整实现 GEX 计算、Regime 判断、风险等级评估
- **test_gamma_skill.py**：演示模式，无需期权数据源即可验证完整流程

## 与系统对接

本 Skill 可被 `agents/risk/agent.py`（RiskAgent）加载，
输出标准 `Signal`（direction/confidence/reasoning/meta），
直接参与 Orchestrator 仲裁博弈。
