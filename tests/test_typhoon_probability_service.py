from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.typhoon_probability_service import run_typhoon_probability


def test_typhoon_probability_requires_coordinates() -> None:
    with pytest.raises(ValueError):
        run_typhoon_probability({"model_scope": "total", "points": []})


def test_typhoon_probability_regression_with_known_dataset() -> None:
    bst_path = Path(r"C:\typhoon forecasting\台风预测\TC_Track_prob_JMA_Total\bst_all.txt")
    if not bst_path.exists():
        pytest.skip("Known bst_all.txt dataset is not available on this machine")

    total = run_typhoon_probability(
        {
            "model_scope": "total",
            "lat": 20.9339,
            "lon": 112.202,
            "radius_km": 200,
            "year_start": 1976,
            "year_end": 2025,
            "months": list(range(1, 13)),
            "wind_threshold_kt": 50,
            "n_boundary": 144,
            "bst_path": str(bst_path),
        }
    )
    assert total["metrics"]["N_storm"] == 1243
    assert total["metrics"]["N_hit"] == 82
    assert total["metrics"]["p_storm"] == pytest.approx(0.0659694288, rel=1e-5)
    assert total["metrics"]["p_year"] == pytest.approx(0.8060199577, rel=1e-5)

    scs = run_typhoon_probability(
        {
            "model_scope": "scs",
            "lat": 20.9339,
            "lon": 112.202,
            "radius_km": 100,
            "year_start": 1976,
            "year_end": 2025,
            "months": list(range(1, 13)),
            "wind_threshold_kt": 50,
            "n_boundary": 72,
            "bst_path": str(bst_path),
        }
    )
    assert scs["metrics"]["N_all"] == 1243
    assert scs["metrics"]["N_enterSCS"] == 529
    assert scs["metrics"]["N_hit"] == 57
    assert scs["metrics"]["p_cond_impact_given_SCS"] == pytest.approx(0.1077504726, rel=1e-5)
    assert scs["metrics"]["p_abs_impact_and_SCS"] == pytest.approx(0.0458567981, rel=1e-5)


def test_typhoon_probability_optional_none_values_use_defaults(tmp_path: Path) -> None:
    bst_path = tmp_path / "bst_all.txt"
    bst_path.write_text(
        "66666 1001 1\n"
        "76010100 0 0 200 1120 0 0 90050 40 90080 60\n",
        encoding="utf-8",
    )

    out = run_typhoon_probability(
        {
            "model_scope": "scs",
            "lat": 20.0,
            "lon": 112.0,
            "radius_km": None,
            "year_start": 1976,
            "year_end": 1976,
            "months": [1],
            "wind_threshold_kt": 50,
            "n_boundary": None,
            "bst_path": str(bst_path),
        }
    )
    assert out["success"] is True
    assert out["input"]["radius_km"] == 100.0
    assert out["config"]["n_boundary"] == 72
