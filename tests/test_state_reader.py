from __future__ import annotations

from fort_gym.bench.env.state_reader import StateReader


def test_normalization_preserves_usable_stock_counts(monkeypatch) -> None:
    """G6 attempt 3 (run 19f692b8) ran WITHOUT the approved usable-stocks
    correction: the state script emitted wood_usable/stone_usable but this
    whitelist silently dropped them. The full pipeline (lua -> raw ->
    normalized -> encoder) must carry the fields end to end."""

    raw = {
        "time": 100,
        "population": 7,
        "stocks": {
            "food": 45,
            "drink": 60,
            "wood": 11,
            "wood_usable": 1,
            "stone": 4,
            "stone_usable": 4,
            "wealth": 9,
        },
        "dead": 0,
    }

    class _Client:
        def get_state(self):
            return raw

    # from_dfhack's exact entry shape varies; normalize directly if exposed,
    # otherwise exercise the private normalizer through the public path.
    normalize = getattr(StateReader, "_normalize", None)
    if normalize is not None:
        normalized = normalize(raw)
    else:  # pragma: no cover - fallback for interface drift
        normalized = StateReader.from_dfhack(_Client())

    assert normalized["stocks"]["wood"] == 11
    assert normalized["stocks"]["wood_usable"] == 1
    assert normalized["stocks"]["stone_usable"] == 4

    # legacy raw payloads (no usable fields) keep working
    legacy = dict(raw, stocks={"food": 1, "drink": 2, "wood": 3, "stone": 0, "wealth": 0})
    if normalize is not None:
        legacy_norm = normalize(legacy)
        assert legacy_norm["stocks"]["wood"] == 3
        assert legacy_norm["stocks"]["wood_usable"] is None
