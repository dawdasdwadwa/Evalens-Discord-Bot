"""
Генератор карточки приветствия (в стиле Sapphire Bot).
"""

import io
import os
import random
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS_DIR = os.path.dirname(os.path.abspath(__file__))  # шрифты лежат рядом с этим файлом

# Poppins не содержит кириллических глифов — русские ники рисовались бы
# "тофу"-квадратами. Rubik поддерживает и латиницу, и кириллицу, поэтому для
# любого текста, где встретилась хотя бы одна русская буква, используем его
# вместо Poppins (полностью для всей строки — так смешанный текст вроде
# "Welcome Иван" выглядит одним шрифтом, а не вперемешку).
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

RUBIK_REGULAR_PATH = os.path.join(FONTS_DIR, "Rubik-Variable.ttf")
RUBIK_ITALIC_PATH = os.path.join(FONTS_DIR, "Rubik-Italic-Variable.ttf")

# Rubik — вариативный шрифт с осью "wght"; эти значения соответствуют
# именованным начертаниям Regular/SemiBold/Bold в исходном файле.
_RUBIK_WEIGHT_VALUES = {"regular": 400, "semibold": 600, "bold": 700}

_POPPINS_FILENAMES = {
    "regular": "Poppins-Regular.ttf",
    "semibold": "Poppins-SemiBold.ttf",
    "bold": "Poppins-Bold.ttf",
}


def _contains_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text))


def _font_for(text: str, weight: str, size: int, italic: bool = False) -> ImageFont.FreeTypeFont:
    """Возвращает шрифт нужного начертания и размера, подобранный под текст:
    Rubik — если в тексте есть кириллица, иначе прежний Poppins."""
    if _contains_cyrillic(text):
        path = RUBIK_ITALIC_PATH if italic else RUBIK_REGULAR_PATH
        font = ImageFont.truetype(path, size)
        try:
            font.set_variation_by_axes([_RUBIK_WEIGHT_VALUES.get(weight, 400)])
        except Exception:
            pass  # если вдруг шрифт не вариативный — используем дефолтное начертание
        return font

    filename = "Poppins-Italic.ttf" if italic else _POPPINS_FILENAMES[weight]
    return ImageFont.truetype(os.path.join(FONTS_DIR, filename), size)

CARD_W, CARD_H = 1200, 800

COLOR_CREAM = (200, 200, 200)       # не используется, оставлено для совместимости
COLOR_TEAL_LIGHT = (130, 130, 130)  # не используется, оставлено для совместимости
COLOR_TEAL_DARK = (80, 80, 80)      # не используется, оставлено для совместимости
COLOR_BADGE_BG = (70, 70, 70, 235)
COLOR_WHITE = (255, 255, 255)
COLOR_TEXT_MUTED = (255, 255, 255, 210)


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((0, 0, size, size), fill=255)
    return mask


