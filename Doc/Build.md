# 编译与依赖

## 目录结构

```
.
├─ Src/                 产品源码（含 quirc 二维码解码、Res 资源）
├─ Lang/                界面语言文件（UTF-16LE + BOM）
├─ Doc/                 文档与图片
├─ ext/Ling/            内置的 Ling GUI 框架（含 yoga 布局引擎）
├─ ext/build-support/   构建脚本 + 运行时回归测试 + 开发小工具
└─ ScreenCapture.slnx   解决方案
```

所有编译产物统一落在 `ext/build/`（已由 `.gitignore` 排除），不会污染源码目录。

## 编译

用 Visual Studio 打开 `ScreenCapture.slnx` 直接编译即可 —— **Ling 框架已经内置在 `ext/Ling`，
不需要再单独准备**。工程里引用的是 `$(SolutionDir)ext\Ling`，相对路径，换机器不用改。

命令行完整重编（含 Ling 与 yoga 从源码重编）：

```bash
bash ext/build-support/rebuild_all.sh
```

脚本会自动：① 用 `ext/build-support/make_build_project.py` 生成构建用的工程副本
`Src/ScreenCapture.build.vcxproj`；② 用 `vswhere` 定位 MSBuild；③ 依次重编 yoga → Ling → ScreenCapture，
日志写到 `ext/build/logs/`。可用环境变量覆盖：`MSBUILD`（MSBuild.exe 路径）、`SC_ROOT`（项目根）。

产物：`ext/build/bin/x64/Release/ScreenCapture.build.exe`

> ⚠ 上面那条命令需要 **Python 3**（只用来生成工程副本，不需要安装任何 Python 包）。
> 没有 Python 的话，用 Visual Studio 打开 `ScreenCapture.slnx` 编译，效果一样。
>
> 为什么要生成副本：不经过 `.slnx` 直接编 `.vcxproj` 时 `$(SolutionDir)` 是空的，
> 工程里的 `$(SolutionDir)ext\Ling` 解析不出来，会报
> `C1083: 无法打开包括文件 "include/Ling.h"`。副本把 Ling 的路径换成绝对路径，
> 并把 `IntDir`/`OutDir` 引到 `ext/build/` 下、不落进仓库。
> 这个副本是本机生成的，**不进仓库** —— 所以每次构建都要重新生成（脚本已经替你做掉了）。

## 依赖

### 链接的系统库

| 库 | 用途 |
|---|---|
| `dwmapi` | DWM 接口：判断窗口是否被 cloaked、取窗口真实边框（截图时按窗口轮廓吸附） |
| `windowsapp` | WinRT，用于 OCR 与图像编解码 |
| `mf` `mfreadwrite` `mfplat` `mfuuid` | Media Foundation，录屏编码 |
| `comctl32` `imm32` `version` `ntdll` `Userenv` | 常规系统库 |

`Yoga.lib` 与 `Ling.lib` 由 `ext/Ling` 现场编译，不是预编译二进制。

### 用到的 Windows 组件

全部是系统自带（要求 Windows 10 1803+），**不需要额外安装或分发任何 DLL**：

- **Direct2D / DirectWrite / D3D11 / DXGI** —— 界面渲染、桌面复制（录屏）
- **WIC** —— PNG 编解码（截图历史、剪贴板）
- **Media Foundation** —— 录屏编码（优先 HEVC，回退 H.264）
- **Windows.Media.Ocr** —— 文字识别。用的是系统自带的 OCR 引擎，**不需要额外的识别插件**
- **Shell API** —— 托盘图标、另存为 / 选文件夹对话框、剪贴板

### 仓库内自带的第三方代码

