# Repository Guidelines

## 项目概述

基于 NoneBot2（Python 3.11）的 QQ 机器人，为物理实验课提供图片查询：

- **大雾1**：按实验名返回物理实验图片；
- **大雾2**：按实验名返回二级大雾题库（考试题目）图片；
- **彩蛋**：按名称返回彩蛋图片；精确与 AI 均未命中时，作为对话机器人回复用户。

前两者与彩蛋都走「精确匹配 → AI 模糊匹配」两级回退，彩蛋另多一级「对话回退」。大雾1 与大雾2 完全同构。

## 项目结构

```
RzyL/
├── bot.py                      # 入口：nonebot.init + 注册 OneBot v11 + load_plugins("src/plugins")
├── pyproject.toml / uv.lock    # 依赖（nonebot2 / alconna / onebot.v11 / aiohttp）
├── pyrightconfig.json          # 类型检查配置（指向 .venv）
├── .env.secret.temple          # 密钥模板；复制为 .env.secret 后填真实值
├── scripts/slice_dawu2.py      # 二级大雾题库 PDF 切图脚本（键→页范围硬编码在脚本里）
└── src/
    ├── asserts/                # 静态资源（图片 + 关键词 JSON），不是 Python 包
    │   ├── dawu/               #   大雾1：{英文键}.jpg + keywords.json
    │   ├── dawu2/              #   大雾2：{英文键}.jpg（27 张）+ keywords.json（27 键）
    │   └── easter_egg/         #   彩蛋资源（详见「彩蛋插件」一节）
    │       ├── keywords.example.json   # 注册表模板（真实 keywords.json 被 gitignore）
    │       ├── prompt_chat.example.md  # 空占位（真实 prompt_chat.md 被 gitignore）
    │       ├── factor/ LLM/ Origin/    # 类内个体资源（factor、Origin 当前 enabled=false）
    │       ├── cjx/ Nico/ CrazyThursday/  # 顶层多照片个体（cjx 当前 enabled=false）
    │       └── Dory.jpg ustc.jpg       # 顶层单照片个体
    ├── utils/                  # 跨插件公共代码
    │   ├── safe_send.py        #   safe_send / safe_finish：发送失败不抛出、不中断流程
    │   └── ai_error.py         #   format_ai_error：错误码 → 可区分原因的中文提示
    └── plugins/
        ├── dawu/               # 大雾1
        ├── dawu2/              # 大雾2（与 dawu 同构，两个目录的文件逐字节相同）
        ├── easter_egg/         # 彩蛋
        └── echo/               # 示例插件，代码全部被注释，实际未启用
```

资源加载统一用 `Path(__file__).parent.parent.parent / "asserts" / ...` 定位；图片路径常用 `Path.cwd() / "src" / "asserts" / ...`。

## 开发命令

```bash
uv sync              # 安装依赖
uv run bot.py        # 运行机器人（OneBot v11 适配器）
uv run pyright       # 静态类型检查（pyrightconfig.json 指向 .venv）
```

若 `uv` 不在 PATH（例如非交互 SSH），可直接用 `.venv/bin/python` / `.venv/bin/pyright`；VM 上 `uv` 位于 `/opt/vlab/bin`。

无测试框架。改动后用 `uv run pyright` + 实际命令验证。

## 命令一览

| 命令 | 说明 |
|------|------|
| `大雾1 <实验名>` | 查询物理实验图片，精确 / AI 模糊匹配 |
| `大雾1 ls` | 列出所有关键词 |
| `大雾1 help` | 帮助信息 |
| `大雾2 <实验名>` | 查询二级大雾题库（考试题目图片），精确 / AI 模糊匹配 |
| `大雾2 ls` | 列出所有关键词 |
| `大雾2 help` | 帮助信息 |
| `彩蛋 <名称>` | 彩蛋查询，精确 / AI 模糊匹配；均未命中时作为对话机器人回复 |
| `彩蛋 ls` | 按类列出所有可见彩蛋 |
| `彩蛋 help` | 彩蛋帮助信息 |

