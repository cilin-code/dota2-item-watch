# 饰品监测 — Dota 2 Steam 市场饰品价格趋势监测与推荐购买分析系统

基于 Steam Community Market 的 Dota 2 饰品价格监测工具，通过多维度数据分析（波动率、趋势、价格位置、技术指标、盘口压力、税率影响），自动评分并推荐适合当前买入的饰品。

---

## 功能

- **数据抓取**：从 Steam Market 获取热门饰品价格和历史数据，支持前 300 名热门饰品
- **更新准入策略**：20 分以下饰品进入冷却，Steam 热门命中、收藏、买入记录和预警会绕过冷却
- **多维度评分**：基于历史分位、近期分位、趋势状态、成交量、波动率、卖压等指标综合评分
- **分段税率**：售价 >= ¥1.60 时按 13% 计算，低于 ¥1.60 时考虑 Steam 最低费用，自动调整保本倍数
- **推荐系统**：S/A/B/C/D/E 六档评分等级，适配当前较保守的评分尺度
- **饰品管理**：搜索、添加、删除、关注饰品、价格预警、买入记录
- **数据维护**：支持清空全部本地饰品数据，便于重新构建监控列表
- **实时进度**：更新数据时显示实时进度动画，并展示热门命中、冷却跳过等更新状态
- **首屏加载优化**：主页优先加载高评分饰品，剩余数据后台分页补齐
- **详情页**：单个饰品的历史价格走势图 + 完整分析报告（日均走势 / 明细走势 / 周期分析）
- **评分回测**：按历史日级信号回放评分，统计 7 日后收益、胜率和样本列表
- **价格校验**：现价以 priceoverview quote 为准，listing 订单簿用于记录差异和卖压分析
- **价格语义隔离**：quote 只用于现价，历史走势和日汇总只使用成交数据
- **快捷操作**：名称栏支持跳转 Steam 和复制名称

---

## 快速开始

### 环境要求

- Python 3.13+
- Windows / macOS / Linux

### 安装

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 启动

```bash
# Windows 双击:
start.bat

# 或命令行启动：
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

浏览器访问 **http://localhost:8000**

### 测试

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.venv\Scripts\python.exe -m compileall backend tests
```

---

## 项目结构

```text
饰品监测/
├── backend/                  # FastAPI 后端
│   ├── main.py               # API 路由定义
│   ├── engine.py              # 评分推荐引擎（核心逻辑）
│   ├── database.py            # SQLite 数据库层
│   ├── steam_update.py        # Steam 批量更新、热门发现、SSE 进度
│   ├── update_policy.py       # 低分饰品更新准入与冷却策略
│   ├── price_semantics.py     # quote / trade / orderbook / 税率语义
│   ├── display.py             # CMD 对齐与价格显示辅助
│   ├── config.py              # 配置（Steam 参数、服务参数）
│   ├── names.py               # 饰品中英文名称映射表
│   └── scrapers/              # Steam 数据抓取
│       ├── __init__.py
│       ├── base.py            # 异步 HTTP 抓取器基类
│       └── steam.py           # Steam Market API 抓取器
├── frontend/                  # 前端页面
│   ├── index.html             # 主页（饰品列表 + 工具栏）
│   ├── detail.html            # 饰品详情页（走势图 + 分析）
│   ├── chart.umd.min.js       # Chart.js（图表库）
│   └── icon.ico               # 网站图标
├── docs/                      # 文档
│   ├── scoring-strategy.md    # 评分推荐策略完整文档
│   ├── steam-dota2-recommender-spec.md  # 推荐系统设计规格
│   ├── steam-dota2-agent-exec-spec.md   # 执行规格说明
│   └── github-ssh-over-443.md # GitHub SSH 443 连接配置记录
├── tests/                     # unittest 测试
├── data.db                    # SQLite 数据库（自动生成，已被 .gitignore 忽略）
├── requirements.txt           # Python 依赖
├── start.bat                  # Windows 一键启动脚本
├── start.ps1                  # 启动实现：关闭旧窗口、占用端口后重启
├── .gitignore
└── README.md
```

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/items | 所有饰品分析结果（支持 min_score 筛选） |
| GET | /api/items/search | 搜索 Steam 市场饰品 |
| GET | /api/items/favorites | 获取已关注的饰品 ID 列表 |
| GET | /api/items/{id} | 单个饰品详细分析 + 历史走势 |
| GET | /api/items/{id}/history | 历史价格数据 |
| GET | /api/items/{id}/periodic | 周期性价格分析 |
| POST | /api/items | 添加饰品到监控列表 |
| DELETE | /api/items/{id} | 删除饰品及其数据 |
| PUT | /api/items/{id}/favorite | 切换关注状态 |
| PUT | /api/items/{id}/alert | 设置价格预警 |
| GET | /api/items/{id}/alert | 获取单个饰品预警 |
| DELETE | /api/items/{id}/alert | 删除单个饰品预警 |
| GET | /api/alerts/all | 获取全部预警 |
| GET | /api/alerts/triggered | 获取已触发预警 |
| POST | /api/items/{id}/purchase | 记录买入 |
| GET | /api/purchases | 买入记录与盈亏 |
| DELETE | /api/purchases/{id} | 删除买入记录 |
| GET | /api/recommendations | 推荐购买列表 |
| GET | /api/backtest | 评分回测 |
| GET | /api/fetch | 批量更新 Steam 数据（SSE 流式） |
| GET | /api/fetch/{id} | 单个饰品刷新 |
| GET | /api/update-status | 当前批量更新状态 |
| GET | /api/stats | 监控统计（饰品数、最近更新等） |
| POST | /api/admin/clear-data | 清空全部本地数据 |
| POST | /api/fix-names | 修复缺少中文名的饰品 |

