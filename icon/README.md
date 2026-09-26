# ZPin 图标

这个目录放着 ZPin 图标的**设计源与生成工具**。

程序的图标来自 **`Doc/logo.ico`**（`Src/Res/Resource.rc` 里写的是
`1 ICON "..\..\Doc\logo.ico"`）—— 成品统一放在 `Doc/` 下，由这里的 `build.py`
生成并发布过去。

（2026-09-25 从工作区的 `assets/icon-z/` 挪进来，并按本项目的规矩整理了依赖、输出目录与忽略规则。）

## 设计

**两套变体**（设置-通用"图标"里二选一，托盘用）：

- **彩色版**（`z-icon`）：圆角方块底，左半红、右半蓝**硬分割**；白色字母 Z 居中、骑在中缝上。
- **简洁版**（`z-icon-simple`）：红蓝底整个透明，只留白色 Z。

配色不是另外定的 —— 从 ZPin 原来的 logo 采样：红 `#FE7974`、蓝 `#6AAFFD`。

产物落 `Doc/` 两份：`logo.ico`（彩色，资源 ID 1，exe 本体与默认托盘）、
`logo-simple.ico`（简洁，资源 ID 2，设置里选"简洁版"时托盘用它）。

## 改图标

**`design.py` 是唯一真源。** 要调形状、配色、比例就改它，然后：

```bash
python build.py
```

一次跑完四步：

```
[rasterize]  design.py 出 SVG → render_all.js（resvg）栅格化成 8 档 PNG
[pack ico]   打包多尺寸 ICO（16/24/32/48/64/128/256）
[preview]    拼三张对比预览图（浅底 / 深底 / 小尺寸像素放大）
[publish]    成品送到 Doc/：logo.png（512 设计稿）+ logo.ico
```

⚠ 小尺寸不是简单地缩：`<32px` 的 16/24 用 **`z-icon-small.svg`**（笔画单独加粗过），
直接拿 512 的设计稿缩到 16px 笔画只剩 2px，看不清。这一对 SVG 由 `design.py`
一份模板参数化产出，别手写两份。

## 文件

| 文件 | 作用 | 进仓库 |
|---|---|---|
| `design.py` | **唯一真源**：参数化 SVG 模板 | ✅ |
| `build.py` | 驱动整条链路 + 发布到 `Doc/` | ✅ |
| `render_all.js` | SVG → PNG（resvg），按 `_tasks.json` 批量渲 | ✅ |
| `verify.py` | 校验产物（alpha 覆盖率等） | ✅ |
| `_review/` | 全部过程产物：8 档 PNG、ICO、两个 SVG、三张预览图 | ❌ 可重建 |
| `_tasks.json` | 栅格化作业单，里面写死本机绝对路径 | ❌ 每次重建 |

**`_review/` 取"复核用"的意思** —— 预览图是给人看的，PNG/ICO/SVG 都是中间产物，
`python build.py` 一条命令就能全部重建，所以整目录排除（见仓库根 `.gitignore`）。

真正进仓库的图标产物只有 `Doc/` 下那两个：

| 产物 | 内容 | 谁在用 |
|---|---|---|
| `Doc/logo.png` | 512×512 设计稿 | 文档 / 页面引用 |
| `Doc/logo.ico` | 7 档 ICO | **`Resource.rc` 编译进 exe** |

## 依赖（都装在项目内，不依赖环境）

- **Python + Pillow**：Pillow 在 `ext/build/.pylibs`，`build.py` 自己挂进 `sys.path`。
  装法：`python -m pip install --target ext/build/.pylibs pillow`
- **Node + @resvg/resvg-js**：在 `ext/build/node_modules`，两个包都要 ——
  `resvg-js` 是主包，**`resvg-js-win32-x64-msvc` 才是真正的二进制**。
  ⚠ 目录名必须是标准的 `node_modules`：resvg 的 `js-binding.js` 靠 Node 的模块解析
  去找那个平台包，写成 `.node_modules` 就找不到了（Python 那边的 `.pylibs` 能用点前缀，
  是因为它由 `sys.path` 显式挂载、不走解析）。

两个路径都由 `build.py` / `render_all.js` 自己算，不依赖环境变量。

## 为什么 RC 指向 .ico 而不是 .png

`Resource.rc` 的 `ICON` 语句**只认 ICO 格式**，喂 png 会编译失败。
所以 `Doc/` 下同时放两份：`logo.png` 给人看、给文档用，`logo.ico` 给编译器用。
（`Src/Res/Resource.rc` 里写的是 `..\..\Doc\logo.ico` —— RC 的相对路径是相对
`.rc` 文件自己所在目录算的。）
