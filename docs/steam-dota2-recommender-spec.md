# Steam Dota 2 饰品波动分析与推荐购买规格文档

> 本文档用于指导 Agent 实现一个 **Steam 平台 Dota 2 饰品监测系统**。  
> 目标是：通过分析 **Steam 上 Dota 2 饰品的历史价格波动、趋势、当前价格位置、盘口结构**，提取出“**推荐购买**”的饰品候选。  
> 本文档仅聚焦 **Steam 数据**，不包含 Buff、跨平台比价、跨平台下单等逻辑。

---

## 0. 项目目标

系统目标不是“预测未来价格”，而是筛选出**更可能适合当前买入**的 Dota 2 饰品。

推荐购买的定义应满足以下条件：

1. 历史价格样本足够
2. 价格波动率处于可接受范围
3. 趋势不是持续下跌
4. 当前价格未处于明显历史高位
5. 短期（近 14 天）价格未处于明显高位
6. 技术指标未出现明显异常暴涨/偏离
7. Steam 卖单盘口压力不过大
8. 系统能给出一个合理的“智能参考买入价/参考挂单价”

### 特别说明：低交易量饰品处理
Dota 2 饰品整体交易热度低于 CS2，很多有潜力的饰品日交易量可能仅为个位数。  
因此，系统不能仅凭“日交易量低”就直接排除饰品，而应该：

- 对低交易量饰品采用更保守的评估标准
- 保留进入推荐池的机会
- 额外标注 `low_volume_risk` / `low_sample_risk`
- 在趋势、价格位置、波动率上收紧阈值

---

## 1. 数据来源与范围

### 1.1 平台
- 只分析 **Steam Community Market**

### 1.2 游戏资产范围
- **Dota 2**

### 1.3 数据类型
系统需要至少获取以下三类数据：

#### A. 历史成交数据
建议字段：
- `timestamp`
- `price`
- `volume`（缺失时可默认 1）

#### B. 当前/最新成交价
建议字段：
- `current_price`
- `last_trade_price`

#### C. 当前卖单盘口（Orderbook）
建议字段：
- `sell_orders: list[{price, volume}]`
- 最好按 `price` 升序

#### D. 日成交量
建议字段：
- `daily_volume`

---

## 2. 推荐系统总体流程

推荐流程应分为以下阶段：

1. 数据采集
2. 数据清洗
3. 活跃度与流动性分类
4. 价格波动分析
5. 趋势分析
6. 当前价格位置分析
7. 技术指标辅助分析
8. Steam 盘口压力分析
9. 智能参考价计算
10. 综合推荐判定
11. 输出推荐结果

---

## 3. 数据清洗规则

### 3.1 使用 IQR 清洗
对历史价格序列 `P`：

1. 排序得到 `sorted(P)`
2. 计算：
   - `Q1 = percentile(sorted(P), 25)`
   - `Q3 = percentile(sorted(P), 75)`
   - `IQR = Q3 - Q1`
3. 计算保护缓冲：
   - `mean_price = mean(P)`
   - `min_buffer = max(0.5, mean_price * 0.05)`
   - `effective_iqr = max(IQR, min_buffer)`
4. 计算上下界：
   - `lower = Q1 - 1.5 * effective_iqr`
   - `upper = Q3 + 1.5 * effective_iqr`
5. 保留区间 `[lower, upper]` 内的价格作为 `clean_prices`

### 3.2 清洗失败兜底
如果清洗后为空：
- 先尝试裁剪首尾各 10%
- 若仍不足，使用原始数据

---

## 4. 成交活跃度与流动性分类

Dota 2 饰品不能简单照搬高热度市场规则，建议分为：

- `LIQUID`：流动性相对较好
- `THIN`：交易稀薄，但仍可能有潜力

### 4.1 样本数门槛
- 若 `count < 5`：直接拒绝
- 若 `5 <= count < 15`：标记为 `LOW_CONFIDENCE`，允许继续评估

### 4.2 日均成交量分层
建议：
- `daily_volume_threshold = 3`

规则：
- 若 `daily_volume >= daily_volume_threshold`：`LIQUID`
- 若 `0 < daily_volume < daily_volume_threshold`：`THIN`
- 若 `daily_volume == 0` 且无近期成交：拒绝

---

## 5. 核心指标 1：价格波动率（CV）

### 5.1 公式
- `avg = mean(clean_prices)`
- `stdev = stdev(clean_prices)`
- `cv = stdev / avg`

