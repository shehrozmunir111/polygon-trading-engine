import csv
from datetime import datetime
from pathlib import Path

from src.broker.base import OrderResult
from src.notifications.telegram_bot import TelegramNotifier, TRADES_FILE
from src.strategy.decide import TradeSignal


def test_format_trade_alert_contains_expected_fields():
    notifier = TelegramNotifier(token="123456:ABCdefGHIjklMNOpqrSTUvwxYZ", chat_id="123")
    result = OrderResult(
        success=True,
        order_id="SIM-00001",
        symbol="C:EURUSD",
        action="BUY",
        units=1000,
        price=1.08415,
        timestamp=1700000000.0,
    )
    signal = TradeSignal(
        action="BUY",
        symbol="C:EURUSD",
        price=1.08415,
        reason="EMA cross UP | RSI=58.3",
        confidence=0.72,
    )

    message = notifier._format_trade_alert(result, signal)

    assert "🟢 BUY | EUR/USD" in message
    assert "1.084150" in message
    assert "EMA cross UP | RSI=58.3" in message
    assert "72%" in message
    assert "SIM-00001" in message


def test_today_trade_summary_counts_wins_and_losses(tmp_path, monkeypatch):
    csv_file = tmp_path / "trades.csv"
    data = [
        {
            "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": "C:EURUSD",
            "action": "BUY",
            "price": "1.08415",
            "units": "1000",
            "order_id": "SIM-00001",
            "reason": "Entry",
            "confidence": "0.72",
            "mode": "simulation",
        },
        {
            "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": "C:EURUSD",
            "action": "CLOSE",
            "price": "1.09000",
            "units": "1000",
            "order_id": "SIM-CLOSE-00002",
            "reason": "Exit",
            "confidence": "0.80",
            "mode": "simulation",
        },
    ]

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp_utc",
            "symbol",
            "action",
            "price",
            "units",
            "order_id",
            "reason",
            "confidence",
            "mode",
        ])
        writer.writeheader()
        writer.writerows(data)

    monkeypatch.setattr("src.notifications.telegram_bot.TRADES_FILE", csv_file)
    notifier = TelegramNotifier(token="123456:ABCdefGHIjklMNOpqrSTUvwxYZ", chat_id="123")
    summary = notifier._today_trade_summary()

    assert "Total trades: 1" in summary
    assert "Wins: 1" in summary
    assert "Losses: 0" in summary
