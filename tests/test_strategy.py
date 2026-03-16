"""Tests for the composable strategy layer."""

from __future__ import annotations

import time
import unittest

from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    CompetitionSnapshot,
    MarketSnapshot,
    PositionSnapshot,
    RiskLimits,
    SignalState,
)
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.strategy.builder import build_strategy_layer
from arena_agent.strategy.layer import StrategyLayer, get_indicator
from arena_agent.strategy.sizing import FixedFractionSizer, VolatilityScaledSizer, RiskPerTradeSizer
from arena_agent.strategy.tpsl import FixedTPSL, ATRBasedTPSL, RMultipleTPSL
from arena_agent.strategy.rules import (
    TrailingStop,
    TimeExit,
    DrawdownExit,
    VolatilityGate,
    TradeBudgetFilter,
)


def _state(
    price: float = 100.0,
    equity: float = 1000.0,
    atr: float = 2.0,
    volatility: float = 0.02,
    position: PositionSnapshot | None = None,
    remaining_trades: int = 30,
) -> AgentState:
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol="BTCUSDT",
            interval="1m",
            last_price=price,
            mark_price=price,
            volatility=volatility,
            orderbook_imbalance=0.1,
            recent_candles=[],
        ),
        signal_state=SignalState(
            version="signal_state.v1",
            backend="builtin",
            requested=[],
            values={"atr_14": atr, "volatility_20": volatility, "sma_20": price * 0.99},
            warmup_complete=True,
            metadata={},
        ),
        account=AccountSnapshot(
            balance=equity,
            equity=equity,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            trade_count=5,
        ),
        position=position,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol="BTCUSDT",
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=10,
            max_trades=40,
            max_trades_remaining=remaining_trades,
            time_remaining_seconds=600.0,
        ),
    )


class GetIndicatorTest(unittest.TestCase):
    def test_exact_match(self) -> None:
        state = _state(atr=3.5)
        self.assertAlmostEqual(get_indicator(state, "atr", 14), 3.5)

    def test_prefix_match(self) -> None:
        state = _state(atr=3.5)
        self.assertAlmostEqual(get_indicator(state, "atr"), 3.5)

    def test_missing(self) -> None:
        state = _state()
        self.assertIsNone(get_indicator(state, "nonexistent"))


class FixedFractionSizerTest(unittest.TestCase):
    def test_computes_size(self) -> None:
        sizer = FixedFractionSizer(fraction=0.05)
        state = _state(price=100.0, equity=1000.0)
        action = Action(type=ActionType.OPEN_LONG)
        size = sizer.compute(action, state)
        self.assertIsNotNone(size)
        self.assertAlmostEqual(size, 0.5)  # 1000 * 0.05 / 100


class VolatilityScaledSizerTest(unittest.TestCase):
    def test_computes_inverse_volatility_size(self) -> None:
        sizer = VolatilityScaledSizer(target_risk_pct=0.02, atr_multiplier=2.0)
        state = _state(equity=1000.0, atr=2.0)
        action = Action(type=ActionType.OPEN_LONG)
        size = sizer.compute(action, state)
        # 1000 * 0.02 / (2.0 * 2.0) = 20 / 4 = 5.0
        self.assertAlmostEqual(size, 5.0)

    def test_returns_none_without_atr(self) -> None:
        sizer = VolatilityScaledSizer()
        state = _state()
        state = AgentState(
            timestamp=state.timestamp,
            market=state.market,
            signal_state=SignalState("v1", "builtin", [], {}, True, {}),
            account=state.account,
            position=None,
            competition=state.competition,
        )
        self.assertIsNone(sizer.compute(Action(type=ActionType.OPEN_LONG), state))


class RiskPerTradeSizerTest(unittest.TestCase):
    def test_sizes_from_sl_distance(self) -> None:
        sizer = RiskPerTradeSizer(max_risk_pct=0.01)
        state = _state(price=100.0, equity=1000.0)
        action = Action(type=ActionType.OPEN_LONG, stop_loss=98.0)
        size = sizer.compute(action, state)
        # risk = 1000 * 0.01 = 10, distance = |100 - 98| = 2, size = 10/2 = 5
        self.assertAlmostEqual(size, 5.0)

    def test_falls_back_to_atr(self) -> None:
        sizer = RiskPerTradeSizer(max_risk_pct=0.01, fallback_atr_multiplier=1.5)
        state = _state(price=100.0, equity=1000.0, atr=2.0)
        action = Action(type=ActionType.OPEN_LONG)  # no SL
        size = sizer.compute(action, state)
        # risk = 10, atr distance = 2 * 1.5 = 3, size = 10/3 ≈ 3.333
        self.assertAlmostEqual(size, 10.0 / 3.0, places=3)


