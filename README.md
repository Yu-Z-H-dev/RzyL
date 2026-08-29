# RzyL - 物理实验查询机器人

基于 NoneBot2 的 QQ 机器人，提供物理实验图片查询功能，支持精确匹配和 AI 模糊匹配，并附带彩蛋插件（迪士尼角色、教师图片、AI 拟人图片与随机文本）。

## 功能特性

- **关键词匹配**：支持精确匹配和 AI 模糊匹配物理实验关键词
- **图片查询**：根据关键词返回对应的实验图片（.jpg 格式）
- **多关键词支持**：一次查询可返回多个匹配的实验图片
- **智能回退**：精确匹配失败时自动使用 AI 进行模糊匹配
- **随机语言**：有概率发送随机一言或小问题，增加互动趣味
- **速率限制**：每用户每 60 秒最多 10 次请求，防止滥用
- **彩蛋系统**：以「类 + 个体 + 复合体」组织彩蛋图片，支持类别/个体级可见性开关
- **彩蛋 AI 回退**：彩蛋精确未命中时先用 AI 模糊匹配出图，仍无匹配则作为对话机器人引用回复用户发言
- **AI 请求优化**：长连接会话复用 + 分段超时（connect/sock_read/total）+ 并发可配置

## 安装

1. 克隆项目
2. 安装依赖：

   ```bash
   uv sync
   ```

## 配置

复制 `.env.secret.temple` 为 `.env.secret`，并根据需要配置 `.env`（OneBot 连接）与 `.env.secret`（AI API 密钥）。

### `.env.secret`（AI 匹配与群组过滤）

```env
BASE_URL=https://api.longcat.chat/openai/v1  # OpenAI 兼容 API 地址
API_KEY="your_api_key"                        # AI 匹配所需的 API Key
MODEL_CHAT=""                                 # 对话模型（彩蛋对话回退使用）
MODEL_THINK=""                                # 推理模型（彩蛋/大雾模糊匹配使用）
MODEL_LITE=""                                 # 轻量模型
AI_TIMEOUT=180                                # AI 请求总超时秒数（默认 180，三个 AI 插件共用）
AI_CONCURRENCY=5                              # AI 请求并发上限（默认 5）
DAWU_ALLOWED_GROUPS=                          # 允许使用大雾1插件的群号，逗号分隔，留空全部放行
DAWU2_ALLOWED_GROUPS=                         # 允许使用大雾2插件的群号，逗号分隔，留空全部放行
DAWU_ALLOWED_GROUPS=                          # 允许使用大雾1插件的群号，逗号分隔，留空全部放行
DAWU2_ALLOWED_GROUPS=                         # 允许使用大雾2插件的群号，逗号分隔，留空全部放行
# 彩蛋对话回退提示词改为独立文件 src/asserts/easter_egg/prompt_chat.md（见「彩蛋系统说明」），不再从 env 读取
```

### `.env`（NoneBot 与 OneBot 连接）

```env
HOST=0.0.0.0
PORT=8080
COMMAND_START=[""]
COMMAND_SEP=[""]
ONEBOT_ACCESS_TOKEN=     # 与 NapCat 等 OneBot 客户端配置一致
ENVIRONMENT=secret
ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]
DRIVER=~aiohttp
```

> `.env` 与 `.env.secret` 均已被 `.gitignore` 忽略，属敏感文件，永不提交。

## 使用方法

### 基本命令

| 命令 | 说明 |
|------|------|
| `大雾1 <实验名>` | 查询物理实验图片，精确/AI 模糊匹配 |
| `大雾1 ls` | 列出所有关键词 |
| `大雾1 help` | 帮助信息 |
| `大雾2 <实验名>` | 查询二级大雾题库（考试题目图片），精确/AI 模糊匹配 |
| `大雾2 ls` | 列出所有关键词 |
| `大雾2 help` | 帮助信息 |
| `彩蛋 <角色/教师>` | 彩蛋查询，精确/AI 模糊匹配；均无匹配时作为对话机器人回复 |
| `彩蛋 ls` | 按类列出所有可用彩蛋 |
| `彩蛋 help` | 彩蛋帮助信息 |

### 示例

```
大雾1 杨氏模量        # 返回杨氏模量实验图片
大雾1 示波器          # 返回示波器使用图片
大雾2 霍尔效应        # 返回二级题库霍尔效应题目图片
彩蛋 玲娜贝儿         # 返回迪士尼角色图片
彩蛋 四大善人         # 返回复合彩蛋（多位教师照片）
彩蛋 那个粉色狐狸     # 精确未命中，AI 模糊匹配到玲娜贝儿并出图
彩蛋 今天好累啊       # 无任何彩蛋匹配，作为对话机器人引用回复你的发言
彩蛋 ls               # 按类列出所有可用彩蛋
彩蛋 help             # 查看彩蛋帮助
```

## 项目结构

