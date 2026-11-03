"""Draws the remote-control icon (icon.ico + icon.png) used by controle_tv.pyw."""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024  # drawn large, then downscaled for smooth edges


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def gradient(size, top, bottom):
    g = Image.new("RGBA", size)
    d = ImageDraw.Draw(g)
    for y in range(size[1]):
        d.line([(0, y), (size[0], y)], fill=lerp(top, bottom, y / size[1]))
    return g


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# background: rounded square, blue -> violet
bg = gradient((S, S), (76, 125, 255, 255), (124, 77, 255, 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=230, fill=255)
img.paste(bg, (0, 0), mask)

# remote body with soft shadow, slightly tilted
body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
bx0, by0, bx1, by1 = 352, 150, 672, 880
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([bx0 + 18, by0 + 30, bx1 + 18, by1 + 30], radius=150, fill=(20, 10, 60, 140))
shadow = shadow.filter(ImageFilter.GaussianBlur(28))
body.alpha_composite(shadow)

shell = gradient((S, S), (40, 44, 58, 255), (22, 24, 32, 255))
smask = Image.new("L", (S, S), 0)
ImageDraw.Draw(smask).rounded_rectangle([bx0, by0, bx1, by1], radius=150, fill=255)
body.paste(shell, (0, 0), smask)
d = ImageDraw.Draw(body)
d.rounded_rectangle([bx0, by0, bx1, by1], radius=150, outline=(255, 255, 255, 40), width=6)

cx = (bx0 + bx1) // 2
# power button
d.ellipse([cx - 34, 215, cx + 34, 283], fill=(229, 72, 77, 255))
# d-pad ring + OK
d.ellipse([cx - 118, 340, cx + 118, 576], fill=(58, 64, 82, 255))
for ang_box in ((cx - 18, 356, cx + 18, 380), (cx - 18, 536, cx + 18, 560), (cx - 102, 440, cx - 78, 476), (cx + 78, 440, cx + 102, 476)):
    d.ellipse(ang_box, fill=(140, 150, 175, 255))
d.ellipse([cx - 56, 402, cx + 56, 514], fill=(76, 125, 255, 255))
# small buttons rows
for row_y in (628, 712):
    for dx in (-80, 0, 80):
        d.rounded_rectangle([cx + dx - 30, row_y, cx + dx + 30, row_y + 44], radius=22, fill=(58, 64, 82, 255))
# volume pill accent
d.rounded_rectangle([cx - 30, 790, cx + 30, 830], radius=20, fill=(61, 214, 140, 255))

body = body.rotate(-18, resample=Image.BICUBIC, center=(S // 2, S // 2))
img.alpha_composite(body)

# keep everything inside the rounded square
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste(img, (0, 0), mask)

final.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon.png"))
final.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
