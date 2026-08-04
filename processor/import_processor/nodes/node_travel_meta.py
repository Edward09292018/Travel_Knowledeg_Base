# processor/import_processor/nodes/node_travel_meta.py
"""
旅游元数据节点：将文档级规则元数据写入每个 chunk，缺失字段用 LLM 补全。
同一条记录按 content_type 只保留一个实体名字段；城市级指南不填具体实体名。
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from processor.import_processor.base import BaseNode, setup_logging
from processor.import_processor.exceptions import StateFieldError
from processor.import_processor.state import ImportGraphState
from utils import llm_utils
from utils.travel_meta_utils import (
    CONTENT_TYPES,
    CONTENT_TYPE_ENTITY_FIELD,
    ENTITY_FIELDS,
    is_city_level_guide,
    is_generic_entity_name,
    normalize_entity_fields,
    parse_md_front_meta,
)

TRAVEL_META_SYSTEM_PROMPT = (
    "你是旅游知识库元数据抽取助手。根据给定切片内容抽取结构化字段，"
    "只返回 JSON，不要解释。"
)

TRAVEL_META_USER_TEMPLATE = """请根据以下旅游文档切片，补全缺失的元数据字段。
已有信息（可能为空）：
- content_type: {content_type}
- region: {region}
- attraction_name: {attraction_name}
- route_name: {route_name}
- hotel_name: {hotel_name}
- restaurant_name: {restaurant_name}
- file_title: {file_title}

切片标题: {title}
切片正文:
{content}

要求：
1. content_type 必须是以下之一（无法判断则保留已有值或空字符串）：{content_types}
2. 一条记录只填与 content_type 对应的一个实体名，其余实体名必须为空字符串：
   - 景点介绍 → 只填 attraction_name
   - 线路推荐 → 只填 route_name
   - 酒店信息 → 只填 hotel_name
   - 美食推荐 → 只填 restaurant_name
   - 交通指南 / 文化民俗 → 四个实体名都为空，可填 region
3. 严禁把文档标题、文件名、地区名当作具体实体名。
   例如「成都住宿推荐」「成都美食推荐」「三亚旅游攻略」都是城市级指南标题，不是具体酒店/餐厅/景点名。
