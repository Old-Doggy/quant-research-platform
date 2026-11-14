"""Model-specific reading notes checked against training, backtest and audit sources.

These notes describe research mechanisms. Historical curves keep their own run
and cost identity; current training code does not identify a historical checkpoint.
"""


def pair(zh, en):
    return {'zh': zh, 'en': en}


MODELS = {
    'model1': {
        'idea': pair('用历史序列学习股票之间的相对强弱，再把排名转成受交易约束的持仓。',
                     'Learn relative stock strength from historical sequences, then translate ranks into constrained holdings.'),
        'data': [
            pair(('价格与成交', '日频行情提供价格变化、成交活跃度和历史序列。特征用于解释相对强弱；成交检查另用执行价格和当日交易状态。'),
                 ('Prices and activity', 'Daily prices and trading activity form historical sequences. Features describe relative strength; execution prices and trading status serve a separate feasibility check.')),
            pair(('特征与预测目标', '训练脚本使用 CS-ALSTM：LSTM（长短期记忆网络）提取每只股票的历史变化特征，横截面注意力比较同一天不同股票的特征。排序损失关注候选的相对次序。'),
                 ('Features and targets', 'The CS-ALSTM training code uses LSTM sequence representations and cross-sectional attention across stocks on the same day. The ranking loss emphasizes relative order.')),
            pair(('股票池与可交易性', '模型分数并不直接等于仓位。候选还需要经过股票池、上市状态和交易可行性检查，资金不足或无法成交会改变最终持仓。'),
                 ('Universe and tradability', 'A model score is not a portfolio weight. Candidates pass universe, listing and tradability checks; unavailable fills or limited capital alter realized holdings.')),
        ],
        'steps': [pair(('序列编码','LSTM 读取每只股票的历史特征，形成时序表示。'),('Sequence encoding','LSTM converts each stock’s feature history into a temporal representation.')),
                  pair(('横截面比较','注意力层比较同日股票，输出用于排序的分数。'),('Cross-sectional comparison','Attention compares stocks on the same session and produces ranking scores.')),
                  pair(('候选与持仓','按排名选取候选，区分新买入门槛与已有持仓的保留条件。'),('Candidates and holdings','Rank candidates and distinguish new-entry conditions from retention of existing holdings.')),
                  pair(('执行与退出','在执行窗口检查成交条件；按持有与再平衡规则退出，扣除成本。'),('Execution and exit','Check executable prices, apply holding and rebalance exits, and deduct costs.'))],
        'timing': pair('历史特征 → 训练/验证按时间切分 → 收盘候选排名 → 后续执行窗口 → 每日估值与成本记录。未来收益标签仅用于训练和评估。',
                       'Historical features → chronological training/validation → closing candidate ranks → subsequent execution → daily valuation and costs. Forward-return labels are used only for training and evaluation.'),
        'validation': [
            pair(('先看参数是否稳定','滚动样本外、固定参数稳健排名和留出区间回答不同问题：前者观察跨年份迁移，后两者检查结果是否依赖单次选优。'),('Parameter stability','Rolling OOS, fixed-parameter stability ranking and holdout periods answer different questions: transfer across years versus dependence on a single optimized choice.')),
            pair(('再看交易摩擦','正式审计分别提高佣金、滑点和综合成本，并检查尾部成交恶化。把压力情景与基线放在同一期间，才能看出信号被成本侵蚀的程度。'),('Trading friction','The formal audit stresses commission, slippage and aggregate costs, including adverse execution tails. Matched periods reveal how friction erodes the signal.')),
            pair(('如何阅读结论','基线年化约 19.90%，综合成本翻倍后约 12.54%。这说明执行质量是主要敏感项；尾盘额外恶化 30 bp 的情景需与基线分开检查。'),('Reading the findings','Annual return is about 19.90% at baseline and 12.54% at twice cost. Execution quality is a key sensitivity; the additional 30 bp adverse-tail case must be read separately.')),
        ],
        'sources': ['模型1_模型训练.py · CS_ALSTM', '模型1_回测.py · 候选、持仓与执行', 'model1_formal_cost_stress_20260507 · 正式审计'],
    },
    'model2': {
        'idea': pair('把红利、质量与低波动转成防御型排名，再用市场宽度和风险预算控制总仓位。',
                     'Rank dividend, quality and low-volatility characteristics, then control exposure with market breadth and risk budgets.'),
        'data': [
            pair(('股息、估值与盈利', '因子计算使用股息率、估值、ROE 和盈利变化等字段。财务指标需要按可得日期对齐，不能把后来披露的数值提前放回历史。'),('Dividend and fundamentals','Factor construction uses dividend yield, valuation, ROE and earnings changes. Fundamentals must be aligned by availability rather than backfilled from later disclosures.')),
            pair(('波动与回撤', '历史收益用于计算波动、下行波动和回撤，低波因子偏向波动较低的候选。趋势、质量和股息增强是可比较的研究分支。'),('Volatility and drawdown','Historical returns provide volatility, downside volatility and drawdown measures. Low-volatility ranking favors calmer candidates; trend, quality and dividend enhancements are distinct research branches.')),
            pair(('市场与股票池', '全市场宽度描述整体上涨参与度，股票池决定候选范围，两者不能混为同一数据。成交使用原始价格，因子计算另保留复权口径。'),('Market and universe','Market breadth measures broad participation while the stock universe limits candidates. They are separate inputs. Executions use raw prices while feature calculations retain their adjustment convention.')),
        ],
        'steps': [pair(('防御因子','计算股息、盈利质量、波动与回撤特征。'),('Defensive factors','Compute dividend, earnings quality, volatility and drawdown characteristics.')),
                  pair(('股票排名','在指定股票池内按组合因子排序，形成调仓候选。'),('Stock ranking','Rank combined factors within the specified universe to form rebalance candidates.')),
                  pair(('总仓位控制','市场宽度决定风险状态，波动和回撤预算进一步缩放总仓位。'),('Exposure budget','Breadth determines market state; volatility and drawdown budgets further scale total exposure.')),
                  pair(('定期再平衡','检查行业集中度、手数与交易限制，调整仓位并保留现金。'),('Periodic rebalance','Check industry concentration, lot sizes and trading limits; rebalance and retain cash.'))],
        'timing': pair('财务/价格数据按时点对齐 → 因子排名 → 预测分数映射至下一交易日 → 按原始价格执行 → 重新估值。',
                       'Align fundamentals and prices by availability → factor ranking → map scores to the next session → execute at raw prices → revalue holdings.'),
        'validation': [
            pair(('股票池验证','2026-05-05 验证批次比较多个股票池，该批次未通过研究验收。该批次保留的图片、日志与摘要不等于可逐日核对的数值序列。'),('Universe validation','The 2026-05-05 batch compares universes and does not pass the recorded gate. Saved images, logs and summary metrics are distinct from a numeric daily series.')),
            pair(('原生引擎样本外','2026-05-04 批次保存了各组参数的日收益及每年的选参记录。页面据此还原逐年样本外收益，并核对每段结果；与 5 月 5 日批次分开展示。'),('Native-engine OOS','A separate 2026-05-04 batch stores daily returns per parameter and annual chosen_param records. The view replays those recorded choices, verifies each fold and keeps this scenario separate.')),
            pair(('如何阅读结论','不同批次的股票池、选参和执行口径会显著改变结果。先选择证据情景，再检查成本与日期；原生引擎曲线的较好表现不替换旧批次的未通过结论。'),('Reading the findings','Universe, selection and execution conventions differ across batches. Choose an evidence scenario and inspect dates and costs; stronger native-engine performance does not replace the failed earlier gate.')),
        ],
        'sources':['模型2_线性模型训练.py · 防御特征','模型2_回测.py · 宽度与风险预算','model2_global_pool_curves.csv + 年度 WFO folds'],
    },
    'model3': {
        'idea': pair('在 ETF 之间比较趋势与动量，风险状态转弱时把配置转向防御资产或现金。',
                     'Compare ETF trends and momentum; move allocation toward defensive assets or cash when the risk state weakens.'),
        'data': [
            pair(('ETF 历史序列','每只 ETF 的价格、成交与历史收益用于计算动量、均线和波动。资产覆盖不足或起始日期不同，会改变可比较的研究区间。'),('ETF history','ETF prices, trading activity and historical returns support momentum, moving-average and volatility features. Coverage and differing inception dates affect the comparable study period.')),
            pair(('进攻与防御资产','模型区分参与风险配置的资产与承担防御角色的资产。信号不仅决定买哪只 ETF，也影响有多少资金配置到防御端或现金。'),('Offensive and defensive assets','The model distinguishes risk assets from defensive assets. Signals determine both the selected ETF and how much capital moves to defense or cash.')),
            pair(('趋势与风险状态','VAA 动量分数配合均线、资产宽度和波动参与排序。正式审计的 hybrid_fast 变体需与其他变体及当前运行配置分别识别。'),('Trend and risk state','VAA momentum scores combine with moving averages, breadth and volatility in ranking. The audited hybrid_fast variant remains distinct from other variants and runtime configurations.')),
        ],
        'steps':[pair(('动量刻画','从多个历史窗口计算资产的相对趋势。'),('Momentum','Measure relative asset trends across historical windows.')),
                 pair(('状态与排名','结合趋势、资产宽度及波动，比较进攻资产的配置优先级。'),('State and ranking','Combine trend, breadth and volatility to rank offensive allocations.')),
                 pair(('配置分流','选取进攻资产，把剩余风险预算分给防御资产或现金。'),('Allocation split','Select offensive assets and direct residual risk budget to defense or cash.')),
                 pair(('调仓估值','按调仓窗口调整权重，检查交易限制并记录每日收益。'),('Rebalance and value','Update weights at rebalance, check execution limits and record daily returns.'))],
        'timing':pair('历史窗口计算 → 信号与执行窗口分离 → 到期调仓 → 资产切换与成本 → 年度样本外检查。',
                      'Historical windows → separate signal and execution windows → scheduled rebalance → asset switching and costs → annual OOS checks.'),
        'validation':[
            pair(('105 组正式参数网格','正式审计比较 105 组参数，并以滚动样本外记录评估跨时期表现。样本外汇总覆盖 2016-01-04 至 2026-04-30。'),('105-case formal grid','The formal audit compares 105 parameter cases and evaluates transfer through walk-forward OOS records. The aggregate OOS period is 2016-01-04 through 2026-04-30.')),
            pair(('年度、负对照与重采样','年度结果用于定位收益集中在哪些市场阶段；负对照和区块重采样检查信号依赖及时间相关性，不能由一条平滑净值替代。'),('Annual results and controls','Annual results locate contributions across market regimes. Negative controls and block bootstrap examine signal dependence and serial correlation beyond a smooth aggregate NAV curve.')),
            pair(('如何阅读结论','全样本年化约 11.86%，但 2022 年样本外年化为 -6.41%。2026 年只截至 4 月 30 日；配置来源日期差异仍需单独核对。'),('Reading the findings','Aggregate annual return is about 11.86%, while 2022 OOS annual return is -6.41%. The 2026 record ends on April 30; configuration source-date differences require separate checking.')),
        ],
        'sources':['模型3_线性模型训练+回测.py · VAA 排名与配置','model3_vaa_formal_audit_full · manifest / 年度 OOS'],
    },
    'model4': {
        'idea': pair('把转债价格、转股溢价、正股动量与风险筛选组合起来，重点检验信号能否实际成交。',
                     'Combine bond price, conversion premium, underlying-stock momentum and risk screens, then test whether signals can actually execute.'),
        'data':[
            pair(('转债与正股行情','转债价格与成交额刻画买入成本和流动性，正股历史价格提供动量背景。转债与正股需要按同一交易日对应，避免错配。'),('Bond and stock prices','Bond prices and turnover describe entry cost and liquidity; underlying-stock history provides momentum context. Bond and stock observations must align to the same session.')),
            pair(('估值与风险字段','转股溢价、发行规模及赎回公告参与筛选。强赎风险必须按公告当时可知信息处理，不能利用事后结果过滤历史候选。'),('Valuation and risk','Conversion premium, issue size and redemption announcements contribute to screening. Redemption risk must use announcements available at the time rather than future outcomes.')),
            pair(('成交约束与费用','审计另外读取执行窗口价格、成交额、最小手数及参与率。目标权重不保证全部成交，受限买卖和部分成交都保留记录。'),('Execution and fees','The audit uses execution-window prices, turnover, lot sizes and participation limits. Target weights do not guarantee full fills; blocked orders and partial fills remain in the record.')),
        ],
        'steps':[pair(('候选筛选','用价格、溢价、流动性和赎回风险缩小转债范围。'),('Candidate screen','Screen bond price, premium, liquidity and redemption risk.')),
                 pair(('动量与配置','结合正股动量和波动分配候选的配置权重。'),('Momentum and allocation','Use underlying-stock momentum and volatility to allocate candidate weights.')),
                 pair(('执行审计','把前一时点目标映射到下一开盘，并施加手数和参与率限制。'),('Execution audit','Map prior-time targets to the next open and apply lot and participation constraints.')),
                 pair(('成交后估值','保留未成交与部分成交，扣除实际模拟费用后逐日估值。'),('Post-fill valuation','Retain blocked and partial fills; value holdings daily after simulated trading fees.'))],
        'timing':pair('T−1 候选信号 → T 日开盘执行检查 → 可成交数量与费用 → 收盘估值。下一尾盘情景缺少历史盘口时使用次日收盘代理。',
                      'T−1 candidate signals → T open feasibility checks → fill quantities and fees → closing valuation. Next-tail scenarios use a next-close proxy when historical intraday quotes are absent.'),
        'validation':[
            pair(('先比较执行窗口','审计对照同日收盘、下一开盘和下一尾盘代理，检验漂亮回测是否依赖过早的成交价格。当前净值页对应 T−1 信号、下一开盘、2 倍成本。'),('Execution-window comparison','The audit compares same-close, next-open and next-tail proxies to identify dependence on premature execution prices. The displayed curve uses T−1 signals, next-open execution and twice cost.')),
            pair(('再比较成本与拦截','同一窗口下比较成本倍数，并记录买入受限、卖出受限及部分成交次数。收益变化需要同时结合换手和成交可达性理解。'),('Costs and execution blocks','Compare cost multipliers within the same window and retain blocked buys, blocked sells and partial fills. Return differences should be read with turnover and fill feasibility.')),
            pair(('如何阅读结论','当前审计情景年化约 13.53%，最大回撤 -28.34%。源净值包含首日交易成本；赎回公告时点和尾盘代理会限制执行结论的精度。'),('Reading the findings','The selected audit scenario returns about 13.53% annually with -28.34% maximum drawdown. Source NAV includes first-day trading costs; announcement timing and tail proxies limit execution precision.')),
        ],
        'sources':['模型4_回测.py · 转债轮动','model4_cb_formal_execution_audit.py · 窗口、成交与费用'],
    },
    'model5': {
        'idea':pair('研究财报公告后的价格延续（PEAD）：盈利变化提供事件背景，跳空与成交量确认市场反应。',
                    'Study post-earnings-announcement drift (PEAD): earnings changes provide the event context while gaps and volume confirm market response.'),
        'data':[
            pair(('财报事件与可得时间','公告日期、时间和净利润同比用于确定事件及可交易起点。盈利数值出现在哪一天，与市场实际何时看到公告，需要分别检查。'),('Events and availability','Announcement dates, times and earnings growth identify events and the tradable starting point. A value’s data date is distinct from when the market actually receives the announcement.')),
            pair(('价格与成交确认','跳空幅度、成交量放大和价格变化判断市场是否响应事件。事件信号不是只凭盈利增长触发，还需要价格与量能条件配合。'),('Price and volume confirmation','Price gaps, volume expansion and price action test the market response. Earnings growth alone does not trigger an event candidate; price and activity conditions also matter.')),
            pair(('持有窗口与成本','持仓天数、追踪止损和调仓费用决定事件收益如何兑现。多个事件可能重叠，需要去重并检查组合资金和持仓数量。'),('Holding window and costs','Holding duration, trailing exits and turnover costs determine realized event P&L. Overlapping events require deduplication, capital checks and position limits.')),
        ],
        'steps':[pair(('识别公告','对齐盈利变化与公告可得日期，生成财报事件。'),('Identify announcements','Align earnings changes with public availability to identify events.')),
                 pair(('市场反应','用跳空、价格与成交量条件确认事件候选。'),('Market response','Confirm event candidates with gap, price and volume conditions.')),
                 pair(('建立持仓','按保守下一交易日时点处理候选，检查资金与交易限制。'),('Build holdings','Process candidates using conservative next-session timing and execution checks.')),
                 pair(('事件退出','持有期到期或追踪退出触发后平仓，记录成本。'),('Event exit','Close at the holding limit or trailing-exit trigger and record costs.'))],
        'timing':pair('公告可得 → 事件顺延与价格确认 → 后续交易窗口 → 持有/追踪退出。缺少可靠公告时间时，采用保守的下一交易日假设。',
                      'Public announcement → delayed event availability and price confirmation → subsequent execution → holding/trailing exit. Missing announcement times use a conservative next-session assumption.'),
        'validation':[
            pair(('参数网格与滚动验证','正式审计设置了 3000 组参数，围绕事件确认、持有和退出条件比较样本外表现。收益曲线由每段样本外日收益连接，展示未参与当轮选参的数据上的表现。'),('Grid and walk-forward validation','The formal audit requests 3,000 parameter cases across event confirmation, holding and exits. The curve uses daily OOS returns rather than the best full-sample parameter result.')),
            pair(('成本、时点与负对照','提高佣金、滑点或成交价格恶化，分别检验执行摩擦；打乱标签、延迟信号等对照用于检查结果是否依赖原始事件关系。'),('Costs, timing and controls','Stress commission, slippage and adverse execution prices separately. Label shuffles and delayed-signal controls test dependence on the original event relationship.')),
            pair(('如何阅读结论','滚动样本外基线年化约 20.70%，2 倍成本约 18.85%。事件公告时间不完整与独立执行时点审计中的负结果仍是重点，不能仅凭汇总收益作结论。'),('Reading the findings','Formal WFO annual return is about 20.70%, falling to 18.85% at twice cost. Incomplete announcement timing and negative independent timing-audit outcomes remain important alongside aggregate returns.')),
        ],
        'sources':['模型5_模型+回测.py · 公告与事件回测','model5_pead_formal_audit.py · WFO / 成本 / 对照'],
    },
    'model6': {
        'idea':pair('用 Alpha-MoE 学习不同股票状态的评分，再检验低波股票池中的锁定候选是否稳定。',
                    'Use Alpha-MoE to learn stock-state-dependent scores, then test a locked candidate in a low-volatility universe.'),
        'data':[
            pair(('股票特征序列','训练输入为按股票组织的历史特征序列，GRU（门控循环网络）提取随时间变化的特征。日频价格和交易状态同时服务于候选筛选与后续成交检查。'),('Stock feature sequences','Training uses historical feature sequences grouped by stock. GRU extracts temporal representations; daily prices and trading status also support selection and subsequent execution checks.')),
            pair(('多专家评分','门控网络通过 softmax 为多个专家分配权重；专家输出加权融合后由最后的输出层生成股票分数，权重随输入状态变化。'),('Mixture-of-experts scoring','A softmax gating network weights multiple experts. Their representations are combined and passed to a scoring head; expert weights vary with the input state.')),
            pair(('低波池与锁定候选','低波、质量与股票池稳定性属于候选和组合层的研究维度；它们不替代神经网络本身。当前曲线只展示已锁定候选及对应成本倍数。'),('Low-volatility universe and locked candidate','Low volatility, quality and universe stability are selection and portfolio research dimensions, not substitutes for the neural architecture. The curve uses the locked candidate and its cost case.')),
        ],
        'steps':[pair(('时序表示','GRU 编码每只股票的历史特征。'),('Temporal representation','GRU encodes each stock’s historical features.')),
                 pair(('专家融合','门控网络为多个专家分配权重（softmax），汇总后为股票打分。'),('Expert fusion','A softmax gate weights expert representations before cross-sectional scoring.')),
                 pair(('组合候选','在目标股票池内排序，按固定持仓和调仓规则生成候选。'),('Portfolio candidate','Rank within the target universe and apply fixed holding and rebalance rules.')),
                 pair(('约束执行','下一开盘执行，检查 T+1、手数、停牌及涨跌停，计入税费。'),('Constrained execution','Execute at the next open with T+1, lot, suspension, price-limit and fee checks.'))],
        'timing':pair('历史序列与训练切分 → 样本外预测 → 股票池排序 → 下一开盘 → 逐日估值。固定候选后，再分段检查收益，并测试交易成本上升的影响。',
                      'Historical sequences and chronological splits → OOS predictions → universe ranking → next-open execution → daily valuation. Recheck the locked candidate with fixed folds and cost multipliers.'),
        'validation':[
            pair(('分段检查','固定模型和参数后，将测试期分成 5 段分别观察收益。基线 5 段均为正收益；交易成本翻倍后，正收益段降为 3 段。'),('Fixed-fold checks','After locking the candidate, inspect performance across fixed folds without repeatedly tuning on the test data. Baseline has five of five positive folds, versus three of five at twice cost.')),
            pair(('成本与近期稳定性','成本敏感性覆盖不同倍数，并单独观察近期区间。高换手会放大交易摩擦，完整样本正收益并不保证每个阶段都有效。'),('Costs and recent stability','Cost sensitivity covers multiple multipliers and recent periods separately. High turnover magnifies friction; positive aggregate returns do not ensure effectiveness in every phase.')),
            pair(('如何阅读结论','基线年化约 21.82%、最大回撤 -18.76%；2 倍成本年化约 15.21%、最大回撤 -20.90%。该候选尚未通过严格验收，主要还需结合分段收益与近期表现判断。'),('Reading the findings','Baseline annual return is about 21.82% with -18.76% drawdown; twice-cost results are 15.21% and -20.90%. strict_gate_pass remains false and should be read with fold and recent-period evidence.')),
        ],
        'sources':['调参+模型训练.py · AlphaMoE / GRU / softmax','model6_locked_candidate_cost_sensitivity.csv','model6_locked_validation_raw · 固定折与决策'],
    },
    'model7': {
        'idea':pair('把多个股票池的选择合并成一个组合，统一处理重复股票、集中度、现金与执行日期。',
                    'Merge multiple stock-pool selections into one portfolio with shared duplicate, concentration, cash and execution-date handling.'),
        'data':[
            pair(('子策略与候选池','锁定的小资金候选融合四个模型 2 股票池。每个子策略先生成自己的候选，组合层读取候选及权重，不把同一股票重复当成独立资产。'),('Strategy legs and pools','The locked small-capital candidate combines four model-2 pools. Each leg generates candidates; the portfolio merges candidates and weights without treating duplicate stocks as separate assets.')),
            pair(('权重与集中度','个股上限、行业上限和各子策略的选股数量共同影响最终配置。超限部分需要重新处理或留成现金，不能直接把子策略收益相加当组合净值。'),('Weights and concentration','Stock caps, industry caps and per-leg selection counts jointly shape allocation. Excess weights require adjustment or cash retention; adding leg returns is not a portfolio accounting method.')),
            pair(('执行日期与质量','目标文件记录信号和执行日期，并核查缺失子策略、有效权重覆盖和标的质量。当前运行状态是目标记录，与历史回测收益分别存储。'),('Execution dates and quality','Targets carry signal and execution dates, with checks for missing legs, active-weight coverage and candidate quality. Runtime target state is stored separately from backtest performance.')),
        ],
        'steps':[pair(('子策略选股','四个股票池分别产生候选与配置份额。'),('Leg selection','Four pools produce candidates and allocation shares.')),
                 pair(('合并去重','同一股票的子策略权重合并，在统一组合里计算实际权重。'),('Merge duplicates','Combine weights of the same stock and calculate exposure within one portfolio.')),
                 pair(('约束与现金','施加个股/行业上限，处理限额与剩余现金。'),('Caps and cash','Apply stock and industry caps and handle residual cash.')),
                 pair(('下一开盘','检查目标日期与子策略数据是否齐全，再进入统一股票级执行模拟。'),('Next open','Verify target dates and leg coverage, then run shared stock-level execution simulation.'))],
        'timing':pair('各子策略收盘候选 → 合并与限额 → 带执行日期的目标配置 → 下一开盘 → 股票级成交与组合估值。',
                      'After-close leg candidates → merge and cap → dated target allocation → next-open execution → stock-level fills and portfolio valuation.'),
        'validation':[
            pair(('选型验证与参数邻域','选型验证评估已固定的小资金组合，并对相邻集中度、选股数量和调仓频率作比较，判断表现是否依赖孤立的单点参数。'),('Selection and parameter neighbors','Selection validation evaluates the locked small-capital portfolio and nearby concentration, selection-count and rebalance choices to assess dependence on an isolated parameter setting.')),
            pair(('股票级成本压力','使用统一股票级组合模拟器检查重复股票、手数、交易约束和成本。选型验证 2 倍成本年化约 26.84%，应与相同批次基线配对。'),('Stock-level cost stress','The unified portfolio simulator handles duplicate stocks, lot sizes, trading limits and fees. Selection-validation annual return at twice cost is about 26.84% and belongs with its matching baseline.')),
            pair(('如何阅读三层结果','选型快照截至 2026-04-24，最新本地回测截至 2026-05-08；年化分别约 30.33% 与 28.89%。运行目标没有历史收益指标，三个层次不能拼成一条曲线。'),('Reading the three layers','The selection snapshot ends on 2026-04-24 and the latest local backtest on 2026-05-08, returning about 30.33% and 28.89% annually. Runtime targets have no historical performance metrics; the layers remain separate.')),
        ],
        'sources':['模型7_配置.py · 子策略、权重与限额','模型7_回测.py · 股票级组合','model7_backtest_metrics.csv · latest','模型7_交易日前与早盘Runbook.md'],
    },
}


def model_explanation(model_id, *, language='zh'):
    if model_id not in MODELS or language not in {'zh','en'}:
        raise ValueError('Unknown model or language')
    data=MODELS[model_id]
    return {key: ([row[language] for row in value] if key in {'data','steps','validation'}
                   else value[language] if key in {'idea','timing'} else list(value))
            for key,value in data.items()}
