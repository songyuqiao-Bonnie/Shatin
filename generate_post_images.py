"""
沙田天气帖文配图生成

流程：HKO 实况 →（可选 DeepSeek 优化英文提示词）→ AI 出图 / 本地信息图
默认使用 Pollinations 免费文生图（无需额外 API Key）。
可选：OPENAI_API_KEY + IMAGE_PROVIDER=openai 使用 DALL·E 3。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from deepseek_utils import configure_stdio_utf8
from image_utils import generate_weather_image
from shatin_weather import analyze_weather, get_shatin_weather, print_weather

configure_stdio_utf8()

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output" / "images"
HK_TZ = ZoneInfo("Asia/Hong_Kong")

# 各平台推荐尺寸
SPECS = (
    ("square", 1080, 1080, "Instagram / WhatsApp 方图"),
    ("youtube", 1280, 720, "YouTube 横图 / 缩略图"),
)


def main() -> int:
    print("正在拉取沙田天气并生成配图...")
    try:
        weather = get_shatin_weather()
    except Exception as e:
        print(f"❌ 天气数据获取失败: {e}", file=sys.stderr)
        return 1

    print_weather(weather)
    analysis = analyze_weather(weather)
    print(f"📊 {analysis['briefing']}\n")

    stamp = datetime.now(HK_TZ).strftime("%Y-%m-%d_%H%M")
    manifest: dict = {
        "stamp": stamp,
        "images": [],
        "weather_fingerprint": weather.get("record_time"),
    }

    for name, w, h, label in SPECS:
        out = OUTPUT_DIR / f"weather_{stamp}_{name}.png"
        print(f"🖼️  正在生成 {label} ({w}×{h})...")
        try:
            path, provider, prompt = generate_weather_image(
                weather, analysis, out, w, h
            )
            print(f"✅ {path.name}（{provider}）")
            manifest["images"].append(
                {
                    "file": path.name,
                    "platform_hint": label,
                    "provider": provider,
                    "prompt_en": prompt[:500],
                }
            )
        except Exception as e:
            print(f"❌ {name} 失败: {e}", file=sys.stderr)

    if not manifest["images"]:
        print("❌ 未生成任何配图", file=sys.stderr)
        return 1

    meta_path = OUTPUT_DIR / f"images_{stamp}_manifest.json"
    meta_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n🎉 共生成 {len(manifest['images'])} 张配图")
    print(f"📁 目录: {OUTPUT_DIR}")
    print(f"📄 说明: {meta_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
