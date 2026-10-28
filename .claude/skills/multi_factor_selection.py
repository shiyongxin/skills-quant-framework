# -*- coding: utf-8 -*-
"""
多因子选股系统 - 增强版
Multi-Factor Stock Selection System - Enhanced Version

基于价值、成长、质量、动量、技术等多维度选股
支持因子有效性检验、组合优化等高级功能
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from scipy import stats
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')

import factor_library
import trade_constraints


def filter_point_in_time(financial_df: pd.DataFrame, as_of) -> pd.DataFrame:
    """point-in-time 财务数据契约 (审计 C-P0-7 止血版)

    只保留『公告日 ≤ as_of』的财报行 — 消除两类泄露:
    ①使用后来重述的财报值; ②把尚未公告的财报当作当日可得。

    Args:
        financial_df: 财务数据 (index=股票代码, 必须含『公告日』列)
        as_of: 截止日 (回测/选股的当前日期, str/datetime 均可)

    Returns:
        过滤后的 financial_df

    Raises:
        ValueError: 缺『公告日』列或未提供 as_of 时**拒绝运行**
                    (而非静默使用可能未公告的数据)
    """
    if '公告日' not in financial_df.columns:
        raise ValueError(
            "point-in-time 财务契约(C-P0-7): financial_df 缺少『公告日』列, "
            "拒绝运行 — 无公告日无法判断财报是否已披露, 直接使用会引入"
            "未来信息泄露。请在数据层补充公告日后再调用 select_stocks。"
        )
    if as_of is None:
        raise ValueError(
            "point-in-time 财务契约(C-P0-7): 必须提供 as_of 截止日"
            "(回测/选股当前日期), 否则无法按『公告日 ≤ as_of』过滤。"
        )

    dates = pd.to_datetime(financial_df['公告日'], errors='coerce')
    # 公告日缺失(NaT)的行无法证明已披露 → 一并剔除
    mask = dates.notna() & (dates <= pd.Timestamp(as_of))
    return financial_df.loc[mask]


def forward_returns(close: pd.Series) -> pd.Series:
    """构造**前瞻收益**标签 (t → t+1) —— 因子拟合的标签口径唯一真相源。

    审计 H6: 因子权重拟合的标签语义必须是"因子在 t 观测到 → t+1 的收益"。
    旧实现把 `returns` 的语义搞混: `ic_weights` 按前瞻同期配对 ✓, 而
    `max_sharpe_weights` / `risk_parity_weights` 用
    `factor_data[col].shift(-1) * aligned_returns` → 那是沿 **index**
    错行一格 (把"下一**只股票**的收益"当成了"下一**期**收益"), 权重
    结果依赖行序; `test_all_factors` 的 `.shift(1)` 同样是错行配对。

    用本函数构造标签, 避免 `pct_change()`(后向收益) 被误当标签 ——
    后向收益会让 IC 变成"因子解释已发生的收益", 看起来很好但没有预测力。
    """
    close = pd.Series(close).astype(float)
    return close.shift(-1) / close - 1.0


@dataclass
class FactorTestResult:
    """因子测试结果"""
    factor_name: str
    ic_mean: float           # IC均值
    ic_std: float            # IC标准差
    ir: float                # Information Ratio (IC/IC_std)
    ic_positive_ratio: float # IC为正的比例
    rank_ic: float           # Rank IC
    t_stat: float            # t统计量
    p_value: float           # p值
    is_significant: bool     # 是否显著 (5%水平)
    # 审计 H6: 口径自证 —— 'cross_section' (同期配对, 单截面, 无时序统计)
    # / 'time_series' (滚动 IC, 需时间索引)
    mode: str = 'cross_section'


class FactorWeightingMethod:
    """因子加权方法"""

    @staticmethod
    def _valid_score_cols(factors_df: pd.DataFrame) -> List[str]:
        """可用因子列：*_Score 且非全 NaN（全 NaN 列会毒化综合分）"""
        return [col for col in factors_df.columns
                if col.endswith('_Score') and factors_df[col].notna().any()]

    @staticmethod
    def _align(factors_df: pd.DataFrame,
               returns: pd.Series) -> tuple:
        """因子与收益的**同期配对** (同一行 = 同一只股票/同一期)。

        审计 H6: 旧实现用 `factor_data[col].shift(-1) * aligned_returns`
        —— 那是沿 **index** 错行一格, 把"下一只股票的收益"当成了
        "下一期的收益" → 权重结果**依赖行序**, 且含未来信息 (前瞻)。
        本方法是全仓唯一的配对入口: 同期配对, 无 shift。

        Returns:
            (factor_data, aligned_returns) —— 双方按同一 index 对齐且无 NaN
        """
        factor_cols = FactorWeightingMethod._valid_score_cols(factors_df)
        if not factor_cols:
            return factors_df.iloc[0:0], pd.Series(dtype=float)
        factor_data = factors_df[factor_cols].dropna()
        aligned_returns = pd.Series(returns).reindex(factor_data.index)
        keep = aligned_returns.notna()
        return factor_data[keep], aligned_returns[keep]

    @staticmethod
    def equal_weights(factors_df: pd.DataFrame) -> Dict[str, float]:
        """等权重（仅覆盖可用因子列）"""
        factor_cols = FactorWeightingMethod._valid_score_cols(factors_df)
        return {col: 1.0 / len(factor_cols) for col in factor_cols}

    @staticmethod
    def equal_weight(factors_df: pd.DataFrame) -> pd.Series:
        """
        等权重加权
        所有因子权重相等（忽略全 NaN 的因子列，避免毒化综合分）
        """
        return FactorWeightingMethod._apply_weights(
            factors_df, FactorWeightingMethod.equal_weights(factors_df))

    @staticmethod
    def ic_weights(factors_df: pd.DataFrame, returns: pd.Series) -> Dict[str, float]:
        """IC 加权权重（|IC| 归一化；样本不足或总 IC 为 0 → 等权）

        审计 H6: 同期配对 (因子[t] 对前瞻收益[t]) —— 口径由
        `_align` 统一, 不再各写各的 shift。
        """
        factor_cols = FactorWeightingMethod._valid_score_cols(factors_df)

        ics = {}
        factor_data, aligned_returns = FactorWeightingMethod._align(
            factors_df, returns)
        for col in factor_cols:
            if col not in factor_data.columns:
                ics[col] = 0.0
                continue
            if len(factor_data) > 10:
                ic = factor_data[col].corr(aligned_returns)
                ics[col] = abs(ic) if not np.isnan(ic) else 0
            else:
                ics[col] = 0

        total_ic = sum(ics.values())
        if total_ic > 0:
            return {col: ic / total_ic for col, ic in ics.items()}
        return FactorWeightingMethod.equal_weights(factors_df)

    @staticmethod
    def ic_weighted(factors_df: pd.DataFrame, returns: pd.Series) -> pd.Series:
        """
        IC加权
        根据历史IC表现分配权重
        """
        return FactorWeightingMethod._apply_weights(
            factors_df, FactorWeightingMethod.ic_weights(factors_df, returns))

    @staticmethod
    def ir_weights(factors_df: pd.DataFrame, ic_history: Dict[str, List[float]]) -> Dict[str, float]:
        """IR 加权权重（IC 均值/IC 标准差，负 IR 记 0；无历史 → 等权）"""
        factor_cols = FactorWeightingMethod._valid_score_cols(factors_df)

        irs = {}
        for col in factor_cols:
            if col in ic_history and len(ic_history[col]) > 1:
                ic_values = ic_history[col]
                ir = np.mean(ic_values) / (np.std(ic_values) + 1e-8)
                irs[col] = max(0, ir)
            else:
                irs[col] = 1.0

        total_ir = sum(irs.values())
        if total_ir > 0:
            return {col: ir / total_ir for col, ir in irs.items()}
        return FactorWeightingMethod.equal_weights(factors_df)

    @staticmethod
    def ir_weighted(factors_df: pd.DataFrame, ic_history: Dict[str, List[float]]) -> pd.Series:
        """
        IR加权 (Information Ratio加权)
        根据IR (IC均值/IC标准差) 分配权重
        """
        return FactorWeightingMethod._apply_weights(
            factors_df, FactorWeightingMethod.ir_weights(factors_df, ic_history))

    @staticmethod
    def max_sharpe_weights(factors_df: pd.DataFrame, returns: pd.Series,
                           risk_free_rate: float = 0.03) -> Dict[str, float]:
        """
        最大夏普比率优化权重
        优化权重使因子组合夏普比率最大（样本不足 → 等权）

        审计 H6: 因子收益 = 因子值 × **同期**前瞻收益 (同一行 = 同一只
        股票); 旧实现沿 index 错行 shift → 结果依赖行序且含未来信息。
        """
        # 提取因子数据 (审计 H6: 同期配对, 无 shift)
        factor_data, aligned_returns = FactorWeightingMethod._align(
            factors_df, returns)
        factor_cols = list(factor_data.columns)
        n_factors = len(factor_cols)
        if n_factors == 0:
            return {}
        if len(factor_data) < 10:
            return FactorWeightingMethod.equal_weights(factors_df)

        # 计算因子收益协方差矩阵
        factor_returns = pd.DataFrame()
        for col in factor_data.columns:
            # 因子收益 = 该因子值 × 该股**前瞻收益** (同期配对: 同一行
            # = 同一只股票/同一期)。旧实现是 `factor_data[col].shift(-1)
            # * aligned_returns` —— 沿 index 错行一格, 把"下一只股票的
            # 收益"当成"下一期收益" (审计 H6: 结果依赖行序 + 含未来信息)
            factor_returns[col] = factor_data[col] * aligned_returns

        factor_returns = factor_returns.dropna()
        if len(factor_returns) < 10:
            return FactorWeightingMethod.equal_weights(factors_df)

        mean_returns = factor_returns.mean()
        cov_matrix = factor_returns.cov()

        # 优化目标：最大化夏普比率
        def negative_sharpe(weights):
            portfolio_return = np.sum(mean_returns * weights)
            portfolio_std = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            sharpe = (portfolio_return - risk_free_rate / 252) / (portfolio_std + 1e-8)
            return -sharpe

        # 约束条件
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})  # 权重和为1
        bounds = tuple((0, 1) for _ in range(n_factors))  # 权重在0-1之间

        # 初始权重 (等权重)
        x0 = np.array([1.0 / n_factors] * n_factors)

        # 优化
        try:
            result = minimize(negative_sharpe, x0, method='SLSQP',
                            bounds=bounds, constraints=constraints)
            optimal_weights = result.x
        except Exception:
            optimal_weights = np.array([1.0 / n_factors] * n_factors)

        return {factor_cols[i]: float(optimal_weights[i]) for i in range(n_factors)}

    @staticmethod
    def max_sharpe(factors_df: pd.DataFrame, returns: pd.Series,
                   risk_free_rate: float = 0.03) -> pd.Series:
        """
        最大夏普比率加权
        优化权重使组合夏普比率最大
        """
        return FactorWeightingMethod._apply_weights(
            factors_df,
            FactorWeightingMethod.max_sharpe_weights(factors_df, returns, risk_free_rate))

    @staticmethod
    def risk_parity_weights(factors_df: pd.DataFrame, returns: pd.Series) -> Dict[str, float]:
        """
        风险平价优化权重
        使各因子对组合风险的贡献相等（样本不足 → 等权）
        """
        factor_cols = FactorWeightingMethod._valid_score_cols(factors_df)
        n_factors = len(factor_cols)

        if n_factors == 0:
            return {}

        # 提取因子数据 (审计 H6: 同期配对, 无 shift)
        factor_data, aligned_returns = FactorWeightingMethod._align(
            factors_df, returns)
        factor_cols = list(factor_data.columns)
        n_factors = len(factor_cols)
        if n_factors == 0:
            return {}

        # 计算因子收益协方差矩阵
        factor_returns = pd.DataFrame()
        for col in factor_cols:
            # 因子收益 = 因子值 × 同期前瞻收益 (审计 H6: 旧实现
            # `.shift(-1)` 沿 index 错行 → 结果依赖行序 + 含未来信息)
            factor_returns[col] = factor_data[col] * aligned_returns

        factor_returns = factor_returns.dropna()
        if len(factor_returns) < 10:
            return FactorWeightingMethod.equal_weights(factors_df)

        cov_matrix = factor_returns.cov()

        # 风险平价优化
        def risk_budget_objective(weights, cov_matrix):
            # 计算各资产的风险贡献
            portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            marginal_contrib = np.dot(cov_matrix, weights)
            contrib = weights * marginal_contrib / portfolio_vol
            # 目标：使风险贡献相等
            target_contrib = np.ones(n_factors) / n_factors
            return np.sum((contrib - target_contrib) ** 2)

        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
        bounds = tuple((0.01, 1) for _ in range(n_factors))  # 避免零权重
        x0 = np.array([1.0 / n_factors] * n_factors)

        try:
            result = minimize(risk_budget_objective, x0,
                            args=(cov_matrix,),
                            method='SLSQP',
                            bounds=bounds,
                            constraints=constraints)
            optimal_weights = result.x
            optimal_weights = optimal_weights / optimal_weights.sum()  # 归一化
        except Exception:
            optimal_weights = np.array([1.0 / n_factors] * n_factors)

        return {factor_cols[i]: float(optimal_weights[i]) for i in range(n_factors)}

    @staticmethod
    def risk_parity(factors_df: pd.DataFrame, returns: pd.Series) -> pd.Series:
        """
        风险平价加权
        使各因子对组合风险的贡献相等
        """
        return FactorWeightingMethod._apply_weights(
            factors_df, FactorWeightingMethod.risk_parity_weights(factors_df, returns))

    @staticmethod
    def _apply_weights(factors_df: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        """应用权重计算综合得分（全 NaN 的因子列跳过，NaN*权重 仍为 NaN 会毒化整行）"""
        composite_score = pd.Series(0.0, index=factors_df.index)

        for col, weight in weights.items():
            if col in factors_df.columns and factors_df[col].notna().any():
                composite_score += factors_df[col] * weight

        return composite_score


class FactorEffectivenessTester:
    """因子有效性检验器"""

    @staticmethod
    def calculate_ic(factor_values: pd.Series, returns: pd.Series,
                    method: str = 'pearson') -> float:
        """
        计算IC (Information Coefficient)
        因子值与未来收益率的相关系数

        Args:
            factor_values: 因子值
            returns: 未来收益率
            method: 'pearson' 或 'spearman'

        Returns:
            IC值
        """
        # 对齐数据
        aligned_idx = factor_values.notna() & returns.notna()
        factor_aligned = factor_values[aligned_idx]
        returns_aligned = returns[aligned_idx]

        if len(factor_aligned) < 5:
            return np.nan

        if method == 'pearson':
            ic = factor_aligned.corr(returns_aligned)
        elif method == 'spearman':
            ic = factor_aligned.corr(returns_aligned, method='spearman')
        else:
            ic = np.nan

        return ic if not np.isnan(ic) else 0.0

    @staticmethod
    def test_factor(factor_values: pd.Series, returns: pd.Series,
                   method: str = 'pearson') -> FactorTestResult:
        """
        测试单个因子的有效性

        Args:
            factor_values: 因子值序列
            returns: 收益率序列
            method: 相关性计算方法

        Returns:
            因子测试结果
        """
        # 滚动计算IC序列
        ic_series = []
        min_periods = 20

        for i in range(min_periods, len(factor_values)):
            factor_slice = factor_values.iloc[i-min_periods:i]
            returns_slice = returns.iloc[i-min_periods:i]

            ic = FactorEffectivenessTester.calculate_ic(factor_slice, returns_slice, method)
            if not np.isnan(ic):
                ic_series.append(ic)

        if len(ic_series) == 0:
            return FactorTestResult(
                factor_name='unknown',
                ic_mean=0, ic_std=0, ir=0,
                ic_positive_ratio=0, rank_ic=0,
                t_stat=0, p_value=1, is_significant=False,
                mode='time_series'
            )

        ic_array = np.array(ic_series)
        ic_mean = np.mean(ic_array)
        ic_std = np.std(ic_array)
        ir = ic_mean / (ic_std + 1e-8)
        ic_positive_ratio = np.sum(ic_array > 0) / len(ic_array)

        # 计算Rank IC
        rank_ic = factor_values.rank().corr(returns.rank())

        # t检验
        t_stat = ic_mean * np.sqrt(len(ic_array)) / (ic_std + 1e-8)
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), len(ic_array) - 1))

        is_significant = p_value < 0.05

        return FactorTestResult(
            factor_name='factor',
            ic_mean=ic_mean,
            ic_std=ic_std,
            ir=ir,
            ic_positive_ratio=ic_positive_ratio,
            rank_ic=rank_ic,
            t_stat=t_stat,
            p_value=p_value,
            is_significant=is_significant,
            mode='time_series'
        )

    @staticmethod
    def test_factor_cross_section(factor_values: pd.Series,
                                  returns: pd.Series,
                                  method: str = 'pearson') -> FactorTestResult:
        """横截面口径的因子检验 (同期配对, 单一截面)。

        审计 H6: 旧 `test_all_factors` 用 `factors_df[col].shift(1)` ——
        那是沿 **index** 错行一格 (股票轴!), 把"上一只股票的因子"当成
        "上一期因子" → IC 完全无意义 (且随行序变化)。横截面下正确的
        配对是**同期**: 因子[i] 对该股前瞻收益[i]。

        单截面只有 1 个 IC 观测 → 时序统计量 (ic_std/ir/正值比例/t 检验)
        **不可得**, 如实记 NaN 且 `is_significant=False` (不拿一个截面
        假装有统计显著性)。
        """
        aligned = factor_values.notna() & returns.notna()
        fv = factor_values[aligned]
        rv = returns[aligned]
        if len(fv) < 5:
            return FactorTestResult(
                factor_name='unknown', ic_mean=float('nan'),
                ic_std=float('nan'), ir=float('nan'),
                ic_positive_ratio=float('nan'), rank_ic=float('nan'),
                t_stat=float('nan'), p_value=float('nan'),
                is_significant=False, mode='cross_section')

        ic = FactorEffectivenessTester.calculate_ic(fv, rv, method)
        rank_ic = fv.rank().corr(rv.rank())
        return FactorTestResult(
            factor_name='factor',
            ic_mean=ic,
            ic_std=float('nan'),
            ir=float('nan'),
            ic_positive_ratio=float('nan'),
            rank_ic=float(rank_ic) if not np.isnan(rank_ic) else float('nan'),
            t_stat=float('nan'),
            p_value=float('nan'),
            is_significant=False,
            mode='cross_section')

    @staticmethod
    def test_all_factors(factors_df: pd.DataFrame, returns: pd.Series,
                         method: str = 'pearson',
                         window: int = None) -> Dict[str, FactorTestResult]:
        """
        测试所有因子的有效性

        审计 H6: 口径显式化 —— 旧实现对**同一份** `returns` 用三种配对
        (`ic_weights` 同期 / `test_all_factors` `.shift(1)` 错行 /
        `max_sharpe_weights` `.shift(-1)` 错行+前瞻), 互相矛盾。

        Args:
            factors_df: 因子DataFrame
            returns: 收益率Series (**前瞻收益**标签, 同期配对)
            method: 相关性计算方法
            window: None → **横截面口径** (同期配对, 单一截面, 时序统计
                不可得 → 如实记 NaN); 给定窗口长度 → **时序口径**
                (滚动 IC, 要求 index 为时间索引, 否则 ValueError ——
                绝不用股票代码轴做滚动窗口)

        Returns:
            因子名到测试结果的字典
        """
        results = {}

        factor_cols = [col for col in factors_df.columns
                       if col.endswith('_Score') or col.endswith('_Factor')]

        time_series = window is not None
        if time_series:
            if not isinstance(factors_df.index, pd.DatetimeIndex):
                raise ValueError(
                    '时序口径 (window 指定) 要求 factors_df 的 index 为时间索引; '
                    f'当前 index 类型={type(factors_df.index).__name__} — '
                    '横截面请用 window=None (默认)')

        for col in factor_cols:
            # 同期配对 (审计 H6: 不再沿 index 错行 shift)
            factor_values = factors_df[col]
            aligned_idx = factor_values.notna() & returns.notna()

            if time_series:
                if aligned_idx.sum() > 30:
                    result = FactorEffectivenessTester.test_factor(
                        factor_values[aligned_idx],
                        returns[aligned_idx],
                        method
                    )
                    result.factor_name = col
                    result.mode = 'time_series'
                    results[col] = result
            else:
                if aligned_idx.sum() > 5:
                    result = FactorEffectivenessTester.test_factor_cross_section(
                        factor_values[aligned_idx],
                        returns[aligned_idx],
                        method
                    )
                    result.factor_name = col
                    results[col] = result

        return results

    @staticmethod
    def generate_test_report(test_results: Dict[str, FactorTestResult]) -> str:
        """生成因子测试报告"""
        report = []
        report.append("=" * 100)
        report.append("                           Factor Effectiveness Test Report")
        report.append("=" * 100)
        report.append("")

        # 表头
        header = "{:<25} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8}".format(
            "Factor", "IC Mean", "IC Std", "IR", "Rank IC", "Pos %", "Signif"
        )
        report.append(header)
        report.append("-" * 100)

        # 按IR排序
        sorted_results = sorted(test_results.items(),
                               key=lambda x: abs(x[1].ir),
                               reverse=True)

        for factor_name, result in sorted_results:
            signif = "Yes" if result.is_significant else "No"
            row = "{:<25} {:>10.4f} {:>10.4f} {:>10.4f} {:>10.4f} {:>10.1f}% {:>8}".format(
                factor_name[:24],
                result.ic_mean,
                result.ic_std,
                result.ir,
                result.rank_ic,
                result.ic_positive_ratio * 100,
                signif
            )
            report.append(row)

        report.append("=" * 100)

        # 统计摘要
        total = len(test_results)
        significant = sum(1 for r in test_results.values() if r.is_significant)
        report.append("")
        report.append(f"Summary: {significant}/{total} factors are significant at 5% level")

        return "\n".join(report)


class FactorModels:
    """因子计算模型"""

    @staticmethod
    def value_factor(df) -> pd.DataFrame:
        """
        价值因子
        PE, PB, PS, PCF, 股息率等

        Args:
            df: 财务指标数据

        Returns:
            因子得分DataFrame
        """
        factors = pd.DataFrame()

        # PE (倒数，越低越好)
        if '市盈率-动态' in df.columns:
            pe = df['市盈率-动态'].replace(0, np.nan)
            factors['PE_Factor'] = 1 / pe

        # PB (倒数)
        if '市净率' in df.columns:
            pb = df['市净率'].replace(0, np.nan)
            factors['PB_Factor'] = 1 / pb

        # PS (倒数)
        if '市销率' in df.columns:
            ps = df['市销率'].replace(0, np.nan)
            factors['PS_Factor'] = 1 / ps

        # PCF (倒数)
        if '市现率' in df.columns:
            pcf = df['市现率'].replace(0, np.nan)
            factors['PCF_Factor'] = 1 / pcf

        # 股息率
        if '股息率' in df.columns:
            factors['Dividend_Yield'] = df['股息率']

        # 综合价值得分 (标准化后平均)
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Value_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def growth_factor(df) -> pd.DataFrame:
        """
        成长因子
        营收增长率、利润增长率、净利率等成长性指标

        审计 C-P1-14: ROE/毛利率原在 growth 与 quality 双计 (合计有效权重
        18.3% 隐性重复) — 已移除, 盈利水平指标统一归 quality_factor。
        Net_Margin 非重复计权, 保留 (盈利水平但仅本块使用)。

        Args:
            df: 财务指标数据

        Returns:
            因子得分DataFrame
        """
        factors = pd.DataFrame()

        # 营收增长率
        if '营业总收入同比增长' in df.columns:
            factors['Revenue_Growth'] = df['营业总收入同比增长']

        # 利润增长率
        if '净利润同比增长' in df.columns:
            factors['Profit_Growth'] = df['净利润同比增长']

        # 净利率
        if '销售净利率' in df.columns:
            factors['Net_Margin'] = df['销售净利率']

        # 标准化
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Growth_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def quality_factor(df) -> pd.DataFrame:
        """
        质量因子
        盈利稳定性、财务健康度、运营效率

        Args:
            df: 财务指标数据

        Returns:
            因子得分DataFrame
        """
        factors = pd.DataFrame()

        # ROE (高盈利能力)
        if '净资产收益率' in df.columns:
            factors['ROE'] = df['净资产收益率']

        # ROA
        if '总资产净利率' in df.columns:
            factors['ROA'] = df['总资产净利率']

        # 毛利率 (高毛利率通常代表竞争优势)
        if '销售毛利率' in df.columns:
            factors['Gross_Margin'] = df['销售毛利率']

        # 资产负债率 (倒数，低杠杆)
        if '资产负债率' in df.columns:
            debt_ratio = df['资产负债率']
            factors['Debt_Ratio'] = -debt_ratio  # 负债率越低越好

        # 流动比率 (高流动性)
        if '流动比率' in df.columns:
            factors['Current_Ratio'] = df['流动比率']

        # 速动比率
        if '速动比率' in df.columns:
            factors['Quick_Ratio'] = df['速动比率']

        # 标准化
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Quality_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def _price_cross_section(price_df) -> Optional[pd.DataFrame]:
        """
        将价格输入归一化为“股票×日期”横截面面板（index=股票码, columns=日期）。

        委托 factor_library.to_close_panel (C-P1-11 因子库统一);
        保留方法名兼容既有调用/测试。
        """
        return factor_library.to_close_panel(price_df)

    @staticmethod
    def momentum_factor(price_df, periods=[20, 60, 120]) -> pd.DataFrame:
        """
        动量因子
        每只股票过去N日的收益率（横截面：index=股票码）

        Args:
            price_df: 价格数据（宽面板或 (股票,日期) 堆叠行，见 _price_cross_section）
            periods: 计算周期列表

        Returns:
            因子得分DataFrame（无法构成横截面时返回空表）
        """
        raw = factor_library.momentum_panel(
            FactorModels._price_cross_section(price_df), periods)

        if raw.shape[1] == 0:
            return raw  # 数据不足，无法计算任何周期

        # 标准化（横截面）— z-score 是 MFS 引擎职责, 不入库
        factors = raw.copy()
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Momentum_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def volatility_factor(price_df, period=20) -> pd.DataFrame:
        """
        波动率因子
        历史波动率、下行风险（横截面：index=股票码，负值表示低波动更好）

        Args:
            price_df: 价格数据（宽面板或 (股票,日期) 堆叠行，见 _price_cross_section）
            period: 计算周期

        Returns:
            因子得分DataFrame (负值表示低波动更好；无法构成横截面时返回空表)
        """
        panel = FactorModels._price_cross_section(price_df)
        if panel is None or panel.shape[1] < 2:
            return pd.DataFrame()

        # 原始值来自因子库; 方向应用（取负 = 低波动得高分）留在引擎层
        factors = pd.DataFrame()
        factors['Volatility'] = -factor_library.realized_volatility_panel(panel, period)
        factors['Downside_Vol'] = -factor_library.downside_volatility_panel(panel, period)
        factors['Max_Drawdown'] = factor_library.max_drawdown_panel(panel, period)

        # 标准化（横截面）
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Volatility_Score'] = factors.mean(axis=1)

        return factors


class MultiFactorSelector:
    """多因子选股器 - 增强版"""

    def __init__(self, factor_weights: Dict[str, float] = None,
                 weighting_method: str = None):
        """
        初始化多因子选股器

        Args:
            factor_weights: 因子权重，如 {'value': 0.3, 'growth': 0.3, 'quality': 0.2, 'momentum': 0.2}
                None 时读 config/multi_factor.json (C-P1-11 Step2); 配置缺失回退内置默认
            weighting_method: 加权方法 ('custom' 使用 factor_weights 配置[默认],
                'equal' 等权, 'ic', 'ir', 'max_sharpe', 'risk_parity')
                None 时读配置文件; 配置缺失回退 'custom'
        """
        cfg = factor_library.load_config('multi_factor') or {}

        if factor_weights is None:
            factor_weights = cfg.get('factor_weights') or {
                'value': 0.25,
                'growth': 0.25,
                'quality': 0.25,
                'momentum': 0.15,
                'volatility': 0.10
            }

        if weighting_method is None:
            weighting_method = cfg.get('weighting_method') or 'custom'

        self.factor_weights = factor_weights
        self.weighting_method = weighting_method
        self.factor_models = FactorModels()
        self.weighting_class = FactorWeightingMethod()
        self.tester = FactorEffectivenessTester()

        # 存储历史IC用于IR加权
        self.ic_history: Dict[str, List[float]] = {}

        # 审计 H6: 最近一次权重拟合的口径自证 (in_sample / n_fit_rows)
        self.last_weight_fit: Dict[str, object] = {}

    def calculate_factors(self, financial_df: pd.DataFrame,
                         price_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        计算所有因子

        Args:
            financial_df: 财务数据
            price_df: 价格数据 (可选，用于动量和波动率因子)

        Returns:
            因子DataFrame
        """
        all_factors = pd.DataFrame(index=financial_df.index)

        def _attach(factor_result, score_col):
            # 仅并入与股票池对齐、且有有效值的得分列：
            # ① 全 NaN 列会毒化综合分（NaN*权重 仍为 NaN）；② reindex 防止价格面板独有股票经 concat 外联进股票池
            if factor_result is None or score_col not in factor_result.columns:
                return
            col = factor_result[score_col].reindex(all_factors.index)
            if col.notna().any():
                all_factors[score_col] = col

        # 价值因子
        try:
            _attach(self.factor_models.value_factor(financial_df), 'Value_Score')
        except Exception as e:
            print(f"[WARN] 价值因子计算失败, 该因子缺席: {str(e)[:80]}")

        # 成长因子
        try:
            _attach(self.factor_models.growth_factor(financial_df), 'Growth_Score')
        except Exception as e:
            print(f"[WARN] 成长因子计算失败, 该因子缺席: {str(e)[:80]}")

        # 质量因子
        try:
            _attach(self.factor_models.quality_factor(financial_df), 'Quality_Score')
        except Exception as e:
            print(f"[WARN] 质量因子计算失败, 该因子缺席: {str(e)[:80]}")

        # 动量和波动率因子 (需要价格数据)
        if price_df is not None and len(price_df) > 0:
            try:
                _attach(self.factor_models.momentum_factor(price_df), 'Momentum_Score')
            except Exception as e:
                print(f"[WARN] 动量因子计算失败, 该因子缺席: {str(e)[:80]}")

            try:
                _attach(self.factor_models.volatility_factor(price_df), 'Volatility_Score')
            except Exception as e:
                print(f"[WARN] 波动率因子计算失败, 该因子缺席: {str(e)[:80]}")

        return all_factors

    def get_composite_score(self, factors_df: pd.DataFrame,
                           returns: pd.Series = None,
                           fitted_weights: Dict[str, float] = None,
                           fit_returns: pd.Series = None) -> pd.Series:
        """
        计算综合得分

        审计 H6 (样本内 vs 样本外): 动态加权方法的权重是用**标签**拟合的,
        若用被评分截面自己的标签去拟合 → **样本内** (权重天然被高估,
        选出的"最优"截面是拟合产物而非预测)。旧实现对此**完全沉默**。

        Args:
            factors_df: 因子DataFrame (index = 股票代码)
            returns: 前瞻收益标签 (与 factors_df 同期配对)
            fitted_weights: 已拟合好的权重 (来自**历史**样本) → 直接套用,
                天然样本外, 不再就地拟合
            fit_returns: 用于拟合的标签 (与 returns 不同期时 → 样本外拟合;
                None → 用 returns 拟合 → **样本内**, 如实标记 + 告警)

        Returns:
            综合得分Series
        """
        self.last_weight_fit = {}

        # ① 外部已拟合权重 → 直接套用 (样本外)
        if fitted_weights:
            self.last_weight_fit = {
                'method': 'fitted_weights',
                'in_sample': False,
                'n_fit_rows': 0,
            }
            return self.weighting_class._apply_weights(factors_df,
                                                      fitted_weights)

        if self.weighting_method == 'equal':
            self.last_weight_fit = {'method': 'equal', 'in_sample': False,
                                     'n_fit_rows': 0}
            return self.weighting_class.equal_weight(factors_df)

        elif self.weighting_method == 'custom':
            self.last_weight_fit = {'method': 'custom', 'in_sample': False,
                                     'n_fit_rows': 0}
            return self._apply_custom_weights(factors_df)

        elif self.weighting_method == 'ir':
            # IR 用历史 IC 序列 (本就是历史信息) → 样本外
            self.last_weight_fit = {'method': 'ir', 'in_sample': False,
                                     'n_fit_rows': len(self.ic_history)}
            return self.weighting_class.ir_weighted(factors_df, self.ic_history)

        # 需要拟合标签的方法 ('ic' / 'max_sharpe' / 'risk_parity')
        fit_src = fit_returns if fit_returns is not None else returns
        if fit_src is None:
            # 无标签 → 回退配置权重 (不静默用等权冒充"拟合结果")
            self.last_weight_fit = {'method': self.weighting_method,
                                     'in_sample': False, 'n_fit_rows': 0,
                                     'note': '缺少拟合标签 → 回退配置权重'}
            return self._apply_custom_weights(factors_df)

        in_sample = fit_returns is None
        factor_data, _ = FactorWeightingMethod._align(factors_df, fit_src)
        self.last_weight_fit = {
            'method': self.weighting_method,
            'in_sample': in_sample,
            'n_fit_rows': int(len(factor_data)),
        }
        if in_sample:
            print("[WARN] 因子权重为**样本内拟合** (in-sample): 权重用被评分"
                  "截面自己的前瞻收益拟合 → 权重天然偏乐观, 选股结果含拟合"
                  "产物。要样本外请传 fit_returns (历史期标签) 或 "
                  "fitted_weights (已拟合权重)")

        if self.weighting_method == 'ic':
            return self.weighting_class.ic_weighted(factors_df, fit_src)

        elif self.weighting_method == 'max_sharpe':
            return self.weighting_class.max_sharpe(factors_df, fit_src)

        elif self.weighting_method == 'risk_parity':
            return self.weighting_class.risk_parity(factors_df, fit_src)

        else:
            # 未识别方法 → 使用配置权重
            self.last_weight_fit = {'method': 'fallback', 'in_sample': False,
                                     'n_fit_rows': 0}
            return self._apply_custom_weights(factors_df)

    def _apply_custom_weights(self, factors_df: pd.DataFrame) -> pd.Series:
        """应用 factor_weights 配置权重（按现存因子重归一化，全 NaN 列跳过）"""
        composite_score = pd.Series(0.0, index=factors_df.index)

        factor_mapping = {
            'Value_Score': 'value',
            'Growth_Score': 'growth',
            'Quality_Score': 'quality',
            'Momentum_Score': 'momentum',
            'Volatility_Score': 'volatility'
        }

        weights = {}
        for factor_col, factor_name in factor_mapping.items():
            if factor_col in factors_df.columns and factor_name in self.factor_weights:
                if not factors_df[factor_col].notna().any():
                    continue  # 全 NaN 列会毒化综合分
                weights[factor_col] = self.factor_weights[factor_name]

        # 按现存因子重归一化，保证 min_score 刻度不随因子可得性漂移
        total = sum(weights.values())
        if total > 0:
            weights = {col: w / total for col, w in weights.items()}

        for factor_col, weight in weights.items():
            composite_score += factors_df[factor_col] * weight

        return composite_score

    def select_stocks(self, financial_df: pd.DataFrame, price_df: pd.DataFrame = None,
                      top_n: int = 20, min_score: float = None,
                      returns: pd.Series = None, as_of=None,
                      fit_returns: pd.Series = None,
                      fitted_weights: Dict[str, float] = None) -> pd.DataFrame:
        """
        选股

        Args:
            financial_df: 财务数据 (必须含『公告日』列, C-P0-7 point-in-time 契约)
            price_df: 价格数据 (可选)
            top_n: 返回前N只股票
            min_score: 最低得分要求 (None表示不限制)
            returns: 前瞻收益标签 (用于动态加权; **样本内** → 见审计 H6)
            as_of: 截止日 (必填: 只使用公告日 ≤ as_of 的财报)
            fit_returns: 用于拟合权重的标签 (历史期 → 样本外拟合)
            fitted_weights: 已拟合好的权重 (来自历史样本 → 直接套用)

        Returns:
            选股结果DataFrame (attrs['weight_fit'] 记录权重拟合口径)

        Raises:
            ValueError: 缺『公告日』列或未提供 as_of (拒绝静默泄露)
        """
        # C-P0-7: 按公告日过滤, 拒绝无公告日/无截止日的调用
        financial_df = filter_point_in_time(financial_df, as_of)

        # 计算因子
        factors_df = self.calculate_factors(financial_df, price_df)

        if len(factors_df.columns) == 0:
            return pd.DataFrame()

        # 计算综合得分 (审计 H6: 样本内/样本外口径显式化)
        composite_score = self.get_composite_score(
            factors_df, returns,
            fitted_weights=fitted_weights, fit_returns=fit_returns)
        factors_df['Composite_Score'] = composite_score

        # 审计 C-P1-12: 收盘面板前置过滤 (min_price + 最新交易日缺数据;
        # 一字板需高低价、ADV 需成交额 — 仅收盘面板时不伪造检查)。
        # 在排序/截断前过滤, 保证 top_n 由可执行标的填满。
        if price_df is not None and len(factors_df) > 0:
            panel = FactorModels._price_cross_section(price_df)
            if panel is not None and len(panel) > 0:
                keep, _ = trade_constraints.check_close_panel(panel)
                drop = [c for c in factors_df.index
                        if c in keep.index and not keep[c]]
                if drop:
                    factors_df = factors_df.drop(index=drop)

        # 排序
        factors_df = factors_df.sort_values('Composite_Score', ascending=False)

        # 筛选
        if min_score is not None:
            selected = factors_df[factors_df['Composite_Score'] >= min_score].head(top_n)
        else:
            selected = factors_df.head(top_n)

        # 审计 H6: 权重拟合口径随结果一起返回 (in_sample / n_fit_rows)
        selected.attrs['weight_fit'] = dict(self.last_weight_fit)

        return selected

    def analyze_factor_contributions(self, stock_code: str, financial_df: pd.DataFrame,
                                   price_df: pd.DataFrame = None) -> Dict:
        """
        分析因子贡献

        Args:
            stock_code: 股票代码
            financial_df: 财务数据
            price_df: 价格数据

        Returns:
            因子贡献分析
        """
        factors_df = self.calculate_factors(financial_df, price_df)

        if stock_code not in factors_df.index:
            return {'error': f'Stock {stock_code} not found'}

        stock_factors = factors_df.loc[stock_code]

        contributions = {}
        factor_mapping = {
            'Value_Score': 'value',
            'Growth_Score': 'growth',
            'Quality_Score': 'quality',
            'Momentum_Score': 'momentum',
            'Volatility_Score': 'volatility'
        }

        for factor_col, factor_name in factor_mapping.items():
            if factor_col in stock_factors:
                weight = self.factor_weights.get(factor_name, 0)
                contribution = stock_factors[factor_col] * weight
                contributions[factor_name] = {
                    'score': stock_factors[factor_col],
                    'weight': weight,
                    'contribution': contribution
                }

        return {
            'stock_code': stock_code,
            'composite_score': stock_factors.get('Composite_Score', 0),
            'factor_contributions': contributions
        }

    def test_factor_effectiveness(self, factors_df: pd.DataFrame,
                                  returns: pd.Series) -> Dict[str, FactorTestResult]:
        """
        测试因子有效性

        Args:
            factors_df: 因子DataFrame
            returns: 收益率Series

        Returns:
            因子测试结果字典
        """
        return self.tester.test_all_factors(factors_df, returns)

    def optimize_weights(self, factors_df: pd.DataFrame,
                         returns: pd.Series,
                         method: str = 'max_sharpe') -> Dict[str, float]:
        """
        优化因子权重

        审计 H6: 权重是在**给定样本**上拟合的 —— 调用方必须保证"拟合样本"
        与"应用样本"不重叠 (否则是样本内, 权重偏乐观)。返回的权重**不含**
        口径信息, 应用侧请用 `get_composite_score(..., fit_returns=...)` 或
        `fitted_weights=...` 显式声明样本外, 或接受 in_sample 标记。

        Args:
            factors_df: 因子DataFrame (index = 股票代码)
            returns: **前瞻收益**标签 (与 factors_df 同期配对)
            method: 优化方法 ('max_sharpe', 'risk_parity', 'ic', 'equal', 'custom')

        Returns:
            优化后的权重字典（key=因子得分列名，value=权重；按现存因子归一化）
        """
        if method == 'equal':
            return FactorWeightingMethod.equal_weights(factors_df)

        elif method == 'max_sharpe':
            return FactorWeightingMethod.max_sharpe_weights(factors_df, returns)

        elif method == 'risk_parity':
            return FactorWeightingMethod.risk_parity_weights(factors_df, returns)

        elif method == 'ic':
            return FactorWeightingMethod.ic_weights(factors_df, returns)

        elif method == 'custom':
            # 配置权重按现存因子重归一化
            factor_mapping = {
                'Value_Score': 'value',
                'Growth_Score': 'growth',
                'Quality_Score': 'quality',
                'Momentum_Score': 'momentum',
                'Volatility_Score': 'volatility'
            }
            weights = {}
            for factor_col, factor_name in factor_mapping.items():
                if factor_col in factors_df.columns and factor_name in self.factor_weights:
                    if not factors_df[factor_col].notna().any():
                        continue
                    weights[factor_col] = self.factor_weights[factor_name]
            total = sum(weights.values())
            if total > 0:
                weights = {col: w / total for col, w in weights.items()}
            return weights

        else:
            return self.factor_weights.copy()


