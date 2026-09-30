import os

# 测试断言沿用中文原文: 固定中文界面, 顺带校验 t() 的中文分支与原文一致。
# 英文界面由 tests/test_i18n.py 在子进程中单独覆盖。
# 必须在导入 dtflow 之前设置 (语言在导入时确定)。
os.environ["DT_LANG"] = "zh"
