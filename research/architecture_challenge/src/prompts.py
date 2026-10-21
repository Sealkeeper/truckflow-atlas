"""Prompt contracts for the four architectures.

Prompts are part of the experiment record. They are intentionally explicit about
the counting convention, because the product spec counts a tractor + trailer as
one truck and counts a clearly separate trailer-only body as one truck.
"""

from __future__ import annotations


COUNT_RULES = """计数口径（必须遵守）：
1. 牵引车 + 半挂/集装箱挂车 = 1 辆；车头与货厢不得拆成两辆。
2. 只看到货厢/集装箱，但能看出它属于通道内的货车（有底盘、支腿、鞍座、与前后车成队列，或明显是运输挂车）时，算 1 辆，visible 标为 trailer_only。蓝色、灰色、白色的集装箱货厢都要检查。
3. 展台、建筑、墙体、货架、装饰物、叉车、轿车、面包车、手推车、工程机械、人物都不计入。
4. 只统计本图实际可见的车辆；完全被挡住或只在画面外的不要猜。
5. 车头或货厢只露出局部、但仍能确定是货车时计入，并在 visible 中说明；无法确定时 uncertain=true。
6. 车型：large=重卡/半挂/长货厢；medium=两轴或三轴中卡/中型厢车；small=轻卡/小型厢式货车。只看到货厢时按货厢长度相对通道宽度、车顶长宽比估计；不确定就写 unknown，不要硬分。
7. 不要把同一辆车的车头框和货厢框分别输出。bbox 要框住整辆可见车辆的联合外接框。"""


JSON_VEHICLE = """{
  "counts": {"total": 0, "large": 0, "medium": 0, "small": 0, "unknown": 0},
  "vehicles": [
    {
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "center": [0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "is_truck": true,
      "cargo_color": "货厢/集装箱颜色",
      "heading": "朝向镜头|背向镜头|横向|不确定",
      "identity_clues": "颜色、货厢纹理、车头特征、队列位置等可用于复核的线索",
      "evidence": "画面中的定位与判定理由",
      "uncertain": false
    }
  ],
  "scene_notes": "遮挡、边界、可能的重复或歧义",
  "uncertain_reasons": []
}"""


def band_prompt(
    band_name: str,
    b0: float,
    b1: float,
    c0: float,
    c1: float,
) -> str:
    del c0, c1
    del b0, b1
    return f"""这是一段货车通道的局部放大（{band_name} 段，来自同一台监控相机的一帧）。
请清点画面里所有可见货车，包括被画面上下边缘截到、只露出货厢或车顶的车。

- 牵引车+挂车算一辆；只看到独立的运输挂车/集装箱货厢也算一辆。
- 展台、建筑、货架、叉车、轿车、面包车、人物不计。
- 蓝色/灰色的集装箱挂车要特别检查，不要当成展台；但蓝色招牌、广告牌、展台墙板也不是货厢，必须有立体货厢轮廓、底盘/支脚或与车头相连才算。
- 只有牵引车头、没有挂车或长货厢的，车型按 medium；带长货厢的半挂/重卡才是 large。
- 上下排列、颜色或纹理不同的两节货厢，如果中间有明确间隙或属于不同底盘，分别计数；同一辆车头与其货厢只算一辆。
- bbox 使用当前裁剪的 0-1 归一化坐标（不是像素）：左上 [0,0]，右下 [1,1]。

只输出严格 JSON：
{{
  "counts": {{"total": 0, "large": 0, "medium": 0, "small": 0, "unknown": 0}},
  "vehicles": [
    {{
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "cargo_color": "颜色",
      "identity_clues": "可用于合并的线索",
      "evidence": "定位与理由"
    }}
  ],
  "notes": "遮挡与歧义"
}}"""


