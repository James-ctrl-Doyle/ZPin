简体中文 | [English](./Doc/README.en-US.md)

![banner](./Doc/banner.png)

**ScreenCapture** 一个小巧但功能强大的Windows截图工具。

## 特性

- 截图、绘图标注、滚动截图（截长图）、录屏（MP4）、文字识别（OCR，贴图后自动识别，拖选文字即可复制）、二维码识别。
- 取景框（拾色器），支持快捷键复制 RGB 颜色（`Ctrl+R`）、 HEX 颜色（`Ctrl+H`）与 CMYK 颜色（`Ctrl+K`）。
- 选区微调：`W`/`A`/`S`/`D`（等价于方向键）按一下把光标挪 1 个像素，拖框前后都能用，配合取景框把起点 / 终点对准；
  长图、录屏阶段不接管这四个键（留给被录的程序）。
- 绘制椭圆、正圆（按住`Shift`）、矩形、正方形（按住`Shift`）、箭头、标号等。
- 绘制曲线、直线（按住`Shift`）、马赛克、橡皮擦、文本。
- 可以随时修改、删除已绘制的元素（鼠标移到元素上）。
- 撤销（`Ctrl+Z`）、重做（`Ctrl+Y`）、保存为文件（`Ctrl+S`）、保存到剪贴板（`Ctrl+C`或双击）。
- 截图历史：每次截图都会留一份"整屏画面 + 截图框"，用 `,` / `.`（可在设置里改）翻看上一张 / 下一张，
  翻出来的那张可以重新裁、接着标注。保留天数可设，默认 3 天。
- 快速保存：开启后点保存直接落到默认目录（默认"下载"，可改），不再每次弹另存为。
- 选区边框粗细可调，拖到 0 就是不要边框。
- 二维码识别：认出来就静默复制内容、**立刻退出截图状态**，那句"已复制二维码内容"由一个小提示窗在原地继续停留 2 秒；不弹对话框。没认出来则留在原地，方便调整选区重扫。
- 运行速度快、内存占用低。
- 体积小、仅一个可执行文件，无需安装，不依赖任何动态链接库。
- 支持多种命令行参数直接启动指定的功能。
- 支持用完即走（进程不驻留在系统中）。
- 托盘菜单可一键关闭所有全局热键（游戏防误触模式），状态重启后保持。
- 开机自启：设置 → 通用里一键开关（写当前用户的注册表 Run 项）；程序以管理员模式运行时，开机也以管理员身份启动。
- 多语言支持（简体中文、English）。

## 下载

[Release](https://github.com/James-ctrl-Doyle/ScreenCapture/releases/) （1MB）

## 常用功能与问题

- 按住 `Ctrl键` 框选截图区域后，直接进入图像标记窗口（钉图窗口）
- 按住 `Ctrl键` 滚动鼠标滚轮可以放大、缩小图像标记窗口（钉图窗口）
- 长截图拼接不符合预期时，尝试调整截图区域往往能解决问题
- 如手动下载新版本，则必须退出老版本再启动新版本

## 支持的操作系统

- Windows 10 1803 or Later

## 编译

- [Ling](https://github.com/xland/Ling) GUI 框架已经内置在 `ext/Ling`，clone 下来直接用
  Visual Studio 打开 `ScreenCapture.slnx` 就能编译，不需要额外准备依赖。
- 命令行完整重编：`bash ext/build-support/rebuild_all.sh`
- 依赖清单、目录结构、开发脚本说明见 [Doc/Build.md](./Doc/Build.md)。
- [2.4.25（基于D2D）](https://github.com/xland/ScreenCapture/tree/2.4.25)或 [2.3.3（基于Qt）](https://github.com/xland/ScreenCapture/tree/2.3.3_qt)是以前的稳定分支。

## 命令行

```
// 截图完成后即退出进程。
> ScreenCapture.exe --auto-quit=true

// 框选完成后不显示工具条，直接进入指定功能：
// pin 钉图/图像标记
> ScreenCapture.exe --enter=pin
// long 长截图
> ScreenCapture.exe --enter=long
// video 屏幕录制
> ScreenCapture.exe --enter=video
// ocr 文字识别
> ScreenCapture.exe --enter=ocr
// qr 二维码识别
> ScreenCapture.exe --enter=qr
// tray 仅注册托盘图标，不执行任何操作
> ScreenCapture.exe --enter=tray

// 两个参数可以联合使用，比如：不注册托盘图标，截完长图后进程直接退出
> ScreenCapture.exe --enter=long --auto-quit=true
```

## 文字识别

文字识别用的是 Windows 系统自带的 OCR 引擎，主程序体积不变，也不依赖任何外部插件。

用法：按 `F3` 把剪贴板里的图片贴到屏幕上，程序会自动识别图里的文字，并把识别到的位置用淡蓝色标出来；按住左键拖选（或双击选中一个词），再按 `Ctrl+C` 即可复制选中的文字。文字层里双击的语义是"选中这个词"，不会像平时那样把整张图复制走。

截图工具条上的「文字识别」按钮走的是同一条路：把选区贴成一张贴图窗口并自动识别。

识别依赖系统里已安装的 OCR 语言包。如果提示没有可用的语言包，请到「设置 → 时间和语言 → 语言和区域」，找到当前语言点「语言选项」，勾选「光学字符识别」并等它装完。

## 便携能力

程序是纯绿色的：所有数据都在 `ScreenCapture.exe` 同目录下，不在系统里留任何东西（不创建 `%appdata%\ScreenCapture`）。

- **配置**：`config.json`（exe 同目录，首次运行自动生成）
- **临时文件与截图历史**：`temp\` 子目录
  - `temp\last.bin`：最近一次截图（按 `F3` 贴图时读它）
  - `temp\shots\`：截图历史，保留天数可在设置里调整
  - `temp.mp4`：录屏临时文件（下次录屏会覆盖）
- **语言文件**：在 exe 同目录建一个 `Lang` 子目录，把语言文件（`Lang\*.json`）放进去，程序会优先读取它

> 装在 `Program Files` 这类没有写权限的目录下时配置无法写入，程序不会回退到 `%appdata%`，请换一个有写权限的目录。

## 致谢与许可

本项目基于 [xland/ScreenCapture](https://github.com/xland/ScreenCapture) 二次开发，遵循 MIT 许可，详见 [LICENSE](./LICENSE)。
感谢原作者 [xland](https://github.com/xland) 的开源工作。

仓库内自带的第三方组件：

| 组件 | 位置 | 许可 |
|---|---|---|
| [Ling](https://github.com/xland/Ling) GUI 框架 | `ext/Ling` | MIT，© 2025 liulun |
| [Yoga](https://github.com/facebook/yoga) 布局引擎（随 Ling 一同分发） | `ext/Ling/yoga` | MIT，© Meta Platforms, Inc. |
| [quirc](https://github.com/dlbeer/quirc) 二维码解码 | `Src/quirc` | ISC，© 2010-2012 Daniel Beer |

其余依赖（Direct2D / DirectWrite / DXGI、WIC、Media Foundation、Windows.Media.Ocr、Shell API）均为 Windows 系统自带，无需额外分发。

本 fork 相对上游的改动清单见 [CHANGELOG.md](./CHANGELOG.md)。