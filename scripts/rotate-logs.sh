#!/bin/bash
# 日志轮转脚本（适配只读根文件系统环境）
#
# 背景：当 NapCat 未就绪时，NoneBot 的 OneBot v11 正向 WS 会每 3 秒重连一次并
#       打印整段 Traceback（约 15 行），即每秒数行；NapCat/QQ 自身的 stdout 同样
#       持续增长。原先日志为 nohup 裸追加，永不轮转，会快速吃满磁盘。
#
# 本机限制（已实测）：
#   - /etc 与 /var/lib/logrotate 均为只读，无 sudo，crontab 不可用
#   => 无法使用标准 logrotate 配置 + cron.daily 方案
#   因此本脚本自带轮转逻辑，配置与状态全部放在项目可写目录内，无需 root。
#
# 策略：单文件超过 MAX_SIZE 即轮转，copytruncate 语义（复制后清空原文件），
#       归档 gzip 压缩，按【分钟数】保留（RETAIN_MINUTES），不重启、不重定向
#       任何进程，对运行中的进程安全。
#
# 变更历史：
#   2026-10-13  阈值 5MiB→50MiB；归档 gzip 压缩；保留期由 RETAIN_DAYS=1(-mtime +1)
#               改为 RETAIN_MINUTES=1440，修复「find -mtime +1 至少要 2 整天、
#               当天归档当天删不掉」导致 10-11 一天堆 10×61M 的 bug。
#
# 用法：
#   ./scripts/rotate-logs.sh          # 按大小检查并轮转（幂等，可反复调用）
#   ./scripts/rotate-logs.sh --watch  # 常驻循环，每 INTERVAL 秒检查一次
#   ./scripts/rotate-logs.sh --once   # 同默认
#   ./scripts/rotate-logs.sh --prune-only  # 只清理过期归档，不轮转
#
# 退出码：0 成功（含无需轮转）；1 参数错误。

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$PROJECT_DIR/.log-rotate"
MAX_SIZE_BYTES=$((50 * 1024 * 1024))     # 50 MiB
RETAIN_MINUTES=1440                       # 归档保留分钟数（=1 天）
INTERVAL=60                               # --watch 模式的检查间隔（秒）

# 需要纳入轮转的日志文件（可继续追加）
LOG_FILES=(
  "$PROJECT_DIR/bot_output.log"
  "$PROJECT_DIR/napcat-data/start_output.log"
)

log_msg() {
  # 轮转脚本自身的输出绝不可写入被轮转的文件，避免自我循环
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [rotate-logs] $*"
}

file_size() {
  # 输出文件字节数；文件不存在或不可读时输出 0
  if [[ -f "$1" ]]; then
    stat -c '%s' "$1" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

# 清理超过保留期的归档。归档两种形态：
#   新：<name>.YYYYmmdd-HHMMSS.log.gz
#   旧：<name>.YYYYmmdd-HHMMSS.log   （兼容历史遗留，一并纳入清理）
# 用 -mmin 按分钟判定，避免 -mtime 的「整天取整 + 必须 >N 整天」陷阱。
prune_old_archives() {
  local target="$1" dir name
  dir="$(dirname "$target")"
  name="$(basename "$target")"
  find "$dir" -maxdepth 1 -type f \( -name "${name}.*.log" -o -name "${name}.*.log.gz" \) \
    -mmin "+$RETAIN_MINUTES" -print -delete 2>/dev/null | while read -r f; do
    log_msg "删除过期归档: $f"
  done
}

rotate_one() {
  local target="$1" size ts archive
  size="$(file_size "$target")"

  if [[ ! -f "$target" ]]; then
    return 0
  fi

  if (( size < MAX_SIZE_BYTES )); then
    return 0
  fi

  ts="$(date '+%Y%m%d-%H%M%S')"
  archive="${target}.${ts}.log"

  # copytruncate 语义：先复制到归档，再清空原文件。
  # 运行中的进程持有的是同一个 inode，清空后继续写入同一文件，无需重启。
  # 注意：复制与清空之间新写入的少量日志会丢失，对高频重复报错场景可接受。
  if ! cp "$target" "$archive" 2>/dev/null; then
    log_msg "复制失败，跳过: $target"
    return 1
  fi

  if ! : > "$target" 2>/dev/null; then
    log_msg "清空失败，回滚归档: $target"
    rm -f "$archive"
    return 1
  fi

  log_msg "已轮转: $target ($(( size / 1024 )) KiB) -> $archive"

  # 压缩归档，失败则保留未压缩版本（不阻塞主流程）
  if gzip -f "$archive" 2>/dev/null; then
    log_msg "已压缩: ${archive}.gz"
  else
    log_msg "压缩失败，保留未压缩归档: $archive"
  fi

  prune_old_archives "$target"
  return 0
}

rotate_all() {
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  for f in "${LOG_FILES[@]}"; do
    rotate_one "$f" || true
  done
}

prune_all() {
  for f in "${LOG_FILES[@]}"; do
    if [[ -f "$f" ]]; then
      prune_old_archives "$f"
    fi
  done
}

# ---------------- 主流程 ----------------

case "${1:---once}" in
  --once)
    rotate_all
    exit 0
    ;;
  --prune-only)
    prune_all
    exit 0
    ;;
  --watch)
    log_msg "启动监视模式：每 ${INTERVAL}s 检查一次，阈值 $(( MAX_SIZE_BYTES / 1024 / 1024 )) MiB，保留 $(( RETAIN_MINUTES / 60 )) 小时"
    while true; do
      rotate_all
      sleep "$INTERVAL"
    done
    ;;
  *)
    echo "用法: $0 [--once|--watch|--prune-only]" >&2
    exit 1
    ;;
esac
