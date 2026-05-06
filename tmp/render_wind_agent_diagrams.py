from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import math

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(r"C:\wind-agent\docs\diagrams")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
if not FONT_PATH.exists():
    raise FileNotFoundError(f"Missing Chinese font: {FONT_PATH}")

TITLE_FONT = ImageFont.truetype(str(FONT_PATH), 34)
SUBTITLE_FONT = ImageFont.truetype(str(FONT_PATH), 20)
SECTION_FONT = ImageFont.truetype(str(FONT_PATH), 22)
NODE_FONT = ImageFont.truetype(str(FONT_PATH), 18)
SMALL_FONT = ImageFont.truetype(str(FONT_PATH), 16)

COLORS = {
    "bg": "#FFFFFF",
    "title": "#0F172A",
    "text": "#1F2937",
    "muted": "#64748B",
    "line": "#475569",
    "blue_fill": "#E8F0FE",
    "blue_border": "#7AA2E3",
    "green_fill": "#EAF6EE",
    "green_border": "#7ABF97",
    "sand_fill": "#FFF4E5",
    "sand_border": "#D6A75C",
    "rose_fill": "#FDECEC",
    "rose_border": "#D28A8A",
    "teal_fill": "#EAF7F7",
    "teal_border": "#67A8A8",
    "purple_fill": "#F4EEFF",
    "purple_border": "#9E8CD7",
    "slate_fill": "#F8FAFC",
    "slate_border": "#94A3B8",
    "note_fill": "#FCFCFD",
}

STYLE_MAP = {
    "blue": (COLORS["blue_fill"], COLORS["blue_border"]),
    "green": (COLORS["green_fill"], COLORS["green_border"]),
    "sand": (COLORS["sand_fill"], COLORS["sand_border"]),
    "rose": (COLORS["rose_fill"], COLORS["rose_border"]),
    "teal": (COLORS["teal_fill"], COLORS["teal_border"]),
    "purple": (COLORS["purple_fill"], COLORS["purple_border"]),
    "slate": (COLORS["slate_fill"], COLORS["slate_border"]),
    "note": (COLORS["note_fill"], COLORS["slate_border"]),
}


def box_to_xyxy(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = box
    return x, y, x + w, y + h


def text_block_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int]:
    left, top, right, bottom = draw.multiline_textbbox(
        (0, 0), text, font=font, spacing=4, align="center"
    )
    return right - left, bottom - top


def wrap_line(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    if not text:
        return [""]
    if " " not in text:
        lines: list[str] = []
        current = ""
        for char in text:
            trial = current + char
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
        return lines

    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(wrap_line(draw, paragraph, font, max_width))
    return "\n".join(lines)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str = COLORS["text"],
) -> None:
    x, y, w, h = box
    wrapped = wrap_text(draw, text, font, w - 24)
    tw, th = text_block_size(draw, wrapped, font)
    draw.multiline_text(
        (x + (w - tw) / 2, y + (h - th) / 2 - 1),
        wrapped,
        font=font,
        fill=fill,
        spacing=4,
        align="center",
    )


def draw_round_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    radius: int = 18,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(
        box_to_xyxy(box), radius=radius, fill=fill, outline=outline, width=width
    )


def draw_diamond(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    width: int = 2,
) -> None:
    x, y, w, h = box
    points = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    draw.polygon(points, fill=fill, outline=outline)
    draw.line(points + [points[0]], fill=outline, width=width)


def anchor(box: tuple[int, int, int, int], side: str) -> tuple[float, float]:
    x, y, w, h = box
    mapping = {
        "left": (x, y + h / 2),
        "right": (x + w, y + h / 2),
        "top": (x + w / 2, y),
        "bottom": (x + w / 2, y + h),
    }
    return mapping[side]


