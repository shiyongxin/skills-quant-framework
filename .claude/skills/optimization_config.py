# -*- coding: utf-8 -*-
"""
优化配置管理 - Optimization Configuration Management

可序列化的优化配置，包含数据范围、GA参数、适应度权重、目标定义等。
支持保存/加载JSON配置。
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime


@dataclass
class DataConfig:
    """数据配置"""
    data_dir: str = "./stock_data"
    regime_labels_file: str = "stock_data/regime_labels.csv"
    min_history_days: int = 5000
    min_rows: int = 2000
    start_date: str = "19960101"
    end_date: str = None  # None表示今天
    stock_sample_size: int = 50
    specific_symbols: list = field(default_factory=list)


@dataclass
class GAConfig:
    """遗传算法配置"""
    population_size: int = 100
    max_generations: int = 50
    tournament_size: int = 3
    crossover_rate: float = 0.8
    mutation_rate: float = 0.15
    elite_ratio: float = 0.1
    convergence_threshold: int = 10
    convergence_tolerance: float = 0.005


@dataclass
class WalkForwardConfig:
    """Walk-Forward验证配置"""
    train_days: int = 504       # 约2年
    test_days: int = 180        # 约6个月
    step_days: int = 63         # 约3个月


@dataclass
class FitnessConfig:
    """适应度函数配置"""
    target_return: float = 10.0         # 目标收益率(%)
    target_probability: float = 0.80    # 目标达标概率
    max_drawdown_limit: float = 25.0    # 最大回撤限制(%)
    # 适应度权重
    w_target_rate: float = 0.40
    w_return: float = 0.25
    w_sharpe: float = 0.20
    w_drawdown: float = 0.15


@dataclass
class RegimeConfig:
    """体制分类配置"""
    method: str = "adaptive"
    crash_threshold: float = -10.0
    recovery_threshold: float = 8.0
    bull_trend_pct: float = 5.0
    bear_trend_pct: float = -5.0


@dataclass
class IterativeRoundConfig:
    """多轮迭代中单轮的配置"""
    round_num: int = 1
    population_size: int = 40
    max_generations: int = 15
    mutation_rate: float = 0.25
    convergence_threshold: int = 5
    description: str = ""


@dataclass
class OptimizationConfig:
    """完整优化配置"""
    # 元信息
    name: str = "default"
    description: str = ""
    created_at: str = ""
    version: str = "1.0"

    # 子配置
    data: DataConfig = field(default_factory=DataConfig)
    ga: GAConfig = field(default_factory=GAConfig)
    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)
    fitness: FitnessConfig = field(default_factory=FitnessConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)

    # 多轮迭代配置
    iterative_rounds: list = field(default_factory=lambda: [
        IterativeRoundConfig(
            round_num=1, population_size=40, max_generations=15,
            mutation_rate=0.25, convergence_threshold=5,
            description="粗粒度搜索"
        ),
        IterativeRoundConfig(
            round_num=2, population_size=60, max_generations=25,
            mutation_rate=0.18, convergence_threshold=6,
            description="中粒度精炼"
        ),
        IterativeRoundConfig(
            round_num=3, population_size=100, max_generations=40,
            mutation_rate=0.12, convergence_threshold=8,
            description="细粒度精确"
        ),
    ])

    # 优化模式
    mode: str = "full"  # "global", "regime", "robust", "iterative", "full"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def save(self, filepath):
        """保存配置到JSON文件"""
        data = self._to_dict()
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] 配置已保存: {filepath}")

    @classmethod
    def load(cls, filepath) -> 'OptimizationConfig':
        """从JSON文件加载配置"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls._from_dict(data)

    def _to_dict(self) -> dict:
        """转为可序列化的字典"""
        result = {
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at,
            'version': self.version,
            'mode': self.mode,
            'data': asdict(self.data),
            'ga': asdict(self.ga),
            'walk_forward': asdict(self.walk_forward),
            'fitness': asdict(self.fitness),
            'regime': asdict(self.regime),
            'iterative_rounds': [asdict(r) for r in self.iterative_rounds],
        }
        return result

    @classmethod
    def _from_dict(cls, data: dict) -> 'OptimizationConfig':
        """从字典构建配置"""
        config = cls()
        config.name = data.get('name', 'default')
        config.description = data.get('description', '')
        config.created_at = data.get('created_at', '')
        config.version = data.get('version', '1.0')
        config.mode = data.get('mode', 'full')

        if 'data' in data:
            config.data = DataConfig(**data['data'])
        if 'ga' in data:
            config.ga = GAConfig(**data['ga'])
        if 'walk_forward' in data:
            config.walk_forward = WalkForwardConfig(**data['walk_forward'])
        if 'fitness' in data:
            config.fitness = FitnessConfig(**data['fitness'])
        if 'regime' in data:
            config.regime = RegimeConfig(**data['regime'])
        if 'iterative_rounds' in data:
            config.iterative_rounds = [
                IterativeRoundConfig(**r) for r in data['iterative_rounds']
            ]

        return config

    def get_ga_params(self) -> dict:
        """获取GA参数字典"""
        return {
            'population_size': self.ga.population_size,
            'max_generations': self.ga.max_generations,
            'tournament_size': self.ga.tournament_size,
            'crossover_rate': self.ga.crossover_rate,
            'mutation_rate': self.ga.mutation_rate,
            'elite_ratio': self.ga.elite_ratio,
            'convergence_threshold': self.ga.convergence_threshold,
            'convergence_tolerance': self.ga.convergence_tolerance,
        }

    def get_fitness_params(self) -> dict:
        """获取适应度参数字典"""
        return {
            'target_return': self.fitness.target_return,
            'target_probability': self.fitness.target_probability,
            'max_drawdown_limit': self.fitness.max_drawdown_limit,
        }

    def validate(self) -> list:
        """验证配置合法性"""
        issues = []

        if self.data.stock_sample_size < 10:
            issues.append("stock_sample_size 应 >= 10")

        if self.ga.population_size < 20:
            issues.append("population_size 应 >= 20")

        if self.ga.max_generations < 5:
            issues.append("max_generations 应 >= 5")

        if not (0 < self.ga.crossover_rate <= 1):
            issues.append("crossover_rate 应在 (0, 1]")

        if not (0 < self.ga.mutation_rate <= 1):
            issues.append("mutation_rate 应在 (0, 1]")

        if self.fitness.target_return <= 0:
            issues.append("target_return 应 > 0")

        if not (0 < self.fitness.target_probability <= 1):
            issues.append("target_probability 应在 (0, 1]")

        return issues


