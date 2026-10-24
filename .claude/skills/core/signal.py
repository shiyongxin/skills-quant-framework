# -*- coding: utf-8 -*-
"""统一信号输出契约 (审计 C #9, 项 21 #9a).

各信号/选股模块的"出口形状"统一为 `Signal` dataclass: 下游因此知道
**什么时候** (`signal_date`)、**能不能执行** (`executable`/`blocked_reasons`)、
**为什么** (`reasons`)、**买多少** (`target_weight`)、**多大概率** (`confidence`)。

刻度诚实原则: `strength` 的量纲随产出模块不同, 用 `scale` 字段显式标明,
**不做静默归一化** (跨模块比较前必须自己选刻度)。

`execute_at` 语义: 默认 `None` = 由执行层 (`execution_model`) 按 t+1 开盘规则决定
—— 仓库暂无交易日历, 强行推算下一个交易日会造假; 调用方持有交易日历时可显式填入。

本模块只定义契约与转换工具, 不含任何打分/指标逻辑 (那些在各自产出模块)。
"""
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional

# 动作
ACTION_BUY = 'BUY'
ACTION_HOLD = 'HOLD'
ACTION_SELL = 'SELL'
ACTIONS = (ACTION_BUY, ACTION_HOLD, ACTION_SELL)

# 强度刻度 (声明量纲, 便于跨模块比较时显式对齐)
# 约定: vote/vote_norm/weighted 为**有符号**分 (正=买方一侧, 负=卖方一侧);
#       prob/score 为**无符号**分 (方向由 action 表达, 分值是"对该方向的把握")。
SCALE_VOTE = 'vote'            # S1 分项求和, 有符号 [-10, 10]
SCALE_VOTE_NORM = 'vote_norm'  # S2 归一化, 有符号 [-1, 1]
SCALE_WEIGHTED = 'weighted'    # (买方分-卖方分)/10, 有符号 [-10, 10]
SCALE_PROB = 'prob'            # 模型对预测方向的概率, 无符号 [0, 1]
SCALE_SCORE = 'score'          # 0-100 绝对分 (SS/LTS/reversal 置信度), 无符号 [0, 100]
SCALE_ZSCORE = 'zscore'        # 横截面 z 分 (MFS), 有符号无固定界

# 有符号刻度 → 量纲边界 (校验用); 无符号刻度单独校验
_SIGNED_BOUNDS = {
    SCALE_VOTE: (-10.0, 10.0),
    SCALE_VOTE_NORM: (-1.0, 1.0),
    SCALE_WEIGHTED: (-10.0, 10.0),
}
_UNSIGNED_BOUNDS = {
    SCALE_PROB: (0.0, 1.0),
    SCALE_SCORE: (0.0, 100.0),
}


@dataclass(frozen=True)
class Signal:
    """统一信号契约 (所有信号/选股模块的出口形状).

    Attributes:
        symbol: 标的代码
        signal_date: 信号对应交易日 (str)
        action: BUY / HOLD / SELL (互斥, 同一时刻只可能有一个)
        strength: 强度分, 量纲见 `scale`
        scale: 强度刻度标识 (SCALE_*)
        reasons: 信号原因 (中文标签, 与产出模块同一张标签表)
        confidence: 置信度 [0, 1]; None = 该模块不产出
        target_weight: 目标仓位比例 [0, 1]; None = 由下游风控决定
        execute_at: 可执行时点; None = 交由执行层 (t+1 开盘) 决定
        executable: 是否通过交易约束前置检查
        blocked_reasons: 阻断原因 (可执行性检查)
        skipped_checks: 因缺数据而诚实跳过的检查项
        source: 产出模块名 (signal_generator / daily_signal_generator / ...)
        extra: 模块特有字段快照 (指标快照、评分明细等)
    """
    symbol: str
    signal_date: str
    action: str
    strength: float = 0.0
    scale: str = SCALE_VOTE
    reasons: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    target_weight: Optional[float] = None
    execute_at: Optional[str] = None
    executable: bool = True
    blocked_reasons: List[str] = field(default_factory=list)
    skipped_checks: List[str] = field(default_factory=list)
    source: str = ''
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(
                f"action 必须是 {ACTIONS} 之一, 收到 {self.action!r}")
        bounds = _SIGNED_BOUNDS.get(self.scale) or \
            _UNSIGNED_BOUNDS.get(self.scale)
        if bounds:
            value = float(self.strength)
            if not bounds[0] <= value <= bounds[1]:
                raise ValueError(
                    f"scale={self.scale} 要求 strength ∈ "
                    f"[{bounds[0]}, {bounds[1]}], 收到 {self.strength}")

    @property
    def is_actionable(self) -> bool:
        """是否可执行且非观望 (供下游下单路径直接判断)"""
        return self.executable and self.action in (ACTION_BUY, ACTION_SELL)


def normalize_date(value) -> str:
    """把多种日期表示统一成 'YYYY-MM-DD' 字符串.

    支持: datetime/date/Timestamp (含 pandas Timestamp) / 'YYYY-MM-DD' 字符串 /
    带时分秒的字符串 (取日期部分)。None → '' (不编造日期)。
    """
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        try:
            return value.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
    text = str(value).strip()
    if not text:
        return ''
    return text.split(' ')[0].split('T')[0]