def draw_dashed_segment(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str,
    width: int = 3,
    dash: int = 10,
    gap: int = 8,
) -> None:
    x1, y1 = start
    x2, y2 = end
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return
    dx = (x2 - x1) / length
    dy = (y2 - y1) / length
    step = 0.0
    while step < length:
        seg_end = min(step + dash, length)
        p1 = (x1 + dx * step, y1 + dy * step)
        p2 = (x1 + dx * seg_end, y1 + dy * seg_end)
        draw.line([p1, p2], fill=color, width=width)
        step += dash + gap


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    points: list[tuple[float, float]] | None = None,
    dashed: bool = False,
    color: str = COLORS["line"],
    width: int = 3,
) -> None:
    polyline = [start] + (points or []) + [end]
    for p1, p2 in zip(polyline[:-1], polyline[1:]):
        if dashed:
            draw_dashed_segment(draw, p1, p2, color, width=width)
        else:
            draw.line([p1, p2], fill=color, width=width)

    tail = polyline[-2]
    head = polyline[-1]
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    head_len = 12
    wing = 6
    left = (
        head[0] - head_len * math.cos(angle) + wing * math.sin(angle),
        head[1] - head_len * math.sin(angle) - wing * math.cos(angle),
    )
    right = (
        head[0] - head_len * math.cos(angle) - wing * math.sin(angle),
        head[1] - head_len * math.sin(angle) + wing * math.cos(angle),
    )
    draw.polygon([head, left, right], fill=color)


def draw_label(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont = SMALL_FONT,
    fill: str = COLORS["muted"],
) -> None:
    draw.text(pos, text, font=font, fill=fill)


def xml_header(name: str, width: int, height: int) -> str:
    return (
        f'<mxfile host="app.diagrams.net" modified="2026-04-27T00:00:00Z" '
        f'agent="Codex Drawio Skill" version="24.7.17" type="device">'
        f'<diagram id="{name}" name="{name}">'
        f'<mxGraphModel dx="{width}" dy="{height}" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{width}" pageHeight="{height}" math="0" shadow="0"><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
    )


def xml_footer() -> str:
    return "</root></mxGraphModel></diagram></mxfile>"


def drawio_rect_style(kind: str) -> str:
    fill, border = STYLE_MAP[kind]
    return (
        "whiteSpace=wrap;html=1;"
        f"fillColor={fill};strokeColor={border};"
        "fontColor=#1F2937;fontSize=16;fontFamily=Microsoft YaHei UI;"
        "align=center;verticalAlign=middle;spacing=8;rounded=1;"
    )


def drawio_text_style(size: int, bold: bool = False, color: str = "#0F172A") -> str:
    return (
        "text;html=1;strokeColor=none;fillColor=none;align=left;"
        "verticalAlign=middle;whiteSpace=wrap;rounded=0;"
        f"fontSize={size};fontStyle={1 if bold else 0};"
        "fontFamily=Microsoft YaHei UI;"
        f"fontColor={color};"
    )


def drawio_edge_style(dashed: bool = False) -> str:
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        "html=1;strokeColor=#475569;endArrow=block;endFill=1;strokeWidth=2;"
    )
    if dashed:
        style += "dashed=1;"
    return style


def add_vertex(xml: list[str], cell_id: str, text: str, box: tuple[int, int, int, int], style: str) -> None:
    x, y, w, h = box
    xml.append(
        f'<mxCell id="{cell_id}" value="{escape(text)}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
    )


def add_edge(
    xml: list[str],
    cell_id: str,
    source: str,
    target: str,
    *,
    points: list[tuple[int, int]] | None = None,
    dashed: bool = False,
    label: str | None = None,
) -> None:
    value = escape(label) if label else ""
    xml.append(
        f'<mxCell id="{cell_id}" value="{value}" style="{drawio_edge_style(dashed)}" edge="1" '
        f'parent="1" source="{source}" target="{target}"><mxGeometry relative="1" as="geometry">'
    )
    if points:
        xml.append('<Array as="points">')
        for x, y in points:
            xml.append(f'<mxPoint x="{x}" y="{y}" />')
        xml.append("</Array>")
    xml.append("</mxGeometry></mxCell>")


