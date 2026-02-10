# -*- coding: utf-8 -*-
"""
机器学习预测器
Machine Learning Predictor

提供股票价格预测、趋势预测等功能
"""

import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import warnings

try:
    from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, mean_squared_error, mean_absolute_error
    from sklearn.metrics import classification_report, confusion_matrix
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    warnings.warn("scikit-learn未安装，ML功能将不可用")


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class PredictionResult:
    """预测结果"""
    symbol: str
    date: datetime
    prediction: str  # up/down/hold
    probability: float  # 预测概率
    confidence: float  # 置信度
    features: Dict[str, float]  # 特征值


@dataclass
class ModelEvaluation:
    """模型评估结果"""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: Any
    feature_importance: Dict[str, float]


# =============================================================================
# 特征工程
# =============================================================================

class FeatureEngineer:
    """特征工程器"""

    def __init__(self):
        """初始化特征工程器"""
        self.scaler = StandardScaler()

    def create_technical_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        创建技术指标特征

        Args:
            data: 包含OHLCV的DataFrame

        Returns:
            添加特征后的DataFrame
        """
        features = data.copy()

        # 确保有必要的列
        required_cols = ['开盘', '最高', '最低', '收盘', '成交量']
        for col in required_cols:
            if col not in features.columns:
                features[col] = 0  # 填充缺失值

        # 价格特征
        features['price_change'] = features['收盘'].pct_change()
        features['price_change_5'] = features['收盘'].pct_change(5)
        features['price_change_10'] = features['收盘'].pct_change(10)
        features['price_change_20'] = features['收盘'].pct_change(20)

        # 波动率特征
        features['volatility_5'] = features['收盘'].pct_change().rolling(5).std()
        features['volatility_10'] = features['收盘'].pct_change().rolling(10).std()
        features['volatility_20'] = features['收盘'].pct_change().rolling(20).std()

        # 动量特征
        features['momentum_5'] = features['收盘'] / features['收盘'].shift(5) - 1
        features['momentum_10'] = features['收盘'] / features['收盘'].shift(10) - 1
        features['momentum_20'] = features['收盘'] / features['收盘'].shift(20) - 1

        # RSI特征
        delta = features['收盘'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features['rsi'] = 100 - (100 / (1 + rs))

        # MACD特征
        ema12 = features['收盘'].ewm(span=12, adjust=False).mean()
        ema26 = features['收盘'].ewm(span=26, adjust=False).mean()
        features['macd'] = ema12 - ema26
        features['macd_signal'] = features['macd'].ewm(span=9, adjust=False).mean()
        features['macd_hist'] = features['macd'] - features['macd_signal']

        # 布林带特征
        features['bb_middle'] = features['收盘'].rolling(window=20).mean()
        features['bb_std'] = features['收盘'].rolling(window=20).std()
        features['bb_upper'] = features['bb_middle'] + 2 * features['bb_std']
        features['bb_lower'] = features['bb_middle'] - 2 * features['bb_std']
        features['bb_position'] = (features['收盘'] - features['bb_lower']) / (features['bb_upper'] - features['bb_lower'])

        # 成交量特征
        features['volume_change'] = features['成交量'].pct_change()
        features['volume_ma5'] = features['成交量'].rolling(5).mean()
        features['volume_ma20'] = features['成交量'].rolling(20).mean()
        features['volume_ratio'] = features['成交量'] / features['volume_ma20']

        # 高低位置
        features['high_low_ratio'] = features['最高'] / features['最低']
        features['close_position'] = (features['收盘'] - features['最低']) / (features['最高'] - features['最低'])

        # 趋势特征
        features['ma5_above_ma20'] = (features['收盘'].rolling(5).mean() > features['收盘'].rolling(20).mean()).astype(int)
        features['ma_trend_up'] = (features['收盘'].rolling(5).mean() > features['收盘'].rolling(5).mean().shift(1)).astype(int)

        return features

    def create_pattern_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        创建K线形态特征

        Args:
            data: 包含OHLCV的DataFrame

        Returns:
            添加形态特征后的DataFrame
        """
        features = data.copy()

        # 锤子线
        body = abs(features['收盘'] - features['开盘'])
        lower_shadow = features[['开盘', '收盘']].min(axis=1) - features['最低']
        upper_shadow = features['最高'] - features[['开盘', '收盘']].max(axis=1)
        features['is_hammer'] = (
            (lower_shadow > body * 2) &
            (upper_shadow < body * 0.3) &
            (body < features['收盘'] * 0.03)
        ).astype(int)

        # 流星线
        features['is_shooting_star'] = (
            (upper_shadow > body * 2) &
            (lower_shadow < body * 0.3) &
            (body < features['收盘'] * 0.03)
        ).astype(int)

        # 大阳线/大阴线
        features['is_big_candle'] = (
            (features['收盘'] / features['开盘'] - 1).abs() > 0.05
        ).astype(int)

        # 十字星
        features['is_doji'] = (body < features['收盘'] * 0.01).astype(int)

        # 吞没形态
        features['is_bullish_engulfing'] = (
            (features['收盘'].shift(1) < features['开盘'].shift(1)) &  # 前一天阴线
            (features['收盘'] > features['开盘']) &  # 当天阳线
            (features['开盘'] < features['收盘'].shift(1)) &  # 开盘低于前收盘
            (features['收盘'] > features['开盘'].shift(1))  # 收盘高于前开盘
        ).astype(int)

        return features

    def create_target(self, data: pd.DataFrame, forward_days: int = 5,
                     threshold: float = 0.02) -> pd.Series:
        """
        创建预测目标

        Args:
            data: 包含收盘价的DataFrame
            forward_days: 向前看的天数
            threshold: 涨跌幅阈值

        Returns:
            目标序列 (1=上涨, 0=下跌/持平)
        """
        future_return = data['收盘'].shift(-forward_days) / data['收盘'] - 1

        target = (future_return > threshold).astype(int)

        return target

    def prepare_features(self, data: pd.DataFrame,
                        forward_days: int = 5,
                        threshold: float = 0.02) -> Tuple[pd.DataFrame, pd.Series]:
        """
        准备特征和目标

        Args:
            data: 原始数据
            forward_days: 向前看的天数
            threshold: 涨跌幅阈值

        Returns:
            特征DataFrame, 目标Series
        """
        # 创建特征
        features = self.create_technical_features(data)
        features = self.create_pattern_features(features)

        # 创建目标
        target = self.create_target(features, forward_days, threshold)

        # 删除NaN
        valid_idx = ~(features.isnull().any(axis=1) | target.isnull())
        features = features[valid_idx]
        target = target[valid_idx]

        return features, target


