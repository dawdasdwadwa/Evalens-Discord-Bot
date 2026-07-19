"""
Генератор карточки приветствия (в стиле Sapphire Bot).
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = os.path.dirname(os.path.abspath(__file__))  # шрифты лежат рядом с этим файлом

CARD_W, CARD_H = 1200, 800

COLOR_CREAM = (200, 200, 200)       # верхний левый блок (светло-серый)
COLOR_TEAL_LIGHT = (130, 130, 130)  # основная карточка (серый)
COLOR_TEAL_DARK = (80, 80, 80)      # нижний правый блок (тёмно-серый)
COLOR_BADGE_BG = (100, 100, 100, 235)
COLOR_WHITE = (255, 255, 255)
COLOR_TEXT_MUTED = (255, 255, 255, 210)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(FONTS_DIR, name)
    return ImageFont.truetype(path, size)


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((0, 0, size, size), fill=255)
    return mask


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font_path: str, max_width: int, start_size: int, min_size: int = 28):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        w = draw.textlength(text, font=font)
        if w <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, min_size)


async def generate_welcome_card(
    avatar_bytes: bytes,
    username: str,
    member_number: int,
    server_name: str,
) -> io.BytesIO:
    base = Image.new("RGBA", (CARD_W, CARD_H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(base)

    _rounded_rect(draw, (0, 0, 620, 420), 60, COLOR_CREAM)
    _rounded_rect(draw, (560, 320, CARD_W, CARD_H), 60, COLOR_TEAL_DARK)

    margin = 40
    card_box = (margin, margin, CARD_W - margin, CARD_H - margin)
    _rounded_rect(draw, card_box, 70, COLOR_TEAL_LIGHT)

    badge_font = _font("Poppins-SemiBold.ttf", 34)
    badge_text = f"Member #{member_number}"
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

    title_font_path = os.path.join(FONTS_DIR, "Poppins-Bold.ttf")
    title_text = f"Welcome {username}"
    title_font = _fit_text(draw, title_text, title_font_path, CARD_W - 160, 62)
    title_y = ring_y + ring_size + 70
    draw.text((CARD_W / 2, title_y), title_text, font=title_font, fill=COLOR_WHITE, anchor="mm")

    to_font = _font("Poppins-Italic.ttf", 32)
    to_y = title_y + 60
    draw.text((CARD_W / 2, to_y), "to", font=to_font, fill=COLOR_TEXT_MUTED, anchor="mm")

    server_tag = f"#{server_name.lower().replace(' ', '')}"
    server_font_path = os.path.join(FONTS_DIR, "Poppins-Bold.ttf")
    server_font = _fit_text(draw, server_tag, server_font_path, CARD_W - 160, 46)
    server_y = to_y + 60
    draw.text((CARD_W / 2, server_y), server_tag, font=server_font, fill=COLOR_WHITE, anchor="mm")

    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