class PortfolioOptimizer:
    """组合优化器"""

    @staticmethod
    def markowitz_optimization(expected_returns: pd.Series,
                               cov_matrix: pd.DataFrame,
                               risk_free_rate: float = 0.03,
                               target_return: float = None) -> Dict:
        """
        马科维茨均值-方差优化

        Args:
            expected_returns: 预期收益率
            cov_matrix: 协方差矩阵
            risk_free_rate: 无风险利率
            target_return: 目标收益率 (None表示最大化夏普比率)

        Returns:
            优化结果字典
        """
        n_assets = len(expected_returns)

        def portfolio_variance(weights):
            return np.dot(weights.T, np.dot(cov_matrix, weights))

        def portfolio_return(weights):
            return np.sum(expected_returns * weights)

        def sharpe_ratio(weights):
            p_return = portfolio_return(weights)
            p_var = portfolio_variance(weights)
            return (p_return - risk_free_rate) / np.sqrt(p_var)

        # 约束条件
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]  # 权重和为1

        if target_return is not None:
            constraints.append({'type': 'eq', 'fun': lambda w: portfolio_return(w) - target_return})

        bounds = tuple((0, 1) for _ in range(n_assets))  # 不允许做空
        x0 = np.array([1.0 / n_assets] * n_assets)  # 初始等权重

        # 优化
        if target_return is None:
            # 最大化夏普比率
            def objective(weights):
                return -sharpe_ratio(weights)
        else:
            # 最小化方差
            def objective(weights):
                return portfolio_variance(weights)

        try:
            result = minimize(objective, x0, method='SLSQP',
                            bounds=bounds, constraints=constraints)

            if result.success:
                optimal_weights = result.x
                opt_return = portfolio_return(optimal_weights)
                opt_var = portfolio_variance(optimal_weights)
                opt_std = np.sqrt(opt_var)
                opt_sharpe = (opt_return - risk_free_rate) / opt_std

                return {
                    'weights': dict(zip(expected_returns.index, optimal_weights)),
                    'expected_return': opt_return,
                    'expected_std': opt_std,
                    'sharpe_ratio': opt_sharpe,
                    'success': True
                }
        except Exception as e:
            print(f"[WARN] 权重优化失败, 回退等权重: {str(e)[:80]}")

        # 如果优化失败，返回等权重
        equal_weights = np.array([1.0 / n_assets] * n_assets)
        eq_return = portfolio_return(equal_weights)
        eq_var = portfolio_variance(equal_weights)

        return {
            'weights': dict(zip(expected_returns.index, equal_weights)),
            'expected_return': eq_return,
            'expected_std': np.sqrt(eq_var),
            'sharpe_ratio': (eq_return - risk_free_rate) / np.sqrt(eq_var),
            'success': False
        }

    @staticmethod
    def equal_risk_contribution(returns_df: pd.DataFrame) -> Dict:
        """
        等风险贡献组合 (Risk Parity)

        Args:
            returns_df: 收益率DataFrame

        Returns:
            权重字典
        """
        cov_matrix = returns_df.cov()
        n_assets = len(cov_matrix)

        def risk_budget_objective(weights):
            portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            marginal_contrib = np.dot(cov_matrix, weights)
            contrib = weights * marginal_contrib / portfolio_vol
            target_contrib = np.ones(n_assets) / n_assets
            return np.sum((contrib - target_contrib) ** 2)

        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = tuple((0.01, 1) for _ in range(n_assets))  # 避免零权重
        x0 = np.array([1.0 / n_assets] * n_assets)

        try:
            result = minimize(risk_budget_objective, x0,
                            method='SLSQP',
                            bounds=bounds,
                            constraints=constraints)
            if result.success:
                weights = result.x / result.x.sum()
                return dict(zip(returns_df.columns, weights))
        except Exception as e:
            print(f"[WARN] 风险平价优化失败, 回退等权重: {str(e)[:80]}")

        # 失败时返回等权重
        equal_weights = np.array([1.0 / n_assets] * n_assets)
        return dict(zip(returns_df.columns, equal_weights))

    @staticmethod
    def min_variance_optimization(cov_matrix: pd.DataFrame) -> Dict:
        """
        最小方差组合

        Args:
            cov_matrix: 协方差矩阵

        Returns:
            权重字典
        """
        n_assets = len(cov_matrix)

        def portfolio_variance(weights):
            return np.dot(weights.T, np.dot(cov_matrix.values, weights))

        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = tuple((0, 1) for _ in range(n_assets))
        x0 = np.array([1.0 / n_assets] * n_assets)

        try:
            result = minimize(portfolio_variance, x0,
                            method='SLSQP',
                            bounds=bounds,
                            constraints=constraints)
            if result.success:
                weights = result.x
                return dict(zip(cov_matrix.index, weights))
        except Exception as e:
            print(f"[WARN] 最小方差优化失败, 回退等权重: {str(e)[:80]}")

        # 失败时返回等权重
        equal_weights = np.array([1.0 / n_assets] * n_assets)
        return dict(zip(cov_matrix.index, equal_weights))

    @staticmethod
    def inverse_volatility_weights(returns_df: pd.DataFrame) -> Dict:
        """
        反波动率加权

        Args:
            returns_df: 收益率DataFrame

        Returns:
            权重字典
        """
        volatility = returns_df.std()
        inv_vol = 1.0 / volatility
        weights = inv_vol / inv_vol.sum()
        return dict(zip(returns_df.columns, weights))

    @staticmethod
    def equal_weights(assets: List[str]) -> Dict:
        """
        等权重组合

        Args:
            assets: 资产列表

        Returns:
            权重字典
        """
        n = len(assets)
        weight = 1.0 / n
        return {asset: weight for asset in assets}


