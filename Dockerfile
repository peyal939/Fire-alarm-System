FROM python:3.12.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run via Daphne (ASGI server for Django Channels)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
