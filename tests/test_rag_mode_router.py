from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.service import _rule_based_auto_mode, _looks_like_typhoon_tool_request


def test_typhoon_scs_map_query_routes_to_wind_agent() -> None:
    query = "请计算该点台风概率并做地图可视化，使用SCS模型，坐标lat=20.9339, lon=112.202, R=100km。"
    assert _looks_like_typhoon_tool_request(query) is True
    mode, reason = _rule_based_auto_mode(query)
    assert mode == "wind_agent"
    assert reason == "rule_typhoon_tool_request"


def test_general_chat_stays_llm_direct() -> None:
    mode, reason = _rule_based_auto_mode("你好，今天天气怎么样")
    assert mode == "llm_direct"
    assert reason == "rule_general_chat"
