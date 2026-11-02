"""生成 S4-2 拍照录入的合成验收图（印刷体，非真实拍摄）。

三张图：
  clean     纯净白底题目图
  rotated   旋转 7° + 高斯噪声（模拟手持拍摄）
  answered  带「我的作答」手写体风格文本（用系统字体模拟，不冒充真实笔迹）
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).with_name("mistake_photo")
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
STEM = "1．已知函数 $f(x)=x^{2}-4x+3$。\n（1）求函数的对称轴；\n（2）当 $x\\in[0,3]$ 时，求 $f(x)$ 的最大值与最小值。"
ANSWER = "我的作答：对称轴 x=2；最大值 3，最小值 -1。"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("找不到可用中文字体，请手工指定 FONT_CANDIDATES")


def _draw(text: str, *, answer: bool) -> Image.Image:
    image = Image.new("RGB", (1000, 620), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 60), text, fill="black", font=_font(30), spacing=18)
    if answer:
        draw.multiline_text((60, 380), ANSWER, fill=(30, 60, 160), font=_font(26), spacing=14)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean = _draw(STEM, answer=False)
    clean.save(OUT / "clean.png")
    rotated = clean.rotate(7, resample=Image.BICUBIC, expand=True, fillcolor="white")
    rotated = rotated.filter(ImageFilter.GaussianBlur(0.6))
    rotated.save(OUT / "rotated.png")
    _draw(STEM, answer=True).save(OUT / "answered.png")
    for path in sorted(OUT.glob("*.png")):
        print(path.name, Image.open(path).size)


if __name__ == "__main__":
    main()