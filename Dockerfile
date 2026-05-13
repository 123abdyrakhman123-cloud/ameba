FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Запускаем через скрипт: инициализируем БД на volume, потом стартуем бота
CMD ["sh", "-c", "python init_db.py && python -u main.py"]
