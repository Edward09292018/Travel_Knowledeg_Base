# processor/query_processor/nodes/node_search_embedding.py
from config.milvus_config import milvus_config
from processor.query_processor.base import NodeBase
from processor.query_processor.state import QueryGraphState
from tool.logger import logger
from utils.embedding_utils import generate_embeddings
from utils.json_format_utils import serialize_json
from utils.milvus_utils import create_hybrid_search_requests, get_milvus_client, hybrid_search
from utils.travel_meta_utils import CHUNK_OUTPUT_FIELDS, build_entity_filter_expr


class NodeSearchEmbedding(NodeBase):
    """
   节点功能：基于已确认旅游实体 + 改写后的用户问题，执行Milvus向量数据库混合检索
   """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_search_embedding"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        """
        核心节点函数：基于已确认实体名 + 改写后的用户问题，执行Milvus混合检索
        """

        try:

            # 1、用户问题和已确认实体名（状态字段仍为 item_names）
            query = state.get("rewritten_query")
            item_names = state.get("item_names")

            # 2、生成向量 (Dense + Sparse)
            embeddings = generate_embeddings([query])
            dense_vec = embeddings.get("dense")[0]
            sparse_vec = embeddings.get("sparse")[0]

            # 3. 获取Milvus的集合
            collection_name = milvus_config.chunks_collection

            # 4、旅游实体过滤：attraction/route/hotel/restaurant/region OR
            expr = build_entity_filter_expr(item_names)
            if expr:
                logger.info(f"过滤条件: {expr}")
            else:
                logger.info("未指定实体过滤，将全库检索")

            # 5、构造Milvus混合搜索请求对象
            reqs = create_hybrid_search_requests(
                dense_vector=dense_vec,
                sparse_vector=sparse_vec,
                expr=expr,
                limit=10
            )

            # 6、执行混合向量检索
            logger.info("开始执行 Milvus 混合检索...")
            client = get_milvus_client()
            res = hybrid_search(
                client=client,
                collection_name=collection_name,
                reqs=reqs,
                ranker_weights=(0.8, 0.2),
                output_fields=CHUNK_OUTPUT_FIELDS,
            )

            # 7、构造并返回结果
            return {"embedding_chunks": res[0] if res else []}

        except Exception as e:
            logger.exception(f"向量搜索失败: {e}")
            return {}


if __name__ == "__main__":
    init_state = {
        "rewritten_query": "成都宽窄巷子怎么玩？",
        "item_names": ["宽窄巷子", "成都"]
    }
    node_search_embedding = NodeSearchEmbedding()
    result = node_search_embedding(init_state)
    logger.info(serialize_json(result, indent=4))
