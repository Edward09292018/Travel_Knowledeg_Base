"""模块 B：也独立 import config_mod 并取一次配置"""
import config_mod

print("[module_b] 我也 import 了 config_mod")


def get_from_b():
    cfg = config_mod.get_config()
    return cfg
