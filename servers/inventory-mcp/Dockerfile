FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "mcp>=1.9,<2.0"
COPY servers/inventory-mcp/app/main.py /app/main.py
RUN useradd --create-home --uid 10001 appuser
USER 10001
EXPOSE 8000
CMD ["python", "main.py"]
