import hmac
import html
import json
import random
import re
import time
import unicodedata
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()  # .env からAPIキーを読み込む

# 上から順に試す。混んでいたら次のモデルに切り替わる
MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]

DISHES_FILE = Path(__file__).parent / "dishes.json"

# 期間の選択肢。「画面に出す名前」: 日数
PERIODS = {"1日": 1, "3日": 3, "1週間": 7}

# 1日に選ぶ料理。(AIの返事で使うキー, 料理リストの役割)
ROLE_KEYS = [("main", "主菜"), ("side", "副菜"), ("soup", "汁物")]

# この単位の材料は「調味料など」として扱う(買い物リストで分けて表示する)
SEASONING_UNITS = {"大さじ", "小さじ", "適量", "少々", "適宜", "ひとつまみ", "つまみ"}

# 表記ゆれをそろえるための置き換え(漢字 → ひらがな)
CANON = {
    "玉ねぎ": "たまねぎ", "玉葱": "たまねぎ", "人参": "にんじん",
    "卵": "たまご", "玉子": "たまご", "生姜": "しょうが", "大蒜": "にんにく",
    "茄子": "なす", "南瓜": "かぼちゃ", "牛蒡": "ごぼう", "蓮根": "れんこん",
    "胡瓜": "きゅうり", "馬鈴薯": "じゃがいも", "椎茸": "しいたけ",
    "舞茸": "まいたけ", "占地": "しめじ",
}

# 「きのこ」と入力したら、これらの食材も対象にする(自由に追加できます)
FOOD_GROUPS = {
    "きのこ": ["きのこ", "しいたけ", "しめじ", "えのき", "まいたけ", "エリンギ"],
    "魚": ["魚", "さけ", "鮭", "さば", "鯖", "さんま", "あじ", "ぶり", "たら", "いわし", "ししゃも"],
    "貝": ["貝", "あさり", "しじみ", "はまぐり", "ほたて", "帆立", "牡蠣"],
    "乳製品": ["牛乳", "チーズ", "バター", "ヨーグルト", "生クリーム"],
    "肉": ["肉", "豚", "鶏", "牛", "ベーコン", "ハム", "ソーセージ"],
    "鶏肉": ["鶏肉", "鶏", "とり肉", "ささみ", "手羽", "チキン"],
    "豚肉": ["豚肉", "豚", "ポーク"],
    "牛肉": ["牛肉", "牛もも", "牛ばら", "牛ロース", "牛こま", "牛薄切り", "牛切り落とし", "牛ひき", "合いびき", "合びき", "合挽き"],
    "ひき肉": ["ひき肉", "挽き肉", "ミンチ", "合いびき", "合びき", "合挽き", "豚ひき", "鶏ひき", "牛ひき"],
}

EPS = 0.05  # 残りがこの割合以下なら「使い切った」とみなす
EXTRA_PENALTY = 0.25  # 買い足しが必要な食材1つごとの減点