def container_row_prompt() -> str:
    return """这是一段通道左侧的纵向局部，画面中可能有多辆上下排列的货车或多节集装箱挂车。

请逐辆/逐节清点，不要因为它们是同一颜色、同一队列或看起来连在一起，就把两辆/两节合并。

判据：
- 两节货厢之间是否有横向缝隙、不同高度的顶面、不同的后门/侧板纹理、不同编号、不同的底盘或支腿。
- 只要两个箱体/车体的边界清楚、颜色/纹理/编号不同，就分别计数。
- 牵引车+货厢算一辆；只看到独立运输挂车/货厢也算一辆。
- 展台、建筑、广告牌、货架、叉车、人物不计。
- bbox 使用当前裁剪的 0-1 归一化坐标（不是像素）。

只输出 JSON：
{"counts":{"total":0,"large":0,"medium":0,"small":0,"unknown":0},"vehicles":[{"bbox":[0,0,0,0],"size":"large|medium|small|unknown","visible":"full|partial_top|partial_side|trailer_only","cargo_color":"","distinct_from_above":"与上一节的区别","evidence":""}],"notes":""}"""


def global_count_prompt() -> str:
    return f"""你是展会撤换展现场的货车清点专家。只依据这张画面，清点所有可见货车。

{COUNT_RULES}

坐标使用 0-1 归一化 [x0,y0,x1,y1]，框住整辆可见车辆的联合外接框。不要因为车辆在通道边缘、被柱子遮挡、颜色暗或靠近另一辆车而漏计。

只输出严格 JSON，不要 markdown，不要额外解释：
{JSON_VEHICLE}"""


def region_proposal_prompt() -> str:
    return """你是货车识别的“区域提案器”。先不要给总数，也不要只盯着最大的那辆车。

请把整张画面中所有“可能有货车”的连续区域找出来：排队车道、停放带、远处装卸口、被展台/立柱/其他车辆遮挡的缺口、画面边缘只露出货厢或车顶的位置。

要求：
1. 至少覆盖画面里所有可见的车道段，不要只给一个走廊中段。
2. 远处的集装箱队列、只看到货厢没有车头的位置，也要作为候选区域。
3. 每个区域必须有 bbox、通道描述、粗略占用情况、为什么怀疑这里有车、以及下一轮放大时应重点看什么。
4. 最多 6 个区域，按从近到远排序。
5. bbox 使用整帧的 0-1 归一化坐标（不是像素）：左上 [0,0]，右下 [1,1]。

只输出严格 JSON：
{
  "regions": [
    {
      "region_id": "R1",
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "lane_description": "这是哪条车道/停放带，近端和远端在哪里",
      "occupancy": "occupied|empty|uncertain",
      "rough_truck_count": 0,
      "why": "为什么认为这里有货车",
      "search_hint": "放大后重点检查什么"
    }
  ],
  "scene_notes": "画面拓扑与遮挡说明"
}"""


def region_count_prompt(
    region_id: str,
    depth: int,
    source_bbox: list[float],
    can_recurse: bool,
) -> str:
    recurse_contract = (
        '"suspect_subregions": [{"bbox": [0.0, 0.0, 0.0, 0.0], "why": "...", "target": "..."}]'
        if can_recurse
        else '"suspect_subregions": []'
    )
    del source_bbox
    return f"""这是一个候选货车区域的放大裁剪（区域 {region_id}，树深度 {depth}）。
请清点画面里所有可见货车，包括被画面边缘截到、被展台/柱子挡住、只露出货厢或车顶的车。

- 牵引车+挂车算一辆；只看到独立的运输挂车/集装箱货厢也算一辆。
- 展台、建筑、货架、叉车、轿车、面包车、人物不计。
- 蓝色/灰色集装箱挂车要特别检查，不要当成展台；但蓝色招牌、广告牌、展台墙板不是货厢。
- 上下排列、颜色或纹理不同的两节货厢，如果中间有明确间隙或属于不同底盘，分别计数。
- bbox 使用当前裁剪的 0-1 归一化坐标：左上 [0,0]，右下 [1,1]。

如果区域内还有看不清、被遮挡、太远或疑似漏检的子区域，列出最多 3 个 suspect_subregions（坐标用当前裁剪的归一化坐标）。

只输出严格 JSON：
{{
  "counts": {{"total": 0, "large": 0, "medium": 0, "small": 0, "unknown": 0}},
  "vehicles": [
    {{
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "center": [0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "is_truck": true,
      "cargo_color": "颜色",
      "heading": "朝向镜头|背向镜头|横向|不确定",
      "identity_clues": "复核线索",
      "evidence": "定位与理由",
      "uncertain": false
    }}
  ],
  {recurse_contract},
  "scene_notes": "..."
}}"""


