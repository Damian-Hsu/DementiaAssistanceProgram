#!/bin/bash
set -e

# 確保掛載的目錄有正確權限
chown -R appuser:appuser /recordings /var/log/streaming
chmod -R u+rwX /recordings /var/log/streaming

# 切換到 appuser 並執行主程序
exec gosu appuser "$@"