def _generate_glow_background(width: int, height: int, seed: int | None = None) -> Image.Image:
    """Чёрный фон со светящимися 'потёками'-штрихами по краям — в стиле
    неонового grunge-эффекта (как на панели верификации). Штрихи разведены
    по краям/углам, а центр слегка затемнён виньеткой, чтобы аватар и текст
    поверх фона оставались хорошо читаемыми."""
    rng = random.Random(seed)
    base = Image.new("RGBA", (width, height), (0, 0, 0, 255))

    corners = [
        (0, 0), (width, 0), (0, height), (width, height),
        (width // 2, 0), (0, height // 2), (width, height // 2), (width // 2, height),
    ]

    # широкий мягкий ореол свечения
    halo_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    halo_draw = ImageDraw.Draw(halo_layer)
    strokes = []
    num_strokes = rng.randint(6, 8)
    for _ in range(num_strokes):
        cx, cy = rng.choice(corners)
        x0 = cx + rng.randint(-80, 80)
        y0 = cy + rng.randint(-80, 80)
        points = [(x0, y0)]
        for _ in range(rng.randint(3, 4)):
            last_x, last_y = points[-1]
            points.append((last_x + rng.randint(-160, 160), last_y + rng.randint(-120, 120)))
        strokes.append(points)
        halo_draw.line(points, fill=(255, 255, 255, 190), width=rng.randint(28, 46), joint="curve")
    halo_layer = halo_layer.filter(ImageFilter.GaussianBlur(36))
    base.alpha_composite(halo_layer)

    # тонкие рваные штрихи поверх ореола — деталь в духе "царапин"
    scratch_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scratch_draw = ImageDraw.Draw(scratch_layer)
    for points in strokes:
        for _ in range(rng.randint(2, 3)):
            jittered = [(x + rng.randint(-12, 12), y + rng.randint(-12, 12)) for x, y in points]
            scratch_draw.line(jittered, fill=(255, 255, 255, rng.randint(110, 170)), width=rng.randint(2, 4), joint="curve")
    scratch_layer = scratch_layer.filter(ImageFilter.GaussianBlur(1.2))
    base.alpha_composite(scratch_layer)

    # виньетка — затемняем центр, чтобы аватар и текст не терялись на фоне
    vignette = Image.new("L", (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    v_draw.ellipse((width * 0.08, height * 0.05, width * 0.92, height * 0.98), fill=90)
    vignette = vignette.filter(ImageFilter.GaussianBlur(120))
    dark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    dark_layer.putalpha(vignette)
    base.alpha_composite(dark_layer)

    return base


def _fit_text(draw: ImageDraw.ImageDraw, text: str, weight: str, max_width: int, start_size: int, min_size: int = 28, italic: bool = False):
    size = start_size
    while size > min_size:
        font = _font_for(text, weight, size, italic=italic)
        w = draw.textlength(text, font=font)
        if w <= max_width:
            return font
        size -= 2
    return _font_for(text, weight, min_size, italic=italic)


async def generate_welcome_card(
    avatar_bytes: bytes,
    username: str,
    member_number: int,
    server_name: str,
) -> io.BytesIO:
    base = _generate_glow_background(CARD_W, CARD_H)
    draw = ImageDraw.Draw(base)

    badge_text = f"Member #{member_number}"
    badge_font = _font_for(badge_text, "semibold", 34)
    text_w = draw.textlength(badge_text, font=badge_font)
    badge_pad_x, badge_pad_y = 42, 20
    badge_w = text_w + badge_pad_x * 2
    badge_h = 34 + badge_pad_y * 2
    badge_x0 = (CARD_W - badge_w) / 2
    badge_y0 = 90
    _rounded_rect(
        draw,
        (badge_x0, badge_y0, badge_x0 + badge_w, badge_y0 + badge_h),
        badge_h / 2,
        COLOR_BADGE_BG,
    )
    draw.text(
        (CARD_W / 2, badge_y0 + badge_h / 2),
        badge_text,
        font=badge_font,
        fill=COLOR_WHITE,
        anchor="mm",
    )

    avatar_size = 300
    avatar_border = 14
    avatar_cy = badge_y0 + badge_h + 40 + avatar_size / 2

    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

    ring_size = avatar_size + avatar_border * 2
    ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse((0, 0, ring_size, ring_size), fill=COLOR_WHITE)

    mask = _circle_mask(avatar_size)
    avatar_circle = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
    avatar_circle.paste(avatar_img, (0, 0), mask)
    ring.paste(avatar_circle, (avatar_border, avatar_border), avatar_circle)

    ring_x = int((CARD_W - ring_size) / 2)
    ring_y = int(avatar_cy - ring_size / 2)
    base.alpha_composite(ring, (ring_x, ring_y))

    title_text = f"Welcome {username}"
    title_font = _fit_text(draw, title_text, "bold", CARD_W - 160, 62)
    title_y = ring_y + ring_size + 70
    draw.text((CARD_W / 2, title_y), title_text, font=title_font, fill=COLOR_WHITE, anchor="mm")

    to_font = _font_for("to", "regular", 32, italic=True)
    to_y = title_y + 60
    draw.text((CARD_W / 2, to_y), "to", font=to_font, fill=COLOR_TEXT_MUTED, anchor="mm")

    server_tag = "#" + server_name.lstrip("#").replace(" ", "")
    server_font = _fit_text(draw, server_tag, "bold", CARD_W - 160, 46)
    server_y = to_y + 60
    draw.text((CARD_W / 2, server_y), server_tag, font=server_font, fill=COLOR_WHITE, anchor="mm")

    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