class SmartBetaStrategy:
    """Smart Beta策略"""

    @staticmethod
    def low_volatility(returns_df: pd.DataFrame, top_n: int = 20) -> List[str]:
        """
        低波动策略
        选择波动率最低的股票

        Args:
            returns_df: 收益率DataFrame
            top_n: 选择数量

        Returns:
            股票代码列表
        """
        volatility = returns_df.std()
        return volatility.nsmallest(top_n).index.tolist()

    @staticmethod
    def high_dividend(financial_df: pd.DataFrame, top_n: int = 20) -> List[str]:
        """
        高股息策略
        选择股息率最高的股票

        Args:
            financial_df: 财务数据
            top_n: 选择数量

        Returns:
            股票代码列表
        """
        if '股息率' not in financial_df.columns:
            return []

        dividend = financial_df['股息_rate'] if '股息_rate' in financial_df.columns else financial_df['股息率']
        return dividend.nlargest(top_n).index.tolist()

    @staticmethod
    def quality_factor(financial_df: pd.DataFrame, top_n: int = 20) -> List[str]:
        """
        质量因子策略
        选择ROE最高的股票

        Args:
            financial_df: 财务数据
            top_n: 选择数量

        Returns:
            股票代码列表
        """
        if '净资产收益率' not in financial_df.columns:
            return []

        roe = financial_df['净资产收益率']
        return roe.nlargest(top_n).index.tolist()

    @staticmethod
    def momentum_strategy(price_df: pd.DataFrame, period: int = 120, top_n: int = 20) -> List[str]:
        """
        动量策略
        选择过去N期涨幅最大的股票

        Args:
            price_df: 价格DataFrame（宽面板或 (股票,日期) 堆叠行，见 FactorModels._price_cross_section）
            period: 回溯周期
            top_n: 选择数量

        Returns:
            股票代码列表（无法构成横截面时返回空列表）
        """
        panel = FactorModels._price_cross_section(price_df)
        if panel is None or panel.shape[1] <= period:
            return []
        momentum = panel.pct_change(period, axis=1).iloc[:, -1]
        return momentum.nlargest(top_n).index.tolist()


