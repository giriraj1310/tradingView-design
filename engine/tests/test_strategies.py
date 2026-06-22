from trader.strategies.trend import TrendFollowing


def test_trend_holds_uptrend(uptrend):
    strat = TrendFollowing(sma_window=200, base_gross=1.0)
    weights = strat.target_weights({"AAA": uptrend})
    assert weights.get("AAA", 0) > 0


def test_trend_avoids_downtrend(downtrend):
    strat = TrendFollowing(sma_window=200, base_gross=1.0)
    weights = strat.target_weights({"BBB": downtrend})
    assert weights.get("BBB", 0) == 0


def test_trend_equal_weights_split(uptrend):
    strat = TrendFollowing(sma_window=200, base_gross=1.0)
    weights = strat.target_weights({"AAA": uptrend, "CCC": uptrend})
    assert weights["AAA"] == weights["CCC"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_trend_respects_warmup():
    strat = TrendFollowing(sma_window=200)
    assert strat.warmup == 201
