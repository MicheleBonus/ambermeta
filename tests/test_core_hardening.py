"""Tests for CORE-D2/D7: natural stage ordering and single-digit sequence detection."""
from ambermeta.protocol import detect_numeric_sequences, _ordered_stems


def test_natural_order_unpadded():
    grouped = {f"prod_{i}": {} for i in (1, 2, 10, 11)}
    assert _ordered_stems(grouped) == ["prod_1", "prod_2", "prod_10", "prod_11"]


def test_sequence_detects_single_digits():
    seqs = detect_numeric_sequences(["prod_1", "prod_2", "prod_3"])
    assert any(len(v) == 3 for v in seqs.values())
