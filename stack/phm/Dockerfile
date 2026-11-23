FROM docker.io/library/python:3.11-slim-bookworm
RUN useradd -r -u 10001 phm
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY phm_worker.py thermal_model.py /app/
USER phm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp
ENTRYPOINT ["python", "/app/phm_worker.py"]
