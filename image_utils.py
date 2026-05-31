"""天气帖文配图：提示词构建 + 多后端出图。"""

import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from deepseek_utils import chat_completion, has_deepseek_api_key

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


def build_image_prompt_en(weather: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    """根据实况生成英文文生图提示（模型对英文更稳）。"""
    temp = weather["air_temperature"]
    rh = weather["relative_humidity"]
    rain = weather["total_rainfall"]
    wind = weather["wind_speed"]
    direction = weather["wind_direction"]
    headline = analysis.get("headline", "")

    scene = "overcast humid" if rh >= 75 else "clear pleasant"
    if float(rain) > 5:
        scene = "rainy wet streets umbrellas"
    elif float(rain) > 0:
        scene = "light rain drizzle"
    if float(temp) >= 30:
        scene += ", hot summer haze"
    elif float(temp) <= 18:
        scene += ", cool crisp air"

    return (
        f"Professional weather photo for social media, Sha Tin district Hong Kong, "
        f"{scene}, {direction} wind, realistic documentary style, soft natural light, "
        f"subtle Hong Kong residential hills in background, no text no watermark no logos, "
        f"atmospheric mood reflecting {headline}, 8k photorealistic"
    )


def refine_prompt_with_deepseek(base_prompt: str) -> str:
    if not has_deepseek_api_key():
        return base_prompt
    try:
        refined = chat_completion(
            f"""Rewrite this image generation prompt in English only (max 80 words).
Keep: Sha Tin Hong Kong weather scene, photorealistic, no text/watermark.
Input: {base_prompt}
Output prompt only:""",
            max_tokens=120,
            temperature=0.7,
        )
        return refined.strip() or base_prompt
    except Exception:
        return base_prompt


def download_pollinations(
    prompt: str,
    width: int,
    height: int,
    output_path: Path,
    timeout: int = 120,
) -> Path:
    encoded = urllib.parse.quote(prompt, safe="")
    seed = abs(hash(prompt)) % 999999
    url = (
        f"{POLLINATIONS_BASE}/{encoded}"
        f"?width={width}&height={height}&nologo=true&seed={seed}"
    )
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def download_openai_image(
    prompt: str,
    size: str,
    output_path: Path,
) -> Path:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    result = client.images.generate(
        model="dall-e-3",
        prompt=prompt[:4000],
        size=size,
        quality="standard",
        n=1,
    )
    image_url = result.data[0].url
    if not image_url:
        raise ValueError("OpenAI 未返回图片 URL")
    response = requests.get(image_url, timeout=60)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def render_pillow_card(
    weather: Dict[str, Any],
    analysis: Dict[str, Any],
    output_path: Path,
    size: Tuple[int, int] = (1080, 1080),
) -> Path:
    """无 AI API 时生成简约天气信息图（本地渲染）。"""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    img = Image.new("RGB", (w, h), (41, 98, 150))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 52)
        body_font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 36)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    lines = [
        "沙田區天氣｜香港天文台數據",
        f"氣溫 {weather['air_temperature']}°C  濕度 {weather['relative_humidity']}%",
        f"雨量(1h) {weather['total_rainfall']} mm",
        f"{weather['wind_direction']}風 {weather['wind_speed']} km/h",
        analysis.get("headline", "")[:40],
    ]
    draw.text((60, 60), lines[0], fill=(255, 255, 255), font=title_font)
    y = 160
    for line in lines[1:]:
        draw.text((60, y), line, fill=(230, 240, 255), font=body_font)
        y += 56

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG", optimize=True)
    return output_path


def generate_weather_image(
    weather: Dict[str, Any],
    analysis: Dict[str, Any],
    output_path: Path,
    width: int,
    height: int,
    provider: Optional[str] = None,
) -> Tuple[Path, str, str]:
    """
    生成一张配图。返回 (路径, 实际使用的 provider, 最终 prompt)。
    provider: auto | pollinations | openai | pillow
    """
    provider = (provider or os.environ.get("IMAGE_PROVIDER", "auto")).lower()
    base_prompt = build_image_prompt_en(weather, analysis)
    prompt = refine_prompt_with_deepseek(base_prompt)

    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
            provider = "openai"
        else:
            provider = "pollinations"

    if provider == "openai":
        size = "1792x1024" if width > height else "1024x1024"
        if width == height:
            size = "1024x1024"
        return (
            download_openai_image(prompt, size, output_path),
            "openai",
            prompt,
        )

    if provider == "pollinations":
        try:
            return (
                download_pollinations(prompt, width, height, output_path),
                "pollinations",
                prompt,
            )
        except requests.RequestException:
            provider = "pillow"

    path = render_pillow_card(weather, analysis, output_path, (width, height))
    return path, "pillow", prompt
