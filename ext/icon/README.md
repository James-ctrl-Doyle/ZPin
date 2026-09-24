# ZPin 图标

这个目录放着 ZPin 图标的**设计源与生成工具**。程序真正加载的成品在
`Src/Res/logo.ico`（`Resource.rc` 里那句 `1 ICON "logo.ico"`）。

（2026-09-25 从工作区的 `assets/icon-z/` 挪进来，并按本项目的规矩整理了依赖与忽略规则。）

## 设计

圆角方块底，左半红、右半蓝**硬分割**；白色字母 Z 居中、骑在中缝上。
配色不是另外定的 —— 从 ZPin 原来的 logo 采样：红 `#FE7974`、蓝 `#6AAFFD`。

## 改图标

**`design.py` 是唯一真源。** 要调形状、配色、比例就改它，然后：

```bash
python build.py
```

链路是：`design.py` 出 SVG 文本 → `render_all.js`（resvg）栅格化成 8 档 PNG
→ Pillow 打包多尺寸 ICO → 拼三张对比预览图。

⚠ 小尺寸不是简单地缩：`<32px` 的 16/24 用 **`z-icon-small.svg`**（笔画是单独加粗过的），
直接拿 1024 的设计稿缩到 16px 笔画只剩 2px，看不清。这一对 SVG 由 `design.py`
一份模板参数化产出，别手写两份。

## 文件

| 文件 | 作用 | 进仓库 |
|---|---|---|
| `design.py` | **唯一真源**：参数化 SVG 模板 | ✅ |
| `build.py` | 驱动整条链路（生成 → 栅格化 → 打包 → 预览） | ✅ |
| `render_all.js` | SVG → PNG（resvg），按 `_tasks.json` 批量渲 | ✅ |
| `verify.py` | 校验产物（alpha 覆盖率等） | ✅ |
| `z-icon.svg` | 大尺寸用（≥32px） | ✅ |
| `z-icon-small.svg` | 小尺寸专用（<32px，笔画加粗） | ✅ |
| `z-icon.ico` | 成品 ICO，7 档（16/24/32/48/64/128/256） | ✅ |
| `png/` | 8 档中间 PNG（16～512） | ❌ 可重建 |
| `preview-{light,dark,small-zoom}.png` | 三张对比预览，人眼复核用 | ❌ 可重建 |
| `_tasks.json` | 栅格化作业单，里面写死本机绝对路径 | ❌ 每次重建 |

忽略规则写在仓库根的 `.gitignore`。

## 依赖（都装在项目内，不依赖环境）

- **Python + Pillow**：Pillow 在 `ext/build/.pylibs`，`build.py` 自己挂进 `sys.path`。
  装法：`python -m pip install --target ext/build/.pylibs pillow`
- **Node + @resvg/resvg-js**：在 `ext/build/node_modules`，两个包都要 ——
  `resvg-js` 是主包，**`resvg-js-win32-x64-msvc` 才是真正的二进制**。
  ⚠ 目录名必须是标准的 `node_modules`：resvg 的 `js-binding.js` 靠 Node 的模块解析
  去找那个平台包，写成 `.node_modules` 就找不到了（Python 那边的 `.pylibs` 能用点前缀，
  是因为它由 `sys.path` 显式挂载，不走解析）。

两个路径都由 `build.py` / `render_all.js` 自己算，不依赖环境变量。

## 同步到程序

`build.py` 只写本目录，改完要把成品拷过去：

```bash
cp ext/icon/z-icon.ico Src/Res/logo.ico
```

（`Src/Res/logo.ico` 进仓库 —— 编译要用它。它是 `z-icon.ico` 的副本。）