## 核心机制

### 大雾1 / 大雾2（同构）

- **注册**：`on_alconna(Alconna("大雾1", Args["name", str]), rule=Rule(check_group), priority=0, block=True)`。
- **群组过滤**：`config.py` 读 `dawu_allowed_groups` / `dawu2_allowed_groups`（两者独立），留空放行全部群。`_parse_groups` 兼容 str / int / list——NoneBot 加载自定义配置时会先 `json.loads`，单个群号会变成 int、JSON 数组会变成 list。
- **精确匹配**：`find_keywords`（定义在 `__init__.py`，不在 `keywords.py`）对每个别名做**子串**匹配（`alias in text`），因此一次输入可命中多个键。`keywords.py` 只负责顶层 `json.loads`。
- **缺失图片**：命中键但 `{键}.jpg` 不存在时，汇总提示缺失的图片文件名。
- **AI 回退**：精确未命中 → `ai_match(text, KEYWORDS)`，调用 OpenAI 兼容 `/chat/completions`。
- **速率限制**：按 `user_id` 每 60 秒最多 10 次。
- **彩蛋联动**：`from src.plugins.easter_egg import try_load_random_text`，出图后按概率追加随机一言。

### 彩蛋插件 easter_egg

彩蛋资源以「类 + 个体 + 复合体」三级模型组织，全部由 `src/asserts/easter_egg/keywords.json` 描述（**该文件是本地配置，被 gitignore，不在版本库里**）：

- **类（category）**：`factor` / `LLM` / `Origin`，各自有 `enabled` 开关。
- **个体（entity）**：`mode: "file"` 单照片（探测多种扩展名），`mode: "dir"` 多照片（目录内随机取一张）。
- **顶层个体**：不属任何类，自身带 `enabled`。
- **复合体（compound）**：一个键映射到多个 target 个体；**所有 target 可见时才可见**。
- **可见性规则**：`enabled` 只挂在「类」和「顶层个体」上，类内个体跟随所属类；不可见项不出现在 `彩蛋 ls` 中，精确匹配也不命中。

查询顺序：**精确匹配**（别名直接相等）→ **AI 模糊匹配** → **对话回退**（引用用户发言）。AI 路径按用户限流，每 60 秒 10 次。

- **动态示例**：`彩蛋 help` 的「例如」行、裸发「彩蛋」的提示、`彩蛋 ls` 的分组，全部由 `keywords.py:build_help_examples()` 从**当前可见集合**实时生成。新增功能时不要在文案里硬编码彩蛋名——被禁用的名字会立刻变成错误提示。
- **AI 返回值**：`easter_egg/ai_match.py` 的 `ai_match` 保证返回的键一定存在于传入的 `keywords` 中（会过滤模型杜撰的键），调用方可放心按 key 取值。
- **对话提示词**：从 `src/asserts/easter_egg/prompt_chat.md` 加载（本地配置、gitignore）；文件缺失或为空时不附加任何提示词。

### AI 调用

三个插件**各自持有一份 `ai_match.py`**（大雾1 与大雾2 的两份逐字节相同；彩蛋那份另含对话回退）。修改其中一个时，注意是否需要同步另外两个。

- **配置**：`base_url` / `api_key` / `model_think`（模糊匹配）/ `model_chat`（对话回退）；`AI_TIMEOUT` 默认 180 秒，`AI_CONCURRENCY` 默认 5。
- **并发**：`asyncio.Semaphore(AI_CONCURRENCY)`，每个插件各一个信号量。
- **瞬时故障重试**：HTTP 500/502/503/504/529、网络错误、超时会重试 1 次（退避 1 秒）。
- **长连接与分段超时**：模块级 `ClientSession` 复用，`ClientTimeout(connect=30, sock_read=120, total=AI_TIMEOUT)`。
- **错误码**：`config` / `timeout` / `network` / `parse` / `http_<status>` / `unknown`，由 `src/utils/ai_error.py` 翻译成可区分原因的中文提示。注意「AI 成功但无匹配」不是错误（error 为 `None`）。