### 5.2 默认阈值
- `cv_threshold = 0.05`

### 5.3 价格区间自适应阈值
- 若 `ref_price <= 15`：`threshold = max(0.05, 0.08)`
- 若 `ref_price >= 100`：`threshold = min(0.05, 0.04)`
- 若 `15 < ref_price < 100`：
  - `ratio = (ref_price - 15) / 85`
  - `threshold = 0.08 - ratio * 0.04`

### 5.4 冷门品收紧
对于 `THIN`：
- `cv_threshold_for_thin = threshold * 0.8`

---

## 6. 核心指标 2：趋势分析（slope + R²）

### 6.1 样本
建议最近 7 天日均价。

### 6.2 slope
- `Sxx = sum(x^2) - (sum(x)^2) / n`
- `Sxy = sum(x*y) - (sum(x)*sum(y)) / n`
- `slope = Sxy / Sxx`

### 6.3 R²
- `intercept = mean(y) - slope * mean(x)`
- `y_hat_i = slope * x_i + intercept`
- `SS_res = sum((y_i - y_hat_i)^2)`
- `SS_tot = sum((y_i - mean(y))^2)`
- `R^2 = 1 - SS_res / SS_tot`

### 6.4 状态分类
- `R² > 0.6`：
  - `slope > 0` → `RISING`
  - else → `FALLING`
- else → `STABLE`

---

## 7. 不同趋势下的推荐规则

### 7.1 STABLE
推荐条件：
- `slope >= -0.005`
- `cv` 在阈值内

冷门品补充：
- `THIN` 且 `slope < 0`：建议拒绝

### 7.2 RISING
推荐条件：
- `R² > 0.8`
- `slope/ref_price <= 0.01`
- `cv` 在阈值内

冷门品补充：
- `THIN` 时 `R² > 0.85`

### 7.3 FALLING / UNKNOWN
直接拒绝。

---

## 8. 当前价格位置分析

### 8.1 历史分位数
- `price_percentile = (current - min) / (max - min)`

阈值：
- `RISING`：默认 > 0.5 拒绝
- 其他：默认 > 0.8 拒绝

冷门品收紧：
- `THIN + RISING`：> 0.4 拒绝
- `THIN + STABLE`：> 0.7 拒绝

### 8.2 近 14 天分位数
- `recent_percentile = (current - recent_min) / (recent_max - recent_min)`
- 阈值同上

---

## 9. 技术指标辅助过滤

### 9.1 EMA
- `alpha = 2 / (span + 1)`
- `EMA_t = price_t * alpha + EMA_{t-1} * (1 - alpha)`

建议计算：
- `EMA7`
- `EMA30`

### 9.2 布林带
- `ma30 = EMA30`
- `bb_stdev = stdev(daily_prices)`
- `min_band = ma30 * 0.02`
- `bb_upper = ma30 + max(2 * bb_stdev, min_band)`
- `bb_lower = ma30 - max(2 * bb_stdev, min_band)`

### 9.3 过滤规则
拒绝条件：
- `ma7 > bb_upper`
- `last_price > bb_upper`
- `last_price < bb_lower`

对 `THIN`：
- 如果样本不足，可降权
- 但建议仍保留 `last_price > bb_upper` 作为硬拒绝

---

## 10. Steam 卖单压力分析

### 10.1 基础卖压
取最低 5 档卖单：
- `base_pressure = sum(volumes) / daily_volume`

若 `daily_volume == 0`：
- `base_pressure = sum(volumes)`
- 若 `base_pressure > 15`：拒绝

### 10.2 动态价差阈值
- `price < 5`：`gap = max(0.10, price*0.08)`
- `price < 20`：`gap = max(0.30, price*0.05)`
- `price < 100`：`gap = max(1.0, price*0.03)`
- `price < 500`：`gap = max(5.0, price*0.02)`
- else：`gap = max(10.0, price*0.015)`

### 10.3 挂单墙修正
若检测到小墙：
- `wall_vol <= max(3, daily_volume * 0.15)`
- `pressure = base_pressure * 0.4`
else：
- `pressure = base_pressure`

### 10.4 阈值判断
- `LIQUID`：拒绝 `pressure > 2.0`
- `THIN`：拒绝 `pressure > 1.5`

---

## 11. Steam 智能参考价

### 11.1 计算步骤
1. 对 `sell_orders` 按 `price` 升序
2. 去掉首档极小挂单（数量 <= 3）
3. 累积前 N 档挂单量，直到达到 `wall_volume_threshold`
4. 如果价格跳跃超过动态阈值：
   - `smart_price = next_price - 0.01`
