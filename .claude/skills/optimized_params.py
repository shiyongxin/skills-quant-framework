# -*- coding: utf-8 -*-
"""
优化结果 → 生产参数下发契约 (审计 E-P1 #19 闭环 P1)

读取 OptimizationEngine.save_results 落盘的 best_params JSON, 提取
systems[].params 作为可直接下发的参数字典:

    params = load_optimized_params('stock_data/optimization_result.json')
    generator = SignalGenerator(use_weighted_scoring=params['use_weighted_scoring'],
                                scoring_params=params)
    metrics = VectorizedBacktester().backtest(data, params)

选择规则:
    regime=None → 优先全局系统 (regime 为空/'GLOBAL'), 其次唯一系统;
                  多个非全局系统时要求显式 regime= (不猜)
    regime=X    → 精确匹配 systems[].regime, 无匹配报错并列出可用值

加权模式标注: 优先显式 use_weighted_scoring 参数; None 时取 JSON 顶层
字段 (E-P1 接线后 save_results 落盘); 旧 JSON 缺键 → True (当前优化器
默认 — 评分维参与 fitness 的运行产出的是加权模式最优解)。
"""
import json


def _select_system(systems, regime):
    """按 regime 选择 system 条目。返回 (index, system); 失败抛 ValueError。"""
    if not systems:
        raise ValueError("优化结果 JSON 无 systems 条目 — 空结果或非 save_results 落盘格式")

    def _is_global(sys):
        r = sys.get('regime')
        return r is None or r == 'GLOBAL'

    if regime is not None:
        for i, s in enumerate(systems):
            if s.get('regime') == regime:
                return i, s
        available = [s.get('regime') for s in systems]
        raise ValueError(f"regime={regime!r} 无匹配 system; 可用: {available}")

    for i, s in enumerate(systems):
        if _is_global(s):
            return i, s
    if len(systems) == 1:
        return 0, systems[0]
    regimes = [s.get('regime') for s in systems]
    raise ValueError(
        f"结果含多个体制系统 {regimes} 且无全局系统 — 请传 regime= 指定其一")


def list_systems(filepath):
    """列出 JSON 内全部 system 的选择摘要 (name/regime/fitness)。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    summary = []
    for s in data.get('systems') or []:
        fs = s.get('fitness_scores') or {}
        summary.append({
            'name': s.get('name'),
            'regime': s.get('regime'),
            'fitness': max(fs.values()) if fs else None,
            'fitness_scores': fs,
            'applicable_regimes': s.get('applicable_regimes'),
            'sample_count': s.get('sample_count'),
        })
    return summary


def load_optimized_params(filepath, regime=None, use_weighted_scoring=None):
    """下发入口: 返回可直接喂给回测/信号层的参数字典。

    Parameters:
    -----------
    filepath : str
        OptimizationEngine.save_results 落盘的 JSON
    regime : str or None
        体制系统选择 (None = 全局/唯一系统)
    use_weighted_scoring : bool or None
        覆盖返回参数中的模式开关; None 时取 JSON 顶层字段 (缺键 → True)

    Returns:
    --------
    dict: systems[].params + use_weighted_scoring 标注
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    idx, system = _select_system(data.get('systems') or [], regime)

    params = system.get('params')
    if not isinstance(params, dict) or not params:
        raise ValueError(f"system[{idx}] params 缺失或为空 — 结果文件不完整")

    # 软校验: 未知键仅警告不阻断 (参数空间前向兼容)
    try:
        from parameter_space import ParameterSpace
        known = set(ParameterSpace.get_param_names())
        unknown = sorted(set(params) - known)
        if unknown:
            print(f"[WARN] params 含参数空间未知键 (跳过校验): {unknown}")
    except ImportError:
        pass

    if use_weighted_scoring is None:
        use_weighted_scoring = bool(data.get('use_weighted_scoring', True))

    out = {**params, 'use_weighted_scoring': use_weighted_scoring}
    print(f"[OK] 已加载优化参数: system[{idx}] name={system.get('name')!r} "
          f"regime={system.get('regime')!r} n_params={len(params)} "
          f"use_weighted_scoring={use_weighted_scoring}")
    return out