## 配置与安全

- 复制 `.env.secret.temple` → `.env.secret`，填入 `BASE_URL` / `API_KEY` / `MODEL_CHAT` / `MODEL_THINK` / `MODEL_LITE`，以及可选的 `AI_TIMEOUT` / `AI_CONCURRENCY` / `DAWU_ALLOWED_GROUPS` / `DAWU2_ALLOWED_GROUPS`。
- `.env`、`.env.secret`、`src/asserts/easter_egg/keywords.json`、`src/asserts/easter_egg/prompt_chat.md` 均被 `.gitignore` 忽略，永不提交。分享日志时同样注意 API 响应中的敏感内容。

## 代码风格与命名

使用惯用 Python，4 空格缩进，需要处加类型注解，网络与 bot 操作一律用 async API。保持模块职责单一：命令路由在 `__init__.py`，配置在 `config.py`，外部 API 逻辑在 `ai_match.py`。函数、变量、模块用 `snake_case`，常量用 `UPPER_SNAKE_CASE`。除非任务明确要求改文案，否则保留现有中文命令与用户可见消息。

## 测试与验证

无测试框架，也不要在没有框架的情况下新增测试文件。改动行为后至少做到：

1. `uv run pyright`（或 `.venv/bin/pyright`）零错误；
2. 用真实命令走一遍关键路径：精确匹配、AI 回退、`ls`、`help`、群组过滤（若改了配置）；
3. 资源名与关键词键保持一致，保证查表行为可预期。

VM 上有项目自身的 venv 和真实配置，可直接驱动插件真实 handler 做端到端验证（`nonebot.init()` + 加载 alconna + 直接调用 handler 并替换 `safe_finish`/`safe_send` 收集输出），比在本地造数据更接近真实。

## 提交规范

使用 Conventional Commits 风格，常带 scope，例如 `feat(dawu): 更新关键词`、`fix(easter_egg): 修正 help 示例`。说明里写清行为变更、验证步骤；用户可见的改动附上机器人输出示例。

## 改动前必读的坑

- **变更链路**：本地 commit → 推到 GitHub → VM 上 `git pull --ff-only` → **重启 bot**（改 Python 必须重启才生效）。不要用 `ssh_upload` 直接覆盖 VM 上的文件，那会让 VM 与 git 记录分叉，后续 `pull` 冲突。
- **VM 重启方式**：`bash start-bot.sh`。它只 `pkill -f 'uv run bot.py'`，不碰 NapCat，因此不会触发重新扫码。启动后看 `bot_output.log` 确认插件加载与 `OneBot V11 | Bot <QQ> connected`。
- **禁用 ≠ 删除**：`enabled: false` 只是不可见，资源仍在仓库里（如 `factor/`、`Origin/`）。文档与提示语里不要写死彩蛋名，用 `build_help_examples()` 之类从可见集合生成。
- **本地没有 `keywords.json`**：它是 gitignore 的本地配置，只在 VM 上。改彩蛋相关行为前，先到 VM 读真实配置，否则会基于错误的前提改动（本地直接跑 `load_entities()` 会抛 `FileNotFoundError`）。
- **切图页码映射**：硬编码在 `scripts/slice_dawu2.py`。题库更新后必须**逐页**核对实验标题与页码，不能想当然——曾出现「双臂电桥」由单页变跨页，导致其后所有实验页码 +1。
- **`二级大雾题库/`**：当前目录里**只有 `二级大雾题库.pdf`**，LaTeX 源码（`main.tex` 等）不在仓库中；该目录整体被 gitignore。重新切片需先自备 PDF。

## 许可证

MIT
