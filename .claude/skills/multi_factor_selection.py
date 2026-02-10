# -*- coding: utf-8 -*-
"""
多因子选股系统 - 增强版
Multi-Factor Stock Selection System - Enhanced Version

基于价值、成长、质量、动量、技术等多维度选股
支持因子有效性检验、组合优化等高级功能
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from scipy import stats
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')


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


class FactorWeightingMethod:
    """因子加权方法"""

    @staticmethod
    def equal_weight(factors_df: pd.DataFrame) -> pd.Series:
        """
        等权重加权
        所有因子权重相等
        """
        factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
        weights = {col: 1.0 / len(factor_cols) for col in factor_cols}
        return FactorWeightingMethod._apply_weights(factors_df, weights)

    @staticmethod
    def ic_weighted(factors_df: pd.DataFrame, returns: pd.Series) -> pd.Series:
        """
        IC加权
        根据历史IC表现分配权重
        """
        factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]

        # 计算每个因子与收益的相关系数 (IC)
        ics = {}
        for col in factor_cols:
            valid_idx = factors_df[col].notna() & returns.notna()
            if valid_idx.sum() > 10:
                ic = factors_df.loc[valid_idx, col].corr(returns.loc[valid_idx])
                ics[col] = abs(ic) if not np.isnan(ic) else 0
            else:
                ics[col] = 0

        # 归一化权重
        total_ic = sum(ics.values())
        if total_ic > 0:
            weights = {col: ic / total_ic for col, ic in ics.items()}
        else:
            weights = {col: 1.0 / len(factor_cols) for col in factor_cols}

        return FactorWeightingMethod._apply_weights(factors_df, weights)

    @staticmethod
    def ir_weighted(factors_df: pd.DataFrame, ic_history: Dict[str, List[float]]) -> pd.Series:
        """
        IR加权 (Information Ratio加权)
        根据IR (IC均值/IC标准差) 分配权重
        """
        factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]

        # 计算IR
        irs = {}
        for col in factor_cols:
            if col in ic_history and len(ic_history[col]) > 1:
                ic_values = ic_history[col]
                ir = np.mean(ic_values) / (np.std(ic_values) + 1e-8)
                irs[col] = max(0, ir)
            else:
                irs[col] = 1.0

        # 归一化权重
        total_ir = sum(irs.values())
        if total_ir > 0:
            weights = {col: ir / total_ir for col, ir in irs.items()}
        else:
            weights = {col: 1.0 / len(factor_cols) for col in factor_cols}

        return FactorWeightingMethod._apply_weights(factors_df, weights)

    @staticmethod
    def max_sharpe(factors_df: pd.DataFrame, returns: pd.Series,
                   risk_free_rate: float = 0.03) -> pd.Series:
        """
        最大夏普比率加权
        优化权重使组合夏普比率最大
        """
        factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
        n_factors = len(factor_cols)

        if n_factors == 0:
            return pd.Series(0, index=factors_df.index)

        # 提取因子数据
        factor_data = factors_df[factor_cols].dropna()
        if len(factor_data) < 10:
            return FactorWeightingMethod.equal_weight(factors_df)

        # 计算因子收益协方差矩阵
        aligned_returns = returns.loc[factor_data.index]
        factor_returns = pd.DataFrame()
        for col in factor_cols:
            # 使用因子值与下一期收益的回归系数作为因子收益
            factor_returns[col] = factor_data[col].shift(-1) * aligned_returns

        factor_returns = factor_returns.dropna()
        if len(factor_returns) < 10:
            return FactorWeightingMethod.equal_weight(factors_df)

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
        except:
            optimal_weights = np.array([1.0 / n_factors] * n_factors)

        # 应用权重
        weights = {factor_cols[i]: optimal_weights[i] for i in range(n_factors)}
        return FactorWeightingMethod._apply_weights(factors_df, weights)

    @staticmethod
    def risk_parity(factors_df: pd.DataFrame, returns: pd.Series) -> pd.Series:
        """
        风险平价加权
        使各因子对组合风险的贡献相等
        """
        factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
        n_factors = len(factor_cols)

        if n_factors == 0:
            return pd.Series(0, index=factors_df.index)

        # 提取因子数据
        factor_data = factors_df[factor_cols].dropna()

        # 计算因子收益协方差矩阵
        aligned_returns = returns.loc[factor_data.index]
        factor_returns = pd.DataFrame()
        for col in factor_cols:
            factor_returns[col] = factor_data[col].shift(-1) * aligned_returns

        factor_returns = factor_returns.dropna()
        if len(factor_returns) < 10:
            return FactorWeightingMethod.equal_weight(factors_df)

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
        except:
            optimal_weights = np.array([1.0 / n_factors] * n_factors)

        weights = {factor_cols[i]: optimal_weights[i] for i in range(n_factors)}
        return FactorWeightingMethod._apply_weights(factors_df, weights)

    @staticmethod
    def _apply_weights(factors_df: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        """应用权重计算综合得分"""
        composite_score = pd.Series(0.0, index=factors_df.index)

        for col, weight in weights.items():
            if col in factors_df.columns:
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
                t_stat=0, p_value=1, is_significant=False
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
            is_significant=is_significant
        )

    @staticmethod
    def test_all_factors(factors_df: pd.DataFrame, returns: pd.Series,
                        method: str = 'pearson') -> Dict[str, FactorTestResult]:
        """
        测试所有因子的有效性

        Args:
            factors_df: 因子DataFrame
            returns: 收益率Series
            method: 相关性计算方法

        Returns:
            因子名到测试结果的字典
        """
        results = {}

        factor_cols = [col for col in factors_df.columns if col.endswith('_Score') or col.endswith('_Factor')]

        for col in factor_cols:
            # 对齐数据
            factor_values = factors_df[col].shift(1)  # 使用t-1期因子预测t期收益
            aligned_idx = factor_values.notna() & returns.notna()

            if aligned_idx.sum() > 30:  # 至少30个有效样本
                result = FactorEffectivenessTester.test_factor(
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
        营收增长率、利润增长率、ROE增长率等

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

        # ROE
        if '净资产收益率' in df.columns:
            factors['ROE'] = df['净资产收益率']

        # 毛利率
        if '销售毛利率' in df.columns:
            factors['Gross_Margin'] = df['销售毛利率']

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
    def momentum_factor(price_df, periods=[20, 60, 120]) -> pd.DataFrame:
        """
        动量因子
        过去N日的收益率

        Args:
            price_df: 价格数据
            periods: 计算周期列表

        Returns:
            因子得分DataFrame
        """
        factors = pd.DataFrame()

        close = price_df['收盘']

        for period in periods:
            if len(close) >= period:
                momentum = close.pct_change(period)
                factors[f'Momentum_{period}'] = momentum.iloc[-1]

        # 标准化
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Momentum_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def volatility_factor(price_df, period=20) -> pd.DataFrame:
        """
        波动率因子
        历史波动率、下行风险

        Args:
            price_df: 价格数据
            period: 计算周期

        Returns:
            因子得分DataFrame (负值表示低波动更好)
        """
        factors = pd.DataFrame()

        close = price_df['收盘']

        # 历史波动率
        returns = close.pct_change()
        volatility = returns.rolling(window=period).std()
        factors['Volatility'] = -volatility.iloc[-1]  # 低波动为正

        # 下行风险
        negative_returns = returns[returns < 0]
        if len(negative_returns) > 0:
            downside_vol = negative_returns.rolling(window=period).std()
            factors['Downside_Vol'] = -downside_vol.iloc[-1]

        # 最大回撤 (倒数)
        cummax = close.cummax()
        drawdown = (close - cummax) / cummax
        max_dd = drawdown.rolling(window=period).min()
        factors['Max_Drawdown'] = -max_dd.iloc[-1]

        # 标准化
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Volatility_Score'] = factors.mean(axis=1)

        return factors

    @staticmethod
    def technical_factor(df) -> pd.DataFrame:
        """
        技术因子
        基于技术指标的因子

        Args:
            df: 包含技术指标的数据

        Returns:
            因子得分DataFrame
        """
        factors = pd.DataFrame()

        # RSI (均值回归，极端值反转)
        if 'RSI' in df.columns:
            rsi = df['RSI'].iloc[-1]
            # RSI在30-70之间为中性，越接近50越好
            factors['RSI_Mean_Reversion'] = -abs(rsi - 50)

        # MACD (动量)
        if 'MACD' in df.columns:
            factors['MACD_Momentum'] = df['MACD'].iloc[-1]

        # 布林带位置
        if 'BB_Upper' in df.columns and 'BB_Lower' in df.columns and '收盘' in df.columns:
            bb_width = df['BB_Upper'].iloc[-1] - df['BB_Lower'].iloc[-1]
            bb_position = (df['收盘'].iloc[-1] - df['BB_Lower'].iloc[-1]) / bb_width
            # 接近下轨为正（超卖）
            factors['BB_Position'] = 1 - bb_position

        # ATR (波动率，倒数)
        if 'ATR' in df.columns:
            factors['ATR'] = -df['ATR'].iloc[-1]

        # 标准化
        for col in factors.columns:
            factors[col] = (factors[col] - factors[col].mean()) / factors[col].std()

        factors['Technical_Score'] = factors.mean(axis=1)

        return factors


class MultiFactorSelector:
    """多因子选股器 - 增强版"""

    def __init__(self, factor_weights: Dict[str, float] = None,
                 weighting_method: str = 'equal'):
        """
        初始化多因子选股器

        Args:
            factor_weights: 因子权重，如 {'value': 0.3, 'growth': 0.3, 'quality': 0.2, 'momentum': 0.2}
            weighting_method: 加权方法 ('equal', 'ic', 'ir', 'max_sharpe', 'risk_parity')
        """
        if factor_weights is None:
            factor_weights = {
                'value': 0.25,
                'growth': 0.25,
                'quality': 0.25,
                'momentum': 0.15,
                'volatility': 0.10
            }

        self.factor_weights = factor_weights
        self.weighting_method = weighting_method
        self.factor_models = FactorModels()
        self.weighting_class = FactorWeightingMethod()
        self.tester = FactorEffectivenessTester()

        # 存储历史IC用于IR加权
        self.ic_history: Dict[str, List[float]] = {}

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

        # 价值因子
        try:
            value_factors = self.factor_models.value_factor(financial_df)
            all_factors = pd.concat([all_factors, value_factors[['Value_Score']]], axis=1)
        except:
            pass

        # 成长因子
        try:
            growth_factors = self.factor_models.growth_factor(financial_df)
            all_factors = pd.concat([all_factors, growth_factors[['Growth_Score']]], axis=1)
        except:
            pass

        # 质量因子
        try:
            quality_factors = self.factor_models.quality_factor(financial_df)
            all_factors = pd.concat([all_factors, quality_factors[['Quality_Score']]], axis=1)
        except:
            pass

        # 动量和波动率因子 (需要价格数据)
        if price_df is not None and len(price_df) > 0:
            try:
                momentum_factors = self.factor_models.momentum_factor(price_df)
                all_factors = pd.concat([all_factors, momentum_factors[['Momentum_Score']]], axis=1)
            except:
                pass

            try:
                volatility_factors = self.factor_models.volatility_factor(price_df)
                all_factors = pd.concat([all_factors, volatility_factors[['Volatility_Score']]], axis=1)
            except:
                pass

        return all_factors

    def get_composite_score(self, factors_df: pd.DataFrame,
                           returns: pd.Series = None) -> pd.Series:
        """
        计算综合得分

        Args:
            factors_df: 因子DataFrame
            returns: 收益率数据 (用于动态加权方法)

        Returns:
            综合得分Series
        """
        if self.weighting_method == 'equal':
            return self.weighting_class.equal_weight(factors_df)

        elif self.weighting_method == 'ic' and returns is not None:
            return self.weighting_class.ic_weighted(factors_df, returns)

        elif self.weighting_method == 'ir' and returns is not None:
            return self.weighting_class.ir_weighted(factors_df, self.ic_history)

        elif self.weighting_method == 'max_sharpe' and returns is not None:
            return self.weighting_class.max_sharpe(factors_df, returns)

        elif self.weighting_method == 'risk_parity' and returns is not None:
            return self.weighting_class.risk_parity(factors_df, returns)

        else:
            # 默认使用自定义权重
            return self._apply_custom_weights(factors_df)

    def _apply_custom_weights(self, factors_df: pd.DataFrame) -> pd.Series:
        """应用自定义权重"""
        composite_score = pd.Series(0, index=factors_df.index)

        factor_mapping = {
            'Value_Score': 'value',
            'Growth_Score': 'growth',
            'Quality_Score': 'quality',
            'Momentum_Score': 'momentum',
            'Volatility_Score': 'volatility'
        }

        for factor_col, factor_name in factor_mapping.items():
            if factor_col in factors_df.columns and factor_name in self.factor_weights:
                weight = self.factor_weights[factor_name]
                composite_score += factors_df[factor_col] * weight

        return composite_score

    def select_stocks(self, financial_df: pd.DataFrame, price_df: pd.DataFrame = None,
                      top_n: int = 20, min_score: float = None,
                      returns: pd.Series = None) -> pd.DataFrame:
        """
        选股

        Args:
            financial_df: 财务数据
            price_df: 价格数据 (可选)
            top_n: 返回前N只股票
            min_score: 最低得分要求 (None表示不限制)
            returns: 收益率数据 (用于动态加权)

        Returns:
            选股结果DataFrame
        """
        # 计算因子
        factors_df = self.calculate_factors(financial_df, price_df)

        if len(factors_df.columns) == 0:
            return pd.DataFrame()

        # 计算综合得分
        composite_score = self.get_composite_score(factors_df, returns)
        factors_df['Composite_Score'] = composite_score

        # 排序
        factors_df = factors_df.sort_values('Composite_Score', ascending=False)

        # 筛选
        if min_score is not None:
            selected = factors_df[factors_df['Composite_Score'] >= min_score].head(top_n)
        else:
            selected = factors_df.head(top_n)

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

        Args:
            factors_df: 因子DataFrame
            returns: 收益率数据
            method: 优化方法 ('max_sharpe', 'risk_parity', 'equal')

        Returns:
            优化后的权重字典
        """
        if method == 'equal':
            factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
            return {col: 1.0 / len(factor_cols) for col in factor_cols}

        elif method == 'max_sharpe':
            # 使用最大夏普比率加权
            score = self.weighting_class.max_sharpe(factors_df, returns)
            # 这里简化处理，实际应该返回权重
            factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
            return {col: 1.0 / len(factor_cols) for col in factor_cols}

        elif method == 'risk_parity':
            # 使用风险平价加权
            score = self.weighting_class.risk_parity(factors_df, returns)
            factor_cols = [col for col in factors_df.columns if col.endswith('_Score')]
            return {col: 1.0 / len(factor_cols) for col in factor_cols}

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
        except:
            pass

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
        except:
            pass

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
        except:
            pass

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
            price_df: 价格DataFrame (收盘价列)
            period: 回溯周期
            top_n: 选择数量

        Returns:
            股票代码列表
        """
        close = price_df['收盘']
        momentum = close.pct_change(period)
        return momentum.nlargest(top_n).index.tolist()


# 便捷函数
def multi_factor_select(financial_df, price_df=None, top_n=20, weighting_method='equal'):
    """多因子选股"""
    selector = MultiFactorSelector(weighting_method=weighting_method)
    return selector.select_stocks(financial_df, price_df, top_n)


def test_factor_effectiveness(factors_df, returns):
    """测试因子有效性"""
    tester = FactorEffectivenessTester()
    results = tester.test_all_factors(factors_df, returns)
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
