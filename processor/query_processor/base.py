# processor/query_processor/base.py

"""
查询流程节点基类

定义统一的节点接口规范，提供通用功能
"""
from abc import abstractmethod, ABC
from typing import TypeVar

from tool.logger import logger
from utils.task_utils import add_running_task, add_done_task

T = TypeVar("T")  # 泛型状态类型


class NodeBase(ABC):
    name: str = "base_node"  # 节点名称，子类应覆盖

    def __call__(self, state: T) -> T:
        """
        节点执行入口
        """
        try:
            # 1. 开始准备执行节点
            logger.info(f"--- {self.name} 开始啦 ---")

            # 开始：记录节点运行状态
            session_id = state.get("session_id")
            is_stream = state.get("is_stream")
            add_running_task(session_id, self.name, is_stream)

            state = self.process(state)

            # 此处加任务追踪，多路搜索节点无法获取session_id，因此需要在process内部处理
            add_done_task(session_id, self.name, is_stream)

            # 3. 执行节点成功
            logger.info(f"--- {self.name} 完成啦 ---")

        except Exception as e:
            logger.error(f"{self.name} 执行失败: {e}")
            raise
        return state

    @abstractmethod
    def process(self, state: T) -> T:
        """
        节点核心处理逻辑
        子类必须实现此方法
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """
        pass