4. 若文档是城市/地区级推荐或指南（标题含推荐/指南/攻略/合集等），对应实体名必须为 ""，只保留 region。
5. 只有正文明确指向某一家具体酒店/餐厅/景点/线路时，才填写对应实体名。
6. 不要编造正文中不存在的具体名称；不确定则填 ""
7. 直接返回 JSON，字段固定为：
{{
  "content_type": "",
  "region": "",
  "attraction_name": "",
  "route_name": "",
  "hotel_name": "",
  "restaurant_name": ""
}}
"""


class NodeTravelMeta(BaseNode):
    """节点：旅游元数据写入与补全"""

    name = "node_travel_meta"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        chunks = state.get("chunks")
        if not chunks or not isinstance(chunks, list):
            raise StateFieldError(field_name="chunks", message="chunks不能为空", expected_type=list)

        file_title = state.get("file_title") or ""
        doc_meta = self._collect_doc_meta(state)

        # 优先解析正文「## 元数据」块
        md_meta = parse_md_front_meta(state.get("md_content") or "")
        if md_meta:
            if md_meta.get("content_type"):
                doc_meta["content_type"] = md_meta["content_type"]
            if md_meta.get("region"):
                doc_meta["region"] = md_meta["region"]

            # 城市级指南：忽略正文里的伪实体名（如 住宿名称：成都住宿推荐）
            city_guide = is_city_level_guide(
                file_title=file_title,
                content_type=doc_meta.get("content_type") or "",
            )
            if not city_guide:
                for field in ENTITY_FIELDS:
                    value = (md_meta.get(field) or "").strip()
                    if not value or doc_meta.get(field):
                        continue
                    if is_generic_entity_name(
                        value,
                        file_title=file_title,
                        region=doc_meta.get("region") or "",
                        content_type=doc_meta.get("content_type") or "",
                    ):
                        continue
                    doc_meta[field] = value
            self.logger.info(f"解析到正文元数据块: {md_meta}")

        # 文档级一次 LLM 补全（城市级指南不强求实体名）
        if self._doc_needs_llm(doc_meta, file_title):
            sample = chunks[0] if chunks else {}
            # 用前几段拼接，避免只看标题段
            sample_content = "\n\n".join(
                (c.get("content") or "")[:800] for c in chunks[:3]
            )
            sample_item = {
                **doc_meta,
                **sample,
                "file_title": file_title,
                "content": sample_content or sample.get("content") or "",
            }
            filled = self._llm_fill_meta(sample_item)
            for key, value in filled.items():
                if value and not doc_meta.get(key):
                    doc_meta[key] = value
            self.logger.info(f"LLM 文档级补全结果: {filled}")

        # 按 content_type 互斥 + 过滤标题类伪实体名
        doc_meta = normalize_entity_fields(doc_meta, file_title=file_title)

        enriched: List[Dict] = []
        for chunk in chunks:
            item = dict(chunk)
            for key, value in doc_meta.items():
                if key not in item or not item.get(key):
                    item[key] = value
            item = normalize_entity_fields(item, file_title=file_title)
            enriched.append(item)

        state["chunks"] = enriched
        if enriched:
            first = enriched[0]
            for key in (
                "content_type",
                "region",
                "attraction_name",
                "route_name",
                "hotel_name",
                "restaurant_name",
                "source_file_name",
                "source_path",
            ):
                if key in first:
                    state[key] = first.get(key) or ""

        primary_field = CONTENT_TYPE_ENTITY_FIELD.get(state.get("content_type") or "", "")
        self.logger.info(
            f"旅游元数据完成: chunks={len(enriched)}, "
            f"content_type={state.get('content_type')}, region={state.get('region')}, "
            f"attraction_name={state.get('attraction_name')}, "
            f"route_name={state.get('route_name')}, "
            f"hotel_name={state.get('hotel_name')}, "
            f"restaurant_name={state.get('restaurant_name')}, "
            f"primary={primary_field}={state.get(primary_field, '') if primary_field else ''}"
        )
        return state

    def _collect_doc_meta(self, state: ImportGraphState) -> Dict[str, str]:
        return {
            "content_type": state.get("content_type") or "",
            "region": state.get("region") or "",
            "attraction_name": state.get("attraction_name") or "",
            "route_name": state.get("route_name") or "",
            "hotel_name": state.get("hotel_name") or "",
            "restaurant_name": state.get("restaurant_name") or "",
            "source_file_name": state.get("source_file_name") or "",
            "source_path": state.get("source_path") or "",
            "file_title": state.get("file_title") or "",
        }

    def _doc_needs_llm(self, doc_meta: Dict[str, str], file_title: str) -> bool:
        content_type = doc_meta.get("content_type") or ""
        if not content_type:
            return True
        if not doc_meta.get("region"):
            return True

        # 城市级推荐/指南、交通指南、文化民俗：允许实体名为空
        if is_city_level_guide(file_title=file_title, content_type=content_type):
            return False

        primary = CONTENT_TYPE_ENTITY_FIELD.get(content_type)
        if primary and not doc_meta.get(primary):
            return True
        return False

    def _llm_fill_meta(self, item: Dict) -> Dict[str, str]:
        empty = {
            "content_type": "",
            "region": "",
            "attraction_name": "",
            "route_name": "",
            "hotel_name": "",
            "restaurant_name": "",
        }
        file_title = item.get("file_title") or ""
        try:
            prompt = TRAVEL_META_USER_TEMPLATE.format(
                content_type=item.get("content_type") or "",
                region=item.get("region") or "",
                attraction_name=item.get("attraction_name") or "",
                route_name=item.get("route_name") or "",
                hotel_name=item.get("hotel_name") or "",
                restaurant_name=item.get("restaurant_name") or "",
                file_title=file_title,
                title=item.get("title") or "",
                content=(item.get("content") or "")[:2400],
                content_types=" / ".join(CONTENT_TYPES),
            )
            chat = llm_utils.get_llm_client(json_mode=True)
            response = chat.invoke(
                [
                    SystemMessage(content=TRAVEL_META_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            content = (response.content or "").strip()
            if content.startswith("```"):
                content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
            if not isinstance(result, dict):
                return empty

            filled = {}
            for key in empty:
                value = str(result.get(key) or "").strip()
                if key == "content_type" and value and value not in CONTENT_TYPES:
                    value = ""
                filled[key] = value
            return normalize_entity_fields(filled, file_title=file_title)
        except Exception as e:
            self.logger.warning(f"LLM 元数据补全失败，跳过: {e}")
            return empty


if __name__ == "__main__":
    setup_logging()
    init_state = {
        "file_title": "成都住宿推荐",
        "content_type": "酒店信息",
        "region": "成都",
        "source_file_name": "成都住宿推荐.md",
        "source_path": r"D:\旅游\数据\酒店信息\成都住宿推荐.md",
        "md_content": open(r"D:\旅游\数据\酒店信息\成都住宿推荐.md", encoding="utf-8").read(),
        "chunks": [
            {
                "title": "# 成都住宿推荐",
                "content": "# 成都住宿推荐\n## 元数据\n- 住宿名称：成都住宿推荐\n",
                "file_title": "成都住宿推荐",
            }
        ],
    }
    node = NodeTravelMeta()
    result = node(init_state)
    logging.getLogger().info(json.dumps(result, ensure_ascii=False, indent=2))
