#!/bin/bash
# Set up Cloud Scheduler jobs for Tennis Match Tracker
# Usage: ./scheduler-setup.sh [project-id] [region]

set -e

# Configuration
PROJECT_ID="${1:-your-project-id}"
REGION="${2:-us-central1}"

echo "=========================================="
echo "Cloud Scheduler Setup"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Set project
gcloud config set project "$PROJECT_ID"

# Create service account for scheduler if it doesn't exist
SA_NAME="scheduler-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Setting up service account..."
gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Cloud Scheduler Invoker" \
    --quiet 2>/dev/null || echo "Service account already exists"

# Grant invoker permissions to the service account
echo "Granting invoker permissions..."
for func in sync_players sync_matches cleanup_events; do
    gcloud functions add-invoker-policy-binding "$func" \
        --region="$REGION" \
        --member="serviceAccount:${SA_EMAIL}" \
        --quiet 2>/dev/null || echo "Permission already granted for $func"
done

# Create scheduler jobs
echo ""
echo "Creating scheduler jobs..."

# Daily player sync at 3 AM UTC
echo "Creating sync-players-daily job..."
gcloud scheduler jobs create http sync-players-daily \
    --location="$REGION" \
    --schedule="0 3 * * *" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/sync_players" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet 2>/dev/null || \
gcloud scheduler jobs update http sync-players-daily \
    --location="$REGION" \
    --schedule="0 3 * * *" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/sync_players" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet

# Match sync every 6 hours
echo "Creating sync-matches-periodic job..."
gcloud scheduler jobs create http sync-matches-periodic \
    --location="$REGION" \
    --schedule="0 */6 * * *" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/sync_matches" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet 2>/dev/null || \
gcloud scheduler jobs update http sync-matches-periodic \
    --location="$REGION" \
    --schedule="0 */6 * * *" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/sync_matches" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet

# Weekly cleanup on Sundays at 2 AM UTC
echo "Creating cleanup-events-weekly job..."
gcloud scheduler jobs create http cleanup-events-weekly \
    --location="$REGION" \
    --schedule="0 2 * * 0" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/cleanup_events" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet 2>/dev/null || \
gcloud scheduler jobs update http cleanup-events-weekly \
    --location="$REGION" \
    --schedule="0 2 * * 0" \
    --time-zone="UTC" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/cleanup_events" \
    --http-method=POST \
    --oidc-service-account-email="$SA_EMAIL" \
    --quiet

echo ""
echo "=========================================="
echo "Scheduler setup complete!"
echo "=========================================="
echo ""
echo "Created jobs:"
echo "- sync-players-daily: Runs at 3 AM UTC daily"
echo "- sync-matches-periodic: Runs every 6 hours"
echo "- cleanup-events-weekly: Runs at 2 AM UTC on Sundays"
echo ""
echo "You can manually trigger a job with:"
echo "  gcloud scheduler jobs run sync-players-daily --location=$REGION"
