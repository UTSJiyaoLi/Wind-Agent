"""本地运行 LangGraph 编排流程的示例脚本。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestration.langgraph_flow import run_wind_analysis_flow


if __name__ == "__main__":
    result = run_wind_analysis_flow(r"wind_data\wind condition @Akida.xlsx")
    print(result["summary"])

