from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot.plugin import on_command, on_regex, on_command, on_keyword
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters.onebot.v11 import Bot, Event, PrivateMessageEvent
from nonebot.exception import ActionFailed, FinishedException, FinishedException
import re
import time
import urllib.parse
import requests
import json
import httpx
import asyncio
import subprocess
import os
import subprocess
import signal
from PIL import Image
import base64 as base64tool
import io
from .config import Config
from .fuzzymatch import match_id, is_pure_alpha
from .playernamecard import render_player_namecard

from plugins.common import autoWrapMessage, callSFImg, callSfVLM, limiter
from plugins.xqm_connector import call_hachibot


def parse_7s_args(args_text: str, default_version: str = "latest"):
    tokens, params = (
        args_text.split(),
        {"debug": False, "language": "CHS", "version": default_version, "query": ""},
    )
    for token in tokens:
        t = token.lower()
        if t == "d":
            params["debug"] = True
        elif t == "en":
            params["language"] = "EN"
        elif t.startswith("v"):
            # vA.B.C 格式，每个都是单个数字
            # v46 -> v4.6.0, v4.6 -> v4.6.0, v4.6.0 -> v4.6.0
            m = re.match(r"^v(\d)(\d)$", t)  # v46 格式
            if m:
                params["version"] = f"v{m.group(1)}.{m.group(2)}.0"
            else:
                m = re.match(r"^v(\d)\.(\d)(?:\.(\d))?$", t)  # v4.6 或 v4.6.0 格式
                if m:
                    params["version"] = (
                        f"v{m.group(1)}.{m.group(2)}.{m.group(3) or '0'}"
                    )
        else:
            params["query"] = token
    return params


__plugin_meta__ = PluginMetadata(
    name="gitcg",
    description="",
    usage="",
    config=Config,
)

ladder = on_command("天梯", priority=10)


@ladder.handle()
async def _(bot: Bot, event: Event):
    msg = event.get_message()
    uid = msg.to_rich_text().split()[-1].strip()

    if len(uid) != 9:
        await ladder.finish("请检查uid, 注意空格")
        return

    precheck = True
    try:
        special_dict = {"": 1}
        precheck &= limiter.check("*", "ladder", 3, 5)
        precheck &= limiter.check(event.user_id, "ladder", 5, 3, special_dict)
    except Exception as e:
        print(f"限流检查失败: {e}")
    if not precheck:
        await ladder.finish("限流中，请稍后再试")
        return

    msg = event.get_message()
    uid = msg.to_rich_text().split()[-1].strip()
    global namemap

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                f"https://gi-tcg-ladder-api.guyutongxue.site/{uid}"
            )
            response.raise_for_status()
            data = response.json()
            if data["success"]:
                content = data["data"]
                if content["is_block"]:
                    return await ladder.finish(
                        "该用户疑似已被封禁，无法查询其天梯数据。"
                    )
                page_info = content["page_info"]
                if page_info["is_shield"]:
                    return await ladder.finish(
                        f"{page_info['nickname']}的个人主页设置了查阅权限"
                    )
                # try:
                #     image_buffer = await render_player_namecard(page_info)
                #     result = MessageSegment.image(image_buffer)
                # except:
                ladder_info = page_info["ladder_info"]
                if ladder_info is None:
                    ladder_level_text = "已隐藏"
                    ladder_text = ""
                else:
                    ladder_level = ladder_info["large"]
                    ladder_level_text = ["暂无段位", "黄铜", "星银", "赤金", "影幻"][
                        ladder_level
                    ]
                    if ladder_level == 4:
                        ladder_text = f"-巅峰{page_info['peak_score']}分"
                    elif ladder_level == 0:
                        ladder_text = ""
                    else:
                        ladder_text = "★" * ladder_info["small"]
                rank_num = page_info["rank_num"]
                if rank_num in ["0", ""]:
                    rank_num = "-"
                roles_text = (
                    "\n".join(
                        [
                            f"{role['name'] or next((item['name'] for item in namemap if item['id'] == role['card_id']), role['card_id'])} ♥ {role['proficiency']}"
                            for role in page_info["roles"]
                        ]
                    )
                    or "暂无"
                )
                events_text = (
                    "\n".join(
                        [
                            f"{event['competition_name']} ♛ {event['label'] or event['competition_result']}"
                            for event in page_info["entry_experience"]
                        ]
                    )
                    or "暂无"
                )
                # result = f"{page_info['nickname']}\n{ladder_level_text}{ladder_text}\n天梯积分: {page_info['ladder_score']}分\n==========\n[原神赛事]\n🙏🙏🙏R.I.P.🙏🙏🙏\n2023/05/19~2026/02/09"
                result = f"{page_info['nickname']}\n{ladder_level_text}{ladder_text}\n天梯积分: {page_info['ladder_score']}分"
                ad = ""
                result = result + ad
                return await ladder.finish(result)
            else:
                return await ladder.finish(f"failed: {data['message']}")

    except TypeError as e:
        return await ladder.finish(f"Error: {str(e)}")
    except httpx.RequestError as e:
        return await ladder.finish(f"Error: {str(e)}")


