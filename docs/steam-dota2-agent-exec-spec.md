# Agent 执行说明：Steam Dota 2 饰品推荐购买

## 任务
分析 Steam 上 Dota 2 饰品的历史价格波动与盘口数据，输出“推荐购买”饰品列表。

## 限制
- 只能使用 Steam 数据
- 不需要 Buff、跨平台比价、跨平台下单
- 最终目标是：给出推荐购买 + 参考价 + 原因

## 特殊说明
Dota 2 饰品交易热度通常低于 CS2，部分优质饰品日交易量可能仅为个位数。  
因此，系统**不能仅凭“日交易量低”就直接排除饰品**。  
对于低交易量饰品，应采用更保守的评估方式，而不是直接丢弃。

---

## 步骤 1：获取数据
对每个 Dota 2 饰品获取：
- 历史成交数据：`timestamp, price, volume`
- 当前价 / 最新价
- Steam 卖单：`[{price, volume}]`
- 日成交量（如有）

---

## 步骤 2：清洗历史价格
使用 IQR 清洗：
- Q1 = percentile(sorted(P), 25)
- Q3 = percentile(sorted(P), 75)
- IQR = Q3 - Q1
- min_buffer = max(0.5, mean(P)*0.05)
- effective_iqr = max(IQR, min_buffer)
- lower = Q1 - 1.5 * effective_iqr
- upper = Q3 + 1.5 * effective_iqr
- clean_prices = prices in [lower, upper]

如果清洗结果为空，降级为首尾各裁剪 10%。

---

## 步骤 3：交易活跃度与冷门品分类
Dota 2 不能直接照搬高热度市场的活跃度门槛。  
建议把饰品分为两类：

- `LIQUID`：流动性相对较好
- `THIN`：交易稀薄，但不一定没有价值

---

### 3.1 样本数门槛
如果历史样本点过少，信息不足，应拒绝或标为低置信度。

建议：
- 若 `count < 5`：直接拒绝
- 若 `5 <= count < 15`：标记为 `LOW_CONFIDENCE`，允许继续评估，但最终结果应降低优先级或附加风险提示

---

### 3.2 日均成交量分层
建议使用：
- `daily_volume_threshold = 3`

规则：
- 若 `daily_volume >= daily_volume_threshold`：`LIQUID`
- 若 `0 < daily_volume < daily_volume_threshold`：`THIN`

说明：
- `daily_volume == 0` 且没有近期成交的资产，仍然建议直接拒绝
- `THIN` 不等于不推荐，只是需要更保守

---

### 3.3 冷门品处理原则
对于 `THIN` 饰品：
- 仍然允许进入推荐流程
- 但在以下方面应更保守：
  - 波动率阈值更严格
  - 趋势要求更高
  - 当前价格位置阈值更严格
  - 卖压权重可以降低
  - 最终建议加上 `low_volume_risk`

---

## 步骤 4：计算波动率
- avg = mean(clean_prices)
- stdev = stdev(clean_prices)
- cv = stdev / avg

自适应阈值：
- ref_price = current_price or avg
- if ref_price <= 15: threshold = max(0.05, 0.08)
- elif ref_price >= 100: threshold = min(0.05, 0.04)
- else: threshold = 0.08 - ((ref_price-15)/85)*0.04

冷门品收紧规则：
- 若状态为 `THIN`
  - `cv_threshold_for_thin = threshold * 0.8`
  - 后续使用该收紧阈值判断

拒绝条件：
- LIQUID：cv > threshold
- THIN：cv > cv_threshold_for_thin

---

## 步骤 5：趋势分析
使用最近 7 天日均价，计算：
- slope
- R²

分类：
- 若 R² > 0.6：
  - slope > 0 → RISING
  - else → FALLING
- else：
  - STABLE

---

## 步骤 6：按趋势状态判断
### STABLE
拒绝条件：
- slope < -0.005
- cv > 对应阈值
- 若 `THIN`：
  - slope < 0 时应更谨慎，建议直接拒绝

### RISING
拒绝条件：
- R² <= 0.8
- slope/ref_price > 0.01
- cv > 对应阈值

补充说明：
- 对 `THIN` 资产：
  - `r2_rising_threshold_for_thin = 0.85`
  - 若 `R² <= 0.85`，不推荐

### FALLING / UNKNOWN
直接拒绝。

---

## 步骤 7：当前价格位置
### 历史分位数
- price_percentile = (current - min) / (max - min)

