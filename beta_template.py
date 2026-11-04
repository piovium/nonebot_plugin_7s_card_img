# Cherry_C9H13N created on 2025/5/15
import json
import re
from pathlib import Path
from pypinyin import lazy_pinyin, Style

# ---------------- 工具函数 ----------------

def get_pinyin(text):
    return ''.join(lazy_pinyin(text))

def get_initials(text):
    return ''.join(lazy_pinyin(text, style=Style.FIRST_LETTER))

def extract_refs_from_description(desc):
    return re.findall(r"\$\[C(\d+)\]", desc or "")

def load_json(filename):
    return json.loads(Path(filename).read_text(encoding="utf-8"))

def collect_children(obj, entities, visited_ids=None):
    if visited_ids is None:
        visited_ids = set()

    children = []

    if obj.get("id") in visited_ids:
        return children  # 防止递归死循环
    visited_ids.add(obj.get("id"))

    # 处理 skills
    for skill in obj.get("skills", []):
        if skill.get("hidden", False) is True:
            continue
        children.append({"id": skill["id"], "name": skill["name"]})
        children.extend(collect_children(skill, entities, visited_ids))

    # 处理 rawDescription 引用
    raw_desc = obj.get("rawDescription", "")
    for entity_id in extract_refs_from_description(raw_desc):
        entity = next((e for e in entities if e["id"] == int(entity_id)), None)
        if entity:
            children.append({"id": entity["id"], "name": entity["name"]})
            children.extend(collect_children(entity, entities, visited_ids))

    return children

# ---------------- 主处理逻辑 ----------------

def generate_namemap(characters, actions, entities):
    combined = characters + actions
    output = []

    for item in combined:
        if "GCG_TAG_ADVENTURE_PLACE" not in item.get("tags", []):
            continue

        name = item["name"]
        entry = {
            "id": item["id"],
            "name": name,
            "englishName": item.get("englishName", ""),
            "pinyin": get_pinyin(name),
            "aliases": list({get_initials(name)}),
            "child": collect_children(item, entities)
        }

        if "GCG_TAG_TALENT" not in item.get("tags", []):
            pass
        else:
            tn = "没找到"
            for c in characters:
                if c["id"] == int(str(item["id"])[1:-1]):
                    tn = f"{c['name']}天赋"
            entry["aliases"].append(tn)

        output.append(entry)

    return output

# ---------------- 执行 ----------------
import requests
import json

if __name__ == "__main__":
    def load_json_from_url(url):
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

    def load_json(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    cData = load_json_from_url("https://static-data.7shengzhaohuan.online/api/v5/data/beta/CHS/characters").get("data")
    aData = load_json_from_url("https://static-data.7shengzhaohuan.online/api/v5/data/beta/CHS/action_cards").get("data")
    eData = load_json_from_url("https://static-data.7shengzhaohuan.online/api/v5/data/beta/CHS/entities").get("data")

    # 根据 category 字段筛选
    characters = [item for item in cData if item.get("category") == "characters"]
    actions = [item for item in aData if item.get("category") == "action_cards"]
    entities = [item for item in eData if item.get("category") == "entities"]

    db = generate_namemap(characters, actions, entities)

    # 保存到文件
    baseFileName = "map/base-NameMap.json"
    with open(baseFileName, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print("✅ 已生成：" + baseFileName)

    # 以 map/NameMap.json 为基础，补充 db 中不存在的 id
    prod_data = load_json("map/NameMap.json")
    prod_ids = {str(item.get("id")) for item in prod_data if "id" in item}

    #排除 id 列表（
    exclude_ids = [
        332047 # 火与战争（test）
                   ]

    # 只添加 db 中 prod_data 没有的 id，且排除 exclude_ids 中的 id
    new_entries = [
        entry for entry in db
        if str(entry.get("id")) not in prod_ids and "id" in entry and entry.get("id") not in exclude_ids
    ]

    merged = prod_data + new_entries

    wipFileName = "map/NameMap.wip.json"
    with open(wipFileName, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print("✅ 已补充新id，生成文件：" + wipFileName)


