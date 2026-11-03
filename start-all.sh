#!/bin/bash
export PATH="$PATH:/opt/vlab/bin"
# 一键启动 NapCat（二维码登录） + NoneBot 机器人
# 适用于根文件系统只读、仅 /home/ubuntu/RzyL 与 /tmp 可写的环境。

NAPCAT_DATA=/home/ubuntu/RzyL/napcat-data
LOGFILE="$NAPCAT_DATA/start_output.log"
BOT_LOG=/home/ubuntu/RzyL/bot_output.log
ROTATE_SCRIPT=/home/ubuntu/RzyL/scripts/rotate-logs.sh
MY_QQ=3888750292

echo "=========================================="
echo "[start-bot-all] 启动前先轮转超额日志..."
echo "=========================================="
if [ -x "$ROTATE_SCRIPT" ]; then
  "$ROTATE_SCRIPT" --once || true
else
  echo "[start-bot-all] ⚠️ 未找到日志轮转脚本，跳过: $ROTATE_SCRIPT"
fi

echo "=========================================="
echo "[start-bot-all] 停止旧 NapCat/QQ 与机器人进程..."
echo "=========================================="
# 只杀实例1：用正则容忍 --disable-gpu 等参数插在中间（见 start-all.sh 历史坑）
pkill -f "no-sandbox.*-q $MY_QQ" 2>/dev/null || true
pkill -f 'bash start-napcat.sh' 2>/dev/null || true
pkill -f 'uv run bot.py' 2>/dev/null || true
pkill -f 'RzyL/.venv/bin/python3 bot.py' 2>/dev/null || true
sleep 1

export DISPLAY=:99

if ! pgrep -f 'Xvfb :99' >/dev/null 2>&1; then
  echo "[start-bot-all] 启动 Xvfb :99 ..."
  Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
  sleep 2
fi

echo "=========================================="
echo "[start-bot-all] 启动 NapCat（默认账号）..."
echo "=========================================="

unshare -Urm bash -c '
export NAPCAT_HOME=/home/ubuntu/.napcat-config
export DISPLAY=:99

# 1) 让 QQ 加载 NapCat 入口（修改后的 package.json）
mount --bind /home/ubuntu/RzyL/napcat-data/package.json /opt/QQ/resources/app/package.json

# 2) NapCat 的 config/cache/logs 改为可写目录
mount --bind /home/ubuntu/RzyL/napcat-data/config /home/ubuntu/napcat/config
mount --bind /home/ubuntu/RzyL/napcat-data/cache /home/ubuntu/napcat/cache
mount --bind /home/ubuntu/RzyL/napcat-data/logs /home/ubuntu/napcat/logs

# 3) QQ 登录数据目录改为可写目录
mount --bind /home/ubuntu/RzyL/qq-data/QQ /home/ubuntu/.config/QQ
mount --bind /home/ubuntu/RzyL/napcat-home/QQ /home/ubuntu/.napcat-config/QQ

cd /home/ubuntu/napcat
exec qq --no-sandbox \
  --disable-gpu --disable-gpu-compositing --disable-software-rasterizer --disable-dev-shm-usage --disable-features=UseOzonePlatform \
  -q 3888750292
' >> "$LOGFILE" 2>&1 &

echo "[start-bot-all] NapCat 已后台启动，等待 3 秒后启动机器人..."
sleep 3

echo "=========================================="
echo "[start-bot-all] 启动 NoneBot 机器人..."
echo "[start-bot-all] 机器人日志: $BOT_LOG"
echo "=========================================="

cd /home/ubuntu/RzyL
export UV_CACHE_DIR=/tmp/uv-cache
nohup uv run bot.py > "$BOT_LOG" 2>&1 &

# 启动后台日志监视：每 60 秒检查一次，超过 50MiB 即轮转（copytruncate + gzip，无需重启进程）
if [ -x "$ROTATE_SCRIPT" ]; then
  pkill -f 'rotate-logs.sh --watch' 2>/dev/null || true
  nohup "$ROTATE_SCRIPT" --watch > /dev/null 2>&1 &
  echo "[start-bot-all] 日志监视已启动（阈值 50MiB / 保留 24 小时）"
fi

sleep 5

echo "=========================================="
echo "[start-bot-all] 进程状态检查"
echo "=========================================="

if pgrep -f "no-sandbox.*-q $MY_QQ" >/dev/null; then
  echo "[NapCat/QQ 实例1 $MY_QQ] ✅ 已启动"
else
  echo "[NapCat/QQ 实例1 $MY_QQ] ❌ 未启动"
fi

if pgrep -f 'RzyL/.venv/bin/python3 bot.py' >/dev/null; then
  echo "[机器人] ✅ 已启动"
else
  echo "[机器人] ❌ 未启动"
fi

echo "=========================================="
echo "NapCat 日志: $LOGFILE"
echo "机器人日志: $BOT_LOG"
