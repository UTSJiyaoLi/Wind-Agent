from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wind_analysis_tool import build_wind_analysis_tool


if __name__ == "__main__":
    tool = build_wind_analysis_tool()
    result = tool.invoke({"excel_path": r"wind_data\wind condition @Akida.xlsx"})
    print(result)
