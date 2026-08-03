"""主程序：A、B、以及 main 自己，三方都 import 同一个 config_mod"""
print("========== main 开始，准备 import ==========")

import config_mod      # 第 1 处 import
import module_a        # module_a 内部又 import config_mod
import module_b        # module_b 内部又 import config_mod

print("\n========== 三个模块各自取 config ==========")
cfg_main = config_mod.get_config()   # main 直接取
cfg_a = module_a.get_from_a()        # 通过 A 取
cfg_b = module_b.get_from_b()        # 通过 B 取

print("\n========== 对比 id ==========")
print("main 里的 config id:", id(cfg_main))
print("A    里的 config id:", id(cfg_a))
print("B    里的 config id:", id(cfg_b))
print("三者是否同一个对象 ?", cfg_main is cfg_a is cfg_b)

print("\n========== 验证模块对象本身也是同一个 ==========")
import sys
print("config_mod in sys.modules ?", "config_mod" in sys.modules)
print("main 的 config_mod  id:", id(config_mod))
print("A 引用的 config_mod id:", id(test.singleton_pkg.config_mod))
print("B 引用的 config_mod id:", id(test.singleton_pkg.module_b.config_mod))
print("模块对象是否同一个  ?", config_mod is test.singleton_pkg.config_mod is test.singleton_pkg.module_b.config_mod)

print("\n========== 跨模块改一处，其它地方都能看到 ==========")
cfg_main.data["key"] = "set-by-main"
print("A 看到的 data:", module_a.get_from_a().data)
print("B 看到的 data:", module_b.get_from_b().data)
