"""
沙田天气内容生成 — 统一入口

拉取 HKO 开放数据，生成 Instagram / WhatsApp / YouTube 帖文及 YouTube 发言稿。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from openai import APIConnectionError, APIError, RateLimitError

from deepseek_utils import (
    chat_completion,
    configure_stdio_utf8,
    format_deepseek_api_error,
    has_deepseek_api_key,
)
from shatin_weather import (
    analyze_weather,
    format_weather_facts,
    get_shatin_weather,
    print_weather,
    weather_fingerprint,
)

configure_stdio_utf8()

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
DATA_DIR = SCRIPT_DIR / "data"
STATE_FILE = DATA_DIR / "state.json"
HK_TZ = ZoneInfo("Asia/Hong_Kong")

Platform = Literal[
    "instagram", "whatsapp", "youtube_post", "youtube_script"
]
PLATFORMS: Tuple[Platform, ...] = (
    "instagram",
    "whatsapp",
    "youtube_post",
    "youtube_script",
)
PLATFORM_LABELS: Dict[Platform, str] = {
    "instagram": "Instagram",
    "whatsapp": "WhatsApp 社群",
    "youtube_post": "YouTube 社群帖",
    "youtube_script": "YouTube 发言稿",
}

SAMPLE_POST_CANTONESE = """各位沙田街坊，午安呀 ☀️

今日沙田大概 26°C，湿度有八成几，风唔大。过去一个钟落雨唔多，出门行街几舒服；如果去行山记得带支水 💧

#沙田天氣 #香港天氣 #粵語日常"""

FIRST_POST_OPENING = (
    "各位沙田街坊，我哋起个天气交流群啦 👋 "
    "以后会每日用天文台即时数据同大家报沙田天气～"
)


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"first_post_completed": False, "last_hashes": {}}


