# Deploying to Google Cloud Run

The repository includes a production container for the Streamlit application.
It listens on `0.0.0.0` and uses the `PORT` value supplied by Cloud Run, with
`8080` as the local default.

## Prerequisites

- A Google Cloud project with billing enabled
- The Google Cloud CLI installed and authenticated
- An existing Supabase project and `incidents` table
- Permission to deploy Cloud Run services and use Secret Manager

Set the project-specific shell variables used below:

```sh
export PROJECT_ID="your-google-cloud-project"
export REGION="us-central1"
export SERVICE="multimodal-incident-analyzer"
gcloud config set project "$PROJECT_ID"
```

Enable the required Google Cloud APIs:

```sh
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

## Configure secrets

Create Secret Manager secrets named `SUPABASE_URL` and `SUPABASE_KEY` through
the Google Cloud console or CLI. Do not put their values in the Dockerfile,
source code, build arguments, or a committed `.env` file.

The identity used by the Cloud Run service needs the
`roles/secretmanager.secretAccessor` role for these two secrets. For tighter
access control, use a dedicated service account rather than the project's
default compute service account.

## Build locally (optional)

```sh
docker build -t multimodal-incident-analyzer .
docker run --rm -p 8080:8080 \
  --env-file .env \
  multimodal-incident-analyzer
```

Open `http://localhost:8080`. The `.env` file is passed only at runtime and is
excluded from the image build context.

## Deploy

Cloud Run can build the checked-in Dockerfile with Cloud Build:

```sh
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --cpu 2 \
  --memory 4Gi \
  --concurrency 1 \
  --timeout 3600 \
  --set-secrets="SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_KEY:latest"
```

The conservative concurrency setting prevents multiple Whisper or YOLO jobs
from competing for the same instance memory. Adjust CPU, memory, concurrency,
and timeout after observing real evidence sizes and processing duration.

The command keeps the service private. Grant intended users the Cloud Run
Invoker role. Use `--allow-unauthenticated` only if public access to uploaded
incident evidence is an explicit requirement.

## Runtime behavior

- Uploaded files and processor CSVs use the container's writable filesystem.
  Cloud Run storage is ephemeral, so Supabase remains the durable data store.
- Whisper and YOLO have safe defaults; set these only when you want to override
  runtime behavior:

  ```sh
  WHISPER_MODEL=small.en
  WHISPER_DEVICE=cpu
  VIDEO_YOLO_SAMPLE_STRIDE=2
  VIDEO_YOLO_IMAGE_SIZE=640
  VIDEO_YOLO_MODEL_PATH=video/yolov8s.pt
  ```

  Use `WHISPER_MODEL=medium.en` for higher accuracy on a faster instance, or
  `WHISPER_MODEL=base.en` if startup/latency matters more.
- Whisper and YOLO download model weights on first use. This increases the
  first processing request's latency, and each new instance has its own cache.
- FFmpeg and Tesseract are installed in the image for audio transcription and
  scanned-PDF OCR.
- The image uses CPU-only PyTorch and headless OpenCV; it does not require a
  display server or CUDA runtime.

## Updating the service

After application or dependency changes, rerun the same `gcloud run deploy`
command. Cloud Run creates a new revision and shifts traffic only after the new
container starts successfully.

View logs with:

```sh
gcloud run services logs read "$SERVICE" --region "$REGION" --limit 100
```
