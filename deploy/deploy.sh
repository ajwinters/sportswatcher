#!/bin/bash
# Deploy Cloud Functions for Tennis Match Tracker
# Usage: ./deploy.sh [project-id] [region]

set -e

# Configuration
PROJECT_ID="${1:-your-project-id}"
REGION="${2:-us-central1}"
FUNCTIONS_DIR="../functions"

echo "=========================================="
echo "Tennis Match Tracker - Deployment Script"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI not found. Please install it first."
    exit 1
fi

# Set project
echo "Setting project..."
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    firestore.googleapis.com \
    calendar-json.googleapis.com \
    cloudscheduler.googleapis.com \
    --quiet

# Deploy API Gateway
echo ""
echo "Deploying api_gateway function..."
gcloud functions deploy api_gateway \
    --gen2 \
    --runtime=python312 \
    --region="$REGION" \
    --source="$FUNCTIONS_DIR" \
    --entry-point=api_gateway \
    --trigger-http \
    --allow-unauthenticated \
    --memory=256MB \
    --timeout=60s \
    --set-env-vars="TENNIS_API_KEY=${TENNIS_API_KEY},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET},OAUTH_REDIRECT_URI=https://${REGION}-${PROJECT_ID}.cloudfunctions.net/api_gateway/auth/callback,FRONTEND_URL=${FRONTEND_URL:-https://storage.googleapis.com/${PROJECT_ID}-frontend/index.html}"

# Deploy sync_players
echo ""
echo "Deploying sync_players function..."
gcloud functions deploy sync_players \
    --gen2 \
    --runtime=python312 \
    --region="$REGION" \
    --source="$FUNCTIONS_DIR" \
    --entry-point=sync_players \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --set-env-vars="TENNIS_API_KEY=${TENNIS_API_KEY}"

# Deploy sync_matches
echo ""
echo "Deploying sync_matches function..."
gcloud functions deploy sync_matches \
    --gen2 \
    --runtime=python312 \
    --region="$REGION" \
    --source="$FUNCTIONS_DIR" \
    --entry-point=sync_matches \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --set-env-vars="TENNIS_API_KEY=${TENNIS_API_KEY},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}"

# Deploy cleanup_events
echo ""
echo "Deploying cleanup_events function..."
gcloud functions deploy cleanup_events \
    --gen2 \
    --runtime=python312 \
    --region="$REGION" \
    --source="$FUNCTIONS_DIR" \
    --entry-point=cleanup_events \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=256MB \
    --timeout=300s \
    --set-env-vars="GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "API Gateway URL:"
echo "https://${REGION}-${PROJECT_ID}.cloudfunctions.net/api_gateway"
echo ""
echo "Next steps:"
echo "1. Run scheduler-setup.sh to set up Cloud Scheduler jobs"
echo "2. Deploy frontend to Cloud Storage"
echo "3. Update FRONTEND_URL environment variable if needed"
