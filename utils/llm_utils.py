# utils/llm_utils.py
"""
统一 LLM / VL 调用入口。
- LLM_BACKEND=transformers：本地 transformers 加载
- LLM_BACKEND=openai：DashScope / OpenAI 兼容接口
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from langchain_openai import ChatOpenAI

from config.lm_config import lm_config
from processor.import_processor.base import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

_chat_client = None
_vl_client = None
_llm_client_cache = {}


def get_llm_client(model: str | None = None, json_mode: bool = False) -> ChatOpenAI:
    """
    获取 LangChain ChatOpenAI 客户端实例
    - model: 允许不同节点使用不同模型
    - json_mode: True 时要求输出 JSON
    """
    m = model or lm_config.llm_model
    key = (m, json_mode)
    if key in _llm_client_cache:
        return _llm_client_cache[key]

    extra_body = {"enable_thinking": False}

    model_kwargs: dict = {}
    if json_mode:
        model_kwargs["response_format"] = {"type": "json_object"}

    client = ChatOpenAI(
        model=m,
        temperature=lm_config.llm_temperature,
        api_key=lm_config.api_key,
        base_url=lm_config.base_url,
        extra_body=extra_body,
        model_kwargs=model_kwargs,
    )
    _llm_client_cache[key] = client
    return client


def _is_local_backend() -> bool:
    return lm_config.backend == "transformers"


def _log_local_perf(msg: str, *args) -> None:
    """本地推理调试/速率日志，远程 API 模式不输出。"""
    if _is_local_backend():
        logger.info(msg, *args)


@dataclass
class SimpleAIMessage:
    """兼容 langchain AIMessage：调用方只读 .content"""
    content: str


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", "user"))
    msg_type = getattr(message, "type", None)
    if msg_type == "human":
        return "user"
    if msg_type == "ai":
        return "assistant"
    if msg_type == "system":
        return "system"
    return "user"


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def _to_openai_messages(messages: Sequence[Any]) -> List[dict]:
    return [{"role": _message_role(m), "content": _message_content(m)} for m in messages]


def _content_to_plain_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _extract_image_bytes(content: Any) -> Optional[bytes]:
    """从 OpenAI 风格 multimodal content 中取出第一张图的 bytes。"""
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "image_url":
            continue
        image_url = item.get("image_url") or {}
        url = image_url.get("url") if isinstance(image_url, dict) else None
        if not url:
            continue
        if isinstance(url, str) and url.startswith("data:") and "," in url:
            b64 = url.split(",", 1)[1]
            return base64.b64decode(b64)
        if isinstance(url, str) and url.startswith("file://"):
            with open(url[7:], "rb") as f:
                return f.read()
        if isinstance(url, str) and not url.startswith("http"):
            with open(url, "rb") as f:
                return f.read()
    return None


class LocalTransformersChat:
    """本地文本 Instruct 模型封装，接口对齐 ChatOpenAI.invoke(messages)。"""

    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        model_path = lm_config.llm_local_path or lm_config.llm_model
        if not model_path:
            raise ValueError("本地文本模型路径未配置：请设置 LLM_LOCAL_PATH 或 LLM_DEFAULT_MODEL")

        self.device = lm_config.device
        self.temperature = lm_config.llm_temperature
        self.max_new_tokens = lm_config.max_new_tokens
        dtype = torch.float16 if lm_config.use_fp16 else torch.float32

        logger.info(f"加载本地文本模型: {model_path} -> {self.device}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        # 单卡用 .to(device) 更稳；device_map 需要 accelerate 且对 "cuda:0" 行为因版本而异
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=dtype,
            trust_remote_code=True,
        ).to(self.device)
        self.model.eval()

    def invoke(self, messages: Sequence[Any], **kwargs) -> SimpleAIMessage:
        import torch

        chat_messages = []
        for m in _to_openai_messages(messages):
            chat_messages.append({
                "role": m["role"],
                "content": _content_to_plain_text(m["content"]),
            })

        prompt = self.tokenizer.apply_chat_template(
            chat_messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

        temperature = kwargs.get("temperature", self.temperature)
        do_sample = temperature is not None and float(temperature) > 0
        gen_kwargs = {
            "max_new_tokens": kwargs.get("max_new_tokens", self.max_new_tokens),
            "do_sample": do_sample,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if do_sample:
            gen_kwargs["temperature"] = float(temperature)

        with torch.inference_mode():
            output_ids = self.model.generate(**inputs, **gen_kwargs)

        generated = output_ids[0][inputs["input_ids"].shape[-1]:]
        text = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        return SimpleAIMessage(content=text)


class LocalTransformersVL:
    """本地视觉语言模型封装，支持文本 + base64/本地图片。"""

    def __init__(self):
        import torch
        from transformers import AutoProcessor

        model_path = lm_config.vl_local_path or lm_config.vl_model
        if not model_path:
            raise ValueError("本地 VL 模型路径未配置：请设置 VL_LOCAL_PATH 或 VL_MODEL")

        self.device = lm_config.device
        self.temperature = lm_config.llm_temperature
        self.max_new_tokens = lm_config.max_new_tokens
        dtype = torch.float16 if lm_config.use_fp16 else torch.float32

        logger.info(f"加载本地 VL 模型: {model_path} -> {self.device}")
        self.processor = AutoProcessor.from_pretrained(
            model_path,
            trust_remote_code=True,
            use_fast=True,
            min_pixels=lm_config.vl_min_pixels,
            max_pixels=lm_config.vl_max_pixels,
        )

        # 优先专用类，失败则回退 AutoModel
        try:
            from transformers import Qwen2_5_VLForConditionalGeneration
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_path,
                dtype=dtype,
                trust_remote_code=True,
            ).to(self.device)
        except Exception:
            from transformers import AutoModelForVision2Seq
            self.model = AutoModelForVision2Seq.from_pretrained(
                model_path,
                dtype=dtype,
                trust_remote_code=True,
            ).to(self.device)
        self.model.eval()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        _log_local_perf("本地 VL 模型加载完成，等待首张图推理（首次可能要编译 CUDA，会较慢）")

    def invoke(self, messages: Sequence[Any], **kwargs) -> SimpleAIMessage:
        import time as _time
        import torch
        from PIL import Image

        t0 = _time.time()
        openai_messages = _to_openai_messages(messages)
        pil_images: List[Image.Image] = []
        hf_messages = []

        for msg in openai_messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, list):
                parts = []
                image_bytes = _extract_image_bytes(content)
                if image_bytes:
                    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    pil_images.append(img)
                    parts.append({"type": "image"})
                text = _content_to_plain_text(content)
                if text:
                    parts.append({"type": "text", "text": text})
                hf_messages.append({"role": role, "content": parts or text})
            else:
                hf_messages.append({"role": role, "content": str(content)})

        if pil_images:
            sizes = ", ".join(f"{im.width}x{im.height}" for im in pil_images)
            _log_local_perf(f"VL 预处理开始，图片尺寸: {sizes}")

        text_prompt = self.processor.apply_chat_template(
            hf_messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        if pil_images:
            inputs = self.processor(
                text=[text_prompt],
                images=pil_images,
                return_tensors="pt",
                padding=True,
            )
        else:
            inputs = self.processor(text=[text_prompt], return_tensors="pt", padding=True)

        inputs = {k: v.to(self.model.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        input_len = int(inputs["input_ids"].shape[-1]) if "input_ids" in inputs else -1
        _log_local_perf(
            "VL generate 开始，input_tokens≈%s（首张图可能卡住数分钟，属正常）",
            input_len,
        )

        # 图片标题不需要很长；默认比文本 LLM 更短，加快推理
        max_new = kwargs.get("max_new_tokens", min(self.max_new_tokens, 128))
        temperature = kwargs.get("temperature", self.temperature)
        # 摘要任务用贪心解码，比采样快且更稳
        gen_kwargs = {
            "max_new_tokens": max_new,
            "do_sample": False,
        }

        with torch.inference_mode():
            output_ids = self.model.generate(**inputs, **gen_kwargs)

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        trimmed = [out[len(inp):] for inp, out in zip(inputs["input_ids"], output_ids)]
        text = self.processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        _log_local_perf(
            "VL generate 完成，耗时 %.1fs，输出长度=%s",
            _time.time() - t0,
            len(text),
        )

        # 单张推理后清理中间张量，降低连续多张图时的峰值显存
        del inputs, output_ids, trimmed
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return SimpleAIMessage(content=text)


class RemoteOpenAIChat:
    """DashScope / OpenAI 兼容封装。"""

    def __init__(self, model: Optional[str] = None, json_mode: bool = False):
        from langchain_openai import ChatOpenAI

        kwargs: dict = {
            "model": model or lm_config.llm_model,
            "api_key": lm_config.api_key,
            "base_url": lm_config.base_url,
            "temperature": lm_config.llm_temperature,
        }
        if model == lm_config.llm_model or model is None:
            kwargs["extra_body"] = {"enable_thinking": False}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        self._client = ChatOpenAI(**kwargs)

    def invoke(self, messages: Sequence[Any], **kwargs) -> Any:
        return self._client.invoke(messages, **kwargs)


def get_chat_openAI(json_mode: bool = False):
    """
    获取文本聊天客户端（单例）。
    保持旧函数名，避免全项目改 import。
    """
    global _chat_client
    if json_mode and lm_config.backend == "openai":
        # JSON mode 每次可独立创建，避免污染单例
        return RemoteOpenAIChat(model=lm_config.item_model or lm_config.llm_model, json_mode=True)

    if _chat_client is not None and not json_mode:
        return _chat_client

    if lm_config.backend == "transformers":
        _chat_client = LocalTransformersChat()
    else:
        _chat_client = RemoteOpenAIChat(model=lm_config.llm_model)
    return _chat_client


def release_vl_model() -> None:
    """释放 VL 模型占用的 GPU/内存，避免与 PyCharm / 后续 BGE 模型抢资源。"""
    global _vl_client
    if _vl_client is None:
        return
    try:
        import gc
        import torch

        if hasattr(_vl_client, "model"):
            del _vl_client.model
        if hasattr(_vl_client, "processor"):
            del _vl_client.processor
        _vl_client = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _log_local_perf("已释放本地 VL 模型显存")
    except Exception as e:
        logger.warning(f"释放 VL 模型时出错: {e}")


def get_vl_chat():
    """获取视觉语言模型客户端（单例）。"""
    global _vl_client
    if _vl_client is not None:
        return _vl_client

    if lm_config.backend == "transformers":
        _vl_client = LocalTransformersVL()
    else:
        _vl_client = RemoteOpenAIChat(model=lm_config.vl_model)
    return _vl_client


def get_item_chat():
    """商品名识别等任务用的文本客户端。"""
    if lm_config.backend == "transformers":
        return get_chat_openAI()
    return RemoteOpenAIChat(model=lm_config.item_model or lm_config.llm_model, json_mode=True)