# 見た目の設定(色を変えたいときは、#ff7a59 や #ff6a88 を好きな色に書き換える)
CSS = """
<style>
.block-container { max-width: 880px; padding-top: 1.6rem; }
#MainMenu, footer { visibility: hidden; }
.hero { background: linear-gradient(135deg, #ff9a56, #ff6a88); color: #fff; padding: 26px 28px;
  border-radius: 20px; margin-bottom: 18px; box-shadow: 0 8px 24px rgba(255,106,136,.28); }
.hero h1 { margin: 0; padding: 0; font-size: 2.1rem; color: #fff; }
.hero p { margin: .5rem 0 0; opacity: .95; font-size: 1rem; }
button[data-baseweb="tab"] { font-size: 1.05rem; font-weight: 700; padding: 12px 18px; }
div.stButton > button { border-radius: 12px; font-weight: 700; padding: .6rem 1.5rem; }
div.stButton > button[kind="primary"] { background: linear-gradient(135deg, #ff9a56, #ff6a88);
  border: none; color: #fff; box-shadow: 0 4px 14px rgba(255,106,136,.35); }
[data-testid="stExpander"] { border-radius: 14px; border: 1px solid rgba(128,128,128,.28);
  background: rgba(128,128,128,.06); margin-bottom: 10px; overflow: hidden; }
[data-testid="stExpander"] summary { font-weight: 700; font-size: 1.02rem; }
[data-testid="stMetric"] { background: rgba(255,122,89,.09); border: 1px solid rgba(255,122,89,.30);
  padding: 14px 16px; border-radius: 14px; }
.day-head { display: flex; justify-content: space-between; align-items: center; margin: 26px 0 10px;
  padding: 10px 16px; border-left: 6px solid #ff7a59; background: rgba(255,122,89,.12);
  border-radius: 10px; font-weight: 800; font-size: 1.12rem; }
.day-head span { font-weight: 600; font-size: .92rem; opacity: .85; }
.chip { display: inline-block; padding: 3px 12px; margin: 0 6px 10px 0; border-radius: 999px;
  background: rgba(255,122,89,.16); font-size: .86rem; font-weight: 700; }
.shop { border-radius: 16px; padding: 4px 22px 16px; border: 1px solid rgba(46,160,67,.40);
  background: rgba(46,160,67,.08); margin-bottom: 12px; }
.shop h4 { margin: 14px 0 6px; }
.shop ul { list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 30px; }
.shop li { break-inside: avoid; padding: 6px 0; border-bottom: 1px dashed rgba(128,128,128,.35); }
.shop li::before { content: "☐"; margin-right: 8px; opacity: .7; }
@media (max-width: 640px) { .hero h1 { font-size: 1.6rem; } .shop ul { columns: 1; } }
</style>
"""

ROLE_ICON = {"主菜": "🍖", "副菜": "🥗", "汁物": "🍲"}


def day_header(title, right=""):
    st.markdown(
        f"<div class='day-head'>{html.escape(title)}<span>{html.escape(right)}</span></div>",
        unsafe_allow_html=True,
    )


def chips(*texts):
    body = "".join(f"<span class='chip'>{html.escape(t)}</span>" for t in texts if t)
    st.markdown(body, unsafe_allow_html=True)


# ---------------------------------------------------------------- AI

_client = None


def get_secret(name):
    """公開サービスの「Secrets」に設定した値を読む。なければNone(自分のパソコンでは.envを使う)"""
    try:
        value = st.secrets.get(name)
    except Exception:
        return None
    return str(value) if value else None


def get_client():
    """AIの接続を必要になったときに作る(AIを使わない機能は、キーがなくても動く)"""
    global _client
    if _client is None:
        key = get_secret("GEMINI_API_KEY")
        _client = genai.Client(api_key=key) if key else genai.Client()
    return _client


