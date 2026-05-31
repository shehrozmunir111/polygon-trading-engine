from src.feeds.polygon_feed import PolygonFeed


def test_parse_forex_quote():
    msg = {"ev": "C", "pair": "EURUSD", "bp": 1.08400, "ap": 1.08420, "t": 1700000000000}
    tick = PolygonFeed._parse(msg)
    assert tick is not None
    assert tick.symbol == "C:EURUSD"
    assert tick.bid == 1.08400
    assert tick.ask == 1.08420
    assert tick.mid == round((1.08400 + 1.08420) / 2, 6)
    assert tick.timestamp == 1700000000000


def test_parse_crypto_quote():
    msg = {"ev": "XQ", "p": "BTC-USD", "b": 42000.0, "a": 42010.0, "t": 1700000001000}
    tick = PolygonFeed._parse(msg)
    assert tick is not None
    assert tick.symbol == "X:BTCUSD"
    assert tick.bid == 42000.0
    assert tick.ask == 42010.0


def test_parse_returns_none_for_unknown_event():
    msg = {"ev": "T", "pair": "EURUSD", "bp": 1.08400, "ap": 1.08420, "t": 1700000000000}
    assert PolygonFeed._parse(msg) is None


def test_parse_returns_none_when_bid_zero():
    msg = {"ev": "C", "pair": "EURUSD", "bp": 0, "ap": 1.08420, "t": 1700000000000}
    assert PolygonFeed._parse(msg) is None


def test_parse_returns_none_when_ask_zero():
    msg = {"ev": "C", "pair": "EURUSD", "bp": 1.08400, "ap": 0, "t": 1700000000000}
    assert PolygonFeed._parse(msg) is None


def test_parse_prefixed_symbol_not_double_prefixed():
    msg = {"ev": "C", "pair": "C:EURUSD", "bp": 1.08400, "ap": 1.08420, "t": 1700000000000}
    tick = PolygonFeed._parse(msg)
    assert tick is not None
    assert tick.symbol == "C:EURUSD"


def test_subscription_channel_forex():
    assert PolygonFeed._subscription_channel("C:EURUSD", "forex") == "C.EUR-USD"


def test_subscription_channel_crypto():
    assert PolygonFeed._subscription_channel("X:BTCUSD", "crypto") == "XQ.BTC-USD"
