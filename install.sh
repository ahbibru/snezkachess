#!/bin/bash

# Выходим сразу, если произойдет любая ошибка
set -e

echo "=== 1. Обновление системы и установка зависимостей ==="
sudo apt update
sudo apt install -y stockfish python3-pip python3-venv python3-dev git

echo "=== 2. Создание изолированного окружения Python ==="
python3 -m venv venv
source venv/bin/activate

echo "=== 3. Установка библиотек ==="
pip install -r requirements.txt

echo "=== 4. Настройка автозапуска через Systemd ==="
CURRENT_DIR=$(pwd)

sudo bash -c "cat > /etc/systemd/system/chess-analysis.service <<EOF
[Unit]
Description=Flask Chess Analysis Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python $CURRENT_DIR/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

echo "=== 5. Запуск службы ==="
sudo systemctl daemon-reload
sudo systemctl enable chess-analysis
sudo systemctl start chess-analysis

echo "======================================================"
echo " Установка успешно завершена!"
echo " Сайт доступен по адресу: http://IP_ВАШЕГО_VPS:5000"
echo "======================================================"
