"""生成程序图标 assets/app.ico（蓝色圆角卡片 + 放大镜 + 列表）。

用法：python tools/make_icon.py
纯 Pillow 绘制，不依赖外部素材。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "app.ico"

BLUE = (37, 99, 235, 255)
DEEP = (30, 64, 175, 255)
WHITE = (255, 255, 255, 255)
LIGHT = (219, 234, 254, 255)


def draw(size: int) -> Image.Image:
    s = size * 4  # 超采样后缩小，边缘更干净
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(s * 0.06)
    r = int(s * 0.24)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r, fill=BLUE)

    # 左侧三条「记录」条
    bx0, bx1 = int(s * 0.18), int(s * 0.56)
    for i, w in enumerate((0.14, 0.12, 0.10)):
        y = int(s * (0.30 + i * 0.16))
        d.rounded_rectangle(
            [bx0, y, int(bx0 + (bx1 - bx0) * (w / 0.14)), y + int(s * 0.075)],
            radius=int(s * 0.035), fill=WHITE if i == 0 else LIGHT,
        )

    # 右下放大镜
    cx, cy = int(s * 0.615), int(s * 0.61)
    rad = int(s * 0.155)
    ring = int(s * 0.055)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=WHITE, width=ring)
    hx0, hy0 = cx + int(rad * 0.68), cy + int(rad * 0.68)
    d.line([hx0, hy0, int(s * 0.87), int(s * 0.87)], fill=WHITE, width=ring)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 16]
    base = draw(256)
    base.save(OUT, format="ICO", sizes=[(n, n) for n in sizes])
    base.save(OUT.with_suffix(".png"))
    print(f"已生成图标 {OUT}（{OUT.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
