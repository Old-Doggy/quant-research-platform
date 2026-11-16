# 本地研究备份与恢复

备份选择明确的行情快照和研究结果，保存它们引用的原始批次、标准化行情、计算输入和结果数组。不会复制整个数据目录、凭据、账户文件或任务数据库。备份含研究原料，仅供本机私有保存，不放入公开仓库。

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

本入口恢复选定行情、研究结果与三类观察批次，不恢复正在运行任务、系统计划任务、自选名单、筛选记录或未选中的观察资料。凭据继续单独配置。源数据授权同样适用于备份，来源可获取不代表可以再次分发。
