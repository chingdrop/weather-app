FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

ENV HOST=0.0.0.0 \
    PORT=5000 \
    FLASK_DEBUG=0

EXPOSE 5000

CMD ["python", "main.py"]