# =============================================================================
# 机器学习预测器
# =============================================================================

class MLPredictor:
    """机器学习预测器"""

    def __init__(self, model_type: str = "random_forest"):
        """
        初始化预测器

        Args:
            model_type: 模型类型 (random_forest, logistic, gradient_boosting)
        """
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn未安装")

        self.model_type = model_type
        self.model = None
        self.scaler = StandardScaler()
        self.feature_engineer = FeatureEngineer()
        self.feature_names = []
        self.is_trained = False

        # 选择模型
        if model_type == "random_forest":
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=10,
                random_state=42
            )
        elif model_type == "logistic":
            self.model = LogisticRegression(
                max_iter=1000,
                random_state=42
            )
        elif model_type == "gradient_boosting":
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
        else:
            raise ValueError(f"未知模型类型: {model_type}")

    def prepare_data(self, data: pd.DataFrame,
                    forward_days: int = 5,
                    threshold: float = 0.02) -> Tuple[pd.DataFrame, pd.Series]:
        """
        准备训练数据

        Args:
            data: 原始数据
            forward_days: 向前看的天数
            threshold: 涨跌幅阈值

        Returns:
            特征DataFrame, 目标Series
        """
        return self.feature_engineer.prepare_features(data, forward_days, threshold)

    def train(self, data: pd.DataFrame,
             test_size: float = 0.2,
             forward_days: int = 5,
             threshold: float = 0.02) -> ModelEvaluation:
        """
        训练模型

        Args:
            data: 训练数据
            test_size: 测试集比例
            forward_days: 向前看的天数
            threshold: 涨跌幅阈值

        Returns:
            模型评估结果
        """
        # 准备数据
        features, target = self.prepare_data(data, forward_days, threshold)

        # 选择特征列
        feature_cols = [col for col in features.columns
                       if col not in ['日期', '开盘', '最高', '最低', '收盘', '成交量']]

        X = features[feature_cols].fillna(0)
        y = target

        # 记录特征名
        self.feature_names = feature_cols

        # 分割数据
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        # 标准化
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # 训练模型
        self.model.fit(X_train_scaled, y_train)
        self.is_trained = True

        # 预测
        y_pred = self.model.predict(X_test_scaled)
        y_pred_proba = None

        if hasattr(self.model, "predict_proba"):
            y_pred_proba = self.model.predict_proba(X_test_scaled)[:, 1]

        # 计算评估指标
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        # 混淆矩阵
        cm = confusion_matrix(y_test, y_pred)

        # 特征重要性
        feature_importance = {}
        if hasattr(self.model, "feature_importances_"):
            for feat, imp in zip(feature_cols, self.model.feature_importances_):
                feature_importance[feat] = imp

        return ModelEvaluation(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            confusion_matrix=cm,
            feature_importance=feature_importance
        )

    def predict(self, data: pd.DataFrame) -> PredictionResult:
        """
        预测单只股票

        Args:
            data: 股票数据

        Returns:
            预测结果
        """
        if not self.is_trained:
            raise ValueError("模型未训练")

        # 准备特征
        features = self.feature_engineer.create_technical_features(data)
        features = self.feature_engineer.create_pattern_features(features)

        # 选择特征
        feature_cols = [col for col in features.columns
                       if col in self.feature_names]

        X = features[feature_cols].fillna(0)

        # 获取最新行
        latest = X.iloc[-1:].values
        latest_scaled = self.scaler.transform(latest)

        # 预测
        prediction = self.model.predict(latest_scaled)[0]
        prediction_str = "up" if prediction == 1 else "down"

        # 预测概率
        probability = 0.5
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(latest_scaled)[0]
            probability = proba[1] if prediction == 1 else proba[0]

        # 置信度
        confidence = abs(probability - 0.5) * 2

        # 特征值
        feature_values = {col: latest[0][i] for i, col in enumerate(feature_cols)}

        return PredictionResult(
            symbol=data.get('symbol', ['UNKNOWN'])[0] if 'symbol' in data.columns else 'UNKNOWN',
            date=data['日期'].iloc[-1] if '日期' in data.columns else datetime.now(),
            prediction=prediction_str,
            probability=probability,
            confidence=confidence,
            features=feature_values
        )

    def predict_batch(self, data_dict: Dict[str, pd.DataFrame]) -> Dict[str, PredictionResult]:
        """
        批量预测

        Args:
            data_dict: {symbol: DataFrame} 字典

        Returns:
            {symbol: PredictionResult} 字典
        """
        results = {}

        for symbol, data in data_dict.items():
            data['symbol'] = [symbol] * len(data)
            try:
                result = self.predict(data)
                results[symbol] = result
            except Exception as e:
                print(f"[WARN] {symbol} 预测失败: {e}")

        return results

    def get_feature_importance(self, top_n: int = 10) -> pd.DataFrame:
        """
        获取特征重要性

        Args:
            top_n: 返回前N个特征

        Returns:
            特征重要性DataFrame
        """
        if not self.is_trained or not hasattr(self.model, "feature_importances_"):
            return pd.DataFrame()

        importance_df = pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)

        return importance_df.head(top_n)

    def cross_validate(self, data: pd.DataFrame,
                       cv: int = 5,
                       forward_days: int = 5,
                       threshold: float = 0.02) -> Dict[str, float]:
        """
        交叉验证

        Args:
            data: 训练数据
            cv: 折数
            forward_days: 向前看的天数
            threshold: 涨跌幅阈值

        Returns:
            评估指标字典
        """
        # 准备数据
        features, target = self.prepare_data(data, forward_days, threshold)

        feature_cols = [col for col in features.columns
                       if col not in ['日期', '开盘', '最高', '最低', '收盘', '成交量']]

        X = features[feature_cols].fillna(0)
        y = target

        # 标准化
        X_scaled = self.scaler.fit_transform(X)

        # 交叉验证
        scores = cross_val_score(self.model, X_scaled, y, cv=cv, scoring='accuracy')

        return {
            'accuracy_mean': scores.mean(),
            'accuracy_std': scores.std(),
            'scores': scores.tolist()
        }