def check_password():
    """APP_PASSWORD が設定されているときだけ、パスワードを確認する(公開したときの悪用防止)"""
    expected = get_secret("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return True
    typed = st.text_input("パスワードを入力してください", type="password")
    if typed:
        if hmac.compare_digest(typed.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    return False


def ask_ai(prompt):
    """AIに質問して返事(JSON文字列)を返す。失敗したら再試行・モデル切り替えをする"""
    config = types.GenerateContentConfig(response_mime_type="application/json")
    last_error = None
    for model in MODELS:
        for attempt in range(2):  # 同じモデルで最大2回試す
            try:
                response = get_client().models.generate_content(
                    model=model, contents=prompt, config=config
                )
                return response.text
            except Exception as e:
                last_error = e
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(3)  # 混雑なら3秒待って再試行
                else:
                    break  # 混雑以外のエラーは、次のモデルへ
    raise last_error


def parse_json(text):
    """AIの返事(文字列)をPythonのデータに変換する"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    return json.loads(text)


# ---------------------------------------------------------------- 小さな道具

def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_float(value):
    """数値に変換する。「1/2」のような分数にも対応。変換できなければ0"""
    try:
        text = str(value).strip()
        if "/" in text:
            a, b = text.split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def format_number(value):
    value = round(value) if value >= 10 else round(value, 1)
    return f"{value:g}"


def format_item(name, unit, amount):
    """「豚ロース肉 200g」のような表示用の文字を作る"""
    if unit == "適量" or amount <= 0:
        return f"{name} 適量"
    if unit in ("大さじ", "小さじ"):
        return f"{name} {unit}{format_number(amount)}"
    return f"{name} {format_number(amount)}{unit}"


def normalize(text):
    """全角半角・カタカナ・漢字の表記ゆれをそろえる"""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    for src, dst in CANON.items():
        text = text.replace(src, dst)
    return text.strip()


def variants(word):
    """食材の検索に使う言葉の一覧(グループ・表記ゆれを含む)"""
    w = normalize(word)
    if not w:
        return set()
    result = {w}
    for key, members in FOOD_GROUPS.items():
        if w == normalize(key):
            result.update(normalize(m) for m in members)
    return result


def split_words(text):
    return [x.strip() for x in re.split(r"[,、，\n]+", text) if x.strip()]


def ing_names(dish, include_seasonings=False):
    """料理の材料名(正規化済み)の一覧。調味料などは除くのが基本"""
    names = []
    for ing in dish.get("ingredients", []):
        if not include_seasonings and ing.get("unit", "") in SEASONING_UNITS:
            continue
        names.append(normalize(ing.get("name", "")))
    return names


def has_any(dish, vset):
    """料理の材料に、vset の言葉のどれかが含まれていればTrue"""
    names = ing_names(dish)
    return any(v in n for v in vset for n in names)


def is_ng(dish, ng_vset):
    """料理名か材料(調味料も含む)に、嫌いな食べ物が含まれていればTrue"""
    text = normalize(dish.get("name", "")) + "".join(ing_names(dish, include_seasonings=True))
    return any(v in text for v in ng_vset)


def make_entries(words):
    """[(入力した言葉, 検索用の言葉の一覧)] を作る"""
    return [(w, variants(w)) for w in words if variants(w)]


# ---------------------------------------------------------------- 買い物リスト

def aggregate(dishes, people):
    """料理の材料を合算する。(食材, 調味料など) を返す"""
    items, seasonings = {}, {}
    for d in dishes:
        for ing in d.get("ingredients", []):
            name = str(ing.get("name", "")).strip()
            unit = str(ing.get("unit", "")).strip()
            amount = to_float(ing.get("amount")) * people
            target = seasonings if unit in SEASONING_UNITS else items
            key = (name, unit)
            target[key] = target.get(key, 0.0) + amount
    return items, seasonings


def shopping_text(title, items, seasonings):
    lines = [title, "", "【食材】"]
    lines += [f"- {format_item(n, u, a)}" for (n, u), a in items.items()] or ["- (なし)"]
    if seasonings:
        lines += ["", "【調味料など(家にあるか確認)】"]
        lines += [f"- {format_item(n, u, a)}" for (n, u), a in seasonings.items()]
    return "\n".join(lines)


def render_shopping(title, items, seasonings):
    def block(heading, pairs):
        lis = "".join(
            f"<li>{html.escape(format_item(n, u, a))}</li>" for (n, u), a in pairs.items()
        )
        return f"<h4>{heading}</h4><ul>{lis}</ul>"

    st.markdown(f"### 🛒 {title}")
    body = block("🥬 食材", items) if items else "<h4>🥬 食材</h4><p>買い足す食材はありません。</p>"
    if seasonings:
        body += block("🧂 調味料など(家にあるか確認してください)", seasonings)
    st.markdown(f"<div class='shop'>{body}</div>", unsafe_allow_html=True)
    with st.expander("📋 コピー用のテキストを表示"):
        st.code(shopping_text(title, items, seasonings), language=None)


# ---------------------------------------------------------------- 料理の表示

def render_dish(dish, people, note=""):
    icon = ROLE_ICON.get(dish.get("role", ""), "🍽️")
    label = f"{icon} {dish.get('role', '')}:{dish.get('name', '名前なし')}{note}"
    with st.expander(label):
        chips(
            f"⏱ {to_int(dish.get('minutes'))}分",
            f"💰 約{to_int(dish.get('price_yen')) * people}円",
            dish.get("category", ""),
        )
        st.markdown(f"**材料({people}人分)**")
        for ing in dish.get("ingredients", []):
            amount = to_float(ing.get("amount")) * people
            st.write(f"- {format_item(ing.get('name', ''), ing.get('unit', ''), amount)}")
        st.markdown("**作り方**")
        for n, step in enumerate(dish.get("steps", []), start=1):
            st.write(f"{n}. {step}")


# ---------------------------------------------------------------- 献立を作る(タブ1)

def build_prompt(candidates, days_count, entries):
    lines = []
    for d in candidates:
        hits = [w for w, vs in entries if has_any(d, vs)]
        mark = "★" + "、".join(hits) if hits else ""
        lines.append(
            f"{d['id']}|{d['role']}|{d['name']}|{d.get('category', '')}|"
            f"{to_int(d.get('minutes'))}分|{to_int(d.get('price_yen'))}円|{mark}"
        )
    wanted = "、".join(w for w, _ in entries)
    wanted_rule = (
        f"- 使いたい食材・好きな食材は「{wanted}」。★が付いた料理を優先して選び、"
        "期間中にそれぞれの食材がなるべく使われるようにする\n"
        if entries
        else ""
    )
    return f"""あなたは管理栄養士です。下の料理リストの中だけから、{days_count}日分の夕食の献立を決めてください。
1日につき、主菜1品・副菜1品・汁物1品を選びます(主食は白ごはんを別に添える前提です)。
条件:
- 必ずリストにある id だけを使う。リストにない料理は作らない
- 同じ id は、期間中に2回以上使わない(候補が足りない場合のみ例外)
{wanted_rule}- 栄養バランスを考える(主菜は肉・魚・卵や豆をまんべんなく、副菜は野菜やきのこ・海藻を取り入れる)
- 同じ日の中で、材料や味付けが重ならないようにする
- 平日は、調理時間の短い料理を中心にする

料理リスト(id|役割|料理名|分類|調理時間|1人分の材料費|★=使いたい食材):
{chr(10).join(lines)}

次のJSON形式だけで答えてください(説明文は不要):
{{"days": [{{"main": "main01", "side": "side03", "soup": "soup02"}}]}}"""


def build_menu(plan, candidates, days_count):
    """AIの選択を確認し、おかしい・重複している場合は代わりの料理を選ぶ"""
    by_id = {d["id"]: d for d in candidates}
    plan_days = plan.get("days", []) if isinstance(plan, dict) else []
    if not isinstance(plan_days, list):
        plan_days = []

    used = set()
    menu = []
    for i in range(days_count):
        day_plan = plan_days[i] if i < len(plan_days) and isinstance(plan_days[i], dict) else {}
        picked = []
        for key, role in ROLE_KEYS:
            dish = by_id.get(day_plan.get(key))
            if dish is None or dish["role"] != role or dish["id"] in used:
                options = [d for d in candidates if d["role"] == role and d["id"] not in used]
                if not options:  # 足りなければ重複を許す
                    options = [d for d in candidates if d["role"] == role]
                dish = random.choice(options)
            used.add(dish["id"])
            picked.append(dish)
        menu.append({"day": f"{i + 1}日目", "dishes": picked})
    return menu


def ensure_wanted(menu, candidates, entries):
    """使いたい食材が献立に入っていなければ、その食材を使う料理に差し替える。見つからなかった食材名を返す"""
    not_found = []
    for word, vset in entries:
        if any(has_any(d, vset) for day in menu for d in day["dishes"]):
            continue
        used_ids = {d["id"] for day in menu for d in day["dishes"]}
        options = [d for d in candidates if d["id"] not in used_ids and has_any(d, vset)]
        if not options:
            not_found.append(word)
            continue
        dish = random.choice(options)
        # 同じ役割の枠のうち、使いたい食材をいちばん使っていない枠と入れ替える
        slots = [
            (i, j)
            for i, day in enumerate(menu)
            for j, d in enumerate(day["dishes"])
            if d["role"] == dish["role"]
        ]
        if not slots:
            not_found.append(word)
            continue

        def hit_count(slot):
            i, j = slot
            return sum(1 for _, vs in entries if has_any(menu[i]["dishes"][j], vs))

        i, j = min(slots, key=hit_count)
        menu[i]["dishes"][j] = dish
    return not_found


def show_menu_result(result):
    people = result["people"]
    menu = result["menu"]
    for message in result["notices"]:
        st.warning(message)

    total = sum(to_int(d.get("price_yen")) for day in menu for d in day["dishes"]) * people
    dish_count = sum(len(day["dishes"]) for day in menu)
    m1, m2, m3 = st.columns(3)
    m1.metric(f"材料費の合計(目安・{people}人分)", f"約{total:,}円")
    m2.metric("日数", f"{len(menu)}日")
    m3.metric("料理数", f"{dish_count}品")
    st.caption("※値段はAIが作った目安です。お店・地域・時期で変わります。")

    for day in menu:
        day_price = sum(to_int(d.get("price_yen")) for d in day["dishes"]) * people
        day_header(day["day"], f"約{day_price:,}円")
        for dish in day["dishes"]:
            render_dish(dish, people)

    items, seasonings = aggregate([d for day in menu for d in day["dishes"]], people)
    render_shopping(f"買い物リスト({people}人分)", items, seasonings)


# ---------------------------------------------------------------- 食材を使い切る(タブ3)

UNIT_ALIASES = {"kg": ("g", 1000.0), "l": ("ml", 1000.0), "ℓ": ("ml", 1000.0), "グラム": ("g", 1.0)}


def parse_stock_line(line, shares):
    """「鶏もも肉 600g」のような1行を、食材のデータに変換する"""
    line = unicodedata.normalize("NFKC", line).strip()
    if not line:
        return None
    m = re.match(r"^(.*?)[\s:]*(\d+(?:\.\d+)?(?:/\d+)?)\s*([^\d\s]*)\s*$", line)
    amount, unit = None, ""
    if m and m.group(1).strip():
        name = m.group(1).strip()
        amount = to_float(m.group(2))
        unit = m.group(3)
        key = unit.lower()
        if key in UNIT_ALIASES:
            unit, factor = UNIT_ALIASES[key]
            amount *= factor
        if amount <= 0:
            amount = None
    else:
        name = re.split(r"[\s　]", line)[0]
    vset = variants(name)
    if not vset:
        return None
    return {"name": name, "vset": vset, "amount": amount, "unit": unit, "frac": 1.0, "share": 1.0 / shares}


def parse_stock_text(text, shares):
    stock = []
    for line in re.split(r"[\n、,，]+", text):
        item = parse_stock_line(line, shares)
        if item:
            stock.append(item)
    return stock


def match_stock(ing_name, stock):
    n = normalize(ing_name)
    found = [s for s in stock if any(v in n for v in s["vset"])]
    for s in found:
        if s["frac"] > EPS:
            return s
    return found[0] if found else None


def evaluate(dish, stock, people):
    """その料理を作ったときの、家の食材の消費・買い足しを調べる(まだ実際には減らさない)"""
    uses, buys, extras = [], [], 0
    for ing in dish.get("ingredients", []):
        unit = str(ing.get("unit", ""))
        if unit in SEASONING_UNITS:
            continue
        name = str(ing.get("name", ""))
        need = to_float(ing.get("amount")) * people
        item = match_stock(name, stock)
        if item is None or item["frac"] <= EPS:
            extras += 1
            buys.append((name, unit, need))
            continue
        if item["amount"] and item["unit"] == unit and need > 0:
            have = item["frac"] * item["amount"]
            if need > have + 1e-9:
                extras += 1
                buys.append((name, unit, need - have))
            uses.append((item, min(need / item["amount"], item["frac"])))
        else:
            uses.append((item, min(item["share"], item["frac"])))
    return uses, buys, extras


def plan_use_up(dishes, stock, people, max_days, max_extra):
    """家の食材を使い切るように、料理を1日分ずつ選んでいく"""
    used_ids = set()
    days = []
    buy_list = []
    for day_no in range(1, max_days + 1):
        if all(s["frac"] <= EPS for s in stock):
            break
        day_items = []
        for _, role in ROLE_KEYS:
            best = None
            best_net = 0.02
            for d in dishes:
                if d.get("role") != role or d["id"] in used_ids:
                    continue
                uses, buys, extras = evaluate(d, stock, people)
                gross = sum(c for _, c in uses)
                if gross <= 0.01 or extras > max_extra:
                    continue
                net = gross - EXTRA_PENALTY * extras + random.random() * 0.01
                if net > best_net:
                    best, best_net, best_eval = d, net, (uses, buys)
            if best is None:
                continue
            uses, buys = best_eval
            for item, c in uses:
                item["frac"] = max(0.0, item["frac"] - c)
            used_ids.add(best["id"])
            buy_list += buys
            day_items.append({"dish": best, "uses": sorted({s["name"] for s, _ in uses})})
        if not day_items:
            break
        days.append({"day": f"{day_no}日目", "items": day_items})

    buy = {}
    for name, unit, amount in buy_list:
        buy[(name, unit)] = buy.get((name, unit), 0.0) + amount
    leftover = [(s["name"], round(s["frac"] * 100)) for s in stock if s["frac"] > EPS]
    return {"people": people, "days": days, "buy": buy, "leftover": leftover}


def show_use_up_result(plan):
    people = plan["people"]
    if not plan["days"]:
        st.warning(
            "使える料理が見つかりませんでした。食材の名前を変えてみる(例:「鶏肉」→「鶏もも肉」)、"
            "1品あたりの買い足し数を増やす、または料理リストを増やしてみてください。"
        )
        return

    st.success(f"{len(plan['days'])}日で食材を使います。(ごはんは別に用意してください)")
    for day in plan["days"]:
        day_header(day["day"])
        for item in day["items"]:
            note = f"  ← {'・'.join(item['uses'])}を使う"
            render_dish(item["dish"], people, note)

    if plan["leftover"]:
        text = "、".join(f"{n}(残り約{p}%)" for n, p in plan["leftover"])
        st.warning(
            f"使い切れなかった食材: {text}\n\n"
            "料理リストを増やす(add_dishes.py を実行)か、「1品で買い足してよい食材の数」を増やすと、使い切れる可能性が上がります。"
        )
    else:
        st.success("入力した食材は、すべて使い切れる計算です。")

    dishes = [item["dish"] for day in plan["days"] for item in day["items"]]
    _, seasonings = aggregate(dishes, people)
    render_shopping("買い足すもの", plan["buy"], seasonings)
    st.caption("※量の計算は目安です。冷蔵庫の中身を見ながら調整してください。")


# ---------------------------------------------------------------- 画面

def main():
    st.set_page_config(page_title="献立AI", page_icon="🍳")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        "<div class='hero'><h1>🍳 献立AI</h1>"
        "<p>献立づくり・買い物リスト・食材の使い切りまで、毎日のごはんをまとめて決めます。</p></div>",
        unsafe_allow_html=True,
    )

    if not check_password():
        st.stop()

    if not DISHES_FILE.exists():
        st.error("dishes.json が見つかりません。add_dishes.py を実行して、料理リストを作ってください。")
        st.stop()
    with open(DISHES_FILE, encoding="utf-8") as f:
        all_dishes = json.load(f)

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            people = st.number_input("何人分?", min_value=1, max_value=6, value=1)
        with col2:
            ng_text = st.text_input("嫌いな食べ物(「、」か「,」で区切る)", "")

    ng_vset = set()
    for w in split_words(ng_text):
        ng_vset |= variants(w)
    candidates = [d for d in all_dishes if not is_ng(d, ng_vset)]
    if len(candidates) < len(all_dishes):
        st.caption(f"嫌いな食べ物を含む{len(all_dishes) - len(candidates)}品を除外しています。(残り{len(candidates)}品)")
    st.caption("※除外は材料名の文字で判定しています。アレルギーがある場合は、必ず材料を自分でも確認してください。")

    tab1, tab2, tab3 = st.tabs(["🍳 献立を作る", "🔎 食材から探す", "🥬 食材を使い切る"])

    # ---- タブ1:献立を作る
    with tab1:
        period = st.radio("何日分の献立を作る?", list(PERIODS.keys()), index=2, horizontal=True)
        want_text = st.text_input(
            "使いたい食材・好きな食材(任意)", "", placeholder="例: 鶏肉、キャベツ、卵", key="want1"
        )
        if st.button(f"{period}の献立を作る", key="make_menu", type="primary"):
            days_count = PERIODS[period]
            entries = make_entries(split_words(want_text))
            notices = []
            empty_roles = [r for _, r in ROLE_KEYS if not any(d["role"] == r for d in candidates)]
            if empty_roles:
                st.error(f"{'・'.join(empty_roles)}の候補がなくなりました。嫌いな食べ物を減らすか、料理リストを増やしてください。")
            else:
                for _, role in ROLE_KEYS:
                    if sum(1 for d in candidates if d["role"] == role) < days_count:
                        notices.append(f"{role}の候補が{days_count}品に足りないため、同じ料理が重なる場合があります。")
                with st.spinner("献立を考えています..."):
                    try:
                        plan = parse_json(ask_ai(build_prompt(candidates, days_count, entries)))
                    except Exception:
                        plan = {}
                        notices.append("AIに接続できなかったため、料理をランダムに選びました。")
                menu = build_menu(plan, candidates, days_count)
                for word in ensure_wanted(menu, candidates, entries):
                    notices.append(f"「{word}」を使う料理が見つかりませんでした。")
                st.session_state["menu_result"] = {"people": people, "menu": menu, "notices": notices}
        if st.session_state.get("menu_result"):
            show_menu_result(st.session_state["menu_result"])

    # ---- タブ2:食材から探す
    with tab2:
        st.write("使いたい食材や好きな食材を入れると、その食材を使う料理を教えます。")
        search_text = st.text_input("食材(「、」か「,」で区切る)", "", placeholder="例: 鶏肉、キャベツ", key="search2")
        entries = make_entries(split_words(search_text))
        if entries:
            results = []
            for d in candidates:
                hits = [w for w, vs in entries if has_any(d, vs)]
                if hits:
                    results.append((len(hits), d, hits))
            results.sort(key=lambda r: (-r[0], to_int(r[1].get("price_yen"))))
            if not results:
                st.info("その食材を使う料理は見つかりませんでした。")
            else:
                all_hit = sum(1 for r in results if r[0] == len(entries))
                if len(entries) > 1:
                    st.write(f"{len(results)}品見つかりました。(すべての食材を使う料理: {all_hit}品)")
                else:
                    st.write(f"{len(results)}品見つかりました。")
                for count, d, hits in results[:30]:
                    render_dish(d, people, f"  〔{'・'.join(hits)}〕")
                if len(results) > 30:
                    st.caption("上位30品を表示しています。")

    # ---- タブ3:食材を使い切る
    with tab3:
        st.write("買い出しした食材を入れると、使い切るまでの料理を日ごとに提案します。(AIは使わないので、すぐ表示されます)")
        stock_text = st.text_area(
            "家にある食材(1行に1つ。量が分かれば一緒に書く)",
            "",
            height=180,
            placeholder="鶏もも肉 600g\nキャベツ\n卵 6個\n玉ねぎ 3個\n豆腐",
            key="stock3",
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            max_days = st.slider("最大日数", 1, 14, 7)
        with c2:
            max_extra = st.slider("1品で買い足してよい食材の数", 0, 4, 2)
        with c3:
            shares = st.slider("量を書かなかった食材を使う品数", 1, 4, 2)
        st.caption("量は「g」「ml」「個」「本」「枚」で書くと、料理の分量と照らして計算します。それ以外(「1袋」など)や量なしの場合は、上の「使う品数」で何品に使うかを決めます。")

        if st.button("使い切る献立を作る", key="make_useup", type="primary"):
            stock = parse_stock_text(stock_text, shares)
            if not stock:
                st.warning("食材を入力してください。")
            else:
                st.session_state["use_plan"] = plan_use_up(candidates, stock, people, max_days, max_extra)
        if st.session_state.get("use_plan"):
            show_use_up_result(st.session_state["use_plan"])


if __name__ == "__main__":
    main()
