FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY servers/woocommerce-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt "uvicorn[standard]>=0.30,<1.0"
COPY servers/woocommerce-mcp/app/main.py /app/main.py
RUN useradd --create-home --uid 10001 appuser
USER 10001
EXPOSE 8000
CMD ["python", "main.py"]
