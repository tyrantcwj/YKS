# YKS

YKS is a small self-hosted dashboard experiment for tracking a personal collection over time.

It includes:

- a lightweight FastAPI web interface
- local SQLite persistence
- Docker Compose deployment
- in-place source update helper
- CSV and database export helpers
- optional Basic Auth for local-only use

## Local Run

```powershell
docker compose up -d
```

Open:

```text
http://localhost:8000
```

## Notes

This repository is intended for local use and small private deployments. Configuration is handled through `.env`; see `.env.example` for available values.
