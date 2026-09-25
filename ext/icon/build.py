r"""图标构建：SVG 设计稿 -> 各尺寸 PNG -> 多尺寸 ICO -> 对比预览图。

链路：design.py 生成 SVG 文本 -> render_all.js（resvg）栅格化 -> Pillow 打包/拼图。
用法：python build.py

⚠ 本目录从工作区的 assets/icon-z/ 挪进 ext/icon/ 之后，下面两处路径跟着改过：
  - Pillow 挂在 ext/build/.pylibs（ZPin 的统一做法，见 ext/build-support/_pylibs.py），
    从 ext/icon/ 往上两级就到 ext/；
  - resvg 的 node_modules 也从工作区外的 .workbuddy 挪进了 ext/build/.node_modules
    （项目风格：依赖一律装在 ext/build 下，那目录整个被 gitignore）。
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
# ext/icon → ext → 拼 build/.pylibs
sys.path.insert(0, os.path.normpath(os.path.join(ROOT, '..', 'build', '.pylibs')))

import design

from PIL import Image, ImageDraw, ImageFont

NODE = r'C:\Users\zqw35\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'
RENDER_JS = os.path.join(ROOT, 'render_all.js')
TASKS = os.path.join(ROOT, '_tasks.json')

# 两套变体：(图标名, 是否简洁版, 完整性检查的非透明占比下限)。
# 简洁版没有底色（透明底 + 白 Z），非透明占比天然很低，不能用彩色版的 0.9 那条线
VARIANTS = [
    (design.NAME, False, 0.9),
    (design.SIMPLE_NAME, True, 0.02),
]
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# 所有产物都写进 ext/icon/_review/（扁平，不再套一层以图标名命名的子目录 ——
# 目录里本来就只有这套图标）。这个目录整体被 gitignore：里面的东西都能重建，
# 真正要进仓库的成品由 publish() 送到 Doc/ 下（见文件末尾）。
OUT = os.path.join(ROOT, '_review')

# 成品送去的地方：Doc/ 下这些是**编译/文档真正会用**的文件（Resource.rc 的
# `1 ICON` 指向 logo.ico、`2 ICON` 指向 logo-simple.ico），所以必须进仓库；
# ext/icon/_review/ 里的同名文件只是过程产物
DOC = os.path.normpath(os.path.join(ROOT, '..', '..', 'Doc'))

FONT = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 22)
FONT_S = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 15)


def rasterize(jobs):
    """jobs: [(svg_path, out_png, size)]，一次 node 进程全部渲完。"""
    with open(TASKS, 'w', encoding='utf-8') as f:
        json.dump([{'svg': s, 'out': o, 'size': n} for s, o, n in jobs], f)
    r = subprocess.run([NODE, RENDER_JS, TASKS], capture_output=True, text=True)
    print('   ', (r.stdout or r.stderr).strip()[:200])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:800])


def check(im, size, path, min_opaque=0.9):
    """抓「渲染没画完」——光看文件存在会把空白图静默打进 ICO。
    圆角方块只挖掉四个角，正常非透明像素占比 ~96%。"""
    hist = im.getchannel('A').histogram()
    opaque = sum(hist[9:]) / (size * size)   # alpha > 8 的像素占比
    if opaque < min_opaque:
        raise RuntimeError(f'{path} 内容不完整（非透明 {opaque * 100:.1f}%，'
                           f'期望 >{min_opaque * 100:.0f}%）')
    return im


def build_variants():
    """两套变体 × 大/小两档 SVG，渲染全部尺寸，返回 {name: {size: Image}}。"""
    svg_paths, jobs, out = {}, [], {}
    os.makedirs(OUT, exist_ok=True)
    for name, simple, _ in VARIANTS:
        out[name] = {}
        for small, suffix in ((False, ''), (True, '-small')):
            p = os.path.join(OUT, f'{name}{suffix}.svg')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(design.build_svg(small, simple))
            svg_paths[(name, small)] = p
        for s in SIZES:
            small = s < design.SMALL_THRESHOLD
            o = os.path.join(OUT, f'{name}-{s}.png')
            jobs.append((svg_paths[(name, small)], o, s))
            out[name][s] = o

    rasterize(jobs)

    imgs = {}
    for name, _, min_opaque in VARIANTS:
        imgs[name] = {}
        for s in SIZES:
            p = out[name][s]
            im = Image.open(p).convert('RGBA')
            if im.size != (s, s):
                raise RuntimeError(f'{p} 尺寸不对 {im.size}')
            imgs[name][s] = check(im, s, p, min_opaque)
        print(f'  {name}: {len(SIZES)} 档 PNG ok')
    return imgs


def pack_ico(name, imgs):
    path = os.path.join(OUT, f'{name}.ico')
    imgs[256].save(path, format='ICO',
                   append_images=[imgs[s] for s in ICO_SIZES if s != 256],
                   sizes=[(s, s) for s in ICO_SIZES])
    got = sorted(Image.open(path).ico.sizes())
    ok = got == sorted((s, s) for s in ICO_SIZES)
    print(f'  {os.path.basename(path)}  '
          f'{"OK" if ok else "尺寸不一致"}  {[s[0] for s in got]}')
    if not ok:
        raise RuntimeError(f'{path} 尺寸不全: {got}')
    return path


def preview(all_imgs):
    """3 行（方案）× 各尺寸；浅底深底各一张。"""
    cols = [256, 128, 64, 48, 32, 24, 16]
    pad, gap, label_w = 28, 34, 150
    cell_h = max(cols)
    for theme, bg, fg in (('light', '#F2F4F8', '#20242C'),
                          ('dark', '#1B1E24', '#E8EAF0')):
        W = pad * 2 + label_w + sum(c + gap for c in cols)
        H = pad * 2 + len(VARIANTS) * (cell_h + gap)
        canvas = Image.new('RGBA', (W, H), bg)
        d = ImageDraw.Draw(canvas)
        y = pad
        for name, _, _ in VARIANTS:
            d.text((pad, y + 6), name, fill=fg, font=FONT)
            d.text((pad, y + 34), ' '.join(str(c) for c in cols), fill=fg,
                   font=FONT_S)
            x = pad + label_w
            for c in cols:
                canvas.alpha_composite(all_imgs[name][c], (x, y + (cell_h - c) // 2))
                x += c + gap
            y += cell_h + gap
        p = os.path.join(OUT, f'preview-{theme}.png')
        canvas.convert('RGB').save(p)
        print(f'  {os.path.basename(p)}')


def zoom_small(all_imgs):
    """小尺寸像素放大图，检查 16~48px 的辨识度。"""
    cols = [16, 24, 32, 48]
    Z = 6
    pad, gap, label_w = 26, 40, 150
    cell = cols[-1] * Z + 30
    W = pad * 2 + label_w + sum(c * Z + gap for c in cols)
    H = pad * 2 + len(VARIANTS) * (cell + gap)
    canvas = Image.new('RGBA', (W, H), '#F2F4F8')
    d = ImageDraw.Draw(canvas)
    y = pad
    for name, _, _ in VARIANTS:
        d.text((pad, y + 6), name, fill='#20242C', font=FONT)
        x = pad + label_w
        for c in cols:
            d.text((x, y + 10), f'{c}px', fill='#6B7280', font=FONT_S)
            img = all_imgs[name][c].resize((c * Z, c * Z), Image.NEAREST)
            canvas.alpha_composite(img, (x, y + 40))
            x += c * Z + gap
        y += cell + gap
    p = os.path.join(OUT, 'preview-small-zoom.png')
    canvas.convert('RGB').save(p)
    print(f'  {os.path.basename(p)}')


def publish(name, imgs):
    """把成品送到 Doc/ 下 —— 这些文件是编译/文档真正会用的，必须进仓库。

      Doc/logo.png          512px 彩色设计稿（人看的那份，也供文档引用）
      Doc/logo.ico          多尺寸彩色 ICO，Resource.rc 里 `1 ICON` 指向它
      Doc/logo-simple.ico   简洁版 ICO，`2 ICON` 指向它（设置里选"简洁版"时托盘用）
      Doc/logo-simple.png   简洁版 512 设计稿（文档/预览用）

    ⚠ 这里拷的是 .ico 而不是让 RC 直接用 .png：Windows 的 RC 编译器给 ICON 语句
      只认 ICO 格式，喂 png 会编译失败。（README 里也从没说过能直接吃 png。）
    """
    os.makedirs(DOC, exist_ok=True)
    if name == design.SIMPLE_NAME:
        imgs[512].save(os.path.join(DOC, 'logo-simple.png'))
        ico = os.path.join(DOC, 'logo-simple.ico')
        shutil.copyfile(os.path.join(OUT, f'{name}.ico'), ico)
        print(f'  Doc/logo-simple.png  ({imgs[512].size[0]}x{imgs[512].size[1]})')
        print(f'  Doc/logo-simple.ico  {[s[0] for s in sorted(Image.open(ico).ico.sizes())]}')
        return
    png = os.path.join(DOC, 'logo.png')
    ico = os.path.join(DOC, 'logo.ico')
    imgs[512].save(png)
    shutil.copyfile(os.path.join(OUT, f'{name}.ico'), ico)
    print(f'  Doc/logo.png  ({imgs[512].size[0]}x{imgs[512].size[1]})')
    print(f'  Doc/logo.ico  {[s[0] for s in sorted(Image.open(ico).ico.sizes())]}')


if __name__ == '__main__':
    print('[rasterize]')
    all_imgs = build_variants()
    print('[pack ico]')
    for name, _, _ in VARIANTS:
        pack_ico(name, all_imgs[name])
    print('[preview]')
    preview(all_imgs)
    zoom_small(all_imgs)
    print('[publish -> Doc/]')
    for name, _, _ in VARIANTS:
        publish(name, all_imgs[name])
    print('done.')
