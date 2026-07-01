import base64
import json
import os
import re
import aiohttp
import asyncio
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageSegment, Message, Bot, Event
from nonebot.params import CommandArg, RegexStr
from nonebot.plugin import PluginMetadata
from nonebot import get_plugin_config

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="gitcg_deck_img",
    description="根据七圣召唤牌组分享码生成牌组图片",
    usage="/deck <分享码>",
    config=Config,
)

config = get_plugin_config(Config)

deck_command = on_command("deck", priority=10, block=True)

# 自动检测 Base64 分享码
base64Event = on_regex(r'[A-Za-z0-9+/]{68,70}={0,2}', block=False)


# --- 1. Base64 解码逻辑 ---

def decode_share_ids(b64_string: str) -> list[int]:
    """
    根据提供的 TypeScript 逻辑，将牌组分享码解码为 33 个 shareId。
    """
    # 确保 Base64 字符串是 URL-safe 的，并进行正确填充
    b64_string = b64_string.replace('-', '+').replace('_', '/')
    missing_padding = len(b64_string) % 4
    if missing_padding:
        b64_string += '=' * (4 - missing_padding)

    try:
        arr_bytes = base64.b64decode(b64_string)
        arr = list(arr_bytes) # 将 bytes 转换为整数列表
    except Exception as e:
        print(f"Base64 解码失败: {e}")
        raise ValueError(f"Base64 解码失败: {e}")

    if len(arr) != 51:
        print(f"解码后的字节长度应为 51，实际为 {len(arr)}")
        raise ValueError(f"解码后的字节长度应为 51，实际为 {len(arr)}")

    last = arr.pop()
    reordered = []

    # 重新排序数组
    for i in range(25):
        reordered.append((arr[2 * i] - last) & 0xff)
    for i in range(25):
        reordered.append((arr[2 * i + 1] - last) & 0xff)
    reordered.append(0)

    # 从3字节块中提取两个12位数字
    result = []
    for i in range(17):
        chunk_start = i * 3
        # 确保索引在范围内
        if chunk_start + 2 >= len(reordered):
             break
        b1, b2, b3 = reordered[chunk_start], reordered[chunk_start + 1], reordered[chunk_start + 2]

        n1 = (b1 << 4) | (b2 >> 4)
        n2 = ((b2 & 0x0f) << 8) | b3
        result.extend([n1, n2])

    result.pop()  # 移除最后一个元素，得到33个ID
    return result


# --- 2. 卡牌数据获取与映射 ---

# 全局缓存 shareId -> id 的映射
SHARE_ID_TO_ID_MAP = None

async def get_card_id_map() -> dict[int, int]:
    """
    异步获取角色卡和行动卡数据，构建并缓存 shareId 到 id 的映射。
    """
    global SHARE_ID_TO_ID_MAP
    if SHARE_ID_TO_ID_MAP:
        return SHARE_ID_TO_ID_MAP

    urls = [
        "https://?/api/v4/data/beta/CHS/characters",
        "https://?/api/v4/data/beta/CHS/action_cards"
    ]
    id_map = {}

    async with aiohttp.ClientSession() as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        for resp in responses:
            if resp.status == 200:
                data = await resp.json()
                if data.get("success"):
                    for item in data.get("data", []):
                        if 'shareId' in item and 'id' in item:
                            # 过滤掉 shareId 为 0 或 None 的情况
                            if item['shareId']:
                                id_map[item['shareId']] = item['id']
            else:
                resp.raise_for_status()

    SHARE_ID_TO_ID_MAP = id_map
    return SHARE_ID_TO_ID_MAP


# --- 3. 图片获取 ---

IMAGE_CACHE_DIR = "image_cache"
if not os.path.exists(IMAGE_CACHE_DIR):
    os.makedirs(IMAGE_CACHE_DIR)

async def fetch_image(session: aiohttp.ClientSession, card_id: int, fallback: Image.Image) -> Image.Image:
    if not card_id or card_id == 0 or str(card_id).strip() in ("", "0"):
        return fallback
    """
    异步获取单个卡牌图片，使用本地文件缓存。
    """
    cache_path = os.path.join(IMAGE_CACHE_DIR, f"{card_id}.png")
    if os.path.exists(cache_path):
        # 确保返回 RGBA 模式的图片副本
        return Image.open(cache_path).convert("RGBA")

    url = f"https://?/api/v4/image/{card_id}?thumbnail=true"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                image_data = await response.read()
                with open(cache_path, "wb") as f:
                    f.write(image_data)
                return Image.open(BytesIO(image_data)).convert("RGBA")
            else:
                # 如果下载失败，返回一个占位图
                print(f"警告：无法下载卡牌图片 ID: {card_id}, 状态码: {response.status}")
                return fallback
    except Exception as e:
        print(f"警告：下载图片时发生错误 ID: {card_id}, 错误: {e}")
        return fallback
def add_padding(img: Image.Image, padding: int = 4) -> Image.Image:
    w, h = img.size
    new_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    new_img.paste(img.resize((w - 2 * padding, h - 2 * padding), Image.Resampling.LANCZOS), (padding, padding))
    return new_img

def apply_frame(base_img: Image.Image, frame: Image.Image) -> Image.Image:
    # 确保两张图为 RGBA 并且尺寸一致后合成，避免 "images do not match" 错误
    base = base_img.convert("RGBA")
    frame_resized = frame.convert("RGBA").resize(base.size, Image.Resampling.LANCZOS)
    return Image.alpha_composite(base, frame_resized)

