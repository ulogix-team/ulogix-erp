FROM python:3.12-slim
# evita segfaults (exit 139) de OpenBLAS/statsmodels en WSL/Docker
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
# sin esto, los print() del middleware quedan buffereados y 'docker compose
# logs' se ve vacio aunque el proceso este corriendo bien
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app/Inicio.py", "--server.address=0.0.0.0", "--server.port=8501"]
