# 前端手工测试用例（风况分析 / 台风预测）

## 测试 1：台风预测（`typhoon_model`）

1. 前端模式选择：`台风预测`
2. 在输入框粘贴：

```text
请做台风预测并给出地图点，使用南海模型（SCS），lat=20.9339, lon=112.202, radius_km=100, year_start=1976, year_end=2025, wind_threshold_kt=50
```

3. 点击发送后，预期结果：

- 回复中出现“台风概率分析（SCS）”字样（或同义的 SCS 概率指标）
- 页面下方出现地图（Leaflet 地图）
- 地图上有目标点标记和半径圈
- 一般会看到 SCS 区域框（矩形）

## 测试 2：风况分析（`wind_analysis`）

1. 前端模式选择：`风况分析`
2. 在输入框粘贴：

```text
请对这个文件做风况分析并给出分析图与结论：C:/wind-agent/wind_data/wind condition @Akida.xlsx
```

3. 点击发送后，预期结果：

- 回复中出现风况分析结论（文字总结）
- 如果分析流程包含图像产出，会在结果区看到图像/画廊块
- 原始返回 JSON 中应包含风况分析相关结构化结果（`analysis` 或 `ui_blocks`）

## 排查建议（如果结果不对）

- 先点“健康检查”，确认后端可用
- 若台风预测没出图，检查输入是否包含 `lat/lon/radius_km`，并确认模式是“台风预测”
- 若风况分析无结果，先确认文件路径存在且可读：`C:/wind-agent/wind_data/wind condition @Akida.xlsx`
