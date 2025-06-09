# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем Java (JDK)
RUN apt-get update && apt-get install -y default-jdk

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем и устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код проекта
COPY . .

# Команда для запуска сервера
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]
# CMD exec gunicorn app:app --bind 0.0.0.0:$PORT