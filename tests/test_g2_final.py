import pandas as pd
import pytest

from bot.run_g2 import TARGET_VOL, gate_v2, profit_factor
from bot.multi import rotation_momentum
from tests.test_bot_multi import _dfs


def test_target_vol_follows_the_announced_rule():
    assert TARGET_VOL == pytest.approx(0.19)


def test_profit_factor():
    t = pd.DataFrame({'pnl': [0.2, 0.2, 0.2, 0.2, -0.05, -0.05, -0.05, -0.05, -0.05, -0.05]})
    assert profit_factor(t) == pytest.approx(0.8 / 0.3)


def test_lower_target_vol_scales_positions_down():
    dfs = _dfs(n=24 * 500)
    _, _, w_hi = rotation_momentum(dfs, target_vol=0.40)
    _, _, w_lo = rotation_momentum(dfs, target_vol=0.19)
    assert (w_lo.sum(axis=1) <= w_hi.sum(axis=1) + 1e-12).all()
    assert w_lo.sum(axis=1).max() > 0


def test_gate_v2():
    good = {'sharpe': 1.8, 'max_drawdown': -0.12, 'profit_factor': 2.0, 't_stat': 3.5}
    assert gate_v2(good)[1]
    assert not gate_v2(dict(good, max_drawdown=-0.25))[1]
    assert not gate_v2(dict(good, profit_factor=1.2))[1]
