FROM python:3.12-slim

WORKDIR /app
COPY . .

ENV PORT=8788
EXPOSE 8788

CMD ["python", "backend/app.py"]
