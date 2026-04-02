import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.wind_analysis_service import run_analysis


if __name__ == "__main__":
    excel_path = r"wind_data\wind condition @Akida.xlsx"
    result = run_analysis(excel_path)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
