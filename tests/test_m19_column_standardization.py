# -*- coding: utf-8 -*-
"""日线列名标准化 / 涨跌幅派生的单一真相源门禁 (审计 M19, 批次 2)

复验结论 (2026-10-29): 审计 M19 属实, 且比审计记的更散 ——

- 列名标准化 (英文 → 中文) 的映射字典在 **5 个模块各写一遍**
  (`stock_data_fetcher` / `historical_data_manager` 个股+指数 /
  `long_term_selector` / `reversal_detector`), 内容已漂移:
  3 处含 `成交额`、2 处不含 → 同一份数据经不同模块得到不同列集。
- "缺失时补 `涨跌幅`" 的 pct_change 块在 **6 处各写一遍**
  (`stock_data_fetcher` ×2 / `historical_data_manager` ×2 /
  `position_analyzer` / `data_cleaner`), 口径也不统一: 5 处不转数值、
  1 处 `to_numeric`; 5 处"缺失才补"、1 处无条件覆盖。

这类漂移运行时**完全无感** (多一列少一列都不报错), 只能靠源码级门禁拦 +
行为等价性断言兜底。

门禁:
- AST: 除 `core/dataframe.py` 外, 任何模块不得再自带 OHLCV 英文→中文映射
- AST: 除 `core/dataframe.py` 外, 任何模块不得再直接给 `['涨跌幅']` 赋值
  (补列/覆盖都必须走 `ensure_change_pct`)
- 行为: 标准化/排序/涨跌幅派生的语义 (幂等、缺失才补、覆盖开关、无收盘不臆造)
- 等价性: 新共享实现与**旧内联实现**在同一输入上逐位一致
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

from core.dataframe import (CHANGE_PCT_COLUMN, OHLCV_COLUMN_MAP,
                            change_pct, ensure_change_pct,
                            sort_by_date, standardize_daily_frame,
                            standardize_ohlcv_columns)

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'
_TRUTH = 'core/dataframe.py'


def _modules():
    for py in sorted(_SKILLS.rglob('*.py')):
        if py.name == '__init__.py':
            continue
        yield py, py.relative_to(_SKILLS).as_posix()


class TestNoDuplicatedColumnMapping:
    """OHLCV 英文→中文映射必须只有一份 (core/dataframe.py)。"""

    def test_no_module_owns_ohlcv_mapping_dict(self):
        offenders = []
        for py, rel in _modules():
            if rel == _TRUTH:
                continue
            tree = ast.parse(py.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = [k.value for k in node.keys
                        if isinstance(k, ast.Constant)
                        and isinstance(k.value, str)]
                values = [v.value for v in node.values
                          if isinstance(v, ast.Constant)
                          and isinstance(v.value, str)]
                # 同时含英文 OHLCV 键与中文值 → 自带列名映射
                if (any(k in keys for k in ('open', 'high', 'low', 'close',
                                            'volume', 'date'))
                        and any(v in values for v in ('开盘', '最高', '最低',
                                                     '收盘', '成交量', '日期'))):
                    offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"自带日线列名映射 (应统一走 core.dataframe.OHLCV_COLUMN_MAP): "
            f"{offenders}")


class TestNoDirectChangePctAssignment:
    """`涨跌幅` 列只能由 core 派生 (禁止各模块自写 pct_change 公式)。"""

    def test_no_module_assigns_change_pct_column_directly(self):
        offenders = []
        for py, rel in _modules():
            if rel == _TRUTH:
                continue
            tree = ast.parse(py.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for t in targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.slice, ast.Constant)
                            and t.slice.value == CHANGE_PCT_COLUMN):
                        offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"直接给 '{CHANGE_PCT_COLUMN}' 赋值 (应走 "
            f"core.dataframe.ensure_change_pct): {offenders}")

    def test_shared_helper_is_actually_used_by_call_sites(self):
        """接线核对: 6 个消费方确实调用了共享实现 (防"建了函数没人用")。"""
        expected = {
            # 个股/指数取数站: 列名标准化 + 日期排序
            'stock_data_fetcher.py': 'standardize_daily_frame',
            'historical_data_manager.py': 'standardize_daily_frame',
            'historical_backtest_validator.py': 'standardize_daily_frame',
            'market_regime_classifier.py': 'standardize_daily_frame',
            'reversal_backtest.py': 'standardize_daily_frame',
            # 涨跌幅派生站
            'position_analyzer.py': 'ensure_change_pct',
            'data_cleaner.py': 'ensure_change_pct',
            # `long_term_selector` / `reversal_detector` 自 M20 起改走共享
            # 数据层 → 标准化由 `historical_data_manager.get_daily_result`
            # 统一完成 (两模块不再自行取数/标准化)
        }
        for name, func in expected.items():
            py = _SKILLS / name
            assert py.exists(), f"{name} 不存在 (模块被改名? 请同步本门禁)"
            src = py.read_text(encoding='utf-8')
            assert func in src, f"{name} 未调用共享实现 {func}"


class TestStandardizeOhlcvColumns:
    def test_renames_all_mapped_columns(self):
        df = pd.DataFrame({
            'date': ['2024-01-02'], 'open': [1.0], 'high': [2.0],
            'low': [0.5], 'close': [1.5], 'volume': [100.0],
            'amount': [150.0],
        })
        out = standardize_ohlcv_columns(df)
        for cn in ('日期', '开盘', '最高', '最低', '收盘', '成交量', '成交额'):
            assert cn in out.columns
        for en in OHLCV_COLUMN_MAP:
            assert en not in out.columns

    def test_is_idempotent(self):
        df = pd.DataFrame({'日期': ['2024-01-02'], '收盘': [1.5]})
        once = standardize_ohlcv_columns(df)
        twice = standardize_ohlcv_columns(once)
        assert list(once.columns) == list(twice.columns)

    def test_keeps_extra_columns(self):
        df = pd.DataFrame({'close': [1.0], 'outstanding_share': [3.0]})
        out = standardize_ohlcv_columns(df)
        assert 'outstanding_share' in out.columns

    def test_missing_columns_are_skipped(self):
        """指数接口无 `成交额` → 同一套映射仍可用 (旧代码有 6 列/7 列两版)。"""
        df = pd.DataFrame({'date': ['2024-01-02'], 'close': [1.0]})
        out = standardize_ohlcv_columns(df)
        assert '日期' in out.columns and '收盘' in out.columns
        assert '成交额' not in out.columns

    def test_does_not_mutate_input(self):
        df = pd.DataFrame({'close': [1.0]})
        standardize_ohlcv_columns(df)
        assert 'close' in df.columns and '收盘' not in df.columns


class TestChangePct:
    def test_percent_semantics(self):
        close = pd.Series([100.0, 110.0, 99.0])
        out = change_pct(close)
        assert out.iloc[0] != out.iloc[0]          # 首行 NaN
        assert out.iloc[1] == pytest.approx(10.0)
        assert out.iloc[2] == pytest.approx(-10.0)

    def test_coerce_handles_string_close(self):
        close = pd.Series(['100.0', '110.0'])
        out = change_pct(close, coerce=True)
        assert out.iloc[1] == pytest.approx(10.0)

    def test_without_coerce_string_close_raises(self):
        """不转数值时保持 pandas 原生行为 (不静默吞掉脏数据)。"""
        with pytest.raises(TypeError):
            change_pct(pd.Series(['100.0', '110.0']))


class TestEnsureChangePct:
    def test_adds_column_when_missing(self):
        df = pd.DataFrame({'收盘': [100.0, 110.0]})
        out = ensure_change_pct(df)
        assert CHANGE_PCT_COLUMN in out.columns
        assert out[CHANGE_PCT_COLUMN].iloc[1] == pytest.approx(10.0)

    def test_keeps_existing_column_by_default(self):
        df = pd.DataFrame({'收盘': [100.0, 110.0], CHANGE_PCT_COLUMN: [0.0, 7.0]})
        out = ensure_change_pct(df)
        assert out[CHANGE_PCT_COLUMN].iloc[1] == pytest.approx(7.0)

    def test_overwrite_recomputes(self):
        df = pd.DataFrame({'收盘': [100.0, 110.0], CHANGE_PCT_COLUMN: [0.0, 7.0]})
        out = ensure_change_pct(df, overwrite=True)
        assert out[CHANGE_PCT_COLUMN].iloc[1] == pytest.approx(10.0)

    def test_no_close_column_is_noop(self):
        df = pd.DataFrame({'成交量': [1.0]})
        out = ensure_change_pct(df)
        assert CHANGE_PCT_COLUMN not in out.columns

    def test_coerce_path(self):
        df = pd.DataFrame({'收盘': ['100.0', '110.0']})
        out = ensure_change_pct(df, coerce=True)
        assert out[CHANGE_PCT_COLUMN].iloc[1] == pytest.approx(10.0)


class TestSortByDate:
    def test_parses_sorts_and_resets(self):
        df = pd.DataFrame({'日期': ['2024-01-03', '2024-01-02'],
                           '收盘': [2.0, 1.0]})
        out = sort_by_date(df)
        assert pd.api.types.is_datetime64_any_dtype(out['日期'])
        assert list(out['收盘']) == [1.0, 2.0]
        assert list(out.index) == [0, 1]

    def test_missing_date_column_raises(self):
        with pytest.raises(KeyError):
            sort_by_date(pd.DataFrame({'收盘': [1.0]}))


class TestStandardizeDailyFrame:
    def test_full_pipeline(self):
        df = pd.DataFrame({
            'date': ['2024-01-03', '2024-01-02'],
            'close': [2.0, 1.0],
        })
        out = standardize_daily_frame(df)
        assert list(out['收盘']) == [1.0, 2.0]
        assert CHANGE_PCT_COLUMN in out.columns

    def test_add_change_false_skips_column(self):
        """`long_term_selector` / `reversal_detector` 不消费涨跌幅 →
        不补该列 (与旧行为一致, 不凭空多一列)。"""
        df = pd.DataFrame({'date': ['2024-01-02'], 'close': [1.0]})
        out = standardize_daily_frame(df, add_change=False)
        assert CHANGE_PCT_COLUMN not in out.columns

    def test_does_not_mutate_input(self):
        df = pd.DataFrame({'date': ['2024-01-02'], 'close': [1.0]})
        standardize_daily_frame(df)
        assert 'close' in df.columns
        assert CHANGE_PCT_COLUMN not in df.columns


class TestEquivalenceWithLegacyInlineCode:
    """新共享实现 vs 旧内联实现: 同一输入必须逐位一致 (不改数值)。"""

    @staticmethod
    def _legacy_fetch_path(df):
        """`stock_data_fetcher.fetch_data` 旧实现 (逐字搬自修复前)。"""
        column_mapping = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
            'amount': '成交额'
        }
        df = df.rename(columns=column_mapping)
        if '日期' in df.columns:
            df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期').reset_index(drop=True)
        if '涨跌幅' not in df.columns:
            df['涨跌幅'] = df['收盘'].pct_change() * 100
        return df

    @staticmethod
    def _legacy_no_change_path(df):
        """`long_term_selector` / `reversal_detector` 旧实现 (不补涨跌幅)。"""
        column_mapping = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
            'amount': '成交额'
        }
        df = df.rename(columns=column_mapping)
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期').reset_index(drop=True)
        return df

    @staticmethod
    def _legacy_index_path(df, start_date, end_date):
        """`historical_data_manager._fetch_index_from_api` 旧实现。"""
        col_map = {'date': '日期', 'open': '开盘', 'high': '最高',
                   'low': '最低', 'close': '收盘', 'volume': '成交量'}
        df = df.rename(columns=col_map)
        df['日期'] = pd.to_datetime(df['日期'])
        df = df[(df['日期'] >= pd.to_datetime(start_date))
                & (df['日期'] <= pd.to_datetime(end_date))]
        df = df.sort_values('日期').reset_index(drop=True)
        if '收盘' in df.columns and '涨跌幅' not in df.columns:
            df['涨跌幅'] = df['收盘'].pct_change() * 100
        return df

    def _assert_same(self, a: pd.DataFrame, b: pd.DataFrame):
        assert list(a.columns) == list(b.columns)
        pd.testing.assert_frame_equal(a, b)

    def test_fetch_path_equivalent(self):
        df = pd.DataFrame({
            'date': ['2024-01-03', '2024-01-02', '2024-01-04'],
            'open': [2.0, 1.0, 3.0], 'high': [2.5, 1.5, 3.5],
            'low': [1.5, 0.5, 2.5], 'close': [2.2, 1.1, 3.3],
            'volume': [10.0, 11.0, 12.0], 'amount': [22.0, 12.0, 39.0],
        })
        self._assert_same(self._legacy_fetch_path(df.copy()),
                          standardize_daily_frame(df.copy()))

    def test_no_change_path_equivalent(self):
        df = pd.DataFrame({
            'date': ['2024-01-03', '2024-01-02'],
            'close': [2.0, 1.0], 'volume': [10.0, 11.0],
        })
        self._assert_same(self._legacy_no_change_path(df.copy()),
                          standardize_daily_frame(df.copy(), add_change=False))

    def test_index_path_equivalent(self):
        df = pd.DataFrame({
            'date': ['2024-01-03', '2024-01-02', '2024-01-04'],
            'open': [2.0, 1.0, 3.0], 'high': [2.5, 1.5, 3.5],
            'low': [1.5, 0.5, 2.5], 'close': [2.2, 1.1, 3.3],
            'volume': [10.0, 11.0, 12.0],
        })
        legacy = self._legacy_index_path(df.copy(), '2024-01-02', '2024-01-03')
        # 新路径: 标准化 → 按窗口过滤 → 标准化(幂等)+排序+重置+涨跌幅
        new = standardize_ohlcv_columns(df.copy())
        new['日期'] = pd.to_datetime(new['日期'])
        new = new[(new['日期'] >= pd.to_datetime('2024-01-02'))
                  & (new['日期'] <= pd.to_datetime('2024-01-03'))]
        new = standardize_daily_frame(new)
        self._assert_same(legacy, new)
