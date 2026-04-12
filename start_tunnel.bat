@echo off
echo ===================================================
echo Запуск туннеля для Telegram WebApp (порт 8080)
echo ===================================================
echo.
echo После запуска скопируйте ссылку (начинается с https:// и заканчивается на .lhr.life)
echo и вставьте в main.py в переменную WEBAPP_URL.
echo.
ssh -o StrictHostKeyChecking=no -R 80:127.0.0.1:8080 nokey@localhost.run
pause
