r"""体检：每个 PNG 的尺寸、非透明像素占比、中心与四角颜色。"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(
    ROOT, '..', '..', 'projects', 'ZPin', 'ext', 'build', '.pylibs')))

from PIL import Image

bad = []
for name in sorted(os.listdir(os.path.join(ROOT, 'png'))):
    d = os.path.join(ROOT, 'png', name)
    if not os.path.isdir(d):
        continue
    print(f'--- {name}')
    for fn in sorted(os.listdir(d), key=lambda x: int(x.split('.')[0])):
        p = os.path.join(d, fn)
        im = Image.open(p).convert('RGBA')
        hist = im.getchannel('A').histogram()
        opaque = sum(hist[9:]) / (im.width * im.height)
        cx, cy = im.width // 2, im.height // 2
        c = im.getpixel((cx, cy))
        corner = im.getpixel((max(0, im.width // 12), max(0, im.height // 12)))
        flag = '' if opaque > 0.3 else '   <== 内容异常'
        if flag:
            bad.append(f'{name}/{fn}')
        print(f'  {fn:>8s}  {im.width}x{im.height}  opaque={opaque*100:5.1f}%'
              f'  center=#{c[0]:02X}{c[1]:02X}{c[2]:02X}a{c[3]:<3d}'
              f'  corner=#{corner[0]:02X}{corner[1]:02X}{corner[2]:02X}a{corner[3]:<3d}{flag}')

print('\n异常文件:', bad if bad else '无')