@dataclass(frozen=True)
class Selection:
    """统一选股结果契约 (L1 横截面选股层; 审计 C #9b, 项 21).

    与 `Signal` **分立** (用户决策): `Selection` 回答"池内哪些标的排名如何、
    是否入选"; `Signal` 回答"何时买卖、能否执行"。两者都带交易约束字段
    (executable/blocked_reasons/skipped_checks), 因此"选出来的票能不能买"
    在两个契约里是同一套语义。

    Attributes:
        symbol: 标的代码
        as_of: 选股基准日 (point-in-time); '' = 产出模块暂无 as-of 语义
            (MFS 有真实公告日过滤; SS/LTS 为实盘实时筛选 — 审计 L10 待修,
            契约如实留空, 不伪造基准日)
        score: 综合分, 量纲见 `scale`
        scale: 分数刻度 (SCALE_ZSCORE / SCALE_SCORE)
        rank: 池内排名 (1-based); None = 未排名
        selected: 是否入选 (过阈值 / TopN / 档位判定)
        grade: 档位标签 (如 LTS 的 STRONG_BUY/BUY/HOLD/AVOID); None = 无档位
        reasons: 入选原因 (产出模块能给出时)
        executable: 是否通过交易约束前置检查
        blocked_reasons: 阻断原因 (可执行性检查)
        skipped_checks: 因缺数据而诚实跳过的检查项
        source: 产出模块名
        extra: 模块特有字段快照 (因子明细/价格/收益率等)
    """
    symbol: str
    as_of: str = ''
    score: float = 0.0
    scale: str = SCALE_SCORE
    rank: Optional[int] = None
    selected: bool = True
    grade: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    executable: bool = True
    blocked_reasons: List[str] = field(default_factory=list)
    skipped_checks: List[str] = field(default_factory=list)
    source: str = ''
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # score 刻度: 'score' → [0,100]; 'zscore' 有符号无固定界, 不校验
        bounds = _UNSIGNED_BOUNDS.get(self.scale)
        if bounds:
            value = float(self.score)
            if not bounds[0] <= value <= bounds[1]:
                raise ValueError(
                    f"scale={self.scale} 要求 score ∈ "
                    f"[{bounds[0]}, {bounds[1]}], 收到 {self.score}")
        if self.rank is not None and int(self.rank) < 1:
            raise ValueError(f"rank 必须 1-based, 收到 {self.rank}")

    @property
    def is_selected(self) -> bool:
        """入选且可执行 (供组合构建直接筛选)"""
        return bool(self.selected) and bool(self.executable)


def action_from_flags(buy: bool, sell: bool, strict: bool = True) -> str:
    """由买/卖布尔标志映射三态动作.

    Args:
        buy: 是否有买入信号
        sell: 是否有卖出信号
        strict: True 时若两者同时为真直接抛错 (契约: 买卖互斥)

    Returns:
        'BUY' / 'HOLD' / 'SELL'
    """
    if buy and sell:
        if strict:
            raise ValueError("买卖信号同时为真 — 违反互斥契约 (信号层应先仲裁)")
        return ACTION_HOLD
    if buy:
        return ACTION_BUY
    if sell:
        return ACTION_SELL
    return ACTION_HOLD


def apply_constraints(signal: Signal, report) -> Signal:
    """把 trade_constraints 的检查结果并入契约 (交易约束唯一挂载点).

    Args:
        signal: 原始 Signal
        report: trade_constraints.ConstraintReport

    Returns:
        新 Signal (frozen dataclass → 返回副本)
    """
    return replace(
        signal,
        executable=bool(getattr(report, 'ok', True)),
        blocked_reasons=list(getattr(report, 'blocked_reasons', []) or []),
        skipped_checks=list(getattr(report, 'skipped_checks', []) or []),
    )


def signal_to_dict(signal: Signal) -> Dict[str, Any]:
    """Signal → 扁平 dict (落盘/manifest/JSON 用)"""
    d = asdict(signal)
    d['reasons'] = list(signal.reasons or [])
    d['blocked_reasons'] = list(signal.blocked_reasons or [])
    d['skipped_checks'] = list(signal.skipped_checks or [])
    d['is_actionable'] = signal.is_actionable
    return d


def selections_to_frame(selections: List[Selection]):
    """Selection 列表 → 扁平 DataFrame (序列落盘/组合消费)."""
    import pandas as pd

    rows = []
    for s in selections:
        d = asdict(s)
        d.pop('extra', None)
        d['reasons'] = '; '.join(s.reasons or [])
        d['blocked_reasons'] = '; '.join(s.blocked_reasons or [])
        d['skipped_checks'] = '; '.join(s.skipped_checks or [])
        rows.append(d)
    columns = ['symbol', 'as_of', 'score', 'scale', 'rank', 'selected',
               'grade', 'reasons', 'executable', 'blocked_reasons',
               'skipped_checks', 'source']
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)


def signals_to_frame(signals: List[Signal]):
    """Signal 列表 → 扁平 DataFrame (序列落盘/回测消费).

    reasons / blocked_reasons 以 '; ' 连接为单列 (便于 parquet/CSV)。
    """
    import pandas as pd

    rows = []
    for s in signals:
        d = signal_to_dict(s)
        d.pop('extra', None)
        d['reasons'] = '; '.join(s.reasons or [])
        d['blocked_reasons'] = '; '.join(s.blocked_reasons or [])
        d['skipped_checks'] = '; '.join(s.skipped_checks or [])
        rows.append(d)
    if not rows:
        return pd.DataFrame(columns=[
            'symbol', 'signal_date', 'action', 'strength', 'scale', 'reasons',
            'confidence', 'target_weight', 'execute_at', 'executable',
            'blocked_reasons', 'skipped_checks', 'source', 'is_actionable'])
    return pd.DataFrame(rows)