def build_agent_diagram() -> None:
    width, height = 2500, 1450
    nodes = {
        "main": (60, 150, 2380, 470),
        "roles": (60, 680, 1760, 430),
        "tools": (1860, 680, 250, 430),
        "contract": (2150, 680, 140, 430),
        "external": (2330, 680, 110, 430),
        "note": (60, 1160, 2380, 110),
        "u": (100, 300, 160, 80),
        "g0": (300, 290, 230, 100),
        "n1": (570, 290, 180, 100),
        "n2": (790, 290, 180, 100),
        "n3": (1010, 290, 180, 100),
        "n4": (1230, 290, 180, 100),
        "n5": (1450, 290, 180, 100),
        "n6": (1670, 290, 180, 100),
        "r": (1890, 280, 220, 120),
        "n1a": (470, 790, 180, 110),
        "n2a": (690, 790, 180, 110),
        "n3a": (910, 790, 180, 110),
        "n4a": (1130, 790, 180, 110),
        "n5a": (1350, 790, 180, 110),
        "n6a": (1570, 790, 180, 110),
        "t1": (1885, 770, 200, 100),
        "t2": (1875, 930, 60, 110),
        "t3": (1967, 930, 60, 110),
        "t4": (2059, 930, 60, 110),
        "c1": (2165, 830, 110, 140),
        "e1": (2335, 790, 100, 110),
        "e2": (2335, 950, 100, 110),
    }

    title = "Wind-Agent Agent 工作流"
    subtitle = "固定 6 节点主链路 + 节点职责、工具依赖、流程契约与外部服务"

    main_nodes = {
        "u": ("用户请求", "blue"),
        "g0": ("run_wind_agent_flow", "blue"),
        "n1": ("input_preprocess", "blue"),
        "n2": ("intent_router", "purple"),
        "n3": ("workflow_planner", "green"),
        "n4": ("rag_executor", "green"),
        "n5": ("tool_executor", "green"),
        "n6": ("answer_synthesizer", "blue"),
        "r": ("返回\nsummary / analysis / trace", "blue"),
        "n1a": ("预处理输入\n识别文件路径/目录\n补全 state", "slate"),
        "n2a": ("意图路由\nrag / tool / workflow", "slate"),
        "n3a": ("生成执行计划\n默认计划或 LLM 计划", "slate"),
        "n4a": ("仅在 rag 意图时\n调用 RAG API", "slate"),
        "n5a": ("执行 workflow 步骤\nrag / llm / tool", "slate"),
        "n6a": ("汇总结果\n输出最终中文答复", "slate"),
        "t1": ("工具注册与统一执行", "teal"),
        "t2": ("风资源\n分析", "teal"),
        "t3": ("台风\n概率", "teal"),
        "t4": ("台风地图\n可视化", "teal"),
        "c1": ("step 类型约束\n默认 plan 构建", "sand"),
        "e1": ("RAG API\nAGENT_RAG_API_URL", "rose"),
        "e2": ("Orchestrator LLM\n用于路由/规划/总结", "rose"),
    }

    img = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    draw.text((60, 28), title, font=TITLE_FONT, fill=COLORS["title"])
    draw.text((60, 78), subtitle, font=SUBTITLE_FONT, fill=COLORS["muted"])

    for container_id in ["main", "roles", "tools", "contract", "external"]:
        draw_round_box(draw, nodes[container_id], COLORS["slate_fill"], COLORS["slate_border"], radius=22)
    draw_round_box(draw, nodes["note"], COLORS["note_fill"], COLORS["slate_border"], radius=18)

    draw_label(draw, (90, 170), "主链路", SECTION_FONT, COLORS["title"])
    draw_label(draw, (90, 700), "节点职责", SECTION_FONT, COLORS["title"])
    draw_label(draw, (1890, 700), "工具模块", SECTION_FONT, COLORS["title"])
    draw_label(draw, (2160, 700), "契约", SECTION_FONT, COLORS["title"])
    draw_label(draw, (2340, 700), "外部", SECTION_FONT, COLORS["title"])

    for node_id, (text, kind) in main_nodes.items():
        draw_round_box(draw, nodes[node_id], *STYLE_MAP[kind])
        draw_centered_text(draw, nodes[node_id], text, NODE_FONT)

    main_flow = ["u", "g0", "n1", "n2", "n3", "n4", "n5", "n6", "r"]
    for left, right in zip(main_flow[:-1], main_flow[1:]):
        draw_arrow(draw, anchor(nodes[left], "right"), anchor(nodes[right], "left"))

    for top_id, bottom_id in [
        ("n1", "n1a"),
        ("n2", "n2a"),
        ("n3", "n3a"),
        ("n4", "n4a"),
        ("n5", "n5a"),
        ("n6", "n6a"),
    ]:
        draw_arrow(
            draw,
            anchor(nodes[top_id], "bottom"),
            anchor(nodes[bottom_id], "top"),
            points=[(nodes[top_id][0] + nodes[top_id][2] / 2, 520)],
            dashed=True,
        )

    draw_arrow(draw, anchor(nodes["n5"], "bottom"), anchor(nodes["t1"], "top"), points=[(1540, 585), (1985, 585), (1985, 770)])
    draw_arrow(draw, anchor(nodes["t1"], "bottom"), anchor(nodes["t2"], "top"))
    draw_arrow(draw, anchor(nodes["t1"], "bottom"), anchor(nodes["t3"], "top"))
    draw_arrow(draw, anchor(nodes["t1"], "bottom"), anchor(nodes["t4"], "top"))
    draw_arrow(draw, anchor(nodes["n3"], "bottom"), anchor(nodes["c1"], "top"), points=[(1100, 610), (2220, 610), (2220, 830)])
    draw_arrow(draw, anchor(nodes["n5"], "bottom"), anchor(nodes["c1"], "top"), points=[(1540, 635), (2260, 635), (2260, 830)])
    draw_arrow(draw, anchor(nodes["n2"], "bottom"), anchor(nodes["e2"], "top"), points=[(880, 525), (2360, 525), (2360, 950)])
    draw_arrow(draw, anchor(nodes["n3"], "bottom"), anchor(nodes["e2"], "top"), points=[(1100, 550), (2385, 550), (2385, 950)])
    draw_arrow(draw, anchor(nodes["n6"], "bottom"), anchor(nodes["e2"], "top"), points=[(1760, 575), (2410, 575), (2410, 950)])
    draw_arrow(draw, anchor(nodes["n4"], "bottom"), anchor(nodes["e1"], "top"), points=[(1320, 500), (2385, 500), (2385, 790)])

    note_text = (
        "说明：流程内容按文档中的 Mermaid 图保持不变，"
        "仅用新的 drawio 布局把主链路、职责说明、工具模块和外部依赖拆开呈现，"
        "避免旧图中过宽链路和支撑信息混杂。"
    )
    draw_centered_text(draw, nodes["note"], note_text, SUBTITLE_FONT)

    png_path = OUT_DIR / "wind-agent-agent-workflow.png"
    img.save(png_path)

    xml: list[str] = [xml_header("Agent-Workflow", width, height)]
    add_vertex(xml, "title", title, (60, 28, 720, 44), drawio_text_style(26, True))
    add_vertex(xml, "subtitle", subtitle, (60, 76, 1300, 28), drawio_text_style(18, False, "#64748B"))
    for container_id in ["main", "roles", "tools", "contract", "external", "note"]:
        kind = "note" if container_id == "note" else "slate"
        add_vertex(
            xml,
            container_id,
            "",
            nodes[container_id],
            f'rounded=1;whiteSpace=wrap;html=1;fillColor={STYLE_MAP[kind][0]};strokeColor={STYLE_MAP[kind][1]};arcSize=12;',
        )
    add_vertex(xml, "main_t", "主链路", (90, 170, 140, 30), drawio_text_style(20, True))
    add_vertex(xml, "roles_t", "节点职责", (90, 700, 140, 30), drawio_text_style(20, True))
    add_vertex(xml, "tools_t", "工具模块", (1890, 700, 120, 30), drawio_text_style(20, True))
    add_vertex(xml, "contract_t", "契约", (2160, 700, 80, 30), drawio_text_style(20, True))
    add_vertex(xml, "external_t", "外部", (2340, 700, 80, 30), drawio_text_style(20, True))

    for node_id, (text, kind) in main_nodes.items():
        add_vertex(xml, node_id, text.replace("\n", "&#xa;"), nodes[node_id], drawio_rect_style(kind))

    edge_specs = []
    for idx, (left, right) in enumerate(zip(main_flow[:-1], main_flow[1:]), start=1):
        edge_specs.append((f"m{idx}", left, right, None, False, None))
    edge_specs.extend(
        [
            ("r1", "n1", "n1a", [(660, 520)], True, None),
            ("r2", "n2", "n2a", [(880, 520)], True, None),
            ("r3", "n3", "n3a", [(1100, 520)], True, None),
            ("r4", "n4", "n4a", [(1320, 520)], True, None),
            ("r5", "n5", "n5a", [(1540, 520)], True, None),
            ("r6", "n6", "n6a", [(1760, 520)], True, None),
            ("t1e", "n5", "t1", [(1540, 585), (1985, 585), (1985, 770)], False, None),
            ("t2e", "t1", "t2", None, False, None),
            ("t3e", "t1", "t3", None, False, None),
            ("t4e", "t1", "t4", None, False, None),
            ("c1e", "n3", "c1", [(1100, 610), (2220, 610), (2220, 830)], False, None),
            ("c2e", "n5", "c1", [(1540, 635), (2260, 635), (2260, 830)], False, None),
            ("e1a", "n2", "e2", [(880, 525), (2360, 525), (2360, 950)], False, None),
            ("e2a", "n3", "e2", [(1100, 550), (2385, 550), (2385, 950)], False, None),
            ("e3a", "n6", "e2", [(1760, 575), (2410, 575), (2410, 950)], False, None),
            ("e4a", "n4", "e1", [(1320, 500), (2385, 500), (2385, 790)], False, None),
        ]
    )
    for edge_id, source, target, points, dashed, label in edge_specs:
        add_edge(xml, edge_id, source, target, points=points, dashed=dashed, label=label)

    add_vertex(xml, "note_text", note_text, (90, 1185, 2320, 60), drawio_text_style(16, False, "#1F2937"))
    xml.append(xml_footer())
    (OUT_DIR / "wind-agent-agent-workflow.drawio").write_text("".join(xml), encoding="utf-8")


