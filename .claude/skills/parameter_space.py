# -*- coding: utf-8 -*-
"""
参数空间定义 - Parameter Space Definition

集中定义所有可优化的技术分析参数，包含类型、上下界、默认值和约束条件。
供优化器、回测引擎、信号生成器和每日推荐系统共同使用。
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamDef:
    """单个参数定义"""
    name: str
    param_type: str   # "int", "float", "categorical"
    low: float
    high: float
    default: float
    step: float = 1.0
    categories: list = None
    group: str = ""   # "indicator", "scoring", "signal", "position"

    def sample_random(self, rng=None) -> Any:
        """随机采样一个值"""
        if rng is None:
            rng = np.random.default_rng()

        if self.param_type == "int":
            return int(rng.integers(int(self.low), int(self.high) + 1))
        elif self.param_type == "float":
            return rng.uniform(self.low, self.high)
        elif self.param_type == "categorical":
            return rng.choice(self.categories)
        return self.default

    def clip(self, value) -> Any:
        """裁剪到合法范围"""
        if self.param_type == "int":
            return int(np.clip(value, self.low, self.high))
        elif self.param_type == "float":
            return float(np.clip(value, self.low, self.high))
        elif self.param_type == "categorical":
            if value in self.categories:
                return value
            return self.default
        return value


class ParameterSpace:
    """
    参数空间定义

    包含4组共25个可优化参数:
    - 指标参数 (12个): MA/MACD/RSI/KDJ/BB/ATR
    - 评分权重 (4个): 趋势/动量/风险/近期表现
    - 信号阈值 (4个): 买入/卖出信号强度阈值
    - 仓位参数 (4个): 止损/止盈/仓位比例/追踪止损
    """

    # ==================== 指标参数 ====================
    MA_FAST = ParamDef("ma_fast", "int", 3, 30, 5, group="indicator")
    MA_SLOW = ParamDef("ma_slow", "int", 15, 120, 20, group="indicator")
    MA_MID = ParamDef("ma_mid", "int", 10, 60, 10, group="indicator")

    MACD_FAST = ParamDef("macd_fast", "int", 6, 20, 12, group="indicator")
    MACD_SLOW = ParamDef("macd_slow", "int", 18, 40, 26, group="indicator")
    MACD_SIGNAL = ParamDef("macd_signal", "int", 5, 15, 9, group="indicator")

    RSI_PERIOD = ParamDef("rsi_period", "int", 5, 30, 14, group="indicator")
    RSI_OVERSOLD = ParamDef("rsi_oversold", "float", 15, 40, 30, group="indicator")
    RSI_OVERBOUGHT = ParamDef("rsi_overbought", "float", 60, 85, 70, group="indicator")

    KDJ_N = ParamDef("kdj_n", "int", 5, 21, 9, group="indicator")

    BB_PERIOD = ParamDef("bb_period", "int", 10, 40, 20, group="indicator")
    BB_STD = ParamDef("bb_std", "float", 1.0, 3.5, 2.0, group="indicator")

    ATR_PERIOD = ParamDef("atr_period", "int", 7, 28, 14, group="indicator")

    # ==================== 评分权重 ====================
    W_TREND = ParamDef("w_trend", "float", 10, 50, 30, group="scoring")
    W_MOMENTUM = ParamDef("w_momentum", "float", 10, 40, 25, group="scoring")
    W_RISK = ParamDef("w_risk", "float", 5, 30, 15, group="scoring")
    W_PERFORMANCE = ParamDef("w_performance", "float", 10, 40, 30, group="scoring")

    # ==================== 信号阈值 ====================
    BUY_THRESHOLD = ParamDef("buy_threshold", "float", 1.0, 6.0, 3.0, group="signal")
    SELL_THRESHOLD = ParamDef("sell_threshold", "float", 1.0, 6.0, 4.0, group="signal")
    SCORE_BUY_THRESHOLD = ParamDef("score_buy_threshold", "float", 40, 80, 60, group="signal")
    SCORE_SELL_THRESHOLD = ParamDef("score_sell_threshold", "float", 20, 50, 35, group="signal")

    # ==================== 仓位参数 ====================
    STOP_LOSS_PCT = ParamDef("stop_loss_pct", "float", 0.03, 0.15, 0.12, group="position")
    TAKE_PROFIT_PCT = ParamDef("take_profit_pct", "float", 0.10, 0.50, 0.30, group="position")
    POSITION_SIZE_PCT = ParamDef("position_size_pct", "float", 0.3, 1.0, 0.8, group="position")
    TRAILING_STOP_PCT = ParamDef("trailing_stop_pct", "float", 0.03, 0.15, 0.10, group="position")
    MIN_HOLDING_DAYS = ParamDef("min_holding_days", "int", 10, 90, 40, group="position")

    # ==================== 类方法 ====================
    @classmethod
    def get_all_params(cls) -> list:
        """获取所有参数定义"""
        params = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if isinstance(attr, ParamDef):
                params.append(attr)
        return params

    @classmethod
    def get_param_names(cls) -> list:
        """获取所有参数名"""
        return [p.name for p in cls.get_all_params()]

    @classmethod
    def get_bounds(cls) -> list:
        """获取参数上下界 (用于优化器)"""
        return [(p.low, p.high) for p in cls.get_all_params()]

    @classmethod
    def get_defaults(cls) -> dict:
        """获取默认参数值"""
        return {p.name: p.default for p in cls.get_all_params()}

    @classmethod
    def get_indicator_params(cls) -> list:
        """获取指标参数"""
        return [p for p in cls.get_all_params() if p.group == "indicator"]

    @classmethod
    def get_scoring_params(cls) -> list:
        """获取评分参数"""
        return [p for p in cls.get_all_params() if p.group == "scoring"]

    @classmethod
    def get_signal_params(cls) -> list:
        """获取信号参数"""
        return [p for p in cls.get_all_params() if p.group == "signal"]

    @classmethod
    def get_position_params(cls) -> list:
        """获取仓位参数"""
        return [p for p in cls.get_all_params() if p.group == "position"]

    @classmethod
    def get_param_def(cls, name: str) -> ParamDef:
        """按名称获取参数定义"""
        for p in cls.get_all_params():
            if p.name == name:
                return p
        raise KeyError(f"Parameter '{name}' not found")

    @classmethod
    def params_to_vector(cls, params_dict: dict) -> np.ndarray:
        """参数字典转向量"""
        names = cls.get_param_names()
        return np.array([params_dict.get(n, cls.get_param_def(n).default) for n in names])

    @classmethod
    def vector_to_params(cls, vector: np.ndarray) -> dict:
        """向量转参数字典"""
        names = cls.get_param_names()
        result = {}
        for i, name in enumerate(names):
            pdef = cls.get_param_def(name)
            result[name] = pdef.clip(vector[i])
        return result

    @classmethod
    def random_sample(cls, rng=None) -> dict:
        """随机采样一组参数"""
        if rng is None:
            rng = np.random.default_rng()
        return {p.name: p.sample_random(rng) for p in cls.get_all_params()}

    @classmethod
    def validate(cls, params: dict) -> tuple[bool, list]:
        """
        验证参数合法性

        Returns:
        --------
        (is_valid, list_of_violations)
        """
        violations = []

        # MA约束: fast < slow
        if params.get('ma_fast', 5) >= params.get('ma_slow', 20):
            violations.append(f"ma_fast({params.get('ma_fast')}) >= ma_slow({params.get('ma_slow')})")

        # MA约束: mid < slow
        if params.get('ma_mid', 10) >= params.get('ma_slow', 20):
            violations.append(f"ma_mid({params.get('ma_mid')}) >= ma_slow({params.get('ma_slow')})")

        # MACD约束: fast < slow
        if params.get('macd_fast', 12) >= params.get('macd_slow', 26):
            violations.append(f"macd_fast({params.get('macd_fast')}) >= macd_slow({params.get('macd_slow')})")

        # RSI约束: oversold < overbought
        if params.get('rsi_oversold', 30) >= params.get('rsi_overbought', 70):
            violations.append(f"rsi_oversold >= rsi_overbought")

        # 权重约束: 总和应接近100
        w_total = (params.get('w_trend', 30) + params.get('w_momentum', 25) +
                   params.get('w_risk', 15) + params.get('w_performance', 30))
        if abs(w_total - 100) > 5:
            violations.append(f"权重总和={w_total:.1f}, 应接近100")

        return len(violations) == 0, violations

    @classmethod
    def repair(cls, params: dict) -> dict:
        """
        修复不合法参数

        在GA变异/交叉后调用，确保参数满足约束。
        """
        p = params.copy()

        # MA约束: fast < mid < slow
        if p.get('ma_fast', 5) >= p.get('ma_slow', 20):
            p['ma_fast'] = max(3, p['ma_slow'] - 5)
        if p.get('ma_mid', 10) >= p.get('ma_slow', 20):
            p['ma_mid'] = max(10, p['ma_slow'] - 3)

        # MACD约束
        if p.get('macd_fast', 12) >= p.get('macd_slow', 26):
            p['macd_fast'] = max(6, p['macd_slow'] - 5)

        # RSI约束
        if p.get('rsi_oversold', 30) >= p.get('rsi_overbought', 70):
            p['rsi_oversold'] = p['rsi_overbought'] - 10

        # 权重归一化
        w_keys = ['w_trend', 'w_momentum', 'w_risk', 'w_performance']
        w_vals = [p.get(k, v) for k, v in zip(w_keys, [30, 25, 15, 30])]
        w_sum = sum(w_vals)
        if w_sum > 0:
            for k, v in zip(w_keys, w_vals):
                p[k] = v / w_sum * 100

        # 所有值裁剪到合法范围
        for param_def in cls.get_all_params():
            name = param_def.name
            if name in p:
                p[name] = param_def.clip(p[name])

        return p

    @classmethod
    def crossover(cls, parent1: dict, parent2: dict, rng=None) -> tuple[dict, dict]:
        """
        均匀交叉

        每个参数从任一父代以50%概率继承。
        """
        if rng is None:
            rng = np.random.default_rng()

        child1, child2 = {}, {}
        for p in cls.get_all_params():
            name = p.name
            if rng.random() < 0.5:
                child1[name] = parent1.get(name, p.default)
                child2[name] = parent2.get(name, p.default)
            else:
                child1[name] = parent2.get(name, p.default)
                child2[name] = parent1.get(name, p.default)

        return cls.repair(child1), cls.repair(child2)

    @classmethod
    def mutate(cls, individual: dict, mutation_rate=0.15, rng=None) -> dict:
        """
        高斯变异(浮点) / 随机重置(整数/类别)
        """
        if rng is None:
            rng = np.random.default_rng()

        result = individual.copy()
        for p in cls.get_all_params():
            if rng.random() < mutation_rate:
                if p.param_type == "float":
                    # 高斯变异，标准差为范围的10%
                    sigma = (p.high - p.low) * 0.1
                    new_val = result.get(p.name, p.default) + rng.normal(0, sigma)
                    result[p.name] = p.clip(new_val)
                elif p.param_type == "int":
                    # 随机重置
                    result[p.name] = p.sample_random(rng)
                elif p.param_type == "categorical":
                    result[p.name] = p.sample_random(rng)

        return cls.repair(result)


def get_defaults_dict() -> dict:
    """获取默认参数字典(快捷函数)"""
    return ParameterSpace.get_defaults()
