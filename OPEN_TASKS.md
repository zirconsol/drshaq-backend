# Open Tasks

1. Replace runtime schema alterations in `app/database.py` with formal migrations (Alembic or equivalent).
   - Create versioned migrations for all tracking/request schema changes.
   - Remove ad-hoc `ALTER TABLE` logic once migration rollout is complete.
   - Validate zero-downtime behavior for multi-instance deployments.