class FixedTPSLTest(unittest.TestCase):
    def test_long_tpsl(self) -> None:
        placer = FixedTPSL(tp_pct=0.01, sl_pct=0.005)
        state = _state(price=100.0)
        tp, sl = placer.compute(Action(type=ActionType.OPEN_LONG), state)
        self.assertAlmostEqual(tp, 101.0)
        self.assertAlmostEqual(sl, 99.5)

    def test_short_tpsl(self) -> None:
        placer = FixedTPSL(tp_pct=0.01, sl_pct=0.005)
        state = _state(price=100.0)
        tp, sl = placer.compute(Action(type=ActionType.OPEN_SHORT), state)
        self.assertAlmostEqual(tp, 99.0)
        self.assertAlmostEqual(sl, 100.5)


class ATRBasedTPSLTest(unittest.TestCase):
    def test_long_atr_tpsl(self) -> None:
        placer = ATRBasedTPSL(atr_tp_mult=2.0, atr_sl_mult=1.5)
        state = _state(price=100.0, atr=2.0)
        tp, sl = placer.compute(Action(type=ActionType.OPEN_LONG), state)
        self.assertAlmostEqual(tp, 104.0)  # 100 + 2*2
        self.assertAlmostEqual(sl, 97.0)   # 100 - 2*1.5


class RMultipleTPSLTest(unittest.TestCase):
    def test_long_r_multiple(self) -> None:
        placer = RMultipleTPSL(sl_atr_mult=1.5, reward_risk_ratio=2.0)
        state = _state(price=100.0, atr=2.0)
        tp, sl = placer.compute(Action(type=ActionType.OPEN_LONG), state)
        # SL distance = 2*1.5 = 3, TP distance = 3*2 = 6
        self.assertAlmostEqual(sl, 97.0)
        self.assertAlmostEqual(tp, 106.0)


class VolatilityGateTest(unittest.TestCase):
    def test_blocks_low_volatility(self) -> None:
        gate = VolatilityGate(min_volatility=0.03)
        state = _state(volatility=0.01)
        ok, reason = gate.allow(Action(type=ActionType.OPEN_LONG), state)
        self.assertFalse(ok)
        self.assertIn("below", reason)

    def test_passes_in_range(self) -> None:
        gate = VolatilityGate(min_volatility=0.01, max_volatility=0.05)
        state = _state(volatility=0.02)
        ok, _ = gate.allow(Action(type=ActionType.OPEN_LONG), state)
        self.assertTrue(ok)


class TradeBudgetFilterTest(unittest.TestCase):
    def test_blocks_when_budget_low(self) -> None:
        f = TradeBudgetFilter(min_remaining_trades=10)
        state = _state(remaining_trades=5)
        ok, reason = f.allow(Action(type=ActionType.OPEN_LONG), state)
        self.assertFalse(ok)

    def test_passes_with_budget(self) -> None:
        f = TradeBudgetFilter(min_remaining_trades=5)
        state = _state(remaining_trades=20)
        ok, _ = f.allow(Action(type=ActionType.OPEN_LONG), state)
        self.assertTrue(ok)


class TrailingStopTest(unittest.TestCase):
    def test_moves_sl_up_for_long(self) -> None:
        rule = TrailingStop(atr_multiplier=2.0)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=95.0,
            unrealized_pnl=5.0, stop_loss=93.0,
            metadata={"openTime": int(time.time() * 1000)},
        )
        state = _state(price=100.0, atr=2.0, position=pos)
        result = rule.check(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.type, ActionType.UPDATE_TPSL)
        self.assertAlmostEqual(result.stop_loss, 96.0)  # 100 - 2*2

    def test_does_not_move_sl_down_for_long(self) -> None:
        rule = TrailingStop(atr_multiplier=2.0)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=95.0,
            unrealized_pnl=1.0, stop_loss=97.0,  # already above new trail
            metadata={"openTime": int(time.time() * 1000)},
        )
        state = _state(price=100.0, atr=2.0, position=pos)
        result = rule.check(state)
        self.assertIsNone(result)  # 100-4=96 < 97, don't move down

    def test_moves_sl_down_for_short(self) -> None:
        rule = TrailingStop(atr_multiplier=2.0)
        pos = PositionSnapshot(
            direction="short", size=0.01, entry_price=105.0,
            unrealized_pnl=5.0, stop_loss=108.0,
            metadata={"openTime": int(time.time() * 1000)},
        )
        state = _state(price=100.0, atr=2.0, position=pos)
        result = rule.check(state)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.stop_loss, 104.0)  # 100 + 2*2


