# utils/travel_meta_utils.py
"""
旅游知识库元数据：路径/文件名规则推断与清洗。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

# 合法内容类型（与 README 一致）
CONTENT_TYPES = (
    "景点介绍",
    "线路推荐",
    "酒店信息",
    "美食推荐",
    "交通指南",
    "文化民俗",
)

# 内容类型 → 本条记录应填写的实体字段（其余实体字段置空）
CONTENT_TYPE_ENTITY_FIELD = {
    "景点介绍": "attraction_name",
    "线路推荐": "route_name",
    "酒店信息": "hotel_name",
    "美食推荐": "restaurant_name",
}

ENTITY_FIELDS = (
    "attraction_name",
    "route_name",
    "hotel_name",
    "restaurant_name",
)

# 文件名中常见的「指南/推荐」类后缀，去掉后才是地区
_TITLE_GENERIC_SUFFIXES = (
    "住宿推荐",
    "酒店推荐",
    "美食推荐",
    "线路推荐",
    "景点推荐",
    "景点介绍",
    "酒店信息",
    "交通指南",
    "文化民俗",
    "旅游攻略",
    "旅行攻略",
    "游玩攻略",
    "住宿攻略",
    "美食攻略",
    "必吃推荐",
    "必住推荐",
    "必去推荐",
    "攻略",
    "指南",
    "推荐",
    "介绍",
    "信息",
    "合集",
    "清单",
    "精选",
    "汇总",
    "大全",
)

# 实体名若像文档标题而非具体对象，应丢弃
_GENERIC_ENTITY_PATTERNS = (
    r".+住宿推荐$",
    r".+酒店推荐$",
    r".+美食推荐$",
    r".+线路推荐$",
    r".+景点推荐$",
    r".+旅游攻略$",
    r".+旅行攻略$",
    r".+游玩攻略$",
    r".+住宿攻略$",
    r".+美食攻略$",
    r".+必吃推荐$",
    r".+必住推荐$",
    r".+必去推荐$",
    r".+攻略$",
    r".+指南$",
    r".+推荐$",
    r".+合集$",
    r".+清单$",
    r".+精选$",
    r".+汇总$",
    r".+大全$",
)


def infer_content_type(file_path: str, file_title: str = "") -> str:
    """
    从路径段或文件名中匹配内容类型关键词。
    优先匹配路径中的目录名，其次匹配文件名。
    """
    path_text = str(file_path).replace("\\", "/")
    title = file_title or Path(file_path).stem

    parts = [p for p in path_text.split("/") if p]
    for part in parts:
        if part in CONTENT_TYPES:
            return part

    haystack = f"{path_text}/{title}"
    for ct in CONTENT_TYPES:
        if ct in haystack:
            return ct
    return ""


def strip_generic_title_suffix(text: str) -> str:
    """反复去掉指南/推荐类通用后缀。"""
    value = (text or "").strip()
    changed = True
    while changed and value:
        changed = False
        for suffix in _TITLE_GENERIC_SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)].strip(" -_/")
                changed = True
                break
    return value


def infer_region(file_title: str, content_type: str = "") -> str:
    """
    从文件名 stem 提取地区。
    例：成都交通指南 → 成都；成都住宿推荐 → 成都
    """
    if not file_title:
        return ""

    region = file_title.strip()
    if content_type and region.endswith(content_type):
        region = region[: -len(content_type)].strip()

    region = strip_generic_title_suffix(region)
    region = re.sub(r"[-_\s]+$", "", region)
    region = re.sub(r"^[-_\s]+", "", region)
    return region


def parse_md_front_meta(md_content: str) -> Dict[str, str]:
    """
    解析文档开头「## 元数据」列表项，如：
    - 内容类型：酒店信息
    - 城市：成都
    - 住宿名称：成都住宿推荐
    """
    result: Dict[str, str] = {}
    if not md_content:
        return result

    head = md_content[:3000]
    meta_match = re.search(r"##\s*元数据\s*\n(.*?)(?=\n##\s|\Z)", head, re.S)
    block = meta_match.group(1) if meta_match else head

    key_map = {
        "内容类型": "content_type",
        "城市": "region",
        "地区": "region",
        "景点名称": "attraction_name",
        "景区名称": "attraction_name",
        "线路名称": "route_name",
        "酒店名称": "hotel_name",
        "住宿名称": "hotel_name",
        "餐厅名称": "restaurant_name",
        "美食名称": "restaurant_name",
    }

    for line in block.splitlines():
        line = line.strip().lstrip("-* ").strip()
        if "：" in line:
            key, value = line.split("：", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = key.strip()
        value = value.strip()
        field = key_map.get(key)
        if field and value:
            result[field] = value

    if result.get("content_type") and result["content_type"] not in CONTENT_TYPES:
        for ct in CONTENT_TYPES:
            if ct in result["content_type"]:
                result["content_type"] = ct
                break
        else:
            result.pop("content_type", None)

    return result


def is_city_level_guide(file_title: str = "", content_type: str = "", entity_name: str = "") -> bool:
    """
    文件名/实体名像城市级推荐或指南，而非单一实体文档。

    判定偏保守：只有明确的「推荐/指南/攻略/合集」等才视为城市级；
    「XX景点介绍」「XX酒店信息」可能是具体对象文档，不在此一律清空。
    """
    title = (file_title or "").strip()
    entity = (entity_name or "").strip()
    content_type = (content_type or "").strip()

    if content_type in ("交通指南", "文化民俗"):
        return True

    city_level_suffixes = (
        "住宿推荐",
        "酒店推荐",
        "美食推荐",
        "线路推荐",
        "景点推荐",
        "旅游攻略",
        "旅行攻略",
        "游玩攻略",
        "住宿攻略",
        "美食攻略",
        "必吃推荐",
        "必住推荐",
        "必去推荐",
        "攻略",
        "指南",
        "推荐",
        "合集",
        "清单",
        "精选",
        "汇总",
        "大全",
    )

    for text in (title, entity):
        if not text:
            continue
        for suffix in city_level_suffixes:
            if text.endswith(suffix):
                return True
    return False


def is_generic_entity_name(
    name: str,
    file_title: str = "",
    region: str = "",
    content_type: str = "",
) -> bool:
    """
    判断实体名是否其实是文档标题/地区级推荐名（不应入库为具体酒店/景点等）。
    """
    value = (name or "").strip()
    if not value:
        return True

    title = (file_title or "").strip()
    city = (region or "").strip()
    bare = re.sub(r"^#+\s*", "", value).strip()

    # 与文件名、地区相同
    if title and value == title:
        return True
    if title and bare == title:
        return True
    if city and value == city:
        return True
    if city and bare == city:
        return True

    # 明确的通用标题模式（推荐/指南/攻略等）
    for pattern in _GENERIC_ENTITY_PATTERNS:
        if re.fullmatch(pattern, value) or re.fullmatch(pattern, bare):
            return True

    # 「成都 + 住宿推荐」：去掉通用后缀后只剩地区
    stripped = strip_generic_title_suffix(bare)
    if city and stripped == city:
        return True
    if title and stripped == infer_region(title, content_type):
        # 仅当原值本身带有指南/推荐类尾巴时才丢弃
        if re.search(r"(推荐|指南|攻略|合集|清单|精选|汇总|大全|介绍|信息)$", bare):
            # 「宽窄巷子景点介绍」去掉后缀后是宽窄巷子 ≠ 文件地区「成都」时不应误杀
            inferred = infer_region(title, content_type)
            if stripped == inferred and (not city or stripped == city):
                # 文件名本身就是城市级标题，实体名等于文件名去后缀后的地区
                if is_city_level_guide(file_title=title, content_type=content_type):
                    return True

    # 城市级指南文档：实体名若仍是指南标题则丢弃
    if is_city_level_guide(file_title=title, content_type=content_type):
        if value == title or bare == title:
            return True
        if re.search(r"(推荐|指南|攻略|合集|清单|精选|汇总|大全)$", bare):
            return True
        if city and city in bare and strip_generic_title_suffix(bare) == city:
            return True

    return False


def sanitize_entity_fields(
    meta: Dict[str, str],
    file_title: str = "",
) -> Dict[str, str]:
    """清空不合理的实体名（文档标题、地区级推荐名等）。"""
    result = dict(meta)
    region = result.get("region") or ""
    content_type = result.get("content_type") or ""
    title = file_title or result.get("file_title") or ""

    # 交通指南 / 文化民俗：永远不写四类实体名
    if content_type in ("交通指南", "文化民俗"):
        for field in ENTITY_FIELDS:
            result[field] = ""
        return result

    # 城市级指南：文档级不写具体实体名
    if is_city_level_guide(file_title=title, content_type=content_type):
        for field in ENTITY_FIELDS:
            result[field] = ""
        return result

    for field in ENTITY_FIELDS:
        value = (result.get(field) or "").strip()
        if is_generic_entity_name(
            value,
            file_title=title,
            region=region,
            content_type=content_type,
        ):
            result[field] = ""
        else:
            result[field] = value
    return result


def infer_travel_meta_from_path(
    file_path: str,
    file_title: Optional[str] = None,
    source_file_name: Optional[str] = None,
    source_path: Optional[str] = None,
) -> Dict[str, str]:
    """基于路径/文件名推断文档级旅游元数据。"""
    path_obj = Path(file_path) if file_path else None
    title = file_title or (path_obj.stem if path_obj else "")
    content_type = infer_content_type(file_path or "", title)
    region = infer_region(title, content_type)

    return {
        "content_type": content_type,
        "region": region,
        "source_file_name": source_file_name
        or (path_obj.name if path_obj else ""),
        "source_path": source_path or (str(file_path) if file_path else ""),
        "attraction_name": "",
        "route_name": "",
        "hotel_name": "",
        "restaurant_name": "",
    }


def normalize_entity_fields(meta: Dict[str, str], file_title: str = "") -> Dict[str, str]:
    """
    按 content_type 只保留对应实体字段，其余实体名清空；
    并过滤文档标题类伪实体名。
    """
    result = sanitize_entity_fields(meta, file_title=file_title)
    content_type = (result.get("content_type") or "").strip()
    primary_field = CONTENT_TYPE_ENTITY_FIELD.get(content_type)

    for field in ENTITY_FIELDS:
        if field == primary_field:
            result[field] = (result.get(field) or "").strip()
        else:
            result[field] = ""

    return result


def get_primary_entity_name(meta: Dict[str, str]) -> str:
    """按 content_type 取本条记录的主实体名（用于向量化前缀）。"""
    content_type = (meta.get("content_type") or "").strip()
    primary_field = CONTENT_TYPE_ENTITY_FIELD.get(content_type)
    if primary_field:
        value = (meta.get(primary_field) or "").strip()
        if value and not is_generic_entity_name(
            value,
            file_title=str(meta.get("file_title") or ""),
            region=str(meta.get("region") or ""),
            content_type=content_type,
        ):
            return value
    return (meta.get("region") or "").strip()


# 查询侧：Milvus 切片常用返回字段
CHUNK_OUTPUT_FIELDS = [
    "chunk_id",
    "content",
    "title",
    "content_type",
    "region",
    "attraction_name",
    "route_name",
    "hotel_name",
    "restaurant_name",
    "source_file_name",
]


def extract_entity_name_from_hit(entity: Dict | None) -> str:
    """从 Milvus hit.entity 中取主实体名（景点/线路/酒店/餐厅/地区）。"""
    if not entity:
        return ""
    for field in ENTITY_FIELDS:
        value = str(entity.get(field) or "").strip()
        if value:
            return value
    return str(entity.get("region") or "").strip()


def build_entity_filter_expr(entity_names: list | None) -> str | None:
    """
    构造旅游实体过滤表达式：在四类实体名 + region 上做 OR。
    例：attraction_name in ["宽窄巷子"] or route_name in [...] or ... or region in [...]
    """
    if not entity_names:
        return None

    cleaned = []
    for name in entity_names:
        value = str(name or "").strip()
        if not value:
            continue
        # 过滤表达式字符串安全转义
        value = value.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
        cleaned.append(value)
    if not cleaned:
        return None

    quoted = "[" + ", ".join(f'"{v}"' for v in cleaned) + "]"
    fields = list(ENTITY_FIELDS) + ["region"]
    return " or ".join(f"{field} in {quoted}" for field in fields)
