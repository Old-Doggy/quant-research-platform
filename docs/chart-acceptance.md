# 精简范围图表验收

更新：2026-11-18（上海时间），应用候选`bc8d258`。**S12现有功能的工程验收通过；未因此认定不合格真实数据可用于回测。**

## 当前范围与证据

静态扫描64处：61处Plotly、1处正式K线、2处旧HTML图形嵌入。当前路由可达57处，另7处只保留定义，没有路由调用链；入口数不是图形变体数。七工作区与专有布局在1024/1280/1440/1920检查，按冻结计划复用共用布局证据；各族数值由计算/账本/快照测试与实际图/表/CSV核对共同覆盖。

只读选择器以手形、无可见插入符；真实搜索可输入。共享Plotly交互配置、14px图形文字、负值/未知/缺口不补零、下载保留全量均有检查。时间图按用途提供悬停、缩放/平移/重置；选择图保留键盘等价选择控件。静态指标图不强加无意义选择事件。

| 图表族 | 数据与图形核对 | 操作与布局证据 |
|---|---|---|
| 正式K线及旧看盘 | 两真实证券6条OHLC/成交量逐点；来源昨收缺失、周/月口径；300日长图指标预热及四预设；旧等权286共同会话/41行排除 | 三面板十字线/同范围、鼠标平移缩放、键盘全部/重置、四宽度；旧单股六页签/组合两图页与研究项目嵌入 |
| 数据覆盖/导入/观察 | 覆盖热图、价格、财务累计/单季/TTM及资产存量；两证券216项独立换算；ETF三批207行CSV与原观察及独立价格指数/回撤换算一致；转债价量/转股价 | 数据中心六页签四宽度；观察表格/图形、证券选择、财务单项和下载；来源空态不造图 |
| 市场概览/筛选 | 固定真实两证券散点与查询坐标；涨跌分布及筛选数量；图/表/下载同源 | 证券选择/筛选保存及重开；完整池发送、来源再次核验；缺真实行业/财务数据保持禁用 |
| 因子诊断/比较/排名策略 | Rank IC和平均排名、季度有效样本、换手/分组标签；缺相关性不变零；两类相关性与共同样本；80日排名策略净值/回撤/现金/暴露读同一账本 | IC实际点击与日期选择、季度图/表；矩阵点击与因子对选择；单/多因子及排名策略专有布局四宽度；执行设置确认有键盘操作 |
| 单股策略/固定时间诊断 | 300净值点/24成交事件及CSV；成本合计与原结果、时间切分和参数/负对照负值；独立窗不拼连续账户 | 事件点击/分页/选择，四主视图；验证三页签四宽度、参数和成本键盘选择、Space切表；缺财务资格不运行质量策略 |
| 组合 | 同账户现金/费用、出入金TWR与贡献；历史持仓/暴露日期；订单/拒单、流动性容量及极值/缺口采样 | 四主视图按需构图，日期/订单点击及选择、分页/表格/下载；1024–1920；真实成交额只作已有容量观察 |
| 实验/历史/运行核对 | 保存结果曲线、IC、最多4项比较、收益回撤散点，版本及原日期保留；ZIP恢复复算；旧实验300日净值复算一致 | 散点实际点击打开/下拉选择原结果；搜索/空态/损坏记录隔离；旧实验最终专属标题后四宽度复核；运行指标/变化表保留缺值 |
| 作品/看盘内研究项目 | 11历史曲线16224点与公开源SHA256及CSV一致；七模型42页签/21专属解释/8产物；28二级视图与成本/年度数据 | 模型/情景键盘选择、图/表/CSV；模型1/6/2实际图例隐藏恢复/缩放重置，嵌入四宽度；成本悬停/年度77日部分年斜纹；模型2/6原未通过状态保留 |

本批关键原始证据保存在本机`output/closeout/chart-final-acceptance.json`，逐静态位置列来源文件/函数、图表族、测试和浏览器证据。私人原始行情和截图日志不随公开仓库上传。数值容差沿用既有1e-12图/表/CSV或对应结果合同，不用视觉相似替代数据校验。

## 当前可达位置

下表按文件/函数登记源代码位置；行号可能随说明修改移动，以函数名检索。可达性来自路由及调用链审阅，运行图形按上述图表族验收，不把静态扫描标记当作浏览器通过。

