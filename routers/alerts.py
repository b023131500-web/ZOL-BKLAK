# ============================================================
# Price Comparison Bot — Environment Variables
# Copy to .env and fill in real values. Never commit .env.
# ============================================================

# PostgreSQL connection
DATABASE_URL=postgresql+asyncpg://price_bot_user:CHANGE_ME@localhost:5432/price_bot

# API server
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=info

# Cron schedule (default: 03:00 every day)
CRON_HOUR=3
CRON_MINUTE=0

# Admin token for /api/admin/trigger-fetch  (used by Lovable dashboard)
ADMIN_TOKEN=CHANGE_ME_TO_A_LONG_RANDOM_STRING

# Optional: Sentry DSN for error tracking
# SENTRY_DSN=https://xxx@sentry.io/yyy
