r"""Z 图标设计源 —— 生成 SVG 文本。

设计：圆角方块底，左半红、右半蓝硬分割；字母 Z 居中，白色骑在中缝上。

配色不是新定的，取自现有 ZPin logo（Doc/logo.png 采样）：
   红 #FE7974   蓝 #6AAFFD
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = 'z-icon'

RED, BLUE = '#FE7974', '#6AAFFD'
RED_HI, RED_LO = '#FF8B85', '#F2635D'
BLUE_HI, BLUE_LO = '#7DBAFF', '#4C91ED'

# Z 的骨架：上横 -> 斜 -> 下横。stroke 用圆头圆角。
#
# 居中怎么算的：stroke-linecap="round" 会让端点向外扩出 stroke-width/2，
# 所以视觉外框是「骨架坐标 ∓ 笔宽/2」，不是骨架本身。
# 按 STROKE_NORMAL=126（外扩 63）算，外框 x 259..765 / y 239..785，
# 中心正好落在 512,512。改笔宽时这个外框会变，得重新配平。
Z_PATH = 'M322 302 H702 L322 722 H702'
STROKE_NORMAL = 126

# 小尺寸光学修正：同样的骨架，笔画加粗。
# 126/1024 缩到 16px 只剩 2px，糊成一团；加到 154 后约 2.4px 才认得出来。
STROKE_SMALL = 154
SMALL_THRESHOLD = 32   # 渲染尺寸 < 该值就用 small 变体

VIEW = 1024
RADIUS = 208


def build_svg(small=False):
    sw = STROKE_SMALL if small else STROKE_NORMAL
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"
     viewBox="0 0 1024 1024">
  <defs>
    <clipPath id="p-clip">
      <rect x="0" y="0" width="1024" height="1024" rx="208" ry="208"/>
    </clipPath>
    <linearGradient id="p-red" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{RED_HI}"/><stop offset="1" stop-color="{RED_LO}"/>
    </linearGradient>
    <linearGradient id="p-blue" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BLUE_HI}"/><stop offset="1" stop-color="{BLUE_LO}"/>
    </linearGradient>
  </defs>

  <g clip-path="url(#p-clip)">
    <rect x="0" y="0" width="512" height="1024" fill="url(#p-red)"/>
    <rect x="512" y="0" width="512" height="1024" fill="url(#p-blue)"/>
  </g>

  <path d="{Z_PATH}" fill="none" stroke="#FFFFFF" stroke-width="{sw}"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''


def main():
    for small, suffix in ((False, ''), (True, '-small')):
        p = os.path.join(ROOT, f'{NAME}{suffix}.svg')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(build_svg(small))
        print('wrote', p)


if __name__ == '__main__':
    main()