# 便捷函数
def multi_factor_select(financial_df, price_df=None, top_n=20, weighting_method='custom',
                        as_of=None, returns=None, fit_returns=None,
                        fitted_weights=None):
    """多因子选股（默认 'custom'：使用构造器默认 factor_weights）

    as_of 必填 (C-P0-7): 只使用公告日 ≤ as_of 的财报。
    审计 H6: 动态加权方法 (ic/max_sharpe/risk_parity) 需要收益标签 ——
    用 `returns` 拟合即**样本内** (如实标记 + 告警); 要样本外请传
    `fit_returns` (历史期标签) 或 `fitted_weights` (已拟合权重)。
    """
    selector = MultiFactorSelector(weighting_method=weighting_method)
    return selector.select_stocks(financial_df, price_df, top_n, as_of=as_of,
                                  returns=returns, fit_returns=fit_returns,
                                  fitted_weights=fitted_weights)


def test_factor_effectiveness(factors_df, returns, window=None):
    """测试因子有效性 (window=None → 横截面口径; 给定窗口 → 时序口径)"""
    tester = FactorEffectivenessTester()
    results = tester.test_all_factors(factors_df, returns, window=window)
    return tester.generate_test_report(results)


def optimize_portfolio_markowitz(returns_df, risk_free_rate=0.03):
    """马科维茨组合优化"""
    optimizer = PortfolioOptimizer()
    expected_returns = returns_df.mean() * 252  # 年化
    cov_matrix = returns_df.cov() * 252  # 年化
    return optimizer.markowitz_optimization(expected_returns, cov_matrix, risk_free_rate)