class TimeExitTest(unittest.TestCase):
    def test_exits_after_timeout(self) -> None:
        rule = TimeExit(max_hold_seconds=60.0)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=100.0,
            unrealized_pnl=0.0,
            metadata={"openTime": int((time.time() - 120) * 1000)},
        )
        state = _state(position=pos)
        result = rule.check(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.type, ActionType.CLOSE_POSITION)

    def test_holds_before_timeout(self) -> None:
        rule = TimeExit(max_hold_seconds=600.0)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=100.0,
            unrealized_pnl=0.0,
            metadata={"openTime": int((time.time() - 10) * 1000)},
        )
        state = _state(position=pos)
        self.assertIsNone(rule.check(state))


class DrawdownExitTest(unittest.TestCase):
    def test_exits_on_drawdown(self) -> None:
        rule = DrawdownExit(max_drawdown_pct=0.01)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=100.0,
            unrealized_pnl=-15.0,  # 15/1000 = 1.5% > 1%
        )
        state = _state(equity=1000.0, position=pos)
        result = rule.check(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.type, ActionType.CLOSE_POSITION)

    def test_no_exit_in_profit(self) -> None:
        rule = DrawdownExit(max_drawdown_pct=0.01)
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=100.0,
            unrealized_pnl=5.0,
        )
        state = _state(position=pos)
        self.assertIsNone(rule.check(state))


class StrategyLayerIntegrationTest(unittest.TestCase):
    def test_refine_applies_sizing_and_tpsl(self) -> None:
        layer = StrategyLayer(
            sizer=FixedFractionSizer(fraction=0.05),
            tpsl_placer=FixedTPSL(tp_pct=0.01, sl_pct=0.005),
        )
        state = _state(price=100.0, equity=1000.0)
        action = Action(type=ActionType.OPEN_LONG)

        refined = layer.refine(action, state)

        self.assertEqual(refined.type, ActionType.OPEN_LONG)
        self.assertAlmostEqual(refined.size, 0.5)
        self.assertAlmostEqual(refined.take_profit, 101.0)
        self.assertAlmostEqual(refined.stop_loss, 99.5)

    def test_exit_rule_overrides_hold(self) -> None:
        layer = StrategyLayer(
            exit_rules=[DrawdownExit(max_drawdown_pct=0.01)],
        )
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=100.0,
            unrealized_pnl=-20.0,
        )
        state = _state(equity=1000.0, position=pos)
        action = Action.hold(reason="agent says hold")

        refined = layer.refine(action, state)

        self.assertEqual(refined.type, ActionType.CLOSE_POSITION)
        self.assertEqual(refined.metadata["strategy_exit_rule"], "drawdown_exit")

    def test_entry_filter_blocks_open(self) -> None:
        layer = StrategyLayer(
            entry_filters=[TradeBudgetFilter(min_remaining_trades=10)],
        )
        state = _state(remaining_trades=3)
        action = Action(type=ActionType.OPEN_LONG)

        refined = layer.refine(action, state)

        self.assertEqual(refined.type, ActionType.HOLD)
        self.assertIn("strategy_filter", refined.metadata["reason"])

    def test_passthrough_when_no_components(self) -> None:
        layer = StrategyLayer()
        state = _state()
        action = Action(type=ActionType.OPEN_LONG, size=0.01)

        refined = layer.refine(action, state)

        self.assertEqual(refined.type, ActionType.OPEN_LONG)
        self.assertEqual(refined.size, 0.01)

    def test_hold_passes_through_without_position(self) -> None:
        layer = StrategyLayer(exit_rules=[DrawdownExit(max_drawdown_pct=0.01)])
        state = _state(position=None)
        action = Action.hold(reason="wait")

        refined = layer.refine(action, state)

        self.assertEqual(refined.type, ActionType.HOLD)


