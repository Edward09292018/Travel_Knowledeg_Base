# config/lm_config.py

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class LLMConfig:
    # openai：走 DashScope / OpenAI 兼容接口；transformers：本地权重推理
    backend: str
    base_url: str
    api_key: str
    vl_model: str
    llm_model: str
    llm_temperature: float
    item_model: str
    # 本地 transformers
    llm_local_path: str
    vl_local_path: str
    device: str
    use_fp16: bool
    max_new_tokens: int
    vl_min_pixels: int
    vl_max_pixels: int
    release_vl_after_use: bool


lm_config = LLMConfig(
    backend=os.getenv("LLM_BACKEND", "transformers").strip().lower(),
    base_url=os.getenv("OPENAI_API_BASE", ""),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    vl_model=os.getenv("VL_MODEL", ""),
    llm_model=os.getenv("LLM_DEFAULT_MODEL", ""),
    llm_temperature=float(os.getenv("LLM_DEFAULT_TEMPERATURE", "0.1") or "0.1"),
    item_model=os.getenv("ITEM_MODEL", ""),
    llm_local_path=os.getenv("LLM_LOCAL_PATH", ""),
    vl_local_path=os.getenv("VL_LOCAL_PATH", ""),
    device=os.getenv("LLM_DEVICE", "cuda:0"),
    use_fp16=_env_bool("LLM_FP16", True),
    max_new_tokens=int(os.getenv("LLM_MAX_NEW_TOKENS", "512") or "512"),
    # Qwen2.5-VL 默认视觉 token 范围过大时易 OOM；256~1280 token 档较省显存
    vl_min_pixels=int(os.getenv("VL_MIN_PIXELS", str(256 * 28 * 28)) or str(256 * 28 * 28)),
    vl_max_pixels=int(os.getenv("VL_MAX_PIXELS", str(768 * 28 * 28)) or str(768 * 28 * 28)),
    release_vl_after_use=_env_bool("LLM_RELEASE_VL_AFTER_USE", True),
)
