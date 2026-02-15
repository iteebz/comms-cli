from comms.health import CheckResult, score


def test_health_score_weighting_and_ok():
    checks = [
        ("a", lambda: CheckResult(ok=True, score=100, detail="ok"), 50),
        ("b", lambda: CheckResult(ok=False, score=0, detail="bad"), 30),
        ("c", lambda: CheckResult(ok=True, score=100, detail="ok"), 20),
    ]

    result = score(checks=checks)

    assert result["ok"] is False
    assert result["score"] == 70
    assert result["checks"]["a"]["ok"] is True
    assert result["checks"]["b"]["ok"] is False
    assert result["checks"]["c"]["ok"] is True
