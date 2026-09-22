# 周期工作台集成

原历史页面和数据保持原样。`assets/trading-workspace.js` 为首页添加私人工作台入口。

在每日复盘的 HTML 和 `site-data.json` 生成后执行：

```sh
python scripts/build-cycle-history.py
```

输出 `assets/cycle-history.json`，连同新增复盘一起提交。私人工作台从该公开资源读取历史表；离线时显示构建时快照和截至日期。个人答卷、仓位、盈亏、私有复盘保存在私人工作台，不进入本仓库。

抽取仅识别带完整日期的题材表。原始值、原始节奏标签、来源链接分别保留；未核、缺失值为 null。同日冲突优先当天原文，否则采用最新引用；差异单独保留。不要用情绪标签推算数值。
