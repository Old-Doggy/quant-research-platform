# V2运行、更新与迁移

开发分支尚未发布。当前交付和缺项见[状态报告](status-v2.md)，真实源范围见[接口记录](provider-coverage.md)。

## 安装与启动

使用Python 3.12或3.13，在仓库根目录创建独立环境，安装`requirements.txt`，从`streamlit_app.py`启动。完整命令见[README](../README.md)。需要运行测试时安装`requirements-dev.txt`；需要免费采集时另外安装`requirements-providers.txt`。

`portfolio_app/local_app.py`是页面模块，正式入口负责包导入。不要将其直接作为部署启动文件。系统不要求预先复制原研究目录或真实行情；没有接口凭据时使用合成示例。

## 独立更新

在数据中心选择来源、证券与区间后更新。页面以外可创建本机JSON请求，例如`output/update-request.json`：

```json
{
  "root": "output/market_service",
  "symbols": ["600000.SH", "000001.SZ"],
  "start": "2026-11-02",
  "end": "2026-11-13",
  "dataset_id": "free-a-daily"
}
```

从仓库根目录运行：

```powershell
./.venv/Scripts/python.exe -m portfolio_app.update_cli --request output/update-request.json --result output/update-result.json
```

免费请求限1–20只沪深股票，区间不超过366天。结果文件保存发布状态、计划身份或错误分类；未成功时不替换可用快照。失败计划可用`{"root":"output/market_service","resume_plan":"原计划身份"}`重试，不能同时改写原计划范围。新数据仍需独立检查单位、覆盖与来源；已发布浏览快照不代表研究数据已合格。

需要每天补抓时，将请求中的`end`去掉，添加`"schedule":"daily_raw"`，并将`root`设为本机状态目录下`market_service`的绝对路径。更新器以北京时间判断收盘日期并记录已完成日期；固定起点超过一年后会超范围，长期滚动分区仍待实现。

`scripts/register_update_task.ps1`默认仅显示说明；显式传入`-Enable -RequestFile 请求绝对路径 -ResultFile 结果绝对路径`才会安装系统任务。当前没有启用系统任务，没有完成设备休眠/唤醒实测，也没有10个真实交易日观察结论。手动重复运行、合成重放不能替代这些验收。

## 升级前保存

1. 停止提交新任务，等待正在运行的任务完成或取消。
2. 使用[备份恢复](recovery-runbook.md)选择行情、结果、观察批次；需要时添加用户状态。
3. 记下当前代码提交与Python/依赖版本，保留原虚拟环境及状态目录。
4. 在另一个目录恢复备份，检查行情范围、用户记录及历史结果。
5. 使用候选代码和独立环境打开恢复目录，再运行对应版本允许的复算。

迁移依靠原始不可变文件重建索引，不直接复制损坏数据库，也不重新编码原始Parquet。旧结果继续保留原计算版本；版本不同不能通过改清单强行复算。

## 回退

保留旧稳定版目录和升级前状态副本。候选版失败时停止候选服务，用原代码、原依赖环境及原状态目录启动。不要让两个版本同时写同一状态目录，不将新结果覆盖到旧结果包。

回退后先检查七个工作区与选定结果，再决定是否重新尝试升级。公开发布前还需完成[发布检查](release-checklist-v2.md)；这份说明不表示新版已经发布。