| 文件 | 函数 | 静态位置数 | 结论 |
|---|---|---:|---|
| `portfolio_app/convertible_view.py` | `render_convertible_data` | 2 | 固定范围通过 |
| `portfolio_app/data_coverage_view.py` | `render_coverage` | 2 | 固定范围通过 |
| `portfolio_app/data_workspace.py` | `_render_import_workflow` | 1 | 固定范围通过 |
| `portfolio_app/etf_view.py` | `render_etf_data` | 1 | 固定范围通过 |
| `portfolio_app/experiment_catalog_view.py` | `render_experiment_scatter` | 1 | 固定范围通过 |
| `portfolio_app/experiment_view.py` | `render_experiments` | 1 | 固定范围通过 |
| `portfolio_app/factor_comparison_view.py` | `render_factor_comparison` | 2 | 固定范围通过 |
| `portfolio_app/factor_drilldown_view.py` | `render_ic_drilldown` | 3 | 固定范围通过 |
| `portfolio_app/factor_rank_strategy_view.py` | `render_factor_strategy` | 2 | 固定范围通过 |
| `portfolio_app/factor_research_view.py` | `_render_factor_research` | 2 | 固定范围通过 |
| `portfolio_app/financial_view.py` | `render_financial_data` | 1 | 固定范围通过 |
| `portfolio_app/local_app.py` | `_render_research_result_view` | 1 | 无当前路由调用 |
| `portfolio_app/local_app.py` | `render_strategy_showcase_card` | 2 | 无当前路由调用 |
| `portfolio_app/local_app.py` | `_render_pure_stock_view` | 1 | 固定范围通过 |
| `portfolio_app/local_app.py` | `render_model_evidence` | 1 | 无当前路由调用 |
| `portfolio_app/local_app.py` | `render_portfolio_home` | 1 | 无当前路由调用 |
| `portfolio_app/local_app.py` | `render_model_comparison` | 1 | 无当前路由调用 |
| `portfolio_app/local_app.py` | `render_data_analysis` | 1 | 无当前路由调用 |
| `portfolio_app/market_overview_view.py` | `render_market_overview` | 2 | 固定范围通过 |
| `portfolio_app/portfolio_capacity_view.py` | `render_capacity` | 1 | 固定范围通过 |
| `portfolio_app/portfolio_order_view.py` | `render_orders` | 1 | 固定范围通过 |
| `portfolio_app/portfolio_workspace_view.py` | `_render_portfolio_workspace` | 7 | 固定范围通过 |
| `portfolio_app/project_evidence_view.py` | `_render_comparison` | 1 | 固定范围通过 |
| `portfolio_app/project_evidence_view.py` | `render_project_evidence` | 1 | 固定范围通过 |
| `portfolio_app/research_audit_view.py` | `render_run_comparison` | 1 | 固定范围通过 |
| `portfolio_app/research_workspace.py` | `_render_single_strategy_result_payload` | 2 | 固定范围通过 |
| `portfolio_app/result_comparison_view.py` | `render_result_comparison` | 1 | 固定范围通过 |
| `portfolio_app/result_history_view.py` | `render_result_history` | 2 | 固定范围通过 |
| `portfolio_app/result_presentations.py` | `render_recent_quotes` | 1 | 固定范围通过 |
| `portfolio_app/result_presentations.py` | `render_validation_results` | 1 | 固定范围通过 |
| `portfolio_app/screener_view.py` | `render_screener` | 2 | 固定范围通过 |
| `portfolio_app/strategy_cost_view.py` | `render_strategy_costs` | 1 | 固定范围通过 |
| `portfolio_app/strategy_event_view.py` | `render_strategy_events` | 1 | 固定范围通过 |
| `portfolio_app/validation_view.py` | `render_timeline` | 1 | 固定范围通过 |
| `portfolio_app/validation_view.py` | `render_parameter_selection` | 1 | 固定范围通过 |
| `portfolio_app/watch_workspace.py` | `_render_watch_workspace_body` | 11 | 固定范围通过 |

## 适用边界

真实研究资格不足的图以明确合成输入验机制和布局；真实观察图以保存的真实批次验数据，授权作品以原历史汇总验曲线。三类证据不互相替代。全市场历史、完整财务PIT/行业、ETF/转债完整引擎等已延期或取消，不属于此S12通过结论。

有些浏览器自动化初版读到了切换前DOM，或按虚拟列表第11项/隐藏input点击失败；这些记录排除。旧实验图的前序“accepted”脚本仍读到运行比较旧图，其该行无效，由`legacy-experiment-final.txt`等待“已保存实验”专属标题后的300点/四宽度结果替代。其他图等待模型/系列身份、目标控件及calcdata后取证。没有为使脚本通过改写数据。

本次合格图冻结；后续只有数据/交互缺陷或共享样式变化才重验受影响项，不继续扩展图形种类。全量本地/干净归档/远端四组1053项均通过，真实连续运行仍1/10。当前总状态见[状态报告](status-v2.md)。

---

# 图表验收历史记录

以下保留各批检查当时的结论和待办；已补验项目以本文页首当前结论为准，取消/延期仍不是通过。

## 覆盖清单