def build_rag_diagram() -> None:
    width, height = 2600, 1620
    nodes = {
        "main": (60, 150, 2480, 930),
        "mods": (60, 1130, 2480, 320),
        "note": (60, 1490, 2480, 90),
        "u": (1120, 220, 240, 82),
        "a": (1080, 350, 320, 100),
        "b": (1080, 500, 320, 100),
        "c": (1120, 650, 240, 120),
        "wa": (360, 690, 260, 100),
        "ld": (1980, 690, 260, 100),
        "rag_box": (820, 810, 760, 190),
        "d1": (860, 840, 150, 110),
        "d2": (1040, 840, 150, 110),
        "d3": (1220, 840, 150, 110),
        "d4": (1400, 840, 150, 110),
        "d5": (860, 970, 150, 110),
        "d6": (1040, 970, 150, 110),
        "d7": (1220, 970, 330, 110),
        "z": (1080, 1210, 320, 100),
        "m1": (180, 1240, 320, 100),
        "m2": (560, 1240, 320, 100),
        "m3": (940, 1240, 320, 100),
        "m4": (1430, 1240, 320, 100),
        "m5": (1810, 1240, 420, 100),
    }

    title = "Wind-Agent RAG 系统工作流"
    subtitle = "请求入口、模式路由、RAG 主链路与关键模块关系"

    node_defs = {
        "u": ("用户/前端请求", "blue"),
        "a": ("RAG API HTTP入口", "blue"),
        "b": ("handle_chat_request 调度", "blue"),
        "wa": ("调用 agent 流程", "sand"),
        "ld": ("直接调用 LLM", "sand"),
        "d1": ("agentic 检索控制\n_run_agentic_retrieve", "green"),
        "d2": ("retrieve_contexts", "green"),
        "d3": ("Embedding + Milvus 混合检索\nDense/BGE + BM25", "green"),
        "d4": ("融合/去重/可选重排\n上下文编排", "green"),
        "d5": ("构建 contexts/\ncitations/media\nretrieval_metrics", "teal"),
        "d6": ("调用 LLM\n生成答案", "purple"),
        "d7": ("答案评分与引用附录\n组装 ui_blocks", "blue"),
        "z": ("统一 JSON 响应", "blue"),
        "m1": ("HTTP 收发/CORS/健康检查", "slate"),
        "m2": ("负责路由、编排、响应组装", "slate"),
        "m3": ("负责检索、融合、上下文构建", "slate"),
        "m4": ("负责 trace/span/event", "slate"),
        "m5": ("Milvus + Embedding/Reranker\n向量检索基础设施", "slate"),
    }

    img = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    draw.text((60, 28), title, font=TITLE_FONT, fill=COLORS["title"])
    draw.text((60, 78), subtitle, font=SUBTITLE_FONT, fill=COLORS["muted"])

    draw_round_box(draw, nodes["main"], COLORS["slate_fill"], COLORS["slate_border"], radius=22)
    draw_round_box(draw, nodes["mods"], COLORS["slate_fill"], COLORS["slate_border"], radius=22)
    draw_round_box(draw, nodes["note"], COLORS["note_fill"], COLORS["slate_border"], radius=18)
    draw_round_box(draw, nodes["rag_box"], COLORS["green_fill"], COLORS["green_border"], radius=18)

    draw_label(draw, (90, 170), "主流程", SECTION_FONT, COLORS["title"])
    draw_label(draw, (860, 820), "RAG 主流程", SECTION_FONT, COLORS["title"])
    draw_label(draw, (90, 1150), "关键模块关系", SECTION_FONT, COLORS["title"])

    for node_id, (text, kind) in node_defs.items():
        draw_round_box(draw, nodes[node_id], *STYLE_MAP[kind])
        draw_centered_text(draw, nodes[node_id], text, NODE_FONT)

    draw_diamond(draw, nodes["c"], COLORS["sand_fill"], COLORS["sand_border"])
    draw_centered_text(draw, nodes["c"], "mode 路由", NODE_FONT)

    draw_arrow(draw, anchor(nodes["u"], "bottom"), anchor(nodes["a"], "top"))
    draw_arrow(draw, anchor(nodes["a"], "bottom"), anchor(nodes["b"], "top"))
    draw_arrow(draw, anchor(nodes["b"], "bottom"), anchor(nodes["c"], "top"))
    draw_arrow(draw, anchor(nodes["c"], "left"), anchor(nodes["wa"], "top"), points=[(900, 790), (490, 790)])
    draw_arrow(draw, anchor(nodes["c"], "right"), anchor(nodes["ld"], "top"), points=[(1580, 790), (2110, 790)])
    draw_arrow(draw, anchor(nodes["c"], "bottom"), anchor(nodes["d1"], "top"))

    rag_order = ["d1", "d2", "d3", "d4"]
    for left, right in zip(rag_order[:-1], rag_order[1:]):
        draw_arrow(draw, anchor(nodes[left], "right"), anchor(nodes[right], "left"))
    draw_arrow(draw, anchor(nodes["d1"], "bottom"), anchor(nodes["d5"], "top"), points=[(935, 930)])
    draw_arrow(draw, anchor(nodes["d2"], "bottom"), anchor(nodes["d6"], "top"), points=[(1115, 930)])
    draw_arrow(draw, anchor(nodes["d4"], "bottom"), anchor(nodes["d7"], "top"), points=[(1475, 930)])
    draw_arrow(draw, anchor(nodes["d5"], "right"), anchor(nodes["d6"], "left"))
    draw_arrow(draw, anchor(nodes["d6"], "right"), anchor(nodes["d7"], "left"))
    draw_arrow(draw, anchor(nodes["wa"], "bottom"), anchor(nodes["z"], "top"), points=[(490, 1080), (1140, 1080)])
    draw_arrow(draw, anchor(nodes["ld"], "bottom"), anchor(nodes["z"], "top"), points=[(2110, 1080), (1340, 1080)])
    draw_arrow(draw, anchor(nodes["d7"], "bottom"), anchor(nodes["z"], "top"), points=[(1385, 1120)])

    draw_arrow(draw, anchor(nodes["m1"], "right"), anchor(nodes["m2"], "left"))
    draw_arrow(draw, anchor(nodes["m2"], "right"), anchor(nodes["m3"], "left"))
    draw_arrow(draw, anchor(nodes["m2"], "bottom"), anchor(nodes["m4"], "top"), points=[(720, 1390), (1590, 1390)])
    draw_arrow(draw, anchor(nodes["m3"], "right"), anchor(nodes["m5"], "left"))

    draw_label(draw, (820, 690), "rag", SMALL_FONT)
    draw_label(draw, (680, 770), "wind_agent", SMALL_FONT)
    draw_label(draw, (1720, 770), "llm_direct", SMALL_FONT)

    note_text = (
        "说明：内容保持与文档中的 Mermaid 图一致，"
        "把入口路由、RAG 主链路和模块关系拆成三个清晰层次，"
        "避免旧图中中文乱码和检索/入库语义混杂。"
    )
    draw_centered_text(draw, nodes["note"], note_text, SUBTITLE_FONT)

    png_path = OUT_DIR / "wind-agent-rag-ingest-retrieval-workflow.png"
    img.save(png_path)

    xml: list[str] = [xml_header("RAG-System-Workflow", width, height)]
    add_vertex(xml, "title", title, (60, 28, 760, 44), drawio_text_style(26, True))
    add_vertex(xml, "subtitle", subtitle, (60, 76, 1100, 28), drawio_text_style(18, False, "#64748B"))
    for container_id in ["main", "mods", "note", "rag_box"]:
        kind = "note" if container_id == "note" else ("green" if container_id == "rag_box" else "slate")
        add_vertex(
            xml,
            container_id,
            "",
            nodes[container_id],
            f'rounded=1;whiteSpace=wrap;html=1;fillColor={STYLE_MAP[kind][0]};strokeColor={STYLE_MAP[kind][1]};arcSize=12;',
        )
    add_vertex(xml, "main_t", "主流程", (90, 170, 120, 30), drawio_text_style(20, True))
    add_vertex(xml, "rag_t", "RAG 主流程", (860, 820, 160, 30), drawio_text_style(20, True))
    add_vertex(xml, "mods_t", "关键模块关系", (90, 1150, 160, 30), drawio_text_style(20, True))

    for node_id, (text, kind) in node_defs.items():
        add_vertex(xml, node_id, text.replace("\n", "&#xa;"), nodes[node_id], drawio_rect_style(kind))
    add_vertex(
        xml,
        "c",
        "mode 路由",
        nodes["c"],
        "rhombus;whiteSpace=wrap;html=1;fillColor=#FFF4E5;strokeColor=#D6A75C;"
        "fontColor=#1F2937;fontSize=16;fontFamily=Microsoft YaHei UI;align=center;verticalAlign=middle;",
    )
    add_vertex(xml, "label_rag", "rag", (820, 690, 60, 24), drawio_text_style(14, False, "#64748B"))
    add_vertex(xml, "label_wa", "wind_agent", (680, 770, 110, 24), drawio_text_style(14, False, "#64748B"))
    add_vertex(xml, "label_ld", "llm_direct", (1720, 770, 100, 24), drawio_text_style(14, False, "#64748B"))

    for edge_id, source, target, points in [
        ("e1", "u", "a", None),
        ("e2", "a", "b", None),
        ("e3", "b", "c", None),
        ("e4", "c", "wa", [(900, 790), (490, 790)]),
        ("e5", "c", "ld", [(1580, 790), (2110, 790)]),
        ("e6", "c", "d1", None),
        ("e7", "d1", "d2", None),
        ("e8", "d2", "d3", None),
        ("e9", "d3", "d4", None),
        ("e10", "d1", "d5", [(935, 930)]),
        ("e11", "d2", "d6", [(1115, 930)]),
        ("e12", "d4", "d7", [(1475, 930)]),
        ("e13", "d5", "d6", None),
        ("e14", "d6", "d7", None),
        ("e15", "wa", "z", [(490, 1080), (1140, 1080)],),
        ("e16", "ld", "z", [(2110, 1080), (1340, 1080)],),
        ("e17", "d7", "z", [(1385, 1120)],),
        ("e18", "m1", "m2", None),
        ("e19", "m2", "m3", None),
        ("e20", "m2", "m4", [(720, 1390), (1590, 1390)]),
        ("e21", "m3", "m5", None),
    ]:
        add_edge(xml, edge_id, source, target, points=points)

    add_vertex(xml, "note_text", note_text, (90, 1510, 2320, 50), drawio_text_style(16, False, "#1F2937"))
    xml.append(xml_footer())
    (OUT_DIR / "wind-agent-rag-ingest-retrieval-workflow.drawio").write_text("".join(xml), encoding="utf-8")


if __name__ == "__main__":
    build_agent_diagram()
    build_rag_diagram()
