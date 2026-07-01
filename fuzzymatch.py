import re 
from pypinyin import pinyin, Style 
import unicodedata 
from itertools import product 



def is_pure_alpha(s): 
    return re.fullmatch(r'[a-zA-Z]+', s) is not None 



def get_all_pinyin_combinations(text): 
    pinyin_list = pinyin(text, style=Style.NORMAL, heteronym=True) 
    all_combinations = [''.join(item) for item in product(*pinyin_list)] 
    return all_combinations 



def normalize(text): 
    if not isinstance(text, str): 
        return "" 
    return ''.join(c for c in text if unicodedata.category(c).startswith(('L', 'N'))).lower() 



def match_id(input_text, database): 
    normalized_input = normalize(input_text) 
    result = { 
        "query": input_text, 
        "matched": False, 
        "fallback": [], 
    } 
    
    # 1. ID 严格匹配 唯一
    if normalized_input.isdigit(): 
        for item in database: 
            if normalized_input == str(item["id"]): 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 

    # 2. 名称 严格匹配 唯一
    for item in database: 
        if normalized_input == normalize(item["name"]): 
            result["query"] = str(item["id"]) 
            result["matched"] = True 
            result["fallback"].append((item["name"], item["englishName"])) 
            return result 

    # 3. 别名 严格匹配 去重
    alias_matched_pool = []
    for item in database: 
        if (normalized_input in item["aliases"]) or (input_text in item["aliases"]): 
            alias_matched_pool.append(item)
    if len(alias_matched_pool) == 1:
        result["query"] = str(alias_matched_pool[0]["id"])
        result["matched"] = True
        result["fallback"].append((alias_matched_pool[0]["name"], alias_matched_pool[0]["englishName"]))
        return result
    elif len(alias_matched_pool) > 1:
        result["fallback"].extend((item["name"], item["englishName"]) for item in alias_matched_pool)
        return result

    # 字串匹配之前校验
    if not normalized_input:
        return result

    # 4. 名称 子串匹配 去重
    name_matched_pool = []
    for item in database: 
        if normalized_input in normalize(item["name"]): 
            name_matched_pool.append(item)
    if len(name_matched_pool) == 1:
        result["query"] = str(name_matched_pool[0]["id"])
        result["matched"] = True
        result["fallback"].append((name_matched_pool[0]["name"], name_matched_pool[0]["englishName"]))
        return result
    elif len(name_matched_pool) > 1:
        result["fallback"].extend((item["name"], item["englishName"]) for item in name_matched_pool)
        return result

    # 5. 拼音 严格匹配 唯一
    if is_pure_alpha(normalized_input): 
        for item in database: 
            if normalized_input == normalize(item["pinyin"]): 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 

    pinyin_variants = get_all_pinyin_combinations(normalized_input) 
    for item in database: 
        target_pinyin = normalize(item["pinyin"]) 
        for variant in pinyin_variants: 
            if normalize(variant) == target_pinyin: 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 

    # 6. 英文名称 严格匹配 唯一 子串匹配 去重
    english_matched_pool = []
    if is_pure_alpha(normalized_input) and len(normalized_input) > 3: 
        for item in database: 
            if normalized_input == normalize(item["englishName"]): 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 
            elif normalized_input in normalize(item["englishName"]): 
                english_matched_pool.append(item)
        if len(english_matched_pool) == 1:
            result["query"] = str(english_matched_pool[0]["id"])
            result["matched"] = True
            result["fallback"].append((english_matched_pool[0]["name"], english_matched_pool[0]["englishName"]))
            return result
        elif len(english_matched_pool) > 1:
            result["fallback"].extend((item["name"], item["englishName"]) for item in english_matched_pool)
            return result

    # 7. child 严格匹配 懒得去重
    for item in database: 
        for child in item["child"]: 
            if normalized_input == str(child["id"]): 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 
            if normalized_input == normalize(child["name"]): 
                result["query"] = str(item["id"]) 
                result["matched"] = True 
                result["fallback"].append((item["name"], item["englishName"])) 
                return result 

    for item in database: 
        # 1. 包含名称 
        if normalize(item["name"]) in normalized_input: 
            result["fallback"].append((item["name"], item["englishName"])) 
        # 2. 别名拼音 
        for alias in item["aliases"]: 
            if len(list(set(pinyin_variants) & set(get_all_pinyin_combinations(alias)))) > 0: 
                result["fallback"].append((item["name"], item["englishName"])) 
                break 
        # 3. child拼音 
        for child in item["child"]: 
            if len(list(set(pinyin_variants) & set(get_all_pinyin_combinations(child["name"])))) > 0: 
                result["fallback"].append((item["name"], item["englishName"])) 
                break 
        # 4. 拼音字串 
        for variant in pinyin_variants: 
            if variant in item["pinyin"] and ((len(normalized_input) > 1 and not is_pure_alpha(normalized_input)) or len(variant) * len(variant) / len(item["pinyin"]) >= 1.8):
                result["fallback"].append((item["name"], item["englishName"])) 
                break 

    result["fallback"] = list(set(result["fallback"])) 
    return result 