class AgentOverrideTest(unittest.TestCase):
    def test_agent_overrides_sizer(self) -> None:
        layer = StrategyLayer(
            sizer=FixedFractionSizer(fraction=0.05),  # YAML default
            tpsl_placer=FixedTPSL(tp_pct=0.01, sl_pct=0.005),
        )
        state = _state(price=100.0, equity=1000.0, atr=2.0)
        # Agent overrides sizing to risk_per_trade
        action = Action(
            type=ActionType.OPEN_LONG,
            stop_loss=98.0,
            metadata={
                "strategy": {
                    "sizing": {"type": "risk_per_trade", "max_risk_pct": 0.01},
                }
            },
        )
        refined = layer.refine(action, state)
        # risk_per_trade: 1000*0.01 / |100-98| = 10/2 = 5.0
        self.assertAlmostEqual(refined.size, 5.0)
        self.assertEqual(refined.metadata["strategy_sizing"], "risk_per_trade")

    def test_agent_overrides_tpsl(self) -> None:
        layer = StrategyLayer(
            tpsl_placer=FixedTPSL(tp_pct=0.01, sl_pct=0.005),  # YAML default
        )
        state = _state(price=100.0, atr=2.0)
        action = Action(
            type=ActionType.OPEN_LONG,
            metadata={
                "strategy": {
                    "tpsl": {"type": "atr_multiple", "atr_tp_mult": 3.0, "atr_sl_mult": 1.0},
                }
            },
        )
        refined = layer.refine(action, state)
        # ATR-based: TP = 100 + 2*3 = 106, SL = 100 - 2*1 = 98
        self.assertAlmostEqual(refined.take_profit, 106.0)
        self.assertAlmostEqual(refined.stop_loss, 98.0)
        self.assertEqual(refined.metadata["strategy_tpsl"], "atr_multiple")

    def test_agent_bypasses_strategy(self) -> None:
        layer = StrategyLayer(
            sizer=FixedFractionSizer(fraction=0.05),
            tpsl_placer=FixedTPSL(tp_pct=0.01, sl_pct=0.005),
        )
        state = _state(price=100.0, equity=1000.0)
        action = Action(
            type=ActionType.OPEN_LONG,
            size=0.002,
            take_profit=105.0,
            stop_loss=95.0,
            metadata={"strategy": "none"},
        )
        refined = layer.refine(action, state)
        # Strategy bypassed — original values preserved
        self.assertEqual(refined.size, 0.002)
        self.assertAlmostEqual(refined.take_profit, 105.0)
        self.assertAlmostEqual(refined.stop_loss, 95.0)
        self.assertEqual(refined.metadata["strategy_override"], "none")

    def test_agent_overrides_exit_rules(self) -> None:
        layer = StrategyLayer(
            exit_rules=[DrawdownExit(max_drawdown_pct=0.01)],  # YAML default
        )
        pos = PositionSnapshot(
            direction="long", size=0.01, entry_price=95.0,
            unrealized_pnl=5.0, stop_loss=93.0,
            metadata={"openTime": int(time.time() * 1000)},
        )
        state = _state(price=100.0, atr=2.0, equity=1000.0, position=pos)
        # Agent overrides exit rules to trailing stop instead of drawdown
        action = Action.hold(
            reason="hold",
            strategy={
                "exit_rules": [{"type": "trailing_stop", "atr_multiplier": 2.0}],
            },
        )
        refined = layer.refine(action, state)
        # Trailing stop fires: 100 - 2*2 = 96 > current SL 93
        self.assertEqual(refined.type, ActionType.UPDATE_TPSL)
        self.assertAlmostEqual(refined.stop_loss, 96.0)

    def test_no_override_uses_defaults(self) -> None:
        layer = StrategyLayer(
            sizer=FixedFractionSizer(fraction=0.05),
        )
        state = _state(price=100.0, equity=1000.0)
        action = Action(type=ActionType.OPEN_LONG)  # no strategy in metadata
        refined = layer.refine(action, state)
        self.assertAlmostEqual(refined.size, 0.5)  # YAML default applied
        self.assertEqual(refined.metadata["strategy_sizing"], "fixed_fraction")


class BuilderTest(unittest.TestCase):
    def test_build_full_strategy(self) -> None:
        config = {
            "sizing": {"type": "volatility_scaled", "target_risk_pct": 0.02},
            "tpsl": {"type": "atr_multiple", "atr_tp_mult": 2.0, "atr_sl_mult": 1.5},
            "entry_filters": [
                {"type": "trade_budget", "min_remaining_trades": 5},
            ],
            "exit_rules": [
                {"type": "trailing_stop", "atr_multiplier": 2.0},
                {"type": "drawdown_exit", "max_drawdown_pct": 0.02},
            ],
        }
        layer = build_strategy_layer(config)
        self.assertIsNotNone(layer)
        self.assertEqual(layer.sizer.name, "volatility_scaled")
        self.assertEqual(layer.tpsl_placer.name, "atr_multiple")
        self.assertEqual(len(layer.entry_filters), 1)
        self.assertEqual(len(layer.exit_rules), 2)

    def test_build_empty_returns_none(self) -> None:
        self.assertIsNone(build_strategy_layer({}))
        self.assertIsNone(build_strategy_layer(None))

    def test_build_partial(self) -> None:
        layer = build_strategy_layer({"sizing": {"type": "fixed_fraction", "fraction": 0.1}})
        self.assertIsNotNone(layer)
        self.assertEqual(layer.sizer.name, "fixed_fraction")
        self.assertIsNone(layer.tpsl_placer)

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_strategy_layer({"sizing": {"type": "nonexistent"}})


if __name__ == "__main__":
    unittest.main()