def scene_graph_prompt() -> str:
    return f"""你在为货车计数构建“场景图”。请先描述通道拓扑，再逐个物理车辆建节点，最后才给数量。

第一步：通道拓扑
- 找出画面中所有可通行/可停放的通道或队列（lane），说明每条通道的近端、远端、走向、被什么遮挡。
- 同一走廊里如果近景和远景被展台隔开，可以分成不同 lane。

第二步：车辆节点
- 每辆物理货车一个节点。车头与货厢属于同一辆时只输出一个节点，bbox 框住两者；不要把车头、货厢拆成两个节点。
- 只看到独立挂车/集装箱、但能确定它是通道内的运输挂车时，输出一个节点，visible=trailer_only。
- 每个节点必须给出 lane_id、queue_index（同一 lane 内从近到远 0,1,2...）、center、heading、cargo_color、body_style、size、is_truck、occluded_by、part_of。
- 如果某个局部（例如单独看到的货厢）需要并入另一节点，把它的 vehicle_id 写进 part_of。

{COUNT_RULES}

关键要求：先按“队列位置”把车排好，再检查每个 queue_index 是否只有一辆车。若两辆车颜色/纹理/朝向明显不同，即使靠得很近也不能合并。

坐标必须使用整帧的 0-1 归一化值，不是像素：左上 [0,0]，右下 [1,1]；例如 [0.44,0.12,0.49,0.25]。

只输出严格 JSON：
{{
  "lanes": [
    {{
      "lane_id": "L1",
      "description": "近端/远端/走向",
      "near_y": 0.0,
      "far_y": 0.0,
      "occlusions": "..."
    }}
  ],
  "vehicles": [
    {{
      "vehicle_id": "V1",
      "lane_id": "L1",
      "queue_index": 0,
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "center": [0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "is_truck": true,
      "heading": "朝向镜头|背向镜头|横向|不确定",
      "cargo_color": "颜色",
      "body_style": "集装箱/厢式/平板/牵引车头等",
      "occluded_by": "无或遮挡物",
      "part_of": null,
      "identity_clues": "复核线索",
      "evidence": "定位与理由",
      "uncertain": false
    }}
  ],
  "scene_notes": "通道拓扑、遮挡和队列顺序说明"
}}"""


def audit_prompt(candidates_text: str) -> str:
    return f"""图 1 是原图；图 2 是同一帧，上面画了上一轮模型给出的彩色编号框。

候选列表：
{candidates_text}

任务分两步，必须按顺序：

第一步（只看图 1）：先完全忽略图 2 的编号框，按每条通道从近到远独立清点所有货车和独立运输挂车/货厢。上一轮经常漏掉暗处、远处、被展台挡住、只露出货厢或车顶的车；这一步要独立找全，输出 independent_recount。

第二步（对照图 2）：拿第一步的清单去比对编号框，找出：
A. 漏检：图 1 里有、但图 2 没有编号框覆盖的货车或独立挂车/货厢。
B. 重复：两个编号框是否其实是同一辆车的车头与货厢，或同一辆车被框了两次。
C. 车型：编号框的 large/medium/small 是否明显错误。

不要假设编号框已经完整；也不要为了凑数虚构车辆。每个 missing 项都必须能在图 1 中指出具体位置和外观证据。

bbox 使用整帧的 0-1 归一化坐标（不是像素）：左上 [0,0]，右下 [1,1]。

只输出严格 JSON：
{{
  "independent_recount": [
    {{"description": "通道+位置+颜色+车型", "bbox": [0.0, 0.0, 0.0, 0.0]}}
  ],
  "missing": [
    {{
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "cargo_color": "颜色",
      "identity_clues": "复核线索",
      "evidence": "为什么认为这里有一辆未被框住的货车"
    }}
  ],
  "duplicates": [{{"a": 1, "b": 2, "reason": "为什么是同一辆"}}],
  "type_corrections": [{{"id": 1, "size": "medium", "reason": "为什么改"}}],
  "audit_notes": "扫描了哪些区域、还有哪些不确定"
}}"""


