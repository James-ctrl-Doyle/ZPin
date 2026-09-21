r"""把本机装的测试依赖（Pillow）挂进 sys.path。

Pillow 装在 `<仓库根>/ext/build/.pylibs`。放在那儿是因为 `ext/build/` 本来就是
构建/测试产物的输出目录（已被 `.gitignore` 排除）—— clone 下来没有它也能编译，
只是跑测试前要装一次：

    python -m pip install --target ext/build/.pylibs pillow

用法：在所有 `from PIL import ...` 之前加一行

    import _pylibs   # noqa: F401

直接运行脚本时 sys.path[0] 就是脚本所在目录，所以能 import 到本模块。

⚠ 历史坑（2026-09-22 收拾的）：
  1. 它原来装在 `_tools/.pylibs`，并把 `_tools` 也牵进了仓库 —— 后来开发脚本
     统一收进 `ext/build-support/`，`_tools` 整个退出仓库，Pillow 一并挪到
     `ext/build/.pylibs`。
  2. 更早的毛病：17 个脚本 import PIL，**只有 4 个挂了路径**，其余十几个全靠
     "环境里恰好有全局 Pillow" 才跑得起来 —— 换台机器就 ModuleNotFoundError。
     现在全部走这一处，不会再漏。
"""
import os
import sys

_PYLIBS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'build', '.pylibs'))

if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