def optimize_portfolio_risk_parity(returns_df):
    """风险平价组合优化"""
    optimizer = PortfolioOptimizer()
    return optimizer.equal_risk_contribution(returns_df)


def optimize_portfolio_min_variance(returns_df):
    """最小方差组合优化"""
    optimizer = PortfolioOptimizer()
    cov_matrix = returns_df.cov() * 252
    return optimizer.min_variance_optimization(cov_matrix)


def to_selections(result_df: pd.DataFrame, as_of=None,
                  selected: bool = True) -> list:
    """select_stocks 结果 → 统一契约 Selection 列表 (审计 C #9b).

    Args:
        result_df: `select_stocks` 返回的因子+综合分 DataFrame
            (index=股票代码, 含 Composite_Score 列)
        as_of: 选股基准日 (与 select_stocks 的 as_of 同值 — MFS 有真实
            point-in-time 公告日过滤语义, 契约里如实记录)
        selected: 是否标记入选 (select_stocks 已按 top_n/min_score 截断,
            默认全部 True; 调用方拿全量因子表再标注时传 False)

    Returns:
        list[core.signal.Selection], 按传入顺序排名 (1-based);
        Composite_Score 为 NaN 的行跳过 (无有效分数不入契约)。
    """
    from core.signal import SCALE_ZSCORE, Selection, normalize_date

    out = []
    if result_df is None or len(result_df) == 0:
        return out
    rank = 0
    for code, row in result_df.iterrows():
        if 'Composite_Score' not in result_df.columns:
            break
        score = row['Composite_Score']
        if pd.isna(score):
            continue
        rank += 1
        factor_snapshot = {
            str(c): float(row[c])
            for c in result_df.columns
            if c != 'Composite_Score' and pd.notna(row[c])
        }
        out.append(Selection(
            symbol=str(code),
            as_of=normalize_date(as_of),
            score=float(score),
            scale=SCALE_ZSCORE,
            rank=rank,
            selected=selected,
            source='multi_factor_selection',
            extra=factor_snapshot,
        ))
    return out


