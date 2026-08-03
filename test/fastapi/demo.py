# test/fastapi/demo.py

import asyncio
import time

import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi import HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, \
    StreamingResponse, Response
from pydantic import BaseModel

from tool.logger import logger

# 创建一个 FastAPI 应用实例
app = FastAPI()


# 定义数据模型
class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = None


# POST 请求接收 JSON 数据
@app.post("/items/", summary="类型检查")
async def create_item(item: Item):
    # item 已经是验证过的 Item 对象
    # 如果客户端传来的 price 是字符串 "abc"，FastAPI 会自动报错
    return {"name": item.name, "price": item.price, "is_offer": item.is_offer}


@app.get("/", summary="第一个测试")
async def read_root():
    return {"Hello": "World"}


# 访问 http://127.0.0.1:8000/items/5?q=somequery
# item_id: 路径参数 (自动转为 int)
# q: 查询参数 (可选，默认 None)
@app.get("/items/{item_id}", summary="获取指定参数")
async def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


# 接收? skip=? & limit = ?
@app.get("/items", summary="分页")
async def read_item(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}


# 1、路由处理函数返回一个 Pydantic 模型实例，FastAPI 将自动将其转换为 JSON 格式，并作为响应发送给客户端：
@app.post("/items/return", summary="返回 Pydantic 模型实例")
async def create_item(item: Item):
    return item


# 2、使用 HTTPException 抛出异常，返回自定义的状态码和详细信息。
# 以下实例在 item_id 为 42 会返回 404 状态码：
@app.delete("/items/{item_id}", summary="抛出异常")
async def read_item(item_id: int):
    if item_id == 42:
        raise HTTPException(status_code=404, detail="Item 找不到")
    return {"item_id": item_id}


@app.get("/api/user")
async def get_user():
    # 等价于直接 return {"name": "张三", "age": 20}（FastAPI 自动转 JSONResponse）
    return JSONResponse(
        content={"name": "张三", "age": 20},
        status_code=200,  # 可选，默认 200
        headers={"X-Custom-Header": "custom-value"}  # 可选，自定义响应头
    )


@app.get("/download/excel")
async def download_excel():
    excel_path = "D:/test.xls"
    # 返回文件并指定下载文件名
    return FileResponse(
        path=excel_path,
        filename="月度报表.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.get("/hello")
async def hello(name: str = "游客"):
    html_content = f"""
    <html>
        <body>
            <h1>你好，{name}！</h1>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/text")
async def get_text():
    return PlainTextResponse(content="这是纯文本响应", status_code=200)


@app.get("/old-path")
async def redirect_old_path():
    # 重定向到 /new-path，状态码 307 表示临时重定向
    return RedirectResponse(url="/new-path", status_code=307)


@app.get("/new-path")
async def new_path():
    return {"message": "这是新接口"}


async def generate_stream():
    # 模拟流式输出（逐字返回）
    words = ["你", "好", "，", "这", "是", "流", "式", "响", "应"]
    for word in words:
        await asyncio.sleep(0.5)
        yield word.encode("utf-8")  # 流式输出需返回字节流


@app.get("/stream")
async def stream_response():
    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@app.get("/custom")
async def custom_response():
    # 返回二进制数据，指定自定义 MIME 类型
    return Response(
        content="<h1>纯文本</h1>",
        # media_type="text/text",
        media_type="text/html",
        status_code=200)


@app.get("/simple-async")
async def simple_async():
    return {"message": "Hello"}


# ✅ 同步版本
@app.get("/simple-sync")
def simple_sync():
    return {"message": "Hello"}


# ✅ 正确：异步函数可以用 await
@app.get("/fetch-data")
async def fetch_data():
    # 模拟耗时操作（如查数据库）
    await asyncio.sleep(1)  # 让出CPU
    return {"data": "完成"}


# ❌ 错误：同步函数不能用 await
# @app.get("/fetch-data")
# def fetch_data():  # 少了 async
#     await asyncio.sleep(1)  # SyntaxError!
#     return {"data": "完成"}


# ⚠️ 勉强能用但不好：同步函数做耗时操作会阻塞
@app.get("/fetch-data-bad")
def fetch_data_bad():
    import time
    time.sleep(1)  # 阻塞整个线程
    return {"data": "完成"}


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # 现在很简单
    return {"user_id": user_id}


# 定义一个模拟的耗时任务（方式1）
# ✅ 此处适合 CPU 密集型或阻塞操作
def write_log1(email: str, content: str):
    while True:
        print(f"异步任务正在执行...... 向 {email} 发邮件，内容是：{content}  {time.asctime()}")
        time.sleep(1)  # 模拟耗时操作
    # process_large_file()  # 同步的文件处理
    # run_cpu_heavy_task()  # CPU 计算


# 定义一个模拟的耗时任务（方式2）
# ✅ 此处适合 IO 密集型任务
async def write_log2(email: str, content: str):
    while True:
        print(f"异步任务正在执行...... 向 {email} 发邮件，内容是：{content}  {time.asctime()}")
        await asyncio.sleep(1)  # 模拟耗时操作
    # await send_email_async(email)  # 调用其他异步函数
    # await save_to_db_async(content)  # 异步数据库操作


@app.post("/send-task/{email}")
async def send_task(email: str, background_tasks: BackgroundTasks):
    # 1. 添加任务到后台队列
    background_tasks.add_task(write_log2, email, "你好")

    # 2. 立即返回响应给用户，不需要等待 write_log 执行完毕
    return {"message": "异步任务已启动"}


if __name__ == "__main__":
    """服务启动入口：本地开发环境直接运行"""
    logger.info("File Import Service 服务启动中...")
    # 启动uvicorn服务，绑定本地IP和8000端口，关闭自动重载（生产环境建议用workers多进程）
    uvicorn.run(
        app=app,
        host="127.0.0.1",  # 仅本地访问，生产环境改为0.0.0.0（允许所有IP访问）
        port=8000  # 服务端口
    )