5. 否则：
   - `smart_price = lowest_price - 0.01`

### 11.2 冷门品调整
- `THIN` 时 `wall_volume_threshold = 10`

---

## 12. 综合推荐判定

### 12.1 硬条件
必须满足：
- `count >= 5`
- `daily_volume > 0`
- `cv` 在阈值内
- `status != FALLING`
- `status != UNKNOWN`
- `price_percentile` 在阈值内
- `recent_percentile` 在阈值内
- `last_price <= bb_upper`
- `pressure` 在阈值内
- `smart_price` 可计算

### 12.2 LIQUID 饰品
满足硬条件：
- `recommend = true`
- `volume_class = LIQUID`

### 12.3 THIN 饰品
满足硬条件：
- `recommend = true`
- `volume_class = THIN`
- `low_volume_risk = true`
- `confidence = MEDIUM`

### 12.4 低样本资产
若 `5 <= count < 15`：
- `recommend = true`
- `confidence = LOW`
- `low_sample_risk = true`

---

## 13. 推荐输出字段

建议输出：
- `name`
- `market_hash_name`
- `current_price`
- `daily_volume`
- `cv`
- `slope`
- `r_squared`
- `status`
- `volume_class`
- `price_percentile`
- `recent_percentile`
- `ma7`
- `ma30`
- `bb_upper`
- `bb_lower`
- `pressure`
- `smart_price`
- `recommend`
- `confidence`
- `low_volume_risk`
- `low_sample_risk`
- `reject_reasons`

---

## 14. 推荐默认参数

### 14.1 基础筛选
- `days = 30`
- `min_sample_count = 5`
- `low_confidence_sample_count = 15`
- `daily_volume_threshold = 3`

### 14.2 波动率
- `cv_threshold = 0.05`
- `cv_threshold_thin_factor = 0.8`

### 14.3 趋势
- `slope_days = 7`
- `r2_threshold = 0.6`
- `slope_stable_floor = -0.005`
- `r2_rising_threshold = 0.8`
- `r2_rising_threshold_thin = 0.85`
- `slope_pct_ceil = 0.01`

### 14.4 价格位置
- `price_percentile_ceil = 0.8`
- `price_percentile_ceil_rising = 0.5`
- `price_percentile_ceil_thin_stable = 0.7`
- `price_percentile_ceil_thin_rising = 0.4`

### 14.5 盘口
- `sell_pressure_threshold = 2.0`
- `sell_pressure_threshold_thin = 1.5`
- `sell_pressure_orders_n = 5`

### 14.6 智能定价
- `wall_volume_threshold = 20`
- `wall_volume_threshold_thin = 10`
- `max_ignore_volume = 4`
- `min_lowest_tier_volume = 3`
- `min_step = 0.01`

---

## 15. 面向 Agent 的实现建议

### 15.1 模块划分
建议拆成以下模块：

1. `steam_data.py`
2. `cleaner.py`
3. `metrics.py`
4. `orderbook.py`
5. `scorer.py`
6. `report.py`

### 15.2 推荐执行顺序
对每个饰品：

1. 拉取历史数据
2. 拉取/计算当前价
3. 拉取 Steam 卖单
4. IQR 清洗
5. 分类 LIQUID / THIN
6. 计算 cv
7. 计算 slope / R² / status
8. 计算 price_percentile / recent_percentile
9. 计算技术指标
10. 计算 pressure
11. 计算 smart_price
12. 输出 recommend / reject_reasons

---

## 16. 最小可用版本（MVP）

建议先实现这 8 个关键字段：

1. `cv`
2. `slope`
3. `r_squared`
4. `price_percentile`
5. `recent_percentile`
6. `pressure`
7. `smart_price`
8. `volume_class`

再加上：
- `recommend`
- `confidence`
- `reject_reasons`

即可形成可运行系统。

---

## 17. 最终总结

本系统用于分析 **Steam 上 Dota 2 饰品的价格波动曲线**，并筛选推荐购买饰品。  
由于 Dota 2 饰品交易热度普遍偏低，系统不能简单剔除低交易量资产，而应：

- 将其识别为 `THIN`
- 使用更保守的阈值
- 保留进入推荐池的机会
- 附加低交易量/低样本风险提示

只有在波动、趋势、价格位置、盘口压力、参考价等维度同时满足时，才推荐购买。
