"""模块 A：独立 import config_mod 并取一次配置"""
import config_mod

print("[module_a] 我也 import 了 config_mod")


def get_from_a():
    cfg = config_mod.get_config()
    return cfg
