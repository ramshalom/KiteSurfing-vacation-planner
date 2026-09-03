FROM python:3.12-slim

WORKDIR /app

# System deps: none needed beyond what pip installs pull in for this project
# (reportlab/crewai/streamlit are all pure-Python-installable wheels).

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects the PORT env var (defaults to 8080) and expects the
# container to listen on 0.0.0.0 at that port - both flags are required or
# the service fails health checks and never goes live.
ENV STREAMLIT_SERVER_HEADLESS=true
EXPOSE 8080
CMD streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0
