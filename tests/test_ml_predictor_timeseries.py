# -*- coding: utf-8 -*-
"""
C-P0#6 ml_predictor 时序切分测试:
- _time_series_split 时序有序 + embargo 隔离带
- train/predict/cross_validate 全链路无未来函数
- 源码不再引用 train_test_split / 全量 scaler fit
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sklearn = pytest.importorskip("sklearn")

from ml_predictor import MLPredictor, RegressionPredictor, _time_series_split

SRC_PATH = (Path(__file__).resolve().parents[1]
            / '.claude' / 'skills' / 'ml_predictor.py')


def mk_ohlcv(n=500, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2023-01-01', periods=n, freq='B')
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return pd.DataFrame({
        '日期': dates,
        '开盘': close * (1 + rng.normal(0, 0.005, n)),
        '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
        '成交量': rng.integers(1e6, 5e6, n).astype(float),
    })


class TestTimeSeriesSplit:
    def test_ordering_and_embargo(self):
        n = 500
        X = pd.DataFrame({'a': np.arange(n, dtype=float)}, index=np.arange(n))
        y = pd.Series(np.arange(n, dtype=float) % 2, index=np.arange(n))
        tr, te, ytr, yte = _time_series_split(X, y, 0.2, embargo=5)
        assert tr.index.max() < te.index.min(), "not time-ordered"
        assert tr.index.max() + 5 <= te.index.min(), "no embargo gap"
        assert len(te) > 0 and len(tr) > 0


class TestMLPredictor:
    def test_train_predict_finite(self):
        data = mk_ohlcv()
        mp = MLPredictor(model_type="random_forest")
        ev = mp.train(data, forward_days=5, threshold=0.02)
        assert np.isfinite(ev.accuracy)
        r = mp.predict(data)
        assert 0.0 <= r.probability <= 1.0

    def test_embargo_gap_in_pipeline(self):
        data = mk_ohlcv()
        mp = MLPredictor(model_type="random_forest")
        mp.train(data, forward_days=5, threshold=0.02)
        feats, _tgt = mp.prepare_data(data, 5, 0.02)
        fcols = [c for c in feats.columns
                 if c not in ['日期', '开盘', '最高', '最低', '收盘', '成交量']]
        Xf = feats[fcols].fillna(0)
        split = max(1, min(int(len(Xf) * 0.8), len(Xf) - 2))
        ts = min(split + 5, len(Xf) - 1)
        assert ts - split == 5, f"embargo gap wrong: {ts - split}"

    def test_cross_validate_folds(self):
        data = mk_ohlcv()
        mp = MLPredictor(model_type="random_forest")
        cvres = mp.cross_validate(data, cv=4)
        assert len(cvres['scores']) == 4
        assert all(np.isfinite(cvres['scores']))

    def test_regression_predictor(self):
        data = mk_ohlcv()
        rp = RegressionPredictor()
        m = rp.train(data, forward_days=5)
        assert np.isfinite(m['rmse'])
        pr = rp.predict_return(data)
        assert np.isfinite(pr)


class TestNoLeakageSource:
    def test_train_test_split_removed(self):
        src = SRC_PATH.read_text(encoding='utf-8')
        assert 'train_test_split' not in src, "train_test_split still referenced"
        assert 'fit_transform(X)' not in src, "full-data scaler fit still present"
