"""编排兼容层：对外保留旧导入路径，内部转调新的 graph 构建与运行函数。"""

from __future__ import annotations

from graph.builder import (
    build_wind_agent_graph,
    build_wind_analysis_graph,
    run_wind_agent_flow,
    run_wind_analysis_flow,
)

__all__ = [
    "build_wind_agent_graph",
    "build_wind_analysis_graph",
    "run_wind_agent_flow",
    "run_wind_analysis_flow",
]