# --- 4 & 5. 核心逻辑：图片合成与输出 ---

async def generate_deck_image(b64_string: str) -> BytesIO:
    """
    主函数，整合所有步骤生成最终的牌组图片。
    """
    font_path = r"/root/nb/dudubot/fonts/HYWH.ttf"

    placeholder = Image.open("assets/UI_Gcg_DeckShare_ImgEmpty.png").convert("RGBA")
    bg = Image.open("assets/UI_Gcg_DeckShare_PhotoBg.png").convert("RGBA")
    frame_normal = Image.open("assets/UI_Gcg_DeckShare_Frame3.png").convert("RGBA")
    frame_esoteric = Image.open("assets/UI_Gcg_DeckShare_Frame3_Esoteric.png").convert("RGBA")
    # ys = Image.open("assets/ys.png").convert("RGBA")

    # 步骤1 & 2 & 3
    id_map = await get_card_id_map()
    share_ids = decode_share_ids(b64_string)

    placeholder_id = None  # 用于标记占位图
    card_ids = [id_map.get(sid, 0) for sid in share_ids]
    main_cards = [
        cid if cid and len(str(cid)) >= 4 else placeholder_id
        for cid in card_ids[:3]
    ]
    small_cards_valid = [cid for cid in card_ids[3:] if cid and len(str(cid)) >= 6]
    small_cards_invalid = [placeholder_id for cid in card_ids[3:] if not cid or len(str(cid)) < 6]
    # 合并，小图占位图排在末尾
    card_ids = main_cards + sorted(small_cards_valid) + small_cards_invalid

    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_image(session, cid, placeholder.copy()) for cid in card_ids]
        images = await asyncio.gather(*fetch_tasks)

    # 步骤4: 布局与绘制
    # 定义尺寸
    W_LARGE, H_LARGE = 142, 232
    W_SMALL, H_SMALL = 89, 144
    PADDING = 16

    canvas = bg.copy()

    font = ImageFont.truetype(font_path, 28)
    draw = ImageDraw.Draw(canvas)
    text_width = draw.textlength("出战阵容", font=font)
    draw.text(((canvas.width - text_width) / 2, 115), "出战阵容", font=font, fill=(132, 96, 61, 255))
    draw.text(((canvas.width - text_width) / 2, H_LARGE + 190), "出战牌组", font=font, fill=(132, 96, 61, 255))

    # 绘制第一行（3张大图）
    start_x_large = (canvas.width - (3 * W_LARGE + 2 * PADDING)) // 2
    for i in range(3):
        cid = card_ids[i]
        img = images[i].resize((W_LARGE, H_LARGE))

        if cid is not None:
            img = add_padding(img, padding=8)
            frame = frame_esoteric if str(cid).startswith("3300") else frame_normal
            img = apply_frame(img, frame.copy())
        x = start_x_large + i * (W_LARGE + PADDING)
        y = 160
        canvas.alpha_composite(img, (x, y))

    # 绘制后五行（5x6张小图）
    start_y_small_rows = PADDING + H_LARGE + PADDING
    start_x_small = (canvas.width - (6 * W_SMALL + 5 * PADDING)) // 2
    start_y_small = 160 + H_LARGE + 80
    for i in range(3, 33):
        row = (i - 3) // 6
        col = (i - 3) % 6
        cid = card_ids[i]
        img = images[i].resize((W_SMALL, H_SMALL))
        if cid is not None:
            img = add_padding(img, padding=6)
            frame = frame_esoteric if str(cid).startswith("3300") else frame_normal
            img = apply_frame(img, frame.copy())
        x = start_x_small + col * (W_SMALL + PADDING)
        y = start_y_small + row * (H_SMALL + PADDING)
        canvas.alpha_composite(img, (x, y))

    # canvas.alpha_composite(ys.resize((238, 174), Image.Resampling.LANCZOS), (740, 1270))

    # 步骤5: 输出到 Buffer
    buffer = BytesIO()
    canvas.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer


@deck_command.handle()
async def handle_deck_command(bot: Bot, event: Event, args: Message = CommandArg()):
    """处理牌组生成命令"""
    # 获取分享码
    code = args.extract_plain_text().strip()

    if not code:
        return

    try:
        # 生成图片
        image_buffer = await generate_deck_image(code)

        # 发送图片
        await deck_command.finish(MessageSegment.image(image_buffer))
        return

    except ValueError as e:
        await deck_command.finish(f"分享码解析失败：{str(e)}\n请检查分享码是否正确")


@base64Event.handle()
async def handle_base64_event(bot: Bot, event: Event):
    """自动检测并处理 Base64 分享码"""
    # 获取消息文本
    msg = event.get_message()
    txt = msg.extract_plain_text()

    # 使用正则匹配deck code
    match = re.search(r'[A-Za-z0-9+/]{68,70}={0,2}', txt)
    if match is None:
        return

    # 获取匹配到的分享码
    code = match.group(0).strip()

    try:
        # 生成图片
        image_buffer = await generate_deck_image(code)

        # 发送图片
        await base64Event.finish(MessageSegment.image(image_buffer))
        return

    except ValueError as e:
        # 如果解析失败，不阻止其他插件处理
        print(f"分享码解析失败：{str(e)}")