# 把 iconfont.ttf 里所有码点渲染成一张对照图，用来挑新增按钮的图标。
# 不改动项目任何文件，只产出一张 png 供人工确认。
import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path
import os
from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
# 本文件在 <仓库根>/ext/build-support/ 下 —— 往上**两级**才是仓库根
ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))
FONT = os.path.join(ROOT, 'Src', 'Res', 'iconfont.ttf')
# 渲染结果丢进产物区（ext/build/ 已被 .gitignore），别落在源码目录里
OUT = os.path.join(ROOT, 'ext', 'build', 'iconfont_glyphs.png')

# 已经在 ToolMain::btnIds/btnCodes 里用掉的码点（含 WinCap 工具条）
USED = {0xE8E8, 0xE6BC, 0xE603, 0xE776, 0xE601, 0xE6EC, 0xE82E,
        0xE6BE, 0xED85, 0xED8A, 0xE62D, 0xE608, 0xE6AD}

CODES = [0xE600, 0xE601, 0xE602, 0xE603, 0xE604, 0xE605, 0xE607, 0xE608,
         0xE62D, 0xE634, 0xE654, 0xE660, 0xE67B, 0xE682, 0xE687, 0xE688,
         0xE6A2, 0xE6AD, 0xE6BC, 0xE6BE, 0xE6EC, 0xE71E, 0xE73B, 0xE73E,
         0xE776, 0xE82E, 0xE8E8, 0xE97F, 0xED85, 0xED8A]

COLS, CELL = 6, 120
ROWS = (len(CODES) + COLS - 1) // COLS
img = Image.new('RGB', (COLS * CELL, ROWS * CELL), 'white')
d = ImageDraw.Draw(img)
glyph = ImageFont.truetype(FONT, 56)
label = ImageFont.truetype('C:/Windows/Fonts/consola.ttf', 13)

for i, cp in enumerate(CODES):
    cx, cy = (i % COLS) * CELL, (i // COLS) * CELL
    # 用掉的画浅灰，空着的画黑 —— 一眼分出哪些还能挑
    color = (190, 190, 190) if cp in USED else (0, 0, 0)
    d.rectangle([cx, cy, cx + CELL - 1, cy + CELL - 1], outline=(230, 230, 230))
    txt = chr(cp)
    box = d.textbbox((0, 0), txt, font=glyph)
    d.text((cx + (CELL - (box[2] - box[0])) / 2 - box[0],
            cy + 28 - (box[3] - box[1]) / 2 - box[1]), txt, font=glyph, fill=color)
    tag = 'USED' if cp in USED else 'free'
    d.text((cx + 6, cy + CELL - 34), 'U+%04X' % cp, font=label, fill=(60, 60, 60))
    d.text((cx + 6, cy + CELL - 18), tag, font=label,
           fill=(200, 60, 60) if cp in USED else (20, 130, 60))

img.save(OUT)
print('saved', OUT, img.size)
