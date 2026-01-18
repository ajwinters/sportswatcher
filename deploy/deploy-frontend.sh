#!/bin/bash
# Deploy frontend to Google Cloud Storage
# Usage: ./deploy-frontend.sh [project-id]

set -e

PROJECT_ID="${1:-your-project-id}"
BUCKET_NAME="${PROJECT_ID}-frontend"
FRONTEND_DIR="../frontend"

echo "=========================================="
echo "Frontend Deployment"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Bucket: $BUCKET_NAME"
echo ""

# Set project
gcloud config set project "$PROJECT_ID"

# Create bucket if it doesn't exist
echo "Creating storage bucket..."
gsutil mb -p "$PROJECT_ID" "gs://${BUCKET_NAME}" 2>/dev/null || echo "Bucket already exists"

# Make bucket public
echo "Setting bucket permissions..."
gsutil iam ch allUsers:objectViewer "gs://${BUCKET_NAME}"

# Set website configuration
echo "Configuring website hosting..."
gsutil web set -m index.html -e index.html "gs://${BUCKET_NAME}"

# Upload frontend files
echo "Uploading frontend files..."
gsutil -m cp -r "${FRONTEND_DIR}/*" "gs://${BUCKET_NAME}/"

# Set cache headers
echo "Setting cache headers..."
gsutil -m setmeta -h "Cache-Control:public, max-age=3600" "gs://${BUCKET_NAME}/*.html"
gsutil -m setmeta -h "Cache-Control:public, max-age=86400" "gs://${BUCKET_NAME}/*.css"
gsutil -m setmeta -h "Cache-Control:public, max-age=86400" "gs://${BUCKET_NAME}/*.js"

echo ""
echo "=========================================="
echo "Frontend deployment complete!"
echo "=========================================="
echo ""
echo "Frontend URL:"
echo "https://storage.googleapis.com/${BUCKET_NAME}/index.html"
echo ""
echo "Don't forget to update:"
echo "1. API_BASE in app.js with your Cloud Function URL"
echo "2. FRONTEND_URL in Cloud Functions with this URL"