运行 `python scripts/inventory_charts.py --output output/chart-inventory-v2.json` 可生成当前入口清单，包含源文件、函数、行号、图表输入、配置、选择事件。当前扫描为64个渲染入口：61个Plotly、1个正式K线组件、2个旧HTML嵌入。一个入口可能绘制多种图，部分旧入口未确认当前路由是否可达；这个数字不是图形总数，也不代表64个入口已验收。

| 范围 | 渲染入口 | 已有检查 | 剩余检查 |
|---|---:|---|---|
| 看盘及旧研究视图 | 11 | K线日期、三面板十字线、真实短行情、自选趋势 | 旧入口可达性、所有指标/事件/单位、长区间、全宽度键盘 |
| 数据覆盖及导入 | 3 | 覆盖图与导入质量用例 | 全源空态/故障及导出矩阵 |
| 财务、ETF、转债 | 4 | 真实三表/TTM、三基金观察、退市转债/转股价及表格切换 | 更多真实边界、专属数据与完整研究入口 |
| 市场概览、筛选 | 4 | 固定真实快照、选择证券、图/表/CSV同源 | 全市场、财务条件、行业与合格研究数据 |
| 因子研究、比较、排名策略 | 9 | IC日期联动、季度、因子热图/散点、保存复算 | 合格真实截面、全部图的逐数组/单位验收 |
| 单股策略 | 4 | 四主视图按需加载、净值/场景、买卖点击明细、300净值点/24事件/CSV核对、事件页四宽度 | 合格真实研究、财务模板及完整键盘/空态矩阵 |
| 组合 | 9 | 四视图、历史日期风险、分项贡献、订单点击/分页/拒单、容量图与表/缺值/真实成交额核算 | 真实事件/行业/完整容量集成、全宽度完整操作 |
| 实验、历史、比较、审计、结果呈现 | 8 | 多结果曲线、散点打开、ZIP导入复算、时间验证输出 | 所有类型恢复/故障、完整导出一致性 |
| 时间验证 | 2 | 300日时间条、真实点击参数热图、12项复算 | 完整交易钻取、参数探索与真实输入 |
| 作品及本地共享/旧展示入口 | 10 | 11条历史曲线日期/净值/回撤浏览器数组与源包SHA256一致，共16224点，七模型三类说明逐项打开 | 二级情景、表格/键盘/图内交互、旧入口清理 |

## 本批修正

- 15个旧Plotly入口补齐统一配置，缩放、平移、重置、响应式和2倍PNG导出按同一配置运行；所有61个Plotly入口已静态核对。
- 组合订单每页8笔，保留原始全局行号，图/表/下载来自同一订单集；零成交不删，缺价格保留空值。
- 组合净值与回撤共同取原始绘图行，现金与暴露同样处理，避免只按一条曲线抽样漏掉另一条极值。总预算不增加；下载和结果不抽样。

## 后续逐图验收要求

每种图登记来源版本、日期、单位、价格/收益口径、实际数组、图表与表格/下载对照、悬停/选择/缩放事件、空态和缺值。重要图至少一个真实样本；研究数据尚不合格的图保留未验收状态。1024/1280/1440/1920分别检查标签、图例、中文/负号、焦点与完整操作。性能另记p50/p95及内存，截图好看和单次操作顺畅不能代替这些检查。

作品数组证据：output/showcase-arrays-acceptance.json记录11条曲线和三列校验值；output/verify_showcase_arrays.js实际切模型/情景后检查浏览器calcdata。model2为独立历史原生批次，不改变其研究验收状态。初次仅按行数等待会读到同长度上一情景，检查已加入曲线标签后重跑全部通过。没有据此改写历史源数据。

响应式进度：七工作区默认页×四种宽度共28次无页面横向溢出及应用异常。新React Aria选择框使用inputmode=none而非readonly；检查确认手形和透明插入符，不能以HTML input标签直接判断为文本输入。完整键盘/运行后子视图仍待验收。


策略事件增量：七个急切渲染标签改为四个按需视图；净值表现、买卖事件、成本与参数、研究记录。事件标记位于执行日的原始策略净值，使用红色上三角/绿色下三角区分买卖，未成交灰色叉号。缺对应净值日期/缺净值不造坐标，仍可在选择框、表格和CSV找到；每40事件分页，原曲线与事件坐标独立取数，采样不挪动事件日期。单股模板按比例收益运行，事件数量为单位化记录，事件现金表不作为净值账户。

浏览器实际合成趋势样本300点、12买入/12卖出，净值按12位小数、事件执行价按页面4位小数与保存结果hash一致；CSV24行12列与保存结果一致。卖出标记点击联动事件2（执行2023-03-03，信号2023-03-02，执行价98.7523）。1024/1280/1440/1920事件页无横向溢出、0应用异常，选择框手形。成本场景和归档返回净值仅保留激活图；截图output/playwright/m3-strategy-events-1024.png等，数组脚本output/verify_strategy_event_arrays.js，报告output/strategy-event-acceptance.json。趋势/均值回归全主视图测试通过；质量动量因示例缺财务时点继续禁止运行，不以合成日期开放。


