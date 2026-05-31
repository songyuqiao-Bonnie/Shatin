# shatin-weather-bot

从香港天文台（HKO）开放数据拉取**沙田自动气象站**实况，一次生成多平台文案。

## 一键生成

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY="sk-你的密钥"   # 可选；未设置则用本地模板

python generate_posts.py
```

输出目录 `output/`：

| 文件 | 平台 |
|------|------|
| `post_*_instagram.txt` | Instagram |
| `post_*_whatsapp.txt` | WhatsApp |
| `post_*_youtube.txt` | YouTube 社群帖 |
| `script_*_youtube.txt` | YouTube 视频发言稿 |

## 模块

| 文件 | 作用 |
|------|------|
| `generate_posts.py` | **主程序**（四平台统一入口） |
| `shatin_weather.py` | HKO API 拉取与分析 |
| `deepseek_utils.py` | DeepSeek API |
| `data/state.json` | 首帖是否已发、各平台上次文案 hash（防重复） |

## GitHub Actions

- 每天 **HKT 08:10** 运行 `generate_posts.py`
- Secret：`DEEPSEEK_API_KEY`
- 产物在 **Artifacts**；`data/state.json` 会由 bot 提交回仓库（记录首帖与去重）

## 为何以前会「七天重复」？

1. **首帖逻辑**：旧版用 `post_*.txt` 判断是否首帖，但生成文件被 gitignore，Actions 每次空目录 → **天天当首帖**，开场白相同。  
2. **现已改为** `data/state.json` 记录，跑过一次后不再加首帖问候。  
3. **提示词** 已加入香港日期、运行编号、观测指纹与去重要求。

手动再发「首帖」：`INCLUDE_FIRST_POST_GREETING=true python generate_posts.py`（仅当需要时）。

## 数据来源

HKO `data.weather.gov.hk` — 沙田站气温/湿度/风况 + rhrread 雨量
