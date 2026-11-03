#!/bin/bash
# NapCat 启动脚本（可写数据目录版）
# 适用于根文件系统只读、仅 /home/ubuntu/RzyL 与 /tmp 可写的环境。
# 原理：通过 unshare 用户+挂载命名空间，把可写目录 bind mount 到
#       NapCat/QQ 原本只读的配置、缓存、日志、QQ 数据目录。
set -e

NAPCAT_DATA=/home/ubuntu/RzyL/napcat-data

echo "[start-napcat-rw] 停止旧 NapCat/QQ 进程..."
pkill -f 'qq --no-sandbox' 2>/dev/null || true
pkill -f 'bash start-napcat.sh' 2>/dev/null || true
sleep 1

export DISPLAY=:99

if ! pgrep -f 'Xvfb :99' >/dev/null 2>&1; then
  echo "[start-napcat-rw] 启动 Xvfb :99 ..."
  Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
fi

LOGFILE="$NAPCAT_DATA/start_output.log"
echo "[start-napcat-rw] 启动 NapCat（可写目录已挂载）..."
echo "[start-napcat-rw] WebUI: http://127.0.0.1:6099"
echo "[start-napcat-rw] 日志: $LOGFILE"

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
exec qq --no-sandbox
' >> "$LOGFILE" 2>&1 &
echo "[start-napcat-rw] 已启动，等待 QQ 登录..."
tail -40 /home/ubuntu/Rzyl/napcat-data/start_output.log