成本/净值视图增量：每日成本柱与累计换手成本阶梯线共轴，超过600日按月汇总成本柱，不抽样丢弃每日成本；累计线按原始行取样。累计成本率明确为逐日相加，不当作复利收益损失。零成本日保留，坏数/缺值/重复日期/合计不符拒绝。净值提供图/表/CSV，图同时保留策略、基准、回撤的极值和缺口。浏览器300日成本率合计2.40%，两份下载各300行与保存结果一致（rtol/atol 1e-12）；成本页四宽度无溢出/异常。截图复核后加宽柱体避免细线难读，14项相关检查及独立浏览器复核通过。证据output/strategy-cost-acceptance.json与output/playwright/m3-strategy-cost-wider-bars.png。

作品说明与文件增量：七模型42主说明页签、21个模型专属说明实际打开；8份登记公开CSV浏览器下载字节hash一致，0应用异常。证据output/showcase-sections-acceptance.json；完整二级证据情景、键盘与图内交互未据此判定通过。

作品成本/年度增量：成本情景点图与年度柱图新增图/表切换、数值CSV；年度负收益保留，部分年斜纹并显示期间/日数。历史净值新增完整CSV，首日不改。模型1成本2行、模型3年度5行实际浏览器下载与页面来源逐列1e-12核对，两页四宽度无溢出/应用异常；年度2026仅77日，保留年化标记。完整1037项回归通过，证据output/evidence-visual-acceptance.json。其他模型成本切换、所有曲线实际下载及键盘仍待矩阵验收。

作品11曲线完整下载增量：实际浏览器逐选七模型11情景，日期/净值/回撤calcdata SHA256再次与原公开包一致；每情景点击完整CSV下载并切换表格，合计16224行CSV与公开原始点逐列一致（rtol/atol 1e-12）。无应用异常，首日保留；模型2/6研究状态不变。证据output/showcase-curves-download-acceptance.json及output/verify_showcase_curve_downloads.js。年度末柱实际鼠标悬停显示2026-01-05至04-30、27.84%年化、77日及不完整年度。28个其他二级视图的早期固定等待脚本读到旧图，未采纳为验收证据；完整矩阵/图内交互/键盘仍待办。


T40/T56财务图形增量：四项概览与单指标切换，流量用柱图、总资产用期末折线；缺数不连线/不补零，整项无数值标注，选中范围无报告期不渲染空图。更新表单收起，范围/口径/图表选择并排，给图形保留首屏空间；选择器只选。图表revision纳入实际观察表/模式，切数据不保留旧轴。19项相关检查通过（2.86秒）；完整1039项通过（103.45秒），同一既有日期警告；随后布局调整19项通过（2.76秒）。

使用已保存新浪600000.SH九期四指标，累计/单季/TTM共108实际图点及缺口与观察表换算一致；总资产不作累计差分；36行TTM浏览器下载与观察转换表逐列一致1e-12。真实独立组件页1024/1280/1440/1920无溢出/应用异常，单指标总资产与表格切换通过；不是完整数据中心所有操作已验收。采集入口/存储/财务计算未改，仍属最新观察浏览，不升级历史PIT能力。证据output/financial-refined-acceptance.json、output/verify_financial_refined.js；截图output/playwright/m3-financial-refined-1280.png、m3-financial-assets-refined.png。


## 2026-11-18精简范围增量

正式看盘组件：generation 2两证券6条真实OHLC与成交量逐点一致，三面板、详情量纲正确；两证券各1024/1280/1440/1920无横向溢出/应用异常，Enter选择“全部”及详情开关通过。证据`output/closeout/kline-acceptance.json`。报价图/表/顶部/catalog统一保留来源昨收未知，周/月不造昨收，legacy fallback不跨证券；新增回归及全量1052项通过。长区间全部指标、缩放和旧入口可达性仍需关账。

作品：28个二级视图实际等待模型及目标内容后打开，无应用异常；模型5/6成本图与表格键盘Space切换、下载及四宽度补验；图点年化收益为20.70220209%/18.84860225%与21.81586141%/15.21067299%，CSV两行数值及日期同源，模型6悬停显示21.82%。原研究未通过状态保留。11曲线16224行、42说明页签和8份产物下载证据继续复用。剩余图内缩放/重置/图例与其余模板键盘验收不因测试数通过而自动关闭。

全市场/历史行业/财务因子和新增品种研究不再属于S12交付；保留的图表仍需数据正确。静态入口64不是运行验收数量，不将缺真实合格输入的研究图认定为真实研究验收。