```
RzyL/
├── bot.py                      # 机器人入口：init + 注册 OneBot v11 + load_plugins
├── pyproject.toml              # 项目配置（nonebot2 / alconna / onebot.v11 / aiohttp）
├── uv.lock                     # 依赖锁定
├── .env.secret.temple          # 密钥配置模板
├── scripts/
│   └── slice_dawu2.py          # 二级大雾题库 PDF 切图脚本
└── src/
    ├── asserts/                # 静态资源目录（图片 + 关键词 JSON）
    │   ├── dawu/               #   大雾1 实验图片 + keywords.json
    │   ├── dawu2/              #   大雾2 题库图片（27 实验）+ keywords.json
    │   └── easter_egg/                #   彩蛋资源目录（图片 + 注册表 + 对话提示词）
    │       ├── keywords.example.json  #     注册表配置模板（真实 keywords.json 本地不同步）
    │       ├── prompt_chat.example.md #     空占位文件（真实 prompt_chat.md 本地不同步）
    │       ├── factor/                 #     人物类（教师照片 + bxh/cj/pjw 子目录）
    │       ├── LLM/            #     AI 拟人类（GLM/Qwen/Gemini/Grok/Claude/DeepSeek/ChatGPT）
    │       ├── Origin/         #     达菲朋友们类（初始开发者遗留图片）
    │       ├── cjx/            #     顶层多照片个体
    │       ├── Nico/           #     顶层多照片个体
    │       ├── CrazyThursday/  #     顶层多照片个体
    │       ├── Dory.jpg        #     顶层单照片个体
    │       └── ustc.jpg        #     顶层单照片个体
    └── plugins/
        ├── dawu/               # 主插件（大雾1）
        │   ├── __init__.py     #   命令处理
        │   ├── config.py       #   配置、群组过滤
        │   ├── keywords.py     #   关键词加载器
        │   └── ai_match.py     #   AI 模糊匹配
        ├── dawu2/              # 题库插件（大雾2），与 dawu 同构
        ├── easter_egg/         # 彩蛋插件
        │   ├── __init__.py     #   命令处理 + 类/个体/复合体出图 + AI 回退
        │   ├── ai_match.py     #   AI 模糊匹配 + 对话回退（OpenAI 兼容 API）
        │   ├── keywords.py     #   注册表解析（含 enabled 过滤）
        │   ├── random_text.py  #   随机文本加载
        │   ├── sentences.txt   #   随机一言
        │   └── question.txt    #   小问题
        └── echo/               # Echo 示例插件
```

## 彩蛋系统说明

彩蛋资源以「类 + 个体 + 复合体」三级模型组织，由 `src/asserts/easter_egg/keywords.json` 统一描述：

- **类（category）**：`factor`（人物）、`LLM`（AI 拟人）、`Origin`（达菲朋友们），每个类可整体开关（`enabled`）。
- **个体（entity）**：可被查询的最小编，分两种形态：
  - `mode: "file"` —— 单照片个体，输出唯一一张；
  - `mode: "dir"` —— 多照片个体（文件夹），随机输出一张。
- **顶层个体**：直接位于 `easter_egg/` 下、不属于任何类的个体，可单独设置 `enabled`。
- **复合体（compound）**：一个关键词映射到多个 target 个体（如 `four_sages` → 四位教师），其可见性受 target 所属类约束。
- **可见性规则**：只有「类」和「顶层个体」持有 `enabled` 开关；类内个体跟随所属类；不可见项查询不响应、也不在 `彩蛋 ls` 中列出。

### 彩蛋 AI 模糊匹配与对话回退

`彩蛋 <name>` 的处理顺序为：

1. **精确匹配**：按别名直接相等匹配个体与复合体，命中则出图（含随机文本）。
2. **AI 模糊匹配**：精确未命中时，把所有可见个体/复合体的别名交给 `MODEL_THINK` 做模糊匹配，命中则出图（前缀「AI 匹配到」）。
3. **对话回退**：AI 也未匹配（即输入与任何彩蛋无关）时，把用户原文交给 `MODEL_CHAT` 生成回复，并以**引用**方式回复该用户的发言——此时机器人充当对话机器人。

- 预设提示词从独立文件 `src/asserts/easter_egg/prompt_chat.md`（UTF-8，可任意换行排版；`prompt_chat.example.md` 仅为空占位文件）加载：文件缺失、无法读取或内容为空时**不附加任何提示词**，直接把用户在彩蛋后的原话交给 `MODEL_CHAT`（等价于直接向 AI 询问）；`MODEL_CHAT` 留空时对话回退不可用（会提示「对话服务未配置」）。
- AI 路径（模糊匹配 + 对话回退）按用户限流，每 60 秒最多 10 次请求。

### AI 请求实现与性能调优

三个 AI 插件（大雾1 / 大雾2 / 彩蛋）共用同一套 OpenAI 兼容调用逻辑（`ai_match.py`），为避免推理模型请求超时做了如下处理：

- **长连接会话复用**：模块级 `ClientSession` 复用（`connector.limit` 与并发上限一致，`ttl_dns_cache=300`），退出时由 `driver.on_shutdown` 关闭，避免每次请求重复 TCP/TLS 握手。
- **分段超时**：`ClientTimeout(connect=30, sock_read=120, total=AI_TIMEOUT)`——连接、两次读取间隔、总时长分别设限，容忍大模型流式生成停顿。
- **并发可控**：`asyncio.Semaphore(AI_CONCURRENCY)`，默认 5，防止并发突刺冲击 API。

相关配置（`.env.secret`）：

```env
AI_TIMEOUT=180       # AI 请求总超时秒数（默认 180，三个插件共用）
AI_CONCURRENCY=5     # AI 请求并发上限（默认 5）
```

若仍有 `AI 请求超时` 日志：先判断卡在哪个阶段（日志中的 connect 阶段 / 读响应停顿 sock_read / 总时长 total），再决定调大 `AI_TIMEOUT`（提升 total）还是降低 `AI_CONCURRENCY`（减少对 API 的冲击）。

## 技术栈

- **框架**：NoneBot2
- **适配器**：OneBot v11
- **命令解析**：Alconna
- **HTTP 客户端**：aiohttp（异步）
- **AI 匹配**：OpenAI 兼容 API

## 开发

运行机器人：

```bash
uv run bot.py
```

类型检查：

```bash
uv run pyright
```

## 许可证

MIT