def verify_candidate_prompt() -> str:
    return f"""这是一张候选车辆的放大裁剪，可能来自画面边缘、暗处、遮挡处或远处。请只判断这一个候选。

{COUNT_RULES}

问题：
1. 这是不是一辆货车（或清晰的独立运输挂车/货厢）？
2. 如果是，车型是 large、medium、small 还是 unknown？
3. 画面是否足以支持这个判断？

只输出严格 JSON：
{{
  "is_truck": true,
  "size": "large|medium|small|unknown",
  "confidence": 0.0,
  "visible": "full|partial_top|partial_side|trailer_only",
  "cargo_color": "颜色",
  "reason": "判断依据",
  "needs_review": false
}}"""


def type_review_prompt() -> str:
    return f"""这是一辆已确认货车候选的放大裁剪。黄色边框是候选框。请只复核候选框内的目标车辆，不要重新数画面里有多少辆车。

{COUNT_RULES}

重点：
- 框内可能同时露出上/下/侧边相邻车辆的局部货厢；相邻车辆不属于目标，不能当作目标的挂车。
- 先找目标的驾驶室/挡风玻璃/格栅。若框内主体是车头，并且没有与它连续相连的长货厢，body_kind 必须是 cab_only，size 必须是 medium；画面上方别人的货厢不能改变这一点。
- 用整车轮廓、车顶长宽比、轴数、货厢长度与通道宽度的比例判断 large/medium/small。
- 只看到货厢时按货厢长度和车顶比例判断；证据不足就输出 unknown。
- 不要因为车看起来大就一律判 large；两轴/三轴中卡应为 medium。
- 只有牵引车头、没有挂车或长货厢的，按 medium；牵引车 + 长集装箱/长货厢才按 large。
- 蓝色招牌、展台墙板、广告牌不是货厢。

只输出严格 JSON：
{{
  "is_truck": true,
  "size": "large|medium|small|unknown",
  "body_kind": "cab_only|tractor_with_trailer|rigid_truck|trailer_only|unknown",
  "has_trailer": false,
  "confidence": 0.0,
  "reason": "车型判断依据",
  "needs_review": false
}}"""


def adjudicate_prompt() -> str:
    return """这张图左边是整帧上下文，黄框标为 A、青框标为 B；右边是 A、B 的目标框内放大。放大图只保留各自候选框附近，框外相邻车辆不是比较对象。

请判断 A 与 B 是否指向同一辆物理货车。

判据：
- 货厢/集装箱颜色与纹理、车头特征、朝向、在通道中的队列位置。
- 如果 A 是 B 的车头、车顶、货厢局部或同一车被框了两次，应判为同一辆。
- 如果一个框只覆盖同一辆车的上半部、另一个框覆盖下半部，但颜色、宽度和车道位置连续，应判为同一辆。
- 一个框同时包含目标车和上方相邻车时，以两个框重叠的那辆车为准，不要把相邻车当成差异证据。
- 结合左图看两个框在队列中的前后关系；右侧放大只用于看外观细节。
- 如果颜色/纹理明显不同，或两车在队列中一前一后、车身不连续，判为不同。
- 只根据可见外观判断；不要因为两个框在画面上重叠就自动判同一辆。

只输出严格 JSON：
{
  "same_vehicle": true,
  "confidence": 0.0,
  "reason": "具体外观/位置证据",
  "if_different": "两辆分别是什么"
}"""
