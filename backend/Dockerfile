FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
RUN useradd --create-home --uid 10001 appuser
USER 10001
EXPOSE 8081
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8081"]
