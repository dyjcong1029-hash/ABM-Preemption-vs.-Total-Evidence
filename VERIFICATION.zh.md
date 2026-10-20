# 当前基线的完整重跑与验收

复现批次：2026-10-19。科学基准：GitHub提交`e105f6217db78222e72633a663871c070d630ed3`。

**完整重跑、重新分析及独立验收均已通过。** 本轮新生成全部12个原生批次；23个`models/`与`data/`科学文件保持上游字节，未增加科学机制或调整种子、先验、似然、预算和主体规则。

## 实际覆盖

| 检查对象 | 从实际报告提取的范围 | 结果 |
|---|---|---|
| 原生完整批次 | 12批；132,600次运行；1,932,600条导出记录 | 通过 |
| 逐轮原始输出 | 3,600次轨迹运行；1,803,600条状态 | 通过 |
| 科学文件 | 23个文件逐字节Git blob校验 | 保持不变 |
| 概率与处理规则 | 1,323项精确概率对照 | 通过 |
| 检查器变异测试 | 10项；来自实际测试日志 | 通过 |
| 原发布端点统计 | 388项独立统计/一致性检查 | 通过 |
| 新运行端点比较 | 8组；含9,000个完整公开端点；最大绝对差7.1054274e-15 | 通过 |
| 完整逐轮回归 | 2组；601,200个配对时点；10,420,800次字段比较；最大绝对差7.1054274e-15 | 通过 |
| 独立校准复核 | 从120,000次新原生校准运行重计；13项原门槛 | 通过 |
| 原R分析检查 | 校准13项；实验0 36项；实验1 33项；实验2 21项 | 全部通过 |
| 发布表重建 | 13个共同公开CSV；最大数值差0 | 通过 |
| 额外原生边界夹具 | 40次运行；5,040条导出状态，另计于完整批次 | 通过 |

主实验共有7,000次运行；校准、共享开关对照和轨迹条件执行另列，不能把同一运行内的学生和时间点视为独立样本。上表数量和误差直接读取本次收据；未沿用此前小批验收的覆盖结论。

## 证据与复现

- [最终证据索引](verification/full_reproduction_2026_10_19/index.json)
- [完整原生管线和命令](verification/full_reproduction_2026_10_19/pipeline.json)
- [独立全量验收](verification/full_reproduction_2026_10_19/postflight/full_reproduction_verification.json)
- [新原始输出的R分析收据](verification/full_reproduction_2026_10_19/analysis/analysis_receipt.json)
- [原始批次哈希与本地归档](verification/full_reproduction_2026_10_19/raw_batches.json)
- [完整本地ZIP成员哈希](verification/full_reproduction_2026_10_19/archive_member_manifest.json)
- [12批原生provenance，gzip JSON](verification/full_reproduction_2026_10_19/native_provenance.json.gz)
- [恢复图布局修正记录](verification/full_reproduction_2026_10_19/figure_layout/receipt.json)

完整原始CSV、原生诊断、全部R输出和日志保存在经过CRC及逐成员SHA256核验的本地ZIP。大原始轨迹不进入Git；没有远程下载链接。仓库发布精简但可核查的收据、原验证CSV、小型结果表和哈希索引。本轮R生成10张PNG；这里不宣称重建图片全部逐像素或逐字节一致。恢复图已有的布局与标签修正保持为单列的展示改动。

```powershell
.\run_all.ps1 verify
.\run_all.ps1 reproduce -Threads 4 -OutputRoot results\my_fresh_reproduction
```

运行及依赖见[复现说明](REPRODUCIBILITY.md)。实际R版本：`Rscript (R) version 4.5.3 (2026-03-11)`。原生动态测试使用收据记录的NetLogo环境；其他操作系统及手动GUI流程没有因此获得动态验收。

## 解释范围

本轮完善了可运行、可重现和可审计性，没有改动23个科学文件。原先的局部贝叶斯更新、Thompson选臂和一次证据基础替换仍是结论前提；本轮未新增静态机制对照、其他行动规则或完整社会贝叶斯推断实验。科学边界见[模型范围](docs/MODEL_SCOPE.zh.md)。