# =============================================================================
# 回归预测器（预测涨跌幅）
# =============================================================================

class RegressionPredictor:
    """回归预测器 - 预测涨跌幅"""

    def __init__(self):
        """初始化回归预测器"""
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn未安装")

        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            random_state=42
        )
        self.scaler = StandardScaler()
        self.feature_engineer = FeatureEngineer()
        self.feature_names = []
        self.is_trained = False

    def train(self, data: pd.DataFrame,
             forward_days: int = 5) -> Dict[str, float]:
        """
        训练回归模型

        Args:
            data: 训练数据
            forward_days: 向前看的天数

        Returns:
            评估指标字典
        """
        # 准备特征
        features = self.feature_engineer.create_technical_features(data)

        # 目标：未来收益率
        features['target_return'] = features['收盘'].shift(-forward_days) / features['收盘'] - 1

        # 删除NaN
        features = features.dropna()

        # 选择特征列
        feature_cols = [col for col in features.columns
                       if col not in ['日期', '开盘', '最高', '最低', '收盘', '成交量', 'target_return']]

        X = features[feature_cols].fillna(0)
        y = features['target_return']

        self.feature_names = feature_cols

        # 分割数据
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # 标准化
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # 训练
        self.model.fit(X_train_scaled, y_train)
        self.is_trained = True

        # 预测
        y_pred = self.model.predict(X_test_scaled)

        # 评估
        mse = mean_squared_error(y_test, y_pred)
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mse)

        # R²
        r2 = self.model.score(X_test_scaled, y_test)

        return {
            'mse': mse,
            'mae': mae,
            'rmse': rmse,
            'r2_score': r2
        }

    def predict_return(self, data: pd.DataFrame) -> float:
        """
        预测收益率

        Args:
            data: 股票数据

        Returns:
            预测的收益率
        """
        if not self.is_trained:
            raise ValueError("模型未训练")

        # 准备特征
        features = self.feature_engineer.create_technical_features(data)

        feature_cols = [col for col in features.columns
                       if col in self.feature_names]

        X = features[feature_cols].fillna(0)

        # 获取最新行
        latest = X.iloc[-1:].values
        latest_scaled = self.scaler.transform(latest)

        # 预测
        predicted_return = self.model.predict(latest_scaled)[0]

        return predicted_return


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("机器学习预测器 - v1.0")
    print()

    # 测试需要实际数据
    try:
        from stock_data_fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=252)

        if data is not None and len(data) > 0:
            data = fetcher.calculate_technical_indicators(data)

            # 创建预测器
            predictor = MLPredictor(model_type="random_forest")

            # 训练
            print("训练模型...")
            evaluation = predictor.train(data)

            print("\n模型评估:")
            print(f"  准确率: {evaluation.accuracy:.2%}")
            print(f"  精确率: {evaluation.precision:.2%}")
            print(f"  召回率: {evaluation.recall:.2%}")
            print(f"  F1分数: {evaluation.f1_score:.2%}")

            # 特征重要性
            print("\n特征重要性 (Top 5):")
            importance_df = predictor.get_feature_importance(top_n=5)
            for _, row in importance_df.iterrows():
                print(f"  {row['feature']}: {row['importance']:.3f}")

            # 预测
            print("\n预测最新数据:")
            result = predictor.predict(data)
            print(f"  预测: {result.prediction}")
            print(f"  概率: {result.probability:.2%}")
            print(f"  置信度: {result.confidence:.2%}")

            print("\n✓ 测试完成！")

        else:
            print("无法获取数据")

    except ImportError as e:
        print(f"✗ 模块未安装: {e}")
        print("请运行: pip install scikit-learn")
    except Exception as e:
        print(f"✗ 测试失败: {e}")