---

## 评分系统概要

系统对每个饰品从以下维度进行评分：

| 维度 | 分值范围 | 说明 |
|------|----------|------|
| 价格位置 | -20 ~ +25 | 当前价在历史分布中的分位数，低位会显示百分比 |
| 近期确认 | 0 ~ +8 | 当前价在近 14 天区间中的位置 |
| 走势状态 | -12 ~ +10 | 横盘稳定、趋势向上、持续下跌 |
| 成交量 | -6 ~ +12 | 24h 成交量反映的流动性 |
| 波动风险 | 0 ~ -10 | CV 偏高时扣分 |
| 卖压风险 | 0 ~ -6 | 当前卖单压力偏高时扣分 |
| 冷门风险 | 0 ~ -5 | THIN 饰品更保守 |
| 前置拒绝 | 0 ~ -25 | 样本不足、无近期成交量、趋势持续下跌等情况 |

详见 [评分推荐策略文档](docs/scoring-strategy.md)。

---

## 更新准入策略

批量更新仍由用户手动触发，但系统会在执行时判断低分饰品是否值得本轮更新。`update_after` 的含义是“早于这个时间，手动批量更新也会跳过”，不是后台自动任务。

| 分数 | 批量更新策略 |
|------|--------------|
| >= 20 | 不限制 |
| 15 ~ 19.9 | 12 小时冷却 |
| 10 ~ 14.9 | 24 小时冷却 |
| 5 ~ 9.9 | 72 小时冷却 |
| < 5 | 168 小时冷却 |

以下情况会绕过冷却并正常更新：

- 本轮 Steam 热门/活跃搜索命中
- 用户收藏
- 有买入记录
- 有启用中的价格预警
- 用户在当前显示范围或详情页手动指定刷新

更新过程中会在 CMD 和前端完成状态里显示“热门命中”“冷却跳过”“热门绕过”等统计。

---

## 推荐等级

| 分数 | 等级 | 含义 |
|------|------|------|
| >= 120 | S | 极强信号 |
| 100 ~ 119 | A | 强信号 |
| 85 ~ 99 | B | 较好信号 |
| 70 ~ 84 | C | 可观察信号 |
| 55 ~ 69 | D | 信号偏弱 |
| < 55 | E | 风险或数据不足 |

---

## 现价与订单簿校验

主页“现价”来自 Steam `priceoverview` 的最新 quote，也就是 Steam 摘要接口返回的当前在售最低价。listing 页面解析出的订单簿最低卖单只用于交叉观察、卖压分析和日志提示，不再覆盖现价：

- quote 明显低于订单簿最低价超过 2%：仍保存 priceoverview quote，并在日志标记 `priceoverview_primary_low`
- quote 明显高于订单簿最低价超过 3%：仍保存 priceoverview quote，并在日志标记 `priceoverview_primary_high`
- 差异在正常范围内：保存 quote，状态为 `ok`
- 无订单簿时：保存 quote，状态为 `unchecked`

历史走势图和日汇总只使用历史成交数据，不使用 quote。

---

## 周期分析

详情页周期分析基于历史成交日汇总和成交快照，不使用 quote。当前输出包括：

- 波动间隔：相邻波峰/波谷拐点之间的平均天数
- 波峰周期：历史高点之间的平均间隔
- 波谷周期：历史低点之间的平均间隔
- 日内价差：按小时成交均价估算的买卖时间差异
- 买入/卖出时间：历史成交均价较低或较高的小时段
- 周内均价规律：按周一到周日聚合成交均价

这些结果是历史统计信号，不代表未来价格一定按相同节奏波动。

---

## 回测机制

评分回测使用历史成交价按日回放：

1. 每个饰品每天最多取最后一条成交记录作为检查点。
2. 只用当日之前的数据计算评分，避免使用未来信息。
3. 当评分达到阈值时记录一次信号。
4. 查找默认 7 天后的成交价并计算收益。
5. 输出信号数、胜率、平均收益、最好/最差收益和样本列表。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI + uvicorn |
| 数据库 | SQLite + aiosqlite |
| HTTP 客户端 | httpx（异步） |
| 前端图表 | Chart.js v4 |
| 前端样式 | 原生 CSS（科技风 + 小清新暗色主题） |
| Python | 3.13 |

---

## 注意事项

- Steam API 有请求频率限制，批量更新默认 3.0 秒/次，前端可切换为 1.0 / 1.5 / 2.0 / 3.0 秒
- 历史价格数据从 Steam listing 页面解析；Steam 通常只提供最近约 90 天数据，本地数据库会随每日更新继续累积，详情页最多展示 360 天
- 对于日成交量极低的饰品，系统会标注 THIN（冷门）并使用更保守的评分标准
- 低于 ¥1.60 的饰品会被 Steam 最低费用显著影响，实际税率可能远超 13%
- 本项目的可见 CMD 窗口用于观察运行状态；再次启动 `start.bat` 会关闭上一次启动的窗口并重启 8000 端口服务

