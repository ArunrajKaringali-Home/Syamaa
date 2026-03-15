FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the SQLite DB directory exists
RUN mkdir -p instance static

# Environment defaults (override at runtime)
ENV ADMIN_EMAIL=admin@syamaa.com
ENV ADMIN_PASSWORD=Syamaa@2025
ENV FLASK_ENV=production

EXPOSE 5000

CMD ["python3", "app.py"]
