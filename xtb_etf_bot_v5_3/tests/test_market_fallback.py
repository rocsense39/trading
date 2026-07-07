from core.models import Instrument
from market.data import _configured_fallback


def test_static_fallback_has_no_candle_confirmations():
    inst = Instrument("AIINFRA", "AIFS.DE", "AIFS.DE", "satellite", .05, fallback_close=9.64)
    snap = _configured_fallback(inst)
    assert snap is not None
    assert snap.source == "static_fallback"
    assert snap.confirmations == ()
