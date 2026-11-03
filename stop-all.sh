#!/bin/bash
# ============================================================
#  停止 NapCat(实例1: 3888750292) 与 RzyL NoneBot 机器人
# ------------------------------------------------------------
#  ⚠️ 本脚本只针对 3888750292 这一套。
#     绝不会碰第二个 NapCat 实例 (3655026431 / BLBot)。
#     第二个实例请用: bash ~/blbot-napcat/stop-blbot-napcat.sh
# ============================================================

MY_QQ=3888750292

echo "=========================================="
echo "正在终止 NapCat(实例1 $MY_QQ) 与 RzyL 机器人进程..."
echo "=========================================="

# 1. 终止 RzyL 机器人（uv 父进程 + venv python 子进程）
pkill -f 'uv run bot.py' 2>/dev/null
pkill -f 'RzyL/.venv/bin/python3 bot.py' 2>/dev/null

# 2. 终止 NapCat/QQ —— 只杀实例1
#    正则 no-sandbox.*-q <QQ> 可容忍 --disable-gpu 等参数插在中间；
#    不可写成 'qq --no-sandbox -q <QQ>'（加了禁GPU参数后就匹配不到了）
pkill -f "no-sandbox.*-q $MY_QQ" 2>/dev/null

# 3. 终止日志轮转监视进程（由 start-all*.sh / start-bot.sh 启动）
pkill -f 'rotate-logs.sh --watch' 2>/dev/null

echo "已发送终止信号，等待 3 秒..."
sleep 3

echo ""
echo "=========================================="
echo "进程状态检查"
echo "=========================================="

bot_alive=false
napcat_alive=false

if pgrep -f 'uv run bot.py' >/dev/null || pgrep -f 'RzyL/.venv/bin/python3 bot.py' >/dev/null; then
    bot_alive=true
fi

if pgrep -f "no-sandbox.*-q $MY_QQ" >/dev/null; then
    napcat_alive=true
fi

if [ "$bot_alive" = true ]; then
    echo "[机器人] ❌ 仍在运行，相关进程如下："
    ps -eo pid,cmd | grep -E 'uv run bot.py|RzyL/.venv/bin/python3 bot.py' | grep -v grep
else
    echo "[机器人] ✅ 已终止"
fi

if [ "$napcat_alive" = true ]; then
    echo "[NapCat/QQ 实例1] ❌ 仍在运行，相关进程如下："
    ps -eo pid,cmd | grep -E "no-sandbox.*-q $MY_QQ" | grep -v grep
else
    echo "[NapCat/QQ 实例1] ✅ 已终止"
fi

if pgrep -f 'rotate-logs.sh --watch' >/dev/null; then
    echo "[日志轮转] ❌ 仍在运行，相关进程如下："
    ps -eo pid,cmd | grep -E 'rotate-logs.sh --watch' | grep -v grep
else
    echo "[日志轮转] ✅ 已终止"
fi

# 友好提示：第二实例未受影响
if pgrep -f 'no-sandbox.*-q 3655026431' >/dev/null; then
    echo "[NapCat/QQ 实例2] ✅ 未受影响（3655026431 仍在运行）"
fi

echo "=========================================="
