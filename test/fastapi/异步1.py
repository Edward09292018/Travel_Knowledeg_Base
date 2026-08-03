# 需要安装 aiohttp: pip install aiohttp
import asyncio
import time

import aiohttp


async def fetch_url(session, url):
    """异步请求一个URL并返回结果"""
    start_time = time.time()
    # async with 也是一种 awaitable 对象
    async with session.get(url) as response:
        # 在等待响应体时，让出 CPU
        await response.text()
        response_time = time.time() - start_time
        return f"{url} 耗时 {response_time:.2f}秒"


async def main():
    urls = [
        "https://www.baidu.com",
        "https://www.bing.com",
        "https://www.github.com"
    ]

    async with aiohttp.ClientSession() as session:
        # 并发请求：总耗时约为单个最慢请求的时间
        print("\n--- 并发请求 ---")
        start_time = time.time()
        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        for result in results:
            print(result)
        print(f"并发总耗时: {time.time() - start_time:.2f}秒")


if __name__ == "__main__":
    asyncio.run(main())
