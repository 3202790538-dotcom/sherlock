#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .venv312/bin/python ]]; then
  echo '缺少 Python 环境，请先配置 .venv312。'
  read
  exit 1
fi
.venv312/bin/python -m gui.app