showData = on_command("七圣", aliases={"7s", "7"}, priority=11, block=True)
showData2 = on_command("七圣2", aliases={"7s2", "7sb", "7sbeta"}, priority=10)


def load_namemap(file: str = "NameMap.json"):
    repo_path = "/data11/nonebot_plugin_7s_card_img"
    result = subprocess.run(
        ["git", "pull"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=True,
    )
    local_path = f"{repo_path}/map/{file}"
    current_time = time.time()
    mod_time = os.path.getmtime(local_path)
    if current_time - mod_time < 600:
        print(f"获取NameMap成功: Github仓库")
        with open(local_path, "r", encoding="utf-8") as f:
            return json.load(f)

    urls = [
        f"http://raw.githubusercontent.com/piovium/nonebot_plugin_7s_card_img/refs/heads/main/map/{file}",
        f"http://raw.gitmirror.com/piovium/nonebot_plugin_7s_card_img/refs/heads/main/map/{file}",
        f"http://cdn.jsdelivr.net/gh/piovium/nonebot_plugin_7s_card_img@main/map/{file}",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                print(f"获取NameMap成功: {url}")
                return resp.json()
        except Exception as e:
            print(f"远程获取NameMap失败: {e}，尝试下一个源")
    with open(local_path, "r", encoding="utf-8") as f:
        return json.load(f)


namemap = load_namemap()

SPECIAL_IMG_MAP = {
    "银狼": "https://7s-1304005994.cos.ap-singapore.myqcloud.com/银狼v6.png"
}


# 轮询（Round-Robin）尝试多个URL，并在所有尝试失败后发送最后一次错误信息
# 目前上层增加了match校验，预期进来一定是有对应id的
async def fetchImg(
    id: int | None,
    version: str,
    retry: int = 3,
    delay: float = 1.0,
    fallback: str = "",
    lang: str = "CHS",
    debug: bool = False,
):
    if id is None:
        return "不可能输出这个。"
    url = "https://new-card-img-gen.exe.xyz/render"
    try:
        if version == "beta":
            author_name = "测试中内容，请以正式上线为准"
        elif version == "latest":
            author_name = "Piovium Labs"
        else:
            author_name = version
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
            payload = {
                "id": id,
                "version": version,
                "authorImageUrl": "https://7s-1304005994.cos.ap-singapore.myqcloud.com/doubao.png"
                if version == "beta"
                else "https://7s-1304005994.cos.ap-singapore.myqcloud.com/dudubot.png",
                "authorName": author_name,
                "cardbackImage": "UI_Gcg_CardBack_Fonta_04",
                "renderFormat": "jpeg",
                "renderQuality": 0.8,
                "language": lang,
                "debug": debug,
            }
            print(payload)
            response = await client.post(url, json=payload)
            data = response.json()
            if data["success"]:
                img_url: str = data["url"]
                _, base64 = img_url.split(",", 1)
                img = Image.open(io.BytesIO(base64tool.b64decode(base64)))
                _, h = img.size
                if (h < 240) and (version != "beta"):
                    return f'Current game version don\'t have "{fallback}". Did you mean /7s2?'
                return MessageSegment.image(f"base64://{base64}")
            else:
                return f"failed: {response.text}"
    except httpx.RequestError as e:
        print(e)
        return f"Error: {str(e)}"


async def get_room_info(url: str, room_id: int):
    try:
        response = requests.get(f"{url}/api/rooms")
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"请求失败: {e}")
        await showData.send(f"获取房间列表失败：{e}")
        return
    data = response.json()
    for item in data:
        if isinstance(item, dict) and item.get("id") == room_id:
            result = []
            result.append(f"房间号: {room_id}")
            result.append(
                f"观战设置: {'允许观战' if item.get('watchable') else '禁止观战'}"
            )
            players = item.get("players", [])
            for player in players:
                name = f"玩家[{str(player.get('name', '')).strip()}]："
                player_id = player.get("id", "")
                link = f"{url}/rooms/{room_id}?player={player_id}"
                result.extend([name, link])
            await showData.send("\n".join(result))
            return
    await showData.send("未找到{room_id}的房间信息，请检查房间号或服务器是否正确。")
    return


@showData.handle()
async def _(bot: Bot, event: Event):
    parts = str(event.get_message()).split(maxsplit=1)
    p = parse_7s_args(parts[1] if len(parts) > 1 else "", "latest")
    try:
        if not p["query"]:
            await showData.finish("请提供卡牌名称, 注意空格. 如: /7s 可莉")
        result = match_id(p["query"], namemap)
        if not result["matched"]:
            fb = result["fallback"]
            await showData.finish(
                f'"{p["query"]}" not found.'
                if not fb
                else f'"{p["query"]}" is not a valid card name. Are you looking for "'
                + '", "'.join([f[0] for f in fb])
                + '"?'
            )
        seg = await fetchImg(
            id=int(result["query"]),
            version=p["version"],
            fallback=result["fallback"][0][0] if result["fallback"] else "",
            lang=p["language"],
            debug=p["debug"],
        )
        await showData.finish(seg)
    except FinishedException:
        return
    except httpx.HTTPError as e:
        # HTTP异常进行fallback
        print(f"HTTP Error: {e}")
        await showData.send("图片服务暂时不可用，正在为您生成文本回复...")
        hachibot_result = await asyncio.wait_for(
            call_hachibot(
                {
                    "qq": "123456789",
                    "group": "123456789",
                    "msg": f"/op 请输出卡牌[{p['query']}]的信息. 面向玩家,纯文本,不要markdown语法.",
                }
            ),
            timeout=233,
        )
        await showData.finish(hachibot_result)
    except Exception as e:
        # 其他异常只打印不进行fallback
        print(f"Error: {e}")
        await showData.finish(f"等等喵, 可能出错了")


UnderMaintenance = False


@showData2.handle()
async def _(bot: Bot, event: Event):
    global UnderMaintenance, namemap
    protectGroupIds = [
        
    ]
    protectUserIds = []
    adminUser = event.user_id in protectUserIds
    ad = "(背七圣单词，上千星奇域「背英语单词！」)"
    if event.user_id not in protectUserIds and event.group_id not in protectGroupIds:
        await showData2.finish(
            "beta数据限制群/用户使用，若需添加当前群至白名单，请联系嘟嘟可"
        )
    parts = str(event.get_message()).split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""
    if adminUser and args_text == "换班时间":
        UnderMaintenance = not UnderMaintenance
        namemap = load_namemap() if not UnderMaintenance else namemap
        await showData2.finish("开始维护" + ad if UnderMaintenance else "维护完成" + ad)
    if UnderMaintenance and not adminUser:
        await showData2.finish("数据维护中，预计于次日2:00维护完成" + ad)
    if UnderMaintenance and adminUser:
        await showData2.send("有宝宝正在维护数据哦~(诚招卡牌别名维护志愿者)")
    p = parse_7s_args(args_text, "beta")
    if not p["query"]:
        await showData2.finish("请提供卡牌名称, 注意加空格")
    result = match_id(p["query"], namemap)
    if not result["matched"]:
        fb = result["fallback"]
        await showData.finish(
            f'"{p["query"]}" not found.'
            if not fb
            else f'"{p["query"]}" is not a valid card name. Are you looking for "'
            + '", "'.join([f[0] for f in fb])
            + '"?'
        )
    seg = await fetchImg(
        id=int(result["query"]),
        version=p["version"],
        lang=p["language"],
        debug=p["debug"],
    )
    await showData2.finish(seg)


moyu = on_command("摸鱼", aliases={"moyu"}, priority=10)


@moyu.handle()
async def _(bot: Bot, event: Event):
    global UnderMaintenance
    global namemap
    protectGroupIds = []
    if event.group_id in protectGroupIds:
        await showData2.finish("岛国岛国岛")


genshinImage = on_command("原神", aliases={"ys"}, priority=3)


@genshinImage.handle()
async def _(bot: Bot, event: Event):
    try:
        msg = str(event.get_message())
        query = msg.split()[-1].strip()
        if query == "雨酱":
            await genshinImage.finish(
                MessageSegment.image(
                    "https://7s-1304005994.cos.ap-singapore.myqcloud.com/ys-yujiang.jpg"
                )
            )
        image = MessageSegment.image(
            f"https://api.guyutongxue.site/genshin-gelbooru?character={urllib.parse.quote(query)}"
        )
        await showData.finish(image)
    except ActionFailed as e:
        await showData.finish(f"抱歉，{e}")


ciallo_tags = [
    "tenshinranman",
    "noble_works",
    "dracu-riot!",
    "amairo_islenauts",
    "sanoba_witch",
    "senren_banka",
    "riddle_joker",
    "cafe_stella_to_shinigami_no_chou",
    "tenshi_souzou_re-boot!",
    "limelight_lemonade_jam",
]

ciallo = on_keyword(["ciallo", "Ciallo"], block=False)


@ciallo.handle()
async def _(event: Event):
    group_id = getattr(event, "group_id", None)
    if group_id:
        if not limiter.check("ciallo_group", str(group_id), 1, 1):
            return
    else:
        if not limiter.check("*", "ciallo", 1, 1):
            return
    try:
        tag = random.choice(ciallo_tags)
        await ciallo.finish(
            MessageSegment.image(
                f"https://api.guyutongxue.site/gelbooru/?tags={urllib.parse.quote(tag)}"
            )
        )
    except ActionFailed as e:
        None


gelbooru = on_command("gelbooru", priority=10)
gelbooru_tag_search = on_command("gelbooru:tag_search", priority=11)


@gelbooru.handle()
async def _(bot: Bot, event: Event):
    if not limiter.check("*", "gelbooru", 1, 4):
        await gelbooru.finish("冷却中，请稍后再试")
        return
    try:
        msg = str(event.get_message())
        query = " ".join(msg.split()[1:])
        await gelbooru.finish(
            MessageSegment.image(
                f"https://api.guyutongxue.site/gelbooru/?tags={urllib.parse.quote(query)}"
            )
        )
    except ActionFailed as e:
        await gelbooru.finish(f"抱歉，{e}")


@gelbooru_tag_search.handle()
async def _(bot: Bot, event: Event):
    msg = str(event.get_message()).split(" ")
    if len(msg) != 2:
        await gelbooru_tag_search.finish(
            'Usage: /gelbooru:tag_search <name_pattern>\n\n<name_pattern>: Tag name that can includes "%" as wildcard character.'
        )
        return
    response = requests.get(
        f"https://api.guyutongxue.site/gelbooru/tags?pattern={urllib.parse.quote(msg[1])}"
    )
    if response.status_code == 200:
        await gelbooru_tag_search.finish(MessageSegment.text(str(response.json())))
    else:
        await gelbooru_tag_search.finish(f"Error: {response.status_code}")


import subprocess
import threading


def run_process_with_timeout(executable, args, timeout):
    def target():
        nonlocal result, error
        try:
            completed_process = subprocess.run(
                [executable] + args, capture_output=True, text=True, check=True
            )
            result = completed_process.stdout
            error = None
        except subprocess.CalledProcessError as e:
            result = None
            error = e.stderr

    result = None
    error = None
    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        return f"Process exceeded timeout of {timeout} seconds"

    if error:
        return error
    return result


def truncate_string(input_string, max_length):
    if len(input_string) <= max_length:
        return input_string
    return input_string[:max_length] + "..."


node = on_command("js", priority=10)

import random


@node.handle()
async def _(bot: Bot, event: Event):
    message = event.get_message().extract_plain_text()[3:]
    is_danger = "pid" in message or "process" in message
    if is_danger or event.user_id in []:
        await node.finish("👆坏人哦(此条拜xqm所赐)")
        return
    is_esm = "import" in message or "export" in message
    output = run_process_with_timeout(
        "node",
        [
            "--experimental-transform-types",
            "--experimental-permission",
            "--no-warnings=ExperimentalWarning",
            "-e" if is_esm else "-p",
            message,
        ],
        120,
    )
    if matches := re.match(
        r"^data:image/[^;]+;base64,([A-Za-z0-9+/=]+)$", output.strip()
    ):
        return await node.finish(MessageSegment.image(f"base64://{matches.group(1)}"))
    await node.finish(truncate_string(output, random.randint(60, 120)), at_sender=True)


rebase = on_command("rebase", priority=10)


@rebase.handle()
async def _(bot: Bot, event: Event):
    if event.user_id not in []:
        return await rebase.finish("no permission")

    response = requests.post(
        "https://api.guyutongxue.site/github-api/repos/piovium/genius-invokation-beta/actions/workflows/rebase_beta.yml/dispatches",
        json={"ref": "beta"},
        headers={
            "Authorization": "Bearer ?",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    return await rebase.finish(
        f"Rebase request sent, status code: {response.status_code}, response: {response.text}"
    )


from plugins.chat_oneapi import wrapMessageForward

yu7s = on_command("yu7s", aliases={"y7s"})

import json
from collections import deque
from typing import List, Dict


def fetch_name_from_api(id: int) -> str:
    url = f"https://beta.assets.gi-tcg.guyutongxue.site/api/v3/data/{id}"
    try:
        data = requests.get(url, timeout=10)
        return data.json().get("name", f"{id} not found")
    except Exception as e:
        return "network error"


def process_dependencies(json_str: str, start_id: int) -> List[str]:
    """处理依赖关系并生成字符串列表"""
    # 解析JSON数据
    items = json.loads(json_str)
    data = {item["id"]: item for item in items}

    # 结果列表
    result = []
    # 待处理队列：(当前ID, 父ID)
    queue = deque([(start_id, None)])
    # 已处理集合，防止循环依赖
    processed = set()

    while queue:
        current_id, parent_id = queue.popleft()

        if current_id in processed:
            continue
        processed.add(current_id)

        item = data.get(current_id)
        if not item:
            continue

        # 获取名称
        name = fetch_name_from_api(current_id)
        # 位置信息
        loc = item["location"]
        location_str = f"{loc['filename']}:{loc['line']},{loc['column']}"

        # 构建条目字符串
        # 第一行显示父ID关系
        entry_lines = []
        if parent_id is None:
            entry_lines.append(f"{current_id}")
        else:
            entry_lines.append(f"child of {parent_id}: {current_id}")

        # 添加详细信息
        entry_lines.append(f"id: {current_id}")
        entry_lines.append(f"name: {name}")
        entry_lines.append(f"Location: {location_str}")
        entry_lines.append(f"dependencies: {item['dependencies']}")
        entry_lines.append("code:")
        # 格式化代码块（每行前加4空格）
        for line in item["code"].splitlines():
            entry_lines.append(f"    {line}")

        # 添加到结果
        result.append("\n".join(entry_lines))

        # 将依赖项加入队列
        for dep_id in item["dependencies"]:
            if dep_id not in processed:
                queue.append((dep_id, current_id))

    return result


@yu7s.handle()
async def _(bot: Bot, event: Event):
    msg = str(event.get_message())
    query = msg.split()[-1].strip()
    result = match_id(query, namemap)
    match_query = result["query"]
    try:
        url = "https://gi-tcg.guyutongxue.site/data-code-analyze-result.json"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.text
            result = process_dependencies(data, int(match_query))
            print(result)
            msgs = wrapMessageForward(f"{match_query}", result)
            await bot.call_api(
                "send_group_forward_msg", group_id=event.group_id, messages=msgs
            )
            base_url = "http://localhost:8013/render?q="
            base_url2 = "http://?/render?q="
            await fetchImg([base_url, base_url2], match_query)
    except Exception as e:
        await yu7s.finish(f"{e}")
