"""被多个模块共享的配置模块。模块级变量 _config 是验证对象。"""

print(f"[config_mod] 模块正在被执行！这行只应该出现一次")

_config = None
_load_count = 0


class Config:
    def __init__(self):
        self.data = {}


def get_config():
    """约定式单例：靠模块级变量 _config 缓存"""
    global _config, _load_count
    if _config is None:
        _load_count += 1
        _config = Config()
        print(f"[config_mod] 真正创建 Config，第 {_load_count} 次")
    return _config
