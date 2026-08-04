# processor/query_processor/nodes/node_item_name_confirm.py

import json
from typing import List, Dict, Tuple

from langchain_core.messages import SystemMessage, HumanMessage

from config.milvus_config import milvus_config
from processor.query_processor.base import NodeBase
from processor.query_processor.prompt.item_name_confirm import ITEM_NAME_EXTRACT_SYSTEM_PROMPT, \
    ITEM_NAME_EXTRACT_TEMPLATE
from processor.query_processor.state import QueryGraphState
from tool.logger import logger
from utils import llm_utils
from utils.embedding_utils import generate_embeddings
from utils.json_format_utils import serialize_json
from utils.milvus_utils import get_milvus_client, create_hybrid_search_requests, hybrid_search
from utils.mongo_history_utils import save_chat_message, update_message_item_names, get_recent_messages
from utils.travel_meta_utils import CHUNK_OUTPUT_FIELDS, extract_entity_name_from_hit


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心旅游实体（景点/线路/酒店/餐厅/地区）。
    状态字段仍使用 item_names，语义上表示已确认的旅游实体名列表。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        """
        必要参数：session_id、original_query
        更新参数：history、rewritten_query、item_names、answer

        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        # 步骤1：校验参数
        session_id, original_query = self._step_1_validate_param(state)
        logger.info(f"步骤1：参数校验通过")

        # 步骤2：获取历史记录
        history = get_recent_messages(session_id)
        logger.info(f"步骤2：获取到 {len(history)} 条历史消息")
        # 更新状态
        state["history"] = history

        # 步骤3：用户初始消息保存
        message_id = save_chat_message(session_id, "user", original_query)
        logger.info(f"步骤3：用户消息已初始保存, ID: {message_id}")

        # 步骤4：提取信息
        extract_res = self._step_4_extract_info(original_query, history)
        item_names = extract_res.get("item_names")
        rewritten_query = extract_res.get("rewritten_query", original_query)
        # 更新状态
        state["rewritten_query"] = rewritten_query
        state["item_names"] = item_names

        # 5. & 6. 如果有提取到实体名，进行搜索和对齐
        align_result = {}
        if len(item_names) > 0:
            query_results = self._step_5_vectorize_and_query(item_names)
            align_result = self._step_6_align_item_names(query_results)
        else:
            logger.info("Node: 未提取到旅游实体名，将全库检索")

        # 7. 检查确认状态
        state = self._step_7_check_confirmation(state, align_result, history, extracted_names=item_names)

        # 8. 写入最终历史
        self._step_8_write_history(state, session_id, rewritten_query, message_id)
        return state

    # 参数校验
    def _step_1_validate_param(self, state: QueryGraphState) -> Tuple[str, str]:

        session_id = state.get("session_id")
        if not session_id:
            raise ValueError("核心参数session_id缺失")

        original_query = state.get("original_query")
        if not original_query:
            raise ValueError("核心参数original_query缺失")

        return session_id, original_query

    # 提取旅游实体名称
    def _step_4_extract_info(self, query, history) -> Dict:
        """
        利用LLM从当前问题以及历史会话中提取出主要询问的旅游实体名 item_names（可多个）
        同时根据上下文重新改写问题，保证问题独立完整
        :return: {"item_names": [...], "rewritten_query": "..."}
        """

        try:
            # 1. 获取llm客户端（本地 transformers 或远程 OpenAI 兼容）
            chat_model = llm_utils.get_item_chat()

            # 2. 构造历史对话文本，拼接为"角色: 内容"的格式，供LLM做上下文理解
            history_text = ""
            for msg in history:
                role = msg.get("role")
                content = msg.get("text")
                history_text += f"{role}: {content}\n"

            # 3. 处理和动态拼接提示词
            # 为了把大括号当作 “普通字符” 保留下来，用双大括号 {{ 表示普通的左大括号 {，双大括号 }} 表示普通的右大括号 }。
            user_prompt = ITEM_NAME_EXTRACT_TEMPLATE.format(
                history_text=history_text,
                query=query
            )

            # 4. 构造LLM调用的消息列表，包含系统角色（定义助手身份）和用户角色（传入提示词）
            messages = [
                SystemMessage(content=ITEM_NAME_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt)
            ]

            # 5. 调用LLM客户端，发起请求获取结果
            response = chat_model.invoke(messages)
            content = response.content

            # 6. 数据清洗：处理LLM可能返回的代码块格式（如```json ... ```），去除包裹符
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "")

            # 7. 数据解析：将JSON字符串转为字典
            result = json.loads(content)

            # 8. 健壮性处理：确保字段存在
            # 确保返回结果包含item_names字段，无则设为空列表
            if "item_names" not in result:
                result["item_names"] = []
            # 确保返回结果包含rewritten_query字段，无则复用原始查询
            if "rewritten_query" not in result:
                result["rewritten_query"] = query

            # 9. 给item_names 去除空格
            result["item_names"] = [
                name.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", "")
                for name in result["item_names"]
            ]

            # 10、返回解析后的提取结果
            return result

        except Exception as e:
            # 捕获所有异常（如LLM调用失败、JSON解析失败等），记录错误日志
            logger.error(f"大模型调用异常：{e}")
            # 异常时返回默认结果：空实体名列表+原始查询
            return {"item_names": [], "rewritten_query": query}

    # 向量化查询（在 chunks 集合上对齐旅游实体名）
    def _step_5_vectorize_and_query(self, item_names) -> List[Dict]:
        """
        把分析出的实体名逐个向量化，并在 travel_chunks 中混合搜索，对齐库内标准实体名。
        """
        results = []
        client = get_milvus_client()
        if not client:
            logger.error("连接 Milvus 失败")
            return results

        collection_name = milvus_config.chunks_collection
        embeddings = generate_embeddings(item_names)

        for i in range(len(item_names)):
            try:
                dense_vector = embeddings.get("dense")[i]
                sparse_vector = embeddings.get("sparse")[i]
                reqs = create_hybrid_search_requests(
                    dense_vector=dense_vector,
                    sparse_vector=sparse_vector,
                    limit=5
                )
                search_res = hybrid_search(
                    client=client,
                    collection_name=collection_name,
                    reqs=reqs,
                    ranker_weights=(0.8, 0.2),
                    limit=5,
                    norm_score=True,
                    output_fields=CHUNK_OUTPUT_FIELDS,
                )

                matches = []
                seen = set()
                if search_res and len(search_res) > 0:
                    for hit in search_res[0]:
                        entity = hit.get("entity", {}) or {}
                        name = extract_entity_name_from_hit(entity)
                        if not name or name in seen:
                            continue
                        seen.add(name)
                        matches.append(
                            {
                                "item_name": name,  # 兼容对齐逻辑字段名
                                "score": hit.get("distance"),
                            }
                        )

                results.append({
                    "extracted_name": item_names[i],
                    "matches": matches
                })

            except Exception as e:
                logger.error(f"查询旅游实体 '{item_names[i]}' 时出错: {e}")

        return results

    def _step_6_align_item_names(self, query_results) -> dict:
        """
        根据Milvus搜索评分对齐旅游实体名。
        规则：
          a 评分>0.85 → 确认
          b 评分≥0.6 且与提取名相同/包含 → 确认（避免把「成都」打成候选后反复反问）
          c 其余≥0.6 → 候选（仅在确实歧义时才用于反问）
        """
        confirmed_item_names: List[str] = []
        options: List[str] = []

        logger.info(f"步骤6：获得待处理的数据源：{query_results}")

        for res in query_results:
            extracted_name = (res.get("extracted_name", "") or "").strip()
            matches = res.get("matches", []) or []
            if not matches:
                # 库内未对齐到时，保留提取名作为软确认，后续可继续检索
                if extracted_name:
                    confirmed_item_names.append(extracted_name)
                continue

            high = [m for m in matches if m.get("score", 0) > 0.85]
            mid = [m for m in matches if m.get("score", 0) >= 0.6]

            if len(high) > 0:
                for m in high:
                    name = (m.get("item_name") or "").strip()
                    if name:
                        confirmed_item_names.append(name)
                continue

            if len(mid) > 0:
                exact = []
                fuzzy = []
                for m in mid:
                    name = (m.get("item_name") or "").strip()
                    if not name:
                        continue
                    if extracted_name and (
                        name == extracted_name
                        or name in extracted_name
                        or extracted_name in name
                    ):
                        exact.append(name)
                    else:
                        fuzzy.append(name)

                if exact:
                    confirmed_item_names.extend(exact)
                elif extracted_name:
                    # 有提取名但库内只有弱相关命中：优先相信提取名，不进入反问
                    confirmed_item_names.append(extracted_name)
                else:
                    options.extend(fuzzy[:3])

        return {
            "confirmed_item_names": list(dict.fromkeys(confirmed_item_names)),
            "options": list(dict.fromkeys(options)),
        }

    def _step_7_check_confirmation(self, state, align_result, history, extracted_names=None):
        """
        检查对齐后的旅游实体状态：
        A. 已确认 → 带实体过滤继续检索
        B. 真正多实体歧义 → 反问
        C. 其他情况 → 软过滤或全库检索，不硬拦截
        """
        confirmed = list(align_result.get("confirmed_item_names", []) or [])
        options = list(align_result.get("options", []) or [])
        extracted_names = [n for n in (extracted_names or []) if n]
        query_text = (state.get("original_query") or "") + " " + (state.get("rewritten_query") or "")

        # 候选里已出现在用户问题/提取名中的，直接升级为确认
        promoted = []
        remain_options = []
        for name in options:
            if not name:
                continue
            if name in extracted_names or name in query_text:
                promoted.append(name)
            else:
                remain_options.append(name)
        if promoted:
            confirmed.extend(promoted)
            options = remain_options

        # 单个候选不反问，直接当确认
        if not confirmed and len(options) == 1:
            confirmed = [options[0]]
            options = []

        confirmed = list(dict.fromkeys(confirmed))
        options = list(dict.fromkeys(options))

        # 分支A：有确认实体
        if confirmed:
            ids_to_update = []
            for msg in history:
                if not msg.get("item_names"):
                    mid = msg.get("_id")
                    if mid:
                        ids_to_update.append(str(mid))

            if ids_to_update:
                update_message_item_names(ids_to_update, confirmed)

            state["item_names"] = confirmed
            state["answer"] = ""
            return state

        # 分支B：仅当存在多个且问题中看不出的歧义实体时反问
        if len(options) >= 2:
            options_str = "、".join(options)
            answer = f"您是想了解以下哪个内容：{options_str}？请再明确一下。"
            state["answer"] = answer
            state["item_names"] = []
            return state

        # 分支C：继续检索（优先提取名软过滤）
        soft_names = extracted_names or options
        state["item_names"] = soft_names
        state["answer"] = ""
        if soft_names:
            logger.info(f"未形成强确认，使用软过滤继续检索: {soft_names}")
        else:
            logger.info("未提取到实体名，后续将全库检索")
        return state

    def _step_8_write_history(self, state, session_id, rewritten_query, message_id):
        """
         8 把本次处理的核心信息（用户问题、助手答案、商品名、改写查询）写入MongoDB的会话历史
         包含2个核心操作：1. 写入助手答案（若有）；2. 更新用户原始问题的关联信息
         :param state: 字典 - step6更新后的会话状态，包含answer/item_names等字段
         :param session_id: 字符串 - 会话唯一标识
         :param rewritten_query: 字符串 - step3改写后的完整问题
         :param message_id: 字符串 - 本次用户问题的消息唯一ID
         :return:
         """
        # 若会话状态中有助手答案（分支B/C），写入助手消息到历史
        if state.get("answer"):
            save_chat_message(
                session_id=session_id,  # 会话ID，关联所属会话
                role="assistant",  # 消息角色：助手
                text=state["answer"],  # 消息内容：向用户确认的提示语/无结果提示语
                rewritten_query="",  # 助手消息无需改写查询，设为空
                item_names=state.get("item_names", [])  # 关联的商品名列表（分支B/C均为空）
            )

        # 强制更新本次用户原始问题的关联信息（核心：补充改写查询、商品名）
        save_chat_message(
            session_id=session_id,  # 会话ID，关联所属会话
            role="user",  # 消息角色：用户
            text=state["original_query"],  # 消息内容：用户原始查询
            rewritten_query=rewritten_query,  # 补充step3改写后的完整问题
            item_names=state.get("item_names", []),  # 补充关联的商品名列表
            message_id=message_id  # 消息ID，指定更新已存在的用户消息（而非新增）
        )

        # 返回最终会话状态，供下游节点使用
        return state


if __name__ == "__main__":
    # 初始化图状态
    init_state = {
        "original_query": "成都宽窄巷子怎么玩？",
        "session_id": "test_session_002"
    }

    # 创建节点对象
    node_item_name_confirm = NodeItemNameConfirm()
    # 执行节点的单元测试
    result = node_item_name_confirm(init_state)
    # 将返回的图状态进行json序列化
    json_state = serialize_json(result)
    # 输出
    logger.info(json_state)
