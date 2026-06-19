# YKS

YKS is a small self-hosted dashboard experiment for tracking a personal collection over time.

It includes:

- a lightweight FastAPI web interface
- local SQLite persistence
- Docker Compose deployment
- CSV and database export helpers
- optional Basic Auth for local-only use

## Local Run

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open:

```text
http://localhost:8000
```

## Notes

This repository is intended for local use and small private deployments. Configuration is handled through `.env`; see `.env.example` for available values.