def _save_state(state: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def _is_duplicate(platform: Platform, text: str, state: Dict[str, Any]) -> bool:
    last = (state.get("last_hashes") or {}).get(platform)
    return bool(last and last == _content_hash(text))


def _should_include_first_post(state: Dict[str, Any]) -> bool:
    """首帖问候仅一次；由仓库内 data/state.json 记录（Actions 会提交更新）。"""
    env = os.environ.get("INCLUDE_FIRST_POST_GREETING", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    return not state.get("first_post_completed", False)


def _run_context(weather: Dict[str, Any]) -> str:
    now = datetime.now(HK_TZ)
    weekdays = "星期一星期二星期三星期四星期五星期六星期日"
    weekday = weekdays[now.weekday()]
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    fp = weather_fingerprint(weather)
    return f"""【本次發佈上下文 — 必須體現在文案中，避免與往日重複】
- 香港時間：{now:%Y年%m月%d日}（{weekday}）{now:%H:%M}
- 工作流運行編號：{run_id}
- 觀測數據指紋：{fp}（氣溫/濕度/雨量/風況組合，與往日不同則用詞須有變化）
- 要求：開場或首句須點出「今日」或具體時段；勿七天連續使用同一句開場白"""


def _uniqueness_rules() -> str:
    return """
【去重】
- 禁止連續多日使用完全相同的開場白、標題或收尾句
- 即使天氣相近，亦須換用不同句式描述
- 必須引用當次觀測的具體數字"""


def _first_post_block() -> str:
    return f"""
【僅本次 · 首帖問候】
{FIRST_POST_OPENING}
參考語氣（勿照抄數字）：{SAMPLE_POST_CANTONESE}
"""


def _build_prompt(
    weather: Dict[str, Any],
    analysis: Dict[str, Any],
    platform: Platform,
    include_first_post: bool,
) -> str:
    facts = format_weather_facts(weather)
    ctx = _run_context(weather)
    first = _first_post_block() if include_first_post else ""
    uniq = _uniqueness_rules()

    if platform == "instagram":
        rules = """
【Instagram】粵語口語，約 80–120 字，2–3 個 emoji
- 結尾：#沙田天氣 #香港天氣 #粵語日常
- 闷热/行山提带水，有雨提带遮"""
    elif platform == "whatsapp":
        rules = """
【WhatsApp】粵語，約 60–90 字，首行【沙田天氣 · 今日】
- 2–4 短行，≤2 個 emoji，最多 1 個 hashtag"""
    elif platform == "youtube_post":
        rules = """
【YouTube 社群帖】繁體書面語，約 120–220 字，≤3 個 emoji
- 首行標題含 🌤️；列核心數據；▶️ 影片連結：（請貼上本集 URL）
- 訂閱並開啟通知；hashtag 含 #沙田天氣 #香港天文台
- 末行：資料來源：香港天文台開放數據 · 沙田自動氣象站"""
    else:
        rules = """
【YouTube 发言稿】繁體書面語，正式播報，約 280–420 字
- 結構：【開場】【主體】【收尾】，主體可加【畫面提示】
- 勿用粵語口語；收尾訂閱頻道；末行【資料來源】香港天文台開放數據 · 沙田自動氣象站"""

    lang = "粵語口語" if platform in ("instagram", "whatsapp") else "繁體書面語"
    return f"""你係香港沙田區天氣內容編輯。根據天文台即時數據撰寫{PLATFORM_LABELS[platform]}。

{ctx}
{facts}

【分析摘要】
{analysis['briefing']}
{first}
{rules}
{uniq}

通用：
- 使用{lang}；只根據上述數據；勿編造預報或警告
- 只輸出可直接發佈正文，不要「好的」「以下是」"""


def _validate(content: str, platform: Platform) -> str:
    text = (content or "").strip()
    if platform == "youtube_script":
        if len(text) < 200:
            raise ValueError(f"发言稿过短（{len(text)} 字）")
        for m in ("【開場】", "【主體】", "【收尾】"):
            if m not in text:
                raise ValueError(f"发言稿缺少 {m}")
    elif platform == "youtube_post":
        if len(text) < 80:
            raise ValueError(f"YouTube 帖过短（{len(text)} 字）")
        if "#沙田天氣" not in text:
            raise ValueError("须包含 #沙田天氣")
    elif platform == "instagram":
        if len(text) < 50:
            raise ValueError(f"Instagram 帖过短（{len(text)} 字）")
    else:
        if len(text) < 35:
            raise ValueError(f"WhatsApp 帖过短（{len(text)} 字）")
    return text


def _template_content(
    weather: Dict[str, Any], analysis: Dict[str, Any], platform: Platform
) -> str:
    """无 API Key 时的备用模板（含日期，减少七日雷同）。"""
    now = datetime.now(HK_TZ)
    date_str = now.strftime("%Y年%m月%d日")
    t, rh = weather["air_temperature"], weather["relative_humidity"]
    rain, wind = weather["total_rainfall"], weather["wind_speed"]
    direction, gust = weather["wind_direction"], weather.get("wind_gust", "—")

    if platform == "instagram":
        return _validate(
            f"各位沙田街坊，{date_str}而家沙田約 {t}°C，濕度 {rh}%，"
            f"過去一個鐘雨量 {rain} mm，{direction}風 {wind} km/h。"
            f"{('記得帶遮同留意路面' if float(rain) > 0 else '出街記得帶水')} 💧\n\n"
            f"#沙田天氣 #香港天氣 #粵語日常",
            platform,
        )
    if platform == "whatsapp":
        return _validate(
            f"【沙田天氣 · {date_str}】\n"
            f"{t}°C｜濕度 {rh}%｜雨量 {rain}mm｜{direction}風 {wind}km/h\n"
            f"{'有雨，帶定遮 ☔' if float(rain) > 0 else '天氣悶熱，記得飲水 💧'}",
            platform,
        )
    if platform == "youtube_post":
        return _validate(
            f"🌤️ 沙田區即時天氣｜{date_str}\n\n"
            f"氣溫 {t}°C｜濕度 {rh}%｜過去一小時雨量 {rain} mm\n"
            f"{direction}風 {wind} km/h｜陣風 {gust} km/h\n\n"
            f"{analysis['briefing'].split('。')[0]}。完整報告請收看最新影片 👆\n\n"
            f"▶️ 影片連結：（請貼上本集 URL）\n"
            f"🔔 訂閱頻道並開啟通知\n\n"
            f"#沙田天氣 #香港天文台 #分區天氣 #即時天氣\n\n"
            f"資料來源：香港天文台開放數據 · 沙田自動氣象站",
            platform,
        )
    return _validate(
        f"【開場】\n各位觀眾，歡迎收看香港天文台沙田分區天氣報告（{date_str}）。\n\n"
        f"【主體】\n"
        f"沙田自動氣象站：氣溫 {t} 度，相對濕度 {rh}%，過去一小時雨量 {rain} 毫米；"
        f"吹{direction}風，平均風速每小時 {wind} 公里，最高陣風 {gust} 公里。"
        f"{analysis['headline']}。\n\n"
        f"【收尾】\n以上為沙田區天氣報告。歡迎訂閱本頻道並開啟通知。多謝收看。\n\n"
        f"【資料來源】香港天文台開放數據 · 沙田自動氣象站",
        platform,
    )


def generate_content(
    weather: Dict[str, Any],
    analysis: Dict[str, Any],
    platform: Platform,
    include_first_post: bool,
    state: Dict[str, Any],
) -> str:
    prompt = _build_prompt(weather, analysis, platform, include_first_post)
    max_tokens = {
        "instagram": 350,
        "whatsapp": 280,
        "youtube_post": 450,
        "youtube_script": 900,
    }[platform]
    temperature = 0.82

    if has_deepseek_api_key():
        for attempt in range(2):
            text = _validate(
                chat_completion(
                    prompt
                    + (
                        "\n【重试】请换一种开场和句式，勿与常见范本相同。"
                        if attempt == 1
                        else ""
                    ),
                    max_tokens=max_tokens,
                    temperature=temperature + (0.12 * attempt),
                ),
                platform,
            )
            if not _is_duplicate(platform, text, state):
                return text
        return text  # 第二次仍重复则仍返回，但已尽力
    return _template_content(weather, analysis, platform)


def _output_path(platform: Platform, stamp: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if platform == "youtube_script":
        return OUTPUT_DIR / f"script_{stamp}_youtube.txt"
    suffix = platform.replace("youtube_post", "youtube")
    return OUTPUT_DIR / f"post_{stamp}_{suffix}.txt"


def generate_all(weather: Dict[str, Any]) -> int:
    analysis = analyze_weather(weather)
    state = _load_state()
    include_first = _should_include_first_post(state)
    if include_first:
        print("📌 本次将加入首帖问候（完成后会更新 data/state.json）")
    else:
        print("ℹ️  非首帖模式（避免每日重复开场白）")

    stamp = datetime.now(HK_TZ).strftime("%Y-%m-%d_%H%M")
    saved = 0
    used_first_for_social = False

    for platform in PLATFORMS:
        label = PLATFORM_LABELS[platform]
        first_for_this = include_first and platform in (
            "instagram",
            "whatsapp",
        ) and not used_first_for_social
        try:
            print(f"\n🤖 正在生成 {label}...")
            content = generate_content(
                weather, analysis, platform, first_for_this, state
            )
            if _is_duplicate(platform, content, state):
                print(f"⚠️ {label} 与上次 hash 相同，已尝试换句式生成", file=sys.stderr)

            path = _output_path(platform, stamp)
            path.write_text(content, encoding="utf-8")
            state.setdefault("last_hashes", {})[platform] = _content_hash(content)
            if first_for_this:
                used_first_for_social = True
            saved += 1
            print(f"✅ 已保存: output/{path.name}")
            print(f"\n--- {label} ---\n{content}\n")
        except (ValueError, APIError, APIConnectionError, RateLimitError) as e:
            if isinstance(e, APIError):
                print(f"❌ {label}: {format_deepseek_api_error(e)}", file=sys.stderr)
            else:
                print(f"❌ {label}: {e}", file=sys.stderr)

    if include_first and used_first_for_social:
        state["first_post_completed"] = True
    _save_state(state)

    manifest = {
        "generated_at_hkt": datetime.now(HK_TZ).isoformat(),
        "weather_fingerprint": weather_fingerprint(weather),
        "platforms": list(PLATFORMS),
        "stamp": stamp,
    }
    (OUTPUT_DIR / "latest_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return saved


def main() -> int:
    print("正在从 HKO 开放数据拉取沙田自动气象站数据...")
    try:
        weather = get_shatin_weather()
    except Exception as e:
        print(f"❌ 天气数据获取失败: {e}", file=sys.stderr)
        return 1

    print_weather(weather)
    print(f"📊 {analyze_weather(weather)['briefing']}\n")

    if not has_deepseek_api_key():
        print("⚠️  未设置 DEEPSEEK_API_KEY，社交/YouTube 文案使用本地模板（含日期）\n")

    saved = generate_all(weather)
    if saved == 0:
        print("❌ 未能生成任何内容", file=sys.stderr)
        return 1
    print(f"\n🎉 共生成 {saved}/{len(PLATFORMS)} 份文案，见 output/ 目录")
    return 0


if __name__ == "__main__":
    sys.exit(main())
