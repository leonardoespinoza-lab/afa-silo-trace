FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8788
EXPOSE 8788

CMD ["python", "backend/app.py"]
