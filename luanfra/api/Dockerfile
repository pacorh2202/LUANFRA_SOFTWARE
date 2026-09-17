FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# pandas y openpyxl van dentro para poder cargar los export del ERP sin
# instalar Python en el ordenador: todo se ejecuta dentro del contenedor.
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" sqlalchemy "psycopg[binary]" \
    pydantic-settings python-dateutil python-multipart \
    pandas openpyxl
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
