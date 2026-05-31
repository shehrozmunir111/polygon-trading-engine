import json
import time
from pathlib import Path

from src.broker.base import OrderResult
from src.ledger.receipt import ReceiptLedger
from src.strategy.decide import TradeSignal


def _result(action="BUY", price=1.08415) -> OrderResult:
    return OrderResult(
        success=True,
        order_id="SIM-00001",
        symbol="C:EURUSD",
        action=action,
        units=1000,
        price=price,
        timestamp=time.time(),
    )


def _signal(action="BUY", price=1.08415) -> TradeSignal:
    return TradeSignal(
        action=action,
        symbol="C:EURUSD",
        price=price,
        reason="EMA cross UP | RSI=58.3",
        confidence=0.72,
    )


def _ledger(tmp_path: Path, secret: str = "test-secret") -> ReceiptLedger:
    return ReceiptLedger(secret_key=secret, mode="simulation", receipts_dir=tmp_path)


# ── generate: field presence ─────────────────────────────────────────────────

def test_generate_returns_all_required_fields(tmp_path):
    ledger = _ledger(tmp_path)
    receipt = ledger.generate(_result(), _signal())

    for field in (
        "receipt_id", "timestamp_utc", "symbol", "action", "price",
        "units", "order_id", "reason", "confidence", "mode", "signature",
    ):
        assert field in receipt, f"Missing field: {field}"


def test_generate_maps_result_and_signal_correctly(tmp_path):
    ledger = _ledger(tmp_path)
    receipt = ledger.generate(_result(action="SELL", price=1.09), _signal(action="SELL", price=1.09))

    assert receipt["symbol"] == "C:EURUSD"
    assert receipt["action"] == "SELL"
    assert receipt["price"] == 1.09
    assert receipt["units"] == 1000
    assert receipt["mode"] == "simulation"
    assert receipt["reason"] == "EMA cross UP | RSI=58.3"
    assert receipt["confidence"] == 0.72


# ── generate: file persistence ────────────────────────────────────────────────

def test_generate_saves_json_file(tmp_path):
    ledger = _ledger(tmp_path)
    receipt = ledger.generate(_result(), _signal())

    saved_path = tmp_path / f"{receipt['receipt_id']}.json"
    assert saved_path.exists()
    on_disk = json.loads(saved_path.read_text())
    assert on_disk["receipt_id"] == receipt["receipt_id"]
    assert on_disk["signature"] == receipt["signature"]


def test_generate_unique_receipt_ids(tmp_path):
    ledger = _ledger(tmp_path)
    r1 = ledger.generate(_result(), _signal())
    r2 = ledger.generate(_result(), _signal())
    assert r1["receipt_id"] != r2["receipt_id"]


# ── verify: valid receipt ─────────────────────────────────────────────────────

def test_verify_returns_true_for_valid_receipt(tmp_path):
    ledger = _ledger(tmp_path, secret="secret123")
    receipt = ledger.generate(_result(), _signal())
    assert ledger.verify(receipt) is True


def test_verify_returns_false_for_tampered_price(tmp_path):
    ledger = _ledger(tmp_path, secret="secret123")
    receipt = ledger.generate(_result(), _signal())
    tampered = dict(receipt)
    tampered["price"] = 9999.0
    assert ledger.verify(tampered) is False


def test_verify_returns_false_for_tampered_action(tmp_path):
    ledger = _ledger(tmp_path, secret="secret123")
    receipt = ledger.generate(_result(), _signal())
    tampered = dict(receipt)
    tampered["action"] = "SELL"
    assert ledger.verify(tampered) is False


def test_verify_returns_false_for_wrong_key(tmp_path):
    signer = _ledger(tmp_path, secret="correct-key")
    verifier = _ledger(tmp_path, secret="wrong-key")
    receipt = signer.generate(_result(), _signal())
    assert verifier.verify(receipt) is False


def test_verify_returns_false_for_missing_signature(tmp_path):
    ledger = _ledger(tmp_path)
    receipt = ledger.generate(_result(), _signal())
    no_sig = {k: v for k, v in receipt.items() if k != "signature"}
    assert ledger.verify(no_sig) is False


# ── file save failure is non-fatal ────────────────────────────────────────────

def test_generate_survives_unwritable_directory(tmp_path):
    """Receipt is returned even when the save path cannot be written."""
    # Create a ledger whose receipts_dir is valid at construction time,
    # then replace _receipts_dir with a file-as-directory to trigger OSError on write.
    ledger = _ledger(tmp_path)
    block = tmp_path / "block.txt"
    block.write_text("x")
    ledger._receipts_dir = block   # save will fail: it's a file, not a dir

    receipt = ledger.generate(_result(), _signal())   # must not raise
    assert "receipt_id" in receipt
    assert "signature" in receipt