默认阈值：
- RISING：> 0.5 拒绝
- 其他状态：> 0.8 拒绝

冷门品收紧：
- THIN + RISING：> 0.4 拒绝
- THIN + STABLE：> 0.7 拒绝

### 近 14 天分位数
- recent_percentile = (current - recent_min) / (recent_max - recent_min)

拒绝条件与上面一致。

---

## 步骤 8：技术指标
计算：
- EMA7
- EMA30
- bb_upper = ma30 + max(2*stdev, ma30*0.02)
- bb_lower = ma30 - max(2*stdev, ma30*0.02)

拒绝条件：
- ma7 > bb_upper
- last_price > bb_upper
- last_price < bb_lower

补充：
- 对 `THIN` 饰品，如果技术指标数据点不足，技术指标判定可降权，但建议仍保留 `last_price > bb_upper` 作为硬拒绝条件。

---

## 步骤 9：Steam 卖压
取前 5 档卖单：
- base_pressure = sum(volumes) / daily_volume

若 `daily_volume == 0`，建议改用：
- `base_pressure = sum(volumes)`
- 若 `base_pressure > 15`，直接拒绝

动态阈值：
- price < 5: gap=max(0.10, price*0.08)
- price < 20: gap=max(0.30, price*0.05)
- price < 100: gap=max(1.0, price*0.03)
- price < 500: gap=max(5.0, price*0.02)
- else: gap=max(10.0, price*0.015)

若检测到小墙：
- wall_vol <= max(3, daily_volume*0.15)
- pressure = base_pressure * 0.4
else：
- pressure = base_pressure

阈值判断：
- LIQUID：拒绝条件 `pressure > 2.0`
- THIN：拒绝条件 `pressure > 1.5`

---

## 步骤 10：智能参考价
1. sort sell_orders by price
2. drop lowest tier if volume <= 3
3. accumulate volume until >= 20
4. if price gap > dynamic threshold:
   - smart_price = next_price - 0.01
5. else:
   - smart_price = lowest_price - 0.01

补充：
- 对低交易量饰品，`wall_volume_threshold` 可降为 `10`
- 这样更容易生成合理参考价

---

## 步骤 11：最终推荐
### 必须满足的硬条件
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

---

### LIQUID 饰品
若上述条件满足：
- `recommend = true`
- `volume_class = LIQUID`

---

### THIN 饰品
若上述条件满足：
- `recommend = true`
- `volume_class = THIN`
- `low_volume_risk = true`
- `confidence = MEDIUM`

---

### LOW_CONFIDENCE
若 `5 <= count < 15`，但其他条件满足：
- `recommend = true`
- `confidence = LOW`
- `low_sample_risk = true`

---

## 输出字段
建议输出：
- name
- market_hash_name
- current_price
- daily_volume
- cv
- slope
- r_squared
- status
- volume_class
- price_percentile
- recent_percentile
- ma7
- ma30
- bb_upper
- bb_lower
- pressure
- smart_price
- recommend
- confidence
- low_volume_risk
- low_sample_risk
- reject_reasons

---

## 推荐默认参数
- `days = 30`
- `min_daily_trades = 3`
- `daily_volume_threshold = 3`
- `cv_threshold = 0.05`
- `cv_threshold_thin_factor = 0.8`
- `slope_days = 7`
- `r2_threshold = 0.6`
- `slope_stable_floor = -0.005`
- `r2_rising_threshold = 0.8`
- `r2_rising_threshold_thin = 0.85`
- `slope_pct_ceil = 0.01`
- `price_percentile_ceil = 0.8`
- `price_percentile_ceil_rising = 0.5`
- `price_percentile_ceil_thin_stable = 0.7`
- `price_percentile_ceil_thin_rising = 0.4`
- `sell_pressure_threshold = 2.0`
- `sell_pressure_threshold_thin = 1.5`
- `sell_pressure_orders_n = 5`
- `wall_volume_threshold = 20`
- `wall_volume_threshold_thin = 10`
- `max_ignore_volume = 4`
- `min_lowest_tier_volume = 3`
- `min_step = 0.01`

---

## 设计原则
1. Dota 2 很多饰品天然低交易量，不能一刀切剔除
2. 低交易量饰品可以推荐，但必须更保守
3. 对低交易量资产，应输出额外风险标签
4. 如果样本过少，应输出低置信度而不是直接拒绝
5. 保留 `reject_reasons`，以便下游 Agent / 用户理解结果