| 位置 | 组件 | 许可 | 用途 |
|---|---|---|---|
| `Src/quirc/` | [quirc](https://github.com/dlbeer/quirc) 二维码解码 | ISC（© 2010-2012 Daniel Beer） | 二维码识别 |
| `Src/Win/VideoMp4.hpp` | Media Foundation 录屏封装（单头文件） | 文件内**没有版权声明**，随上游仓库带入 —— 建议确认后补上出处 | 录屏出 MP4 |
| `ext/Ling/` | Ling GUI 框架 + [yoga](https://github.com/facebook/yoga) 布局引擎 | Ling 为 MIT（© 2025 liulun），yoga 见 `ext/Ling/yoga/LICENSE` | 界面与布局 |
| `Src/Res/iconfont.ttf` | 工具栏图标字体（30 个字形） | 字体文件内未内嵌许可声明 —— 若来自 iconfont.cn 等站点，商用前建议确认授权 | 工具条图标 |

上游项目自身的许可见仓库根 `LICENSE`。

### 只在开发 / 测试时才需要的

| 依赖 | 用途 |
|---|---|
| Python 3 | 运行 `ext/build-support/runtime_*_test.py` 这组回归测试 |
| [Pillow](https://python-pillow.org/) | 测试里要读屏幕像素、比图。装在 `ext/build/.pylibs`（**不进仓库**）：`python -m pip install --target ext/build/.pylibs pillow`。测试脚本通过同目录的 `_pylibs.py` 挂载它，不依赖环境里的全局包 |
| Visual Studio 2026 | 编译（含 C++ 桌面开发组件与 Windows SDK） |

这些都不影响最终产物的构建与运行 —— 产物是单个 exe，无外部依赖。

## 关于内置的 Ling

Ling 原本是独立仓库（[xland/Ling](https://github.com/xland/Ling)）。本仓库把它内置在 `ext/Ling`，
原因是它只服务于这个项目，内置之后 clone 下来就能编。

- 内置版本：`xland/Ling@b77448ec7e72b1b961d3c6f8f87502d8df72aa5f`
- 内置方式是**直接复制源码**（`src/ include/ yoga/ demo/ doc/` + 工程文件），并去掉了它自己的 `.git`
- `ext/Ling/x64/`（编译产物）由 `ext/Ling/.gitignore` 排除
- 将来要升级 Ling：重新 clone 上游到临时目录，与 `ext/Ling` 对比后手工合并

## 开发脚本

全部集中在 `ext/build-support/`（2026-09-22 从原来的 `_tools/` 收拢过来）。

| 脚本 | 说明 |
|---|---|
| `rebuild_all.sh` | 完整重编（yoga → Ling → ScreenCapture）。构建成功后会另外备一份带版本号的发布件到 `ext/build/release/ScreenCapture_<版本>.exe` |
| `release.sh` | 把发布件发到 GitHub Releases（打 tag + 建 release + 传 exe）。`--dry-run` 只做本地准备。见下 |
| `runtime_*_test.py` | 运行时回归测试（截图、绘图、长图、录屏、二维码、快捷键、历史回溯、设置页、放大镜…）。需要先编出 exe，并用 exe 同目录的 `config.json` 做便携配置；脚本会备份/还原你真实的配置 |
| `_pylibs.py` | 把 `ext/build/.pylibs`（Pillow）挂进 `sys.path`。每个要 `import PIL` 的测试脚本在开头 `import _pylibs` 就行 |
| `_cfg_guard.py` | 测试用便携配置的备份/还原护栏，防止误写真实 `config.json` |
| `scroll_target.py` | 造一个可滚动窗口，供长图测试用 |
| `make_build_project.py` | 生成本机用的构建工程副本（`rebuild_all.sh` 第 0 步会调它） |
| `render_iconfont.py` | 把 `iconfont.ttf` 的字形渲染成对照图（输出到 `ext/build/`），加图标前用来确认码点存在 |
| `fix_lang_eol.py` | 把语言文件统一成 UTF-16LE + BOM + CRLF |
| `check_shortcut_logic.py` | 把 `Setting.cpp` 的快捷键表/迁移/冲突逻辑复刻成 Python，先证明语义正确 |
| `_msvc_env.sh` | 直接调 `cl.exe` 编小工具时的最小环境（不走 MSBuild） |

## 发布

```bash
bash ext/build-support/rebuild_all.sh    # 1. 编出 exe（同时备好带版本号的发布件）
bash ext/build-support/release.sh        # 2. 发到 GitHub Releases
```

`release.sh` 会：从 **exe 自己的版本资源**读版本号（不另外维护一处版本号）→ 复制成
`ext/build/release/ScreenCapture_<版本>.exe` → 从 `CHANGELOG.md` 抽该版本段落当 release 说明
→ 打 tag `v<版本>` 并推送 → 建 release 并把 exe 传上去。

- 发之前**工作区必须干净**（发布件要对得上一个确定的提交），否则直接拒绝。
- 先看要发什么、不碰 GitHub：`bash ext/build-support/release.sh --dry-run`
- 仓库地址从 `git remote` 取，凭据走 `git credential fill`（不落地任何文件）。
- 版本号唯一真源是 `Src/Res/Resource.rc` 的 `VERSIONINFO`。其中 `FILEVERSION` /
  `PRODUCTVERSION` 是 Windows 定点数格式**必须四段**（`2,6,0,0`），而 `StringFileInfo` 里
  的 `FileVersion` / `ProductVersion` 是给人看的字符串，写 `2.6.0` 即可 —— 写四段的话
  资源管理器里会多出一个尾巴。**改版本要同时改这四处。**


