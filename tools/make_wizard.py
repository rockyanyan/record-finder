"""生成安装程序用素材：向导大图 WizModernImage.bmp + 小图 WizModernSmallImage.bmp。

Inno Setup 要求 BMP（24 位），大图 164x314，小图 55x55。
用法：python tools/make_wizard.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "installer" / "assets"

BLUE = (37, 99, 235)
DEEP = (29, 78, 216)
LIGHT = (219, 234, 254)
WHITE = (255, 255, 255)


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def big_image() -> Image.Image:
    """左侧竖图：渐变底 + 放大镜图标 + 标题。"""
    w, h = 164, 314
    img = Image.new("RGB", (w, h), BLUE)
    d = ImageDraw.Draw(img)

    # 竖向渐变
    for y in range(h):
        t = y / (h - 1)
        r = int(BLUE[0] + (DEEP[0] - BLUE[0]) * t)
        g = int(BLUE[1] + (DEEP[1] - BLUE[1]) * t)
        b = int(BLUE[2] + (DEEP[2] - BLUE[2]) * t)
        d.line([(0, y), (w, y)], fill=(r, g, b))

    # 底部斜切装饰
    d.polygon([(0, h - 70), (w, h - 110), (w, h), (0, h)], fill=(23, 62, 173))

    # 放大镜
    cx, cy, rad = 82, 108, 34
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=WHITE, width=9)
    d.line([cx + 24, cy + 24, cx + 48, cy + 48], fill=WHITE, width=9)

    # 记录条
    for i in range(3):
        y = 30 + i * 13
        ww = 44 - i * 8
        d.rounded_rectangle([26, y, 26 + ww, y + 7], radius=3, fill=LIGHT)

    # 标题
    f = font(17)
    d.text((76, 178), "记录检索器", font=f, fill=WHITE, anchor="ma")
    f2 = font(10)
    d.text((82, 202), "搜一个词，找到那一行", font=f2, fill=(191, 214, 255), anchor="ma")
    d.text((82, 258), "v1.0.0", font=font(9), fill=(147, 180, 245), anchor="ma")

    return img


def small_image() -> Image.Image:
    """右上角小图：蓝色圆角方块 + 放大镜。"""
    s = 55
    img = Image.new("RGB", (s, s), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, s - 3, s - 3], radius=12, fill=BLUE)
    cx, cy, rad = 24, 23, 11
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=WHITE, width=4)
    d.line([cx + 8, cy + 8, cx + 17, cy + 17], fill=WHITE, width=4)
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    big = big_image()
    big.save(OUT / "WizModernImage.bmp", format="BMP")
    small = small_image()
    small.save(OUT / "WizModernSmallImage.bmp", format="BMP")
    big.save(OUT / "wizard-big.png")
    small.save(OUT / "wizard-small.png")
    for name in ("WizModernImage.bmp", "WizModernSmallImage.bmp"):
        p = OUT / name
        print(f"生成 {p}  ({p.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
