# Tennis Match Tracker - SportsWatcher

Track your favorite tennis players and automatically sync their upcoming matches to your Google Calendar.

## Features

- **Search ATP/WTA Players**: Find any ranked tennis player
- **Follow Players**: Track multiple players simultaneously
- **Auto-Sync to Google Calendar**: Matches are automatically added to your calendar
- **Match Updates**: Calendar events update when schedules change
- **Smart Notifications**: Get reminders before matches

## Architecture

```
                                    ┌─────────────────┐
                                    │  Cloud Storage  │
                                    │   (Frontend)    │
                                    └────────┬────────┘
                                             │
                                             ▼
┌──────────────┐    ┌─────────────────────────────────────┐
│  Tennis API  │◄───│          Cloud Functions            │
│  (RapidAPI)  │    │  ┌─────────────────────────────┐   │
└──────────────┘    │  │       api_gateway           │   │
                    │  │  (REST API for frontend)    │   │
┌──────────────┐    │  └─────────────────────────────┘   │
│   Google     │◄───│  ┌─────────────────────────────┐   │
│  Calendar    │    │  │      sync_players           │   │
│     API      │    │  │  (Daily player refresh)     │   │
└──────────────┘    │  └─────────────────────────────┘   │
                    │  ┌─────────────────────────────┐   │
┌──────────────┐    │  │      sync_matches           │   │
│  Firestore   │◄───│  │  (Match sync every 6hrs)   │   │
│  (Database)  │    │  └─────────────────────────────┘   │
└──────────────┘    └─────────────────────────────────────┘
                                    ▲
                                    │
                              Cloud Scheduler
```

## Prerequisites

1. **Google Cloud Platform Account** with billing enabled
2. **Tennis API Key** from [RapidAPI](https://rapidapi.com/api-sports/api/api-tennis) - for live matches and rankings
3. **SerpAPI Key** from [SerpAPI](https://serpapi.com/) - for scheduled match data (free tier: 100 searches/month)
4. **Google OAuth Credentials** for Calendar API

## Setup

### 1. Clone and Configure

```bash
git clone <repo-url>
cd sportswatcher

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
```

### 2. Set Up GCP Project

```bash
# Create project (or use existing)
gcloud projects create your-project-id

# Set as active project
gcloud config set project your-project-id

# Enable billing (required)
# Visit: https://console.cloud.google.com/billing

# Enable required APIs
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    firestore.googleapis.com \
    calendar-json.googleapis.com \
    cloudscheduler.googleapis.com
```

### 3. Create Firestore Database

```bash
# Create Firestore in Native mode
gcloud firestore databases create --region=us-central1
```

### 4. Set Up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI:
   ```
   https://YOUR_REGION-YOUR_PROJECT.cloudfunctions.net/api_gateway/auth/callback
   ```
4. Note down Client ID and Client Secret

### 5. Get API Keys

**Tennis API (RapidAPI)**:
1. Sign up at [RapidAPI](https://rapidapi.com)
2. Subscribe to [TennisApi1](https://rapidapi.com/api-sports/api/tennisapi1) (free tier available)
3. Copy your API key

**SerpAPI** (for scheduled matches):
1. Sign up at [SerpAPI](https://serpapi.com/)
2. Get your API key from the dashboard (free tier: 100 searches/month)
3. Copy your API key

### 6. Set Environment Variables

```bash
# Export for deployment
export TENNIS_API_KEY="your-rapidapi-key"
export SERPAPI_KEY="your-serpapi-key"
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export FRONTEND_URL="https://storage.googleapis.com/your-project-frontend/index.html"
```

### 7. Deploy

```bash
cd deploy

# Deploy Cloud Functions
chmod +x deploy.sh
./deploy.sh your-project-id us-central1

# Set up Cloud Scheduler
chmod +x scheduler-setup.sh
./scheduler-setup.sh your-project-id us-central1

# Deploy Frontend
chmod +x deploy-frontend.sh
./deploy-frontend.sh your-project-id
```

### 8. Update Frontend Configuration

Edit `frontend/app.js` and update `API_BASE`:

```javascript
const API_BASE = 'https://us-central1-your-project-id.cloudfunctions.net/api_gateway';
```

Then redeploy the frontend:

```bash
./deploy-frontend.sh your-project-id
```

## Usage

1. Visit your frontend URL
2. Sign in with Google
3. Search for tennis players (e.g., "Sinner", "Alcaraz")
4. Click "Follow" on players you want to track
5. Matches will automatically appear in your Google Calendar!

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/players?q=query` | Search players |
| GET | `/players/followed` | Get followed players |
| POST | `/players/follow` | Follow a player |
| DELETE | `/players/follow/:id` | Unfollow a player |
| GET | `/auth/google` | Start OAuth flow |
| GET | `/user/profile` | Get user profile |
| GET | `/health` | Health check |

## Development

### Local Testing

```bash
cd functions

# Install dependencies
pip install -r ../requirements.txt

# Run locally
functions-framework --target=api_gateway --debug --port=8080
```

### Running Tests

```bash
cd functions
pytest ../tests/
```

## Rate Limits

The free tier of Tennis API allows:
- 100 requests per day
- 10 requests per minute

The app is designed to stay well within these limits with aggressive caching.

## Troubleshooting

### OAuth Redirect Error
- Ensure redirect URI in Google Console matches exactly
- Include the `/auth/callback` path

### No Players Found
- Run `sync_players` manually to populate database
- Check API key is valid

### Calendar Events Not Appearing
- Verify OAuth scopes include calendar.events
- Check user has valid tokens (try re-authenticating)

## License

MIT
