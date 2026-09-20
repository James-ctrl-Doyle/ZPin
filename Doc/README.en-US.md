[简体中文](../README.md) | English

![banner](./banner.png)

**ScreenCapture** A powerful and lightweight Windows screenshot tool.

## Features

- Screenshot, drawing annotations, scrolling screenshot (long screenshot), screen recording (GIF/MP4), text recognition (OCR, recognized automatically after pasting an image — drag to select text and copy it), QR code recognition.
- Color picker, supports shortcut keys to copy RGB color (`Ctrl+R`), HEX color (`Ctrl+H`) and CMYK color (`Ctrl+K`).
- Draw ellipses, perfect circles (hold `Shift`), rectangles, squares (hold `Shift`), arrows, numbered labels, etc.
- Draw curves, straight lines (hold `Shift`), mosaic, eraser, text.
- Modify or delete drawn elements at any time (hover the mouse over an element).
- Undo (`Ctrl+Z`), redo (`Ctrl+Y`), save to file (`Ctrl+S`), save to clipboard (`Ctrl+C` or double-click).
- Fast performance with low memory usage.
- Small size, a single executable file, no installation required, does not depend on any dynamic link libraries.
- Supports a variety of command-line arguments for launching a specified function directly.
- Supports one-time execution mode (the process will not remain resident in the system).
- Multi-language support.

## Download

[Release](https://github.com/James-ctrl-Doyle/ScreenCapture/releases/) (1MB)

## Supported Operating Systems

- Windows 10 1803 or Later

## Compilation

- The main branch depends on the [Ling](https://github.com/xland/Ling) GUI framework.
- The project can be compiled with Visual Studio 2026 (installed with the C++ Desktop Development Kit).

## Command Line

```
// Terminate the process immediately after the capture is finished.
> ScreenCapture.exe --auto-quit=true

// Skip the toolbar once the region is selected and go straight into the specified feature:
// long = scrolling capture (long screenshot)
> ScreenCapture.exe --enter=long
// video = screen recording
> ScreenCapture.exe --enter=video
// ocr = text recognition
> ScreenCapture.exe --enter=ocr
// qr = QR code recognition
> ScreenCapture.exe --enter=qr

// The two arguments can be combined, for example: no tray icon, and the process quits right after the long screenshot is taken.
> ScreenCapture.exe --enter=long --auto-quit=true
```

## Text Recognition (OCR)

Text recognition uses the OCR engine built into Windows. The size of the main program does not change, and no external plugin is needed.

How to use: press `F3` to paste the image from the clipboard onto the screen. The text in the image is recognized automatically and highlighted in light blue. Drag with the left mouse button to select text (or double-click to select a single word), then press `Ctrl+C` to copy the selection. Inside the text layer a double-click means "select this word" instead of copying the whole image as usual.

The "Text Recognition" button on the screenshot toolbar takes the same path: it pastes the selection into a pinned image window and recognizes it automatically.

Recognition requires an OCR language pack to be installed. If you are told that no language pack is available, open Settings → Time & language → Language & region, choose your language, open its language options and install "Optical character recognition".

## Credits and License

This project is a fork of [xland/ScreenCapture](https://github.com/xland/ScreenCapture), released under the MIT License - see [LICENSE](../LICENSE).
Thanks to the original author [xland](https://github.com/xland).

Third-party components bundled in this repository:

| Component | Location | License |
|---|---|---|
| [Ling](https://github.com/xland/Ling) GUI framework | `ext/Ling` | MIT, (c) 2025 liulun |
| [Yoga](https://github.com/facebook/yoga) layout engine (bundled with Ling) | `ext/Ling/yoga` | MIT, (c) Meta Platforms, Inc. |
| [quirc](https://github.com/dlbeer/quirc) QR code decoder | `Src/quirc` | ISC, (c) 2010-2012 Daniel Beer |

All other dependencies (Direct2D / DirectWrite / DXGI, WIC, Media Foundation, Windows.Media.Ocr, Shell API) ship with Windows and need no redistribution.

See [CHANGELOG.md](../CHANGELOG.md) for the changes relative to upstream.
