# tool/download_local_llm.py
"""
从 ModelScope 下载本地文本 LLM 与视觉语言模型（transformers 推理用）。
用法：
    python tool/download_local_llm.py
    python tool/download_local_llm.py --llm-only
    python tool/download_local_llm.py --vl-only
"""

from __future__ import annotations

import argparse

from modelscope.hub.snapshot_download import snapshot_download

# 与 .env / lm_config 默认值对齐；8GB 显存优先小模型
DEFAULT_CACHE = "D:/ai_models/modelscope_cache"
# 文本：替代远程 qwen-flash
DEFAULT_LLM_REPO = "Qwen/Qwen2.5-1.5B-Instruct"
# 视觉：替代远程 qwen3-vl-flash
DEFAULT_VL_REPO = "Qwen/Qwen2.5-VL-3B-Instruct"


def download_model(repo_id: str, cache_dir: str) -> str:
    model_dir = snapshot_download(repo_id, cache_dir=cache_dir)
    print(f"[{repo_id}] 已下载到: {model_dir}")
    return model_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="下载本地 LLM / VL 模型到 ModelScope 缓存")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="ModelScope 缓存目录")
    parser.add_argument("--llm-repo", default=DEFAULT_LLM_REPO, help="文本 Instruct 模型仓库 ID")
    parser.add_argument("--vl-repo", default=DEFAULT_VL_REPO, help="视觉 VL 模型仓库 ID")
    parser.add_argument("--llm-only", action="store_true", help="只下载文本模型")
    parser.add_argument("--vl-only", action="store_true", help="只下载视觉模型")
    args = parser.parse_args()

    download_llm = not args.vl_only
    download_vl = not args.llm_only

    if download_llm:
        download_model(args.llm_repo, args.cache_dir)
    if download_vl:
        download_model(args.vl_repo, args.cache_dir)

    print("\n下载完成。请把路径填进 .env：")
    print("  LLM_LOCAL_PATH=<上方文本模型路径>")
    print("  VL_LOCAL_PATH=<上方视觉模型路径>")
    print("  LLM_BACKEND=transformers")


if __name__ == "__main__":
    main()
