"""Manual live qualification tests for TestConnection (SWE.6, Set 2).

All tests are marked @pytest.mark.live and require TWS running on
127.0.0.1:5931 with API enabled. Excluded from CI runs.

Run locally:
    pytest tests/qualification/test_live_flow.py -v -m live
"""

import pytest


# ── TestLiveTWSConnection ─────────────────────────────────────────────────────


class TestLiveTWSConnection:
    """End-to-end qualification against a real TWS session (SWE.6, Set 2).

    Each test drives TestConnection through the flow up to the point under
    test and asserts on the resulting state. Tests are ordered by flow step —
    later tests depend on earlier ones completing successfully.
    """

    @pytest.mark.live
    def test_live_connects_and_handshake_completes(self) -> None:
        pytest.skip("pending")

    @pytest.mark.live
    def test_live_underlying_price_received(self) -> None:
        pytest.skip("pending")

    @pytest.mark.live
    def test_live_contract_id_resolved(self) -> None:
        pytest.skip("pending")

    @pytest.mark.live
    def test_live_option_chain_parameters_loaded(self) -> None:
        pytest.skip("pending")

    @pytest.mark.live
    def test_live_atm_greeks_populate_within_30s(self) -> None:
        pytest.skip("pending")