def to_selections(result_df: pd.DataFrame, as_of=None,
                  selected: bool = True) -> list:
    """select_stocks 结果 → 统一契约 Selection 列表 (审计 C #9b).

    Args:
        result_df: `select_stocks` 返回的因子+综合分 DataFrame
            (index=股票代码, 含 Composite_Score 列, 已按分降序)
        as_of: 选股基准日 (与 select_stocks 的 as_of 同值 — MFS 有真实
            point-in-time 公告日过滤语义, 契约里如实记录)
        selected: 是否标记入选 (select_stocks 已按 top_n/min_score 截断,
            默认全部 True; 调用方拿全量因子表再自行标注时传 False)

    Returns:
        list[core.signal.Selection], 按传入顺序排名 (1-based);
        Composite_Score 为 NaN 的行跳过 (无有效分数不入契约)。
    """
    from core.signal import SCALE_ZSCORE, Selection, normalize_date

    out = []
    if result_df is None or len(result_df) == 0:
        return out
    if 'Composite_Score' not in result_df.columns:
        return out
    rank = 0
    for code, row in result_df.iterrows():
        score = row['Composite_Score']
        if pd.isna(score):
            continue
        rank += 1
        factor_snapshot = {
            str(c): float(row[c])
            for c in result_df.columns
            if c != 'Composite_Score' and pd.notna(row[c])
        }
        out.append(Selection(
            symbol=str(code),
            as_of=normalize_date(as_of),
            score=float(score),
            scale=SCALE_ZSCORE,
            rank=rank,
            selected=selected,
            source='multi_factor_selection',
            extra=factor_snapshot,
        ))
    return out


if __name__ == "__main__":
    print("Multi-Factor Stock Selection System - Enhanced Version v2.0")
    print("\nFactor Models:")
    print("- Value:      PE, PB, PS, PCF, Dividend")
    print("- Growth:     Revenue Growth, Profit Growth, ROE, Margins")
    print("- Quality:    ROE, ROA, Margins, Debt Ratio")
    print("- Momentum:   Price Momentum over multiple periods")
    print("- Volatility: Historical Volatility, Downside Risk")
    print("\nWeighting Methods:")
    print("- equal:       Equal weights for all factors")
    print("- ic:          IC weighted (Information Coefficient)")
    print("- ir:          IR weighted (Information Ratio)")
    print("- max_sharpe:  Maximize Sharpe ratio")
    print("- risk_parity: Risk parity weighting")
    print("\nPortfolio Optimization:")
    print("- Markowitz:   Mean-variance optimization")
    print("- Risk Parity: Equal risk contribution")
    print("- Min Variance: Minimum variance portfolio")
    print("- Inverse Vol: Inverse volatility weighting")
    print("\nFactor Effectiveness Testing:")
    print("- IC (Information Coefficient)")
    print("- IR (Information Ratio)")
    print("- Rank IC")
    print("- Statistical significance test")
