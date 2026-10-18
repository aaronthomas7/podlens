#!/usr/bin/env bash
# Deploy PodLens to Cloud Run in one go. Run it from this folder in Cloud Shell
# (or anywhere gcloud is logged in). Safe to run again: every step is idempotent.
#
#   bash deploy.sh                      # uses your current gcloud project
#   PROJECT_ID=my-proj REGION=asia-southeast1 bash deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-podlens}"
MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
SA_NAME="podlens-run"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "No project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi
echo "==> Deploying '${SERVICE}' to project ${PROJECT_ID} (${REGION})"

# IAM changes can take a few seconds to reach every Google service, so retry.
bind() {
  local member="$1" role="$2"
  for attempt in 1 2 3 4 5; do
    if gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member "${member}" --role "${role}" --condition=None --quiet >/dev/null 2>&1; then
      return 0
    fi
    sleep $((attempt * 4))
  done
  echo "    Warning: couldn't grant ${role} to ${member}"
  return 1
}

echo "==> Enabling APIs (first run takes a minute or two)"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com firestore.googleapis.com iam.googleapis.com \
  compute.googleapis.com \
  --project "${PROJECT_ID}"

SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "==> Service account ${SA}"
if ! gcloud iam service-accounts describe "${SA}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" --display-name "PodLens on Cloud Run" --project "${PROJECT_ID}"
  sleep 8
fi
for ROLE in roles/aiplatform.user roles/datastore.user roles/logging.logWriter; do
  bind "serviceAccount:${SA}" "${ROLE}" || true
done

# Source deploys build with the Compute Engine default service account.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format 'value(projectNumber)')"
bind "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" roles/run.builder || true

echo "==> Firestore (stores finished checks so share links work)"
USE_FIRESTORE=1
if ! gcloud firestore databases describe --database="(default)" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  if ! gcloud firestore databases create --location="${REGION}" --type=firestore-native --project "${PROJECT_ID}" --quiet; then
    echo "    Couldn't create Firestore; results will be kept in memory only."
    USE_FIRESTORE=0
  fi
fi

EXTRA_ENV=""
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo "==> Using a Gemini API key (Gemini Developer API) for model calls"
  EXTRA_ENV=",GEMINI_API_KEY=${GEMINI_API_KEY}"
fi

echo "==> Building and deploying (3 to 5 minutes)"
gcloud run deploy "${SERVICE}" \
  --source . \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --service-account "${SA}" \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 \
  --timeout 900 \
  --concurrency 40 \
  --max-instances 3 \
  --update-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=${MODEL},USE_FIRESTORE=${USE_FIRESTORE}${EXTRA_ENV}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')"
echo
echo "==> Live at: ${URL}"
echo "==> Health check:"
curl -fsS "${URL}/api/health" && echo || echo "(not answering yet; try again in a few seconds)"