# ==================== 预设配置 ====================

def quick_test_config() -> OptimizationConfig:
    """快速测试配置 (小种群、少代数)"""
    config = OptimizationConfig(
        name="quick_test",
        description="快速测试用配置，小种群少代数",
    )
    config.data.stock_sample_size = 20
    config.ga.population_size = 30
    config.ga.max_generations = 10
    config.ga.convergence_threshold = 5
    return config


def standard_config() -> OptimizationConfig:
    """标准配置"""
    return OptimizationConfig(
        name="standard",
        description="标准优化配置",
    )


def thorough_config() -> OptimizationConfig:
    """深度优化配置 (大种群、多代数)"""
    config = OptimizationConfig(
        name="thorough",
        description="深度优化配置，大种群多代数，适合最终优化",
    )
    config.data.stock_sample_size = 100
    config.ga.population_size = 150
    config.ga.max_generations = 80
    config.ga.convergence_threshold = 15
    return config


def production_config() -> OptimizationConfig:
    """生产环境配置"""
    config = OptimizationConfig(
        name="production",
        description="生产环境优化配置，平衡速度与质量",
    )
    config.data.stock_sample_size = 80
    config.ga.population_size = 100
    config.ga.max_generations = 50
    return config


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='优化配置管理')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # create: 创建配置
    p_create = subparsers.add_parser('create', help='创建配置文件')
    p_create.add_argument('--preset', choices=['quick', 'standard', 'thorough', 'production'],
                         default='standard', help='预设配置')
    p_create.add_argument('--output', default='stock_data/optimization_config.json',
                         help='输出路径')

    # validate: 验证配置
    p_validate = subparsers.add_parser('validate', help='验证配置文件')
    p_validate.add_argument('config_file', help='配置文件路径')

    # show: 显示配置
    p_show = subparsers.add_parser('show', help='显示配置')
    p_show.add_argument('config_file', help='配置文件路径')

    args = parser.parse_args()

    if args.command == 'create':
        presets = {
            'quick': quick_test_config,
            'standard': standard_config,
            'thorough': thorough_config,
            'production': production_config,
        }
        config = presets[args.preset]()
        config.save(args.output)

    elif args.command == 'validate':
        config = OptimizationConfig.load(args.config_file)
        issues = config.validate()
        if issues:
            print("配置问题:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("配置合法")

    elif args.command == 'show':
        config = OptimizationConfig.load(args.config_file)
        print(json.dumps(config._to_dict(), ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
