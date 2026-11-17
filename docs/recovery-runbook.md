# 本地研究备份与恢复

备份选择明确的行情快照和研究结果，保存它们引用的原始批次、标准化行情、计算输入和结果数组。不会复制整个数据目录、凭据或账户文件；任务记录按白名单导出，不复制任务数据库。备份含研究原料，仅供本机私有保存，不放入公开仓库。

备份前在数据中心记下行情 `snapshot_id`，在实验记录取得研究 `task_id`。可重复传入多个 `--snapshot` 和 `--result`，至少选择一项：

```powershell
./.venv/Scripts/python.exe -m portfolio_app.backup_service create --root output --target D:/ResearchBackups/checkpoint-01 --snapshot snapshot-完整身份 --result 研究身份
```

目标必须是新目录，与源目录互不包含。备份逐文件核对内容，超过默认2 GB预算会停止；不会留下已发布的半成品。备份清单保留引用范围、文件校验值与私有属性。

财务、ETF和转债观察批次也可单独选择。分别重复传入 `--financial batch-完整身份`、`--etf batch-完整身份`、`--convertible batch-完整身份`；可以与行情/结果一起备份，也可以只备份观察批次。例如：

```powershell
./.venv/Scripts/python.exe -m portfolio_app.backup_service create --root output --target D:/ResearchBackups/checkpoint-02 --financial batch-财务身份 --etf batch-基金身份 --convertible batch-转债身份
```

恢复保留原始文件字节和批次身份，只重建索引。不会将读取后的表重新编码为新文件；相同数值经过再次编码，文件身份也可能不同。旧版仅含行情与结果的备份仍可恢复。

恢复到一个尚不存在的目录：

```powershell
./.venv/Scripts/python.exe -m portfolio_app.backup_service restore --source D:/ResearchBackups/checkpoint-01 --target D:/ResearchRestore/checkpoint-01
```

恢复前检查每个文件，恢复后重新验证快照及结果，再由不可变文件重建索引。当前行情指针选择备份中该数据集最高版本；需要其他保留版时在数据中心显式回退。原损坏数据库与已有工作目录不会被覆盖。

核对完成后，将 `PORTFOLIO_STATE_DIR` 设置为恢复目录，重新启动应用。到数据中心检查范围和版本，再在实验记录打开原研究，选择“重新计算并核对”。算法与依赖版本不同会停止复算；恢复文件本身不会升级计算口径。

需要连同自选、最近访问、保存筛选和任务记录一起恢复时，在创建命令添加 `--include-user-state`。也可以只备份用户状态，不选择行情或结果；但保存筛选引用的快照必须一同选择，否则创建会停止。损坏的自选或筛选文件会报错，不会悄悄清空后备份。

任务历史最多1000条，失败仅保存错误分类和诊断编号。原运行中任务恢复为“已中断”，不会自动重新执行；成功任务仅在结果包也被选中时保留结果引用。未选中的结果不会因任务列表存在而被宣称已恢复。自选、筛选和任务快照在创建后逐文件校验。

本入口不恢复系统计划任务或未选中的观察资料。凭据继续单独配置。源数据授权同样适用于备份，来源可获取不代表可以再次分发。

2026-11-17恢复演练：1个真实行情快照、16个研究结果包、1条保存筛选及15条任务记录，在新目录恢复后逐条导出的用户状态一致；保存筛选使用原快照复算一致。该实际目录没有自选，自选/最近访问通过独立样本验证。修复任务数据库连接释放后，当前计算版本已改变：旧结果仍可读，旧版本复算需原版本代码，不改写历史版本身份。
