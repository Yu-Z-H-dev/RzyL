#!/bin/bash
export PATH="$PATH:/opt/vlab/bin"
# 启动 NoneBot2 机器人
cd /home/ubuntu/RzyL
ROTATE_SCRIPT=/home/ubuntu/RzyL/scripts/rotate-logs.sh

# 启动前先轮转超额日志，避免旧的大文件一直被追加
if [ -x "$ROTATE_SCRIPT" ]; then
  "$ROTATE_SCRIPT" --once || true
fi

pkill -f 'uv run bot.py' 2>/dev/null || true
sleep 1
export UV_CACHE_DIR=/tmp/uv-cache
nohup uv run bot.py > /home/ubuntu/RzyL/bot_output.log 2>&1 &

# 启动后台日志监视：每 60 秒检查一次，超过 50MiB 即轮转（copytruncate + gzip，无需重启进程）
if [ -x "$ROTATE_SCRIPT" ]; then
  pkill -f 'rotate-logs.sh --watch' 2>/dev/null || true
  nohup "$ROTATE_SCRIPT" --watch > /dev/null 2>&1 &
  echo "日志监视已启动（阈值 50MiB / 保留 24 小时）"
else
  echo "⚠️ 未找到日志轮转脚本，跳过: $ROTATE_SCRIPT"
fi

echo "机器人已启动，日志: /home/ubuntu/RzyL/bot_output.log"
