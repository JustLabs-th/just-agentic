Run pending Alembic migrations.

```bash
cd /Users/jin/dev/just-agentic && alembic upgrade head 2>&1
```

Show which migrations were applied. If error, show the full traceback.
