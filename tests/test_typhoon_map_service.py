from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.typhoon_map_service import run_typhoon_map_visualization


def test_typhoon_map_visualization_from_direct_payload(tmp_path: Path) -> None:
    out = run_typhoon_map_visualization(
        {
            "model_scope": "scs",
            "lat": 20.9339,
            "lon": 112.202,
            "radius_km": 100,
            "output_dir": str(tmp_path),
        }
    )
    assert out["success"] is True
    assert out["map_spec"]["model_scope"] == "scs"
    assert Path(out["html_path"]).exists()


def test_typhoon_map_visualization_from_typhoon_result(tmp_path: Path) -> None:
    out = run_typhoon_map_visualization(
        {
            "typhoon_result": {
                "model_scope": "total",
                "input": {"model_scope": "total", "lat": 20.9, "lon": 112.2, "radius_km": 200},
                "metrics": {"N_storm": 1243, "N_hit": 82},
            },
            "output_dir": str(tmp_path),
        }
    )
    assert out["success"] is True
    assert out["map_spec"]["center"]["lat"] == 20.9
    assert Path(out["html_path"]).exists()
