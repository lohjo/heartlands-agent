# Heartland Commons

A voice-first AI platform for Singapore heartland merchants and the communities
around them. Three interlocking parts, built in sequence:

1. **AI Copilot** — a voice-first business assistant for merchants (this phase).
2. **Discovery Trail + Digital Passport** — QR stamps, merchant stories, rewards.
3. **Volunteer Management System** — students propose & run projects for merchants.

The Copilot is adapted from [`soar-main`](https://github.com/lohjo/soar-main)
(Google ADK + Gemini Live API) — infrastructure patterns kept, medical domain
stripped. Architecture decisions and the ADR ledger live in `CLAUDE.md`.

---

## Local Setup

### Prerequisites
- Python 3.11+
- `gcloud` CLI authenticated (`gcloud auth application-default login`)
- A Google Cloud project with the Vertex AI API enabled
- (For persistence) a Firestore database created in **`asia-southeast1`** (PDPA)

### 1. Clone
```bash
git clone https://github.com/lohjo/heartlands-agent.git
cd heartlands-agent
```

### 2. Create and activate a Python environment
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```
Or with conda:
```bash
conda create -n heartland python=3.11
conda activate heartland
pip install -e .
```

### 3. Configure environment variables
```bash
cp app/.env.template app/.env
```
Edit `app/.env` (placeholders shown):
```env
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=heartland-commons
GOOGLE_CLOUD_LOCATION=us-central1
DEMO_AGENT_MODEL=gemini-live-2.5-flash-native-audio
COPILOT_VOICE=Aoede
FIRESTORE_DATABASE=(default)
SEA_LION_URL=
```
> **Never commit `app/.env`.** Verify the current model id at
> https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models

### 4. Authenticate with Google Cloud
```bash
gcloud auth application-default login
gcloud config set project your-gcp-project-id
```

### 5. Run the server
```bash
cd app
uvicorn main:app --reload --port 8080
```
> **Critical:** run `uvicorn` from inside the `app/` directory. Running from the
> project root causes `ModuleNotFoundError` for `soar_orchestrator`.

### 6. Open the console
- App: http://localhost:8080
- Copilot console: http://localhost:8080/console — click the **mic** to start a
  session and allow microphone access. A merchant is identified by the
  `?merchant=<id>` query param (defaults to `demo_merchant`).

> Without GCP credentials the app still boots: Firestore and Vertex degrade
> gracefully (in-memory state, no persistence). Live voice requires Vertex AI.

---

## Region strategy (PDPA)
Gemini Live native-audio is hosted in **`us-central1`** (model availability), so
the live audio session runs there. **All stored merchant data lives in
`asia-southeast1`** — that is the Firestore database location, fixed at database
creation. See `CLAUDE.md` for the documented audio-transit caveat.

---

## Deployment (Cloud Run, single shared service — ADR-6)

Single shared image serves all standard-tier tenants; isolation is logical and
per-tenant in Firestore. A **staging gate** is required: PRs deploy to staging,
production is promoted manually.

### One-time GCP setup (placeholders)
```bash
export PROJECT=heartland-commons
export REGION=us-central1

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com aiplatform.googleapis.com firestore.googleapis.com

# Artifact Registry repo for the image
gcloud artifacts repositories create heartland \
    --repository-format=docker --location="$REGION"

# Firestore database — MUST be asia-southeast1 for PDPA
gcloud firestore databases create --location=asia-southeast1
```

### Build + deploy to staging
```bash
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_SERVICE=heartland-commons-staging,_REGION="$REGION",_PROJECT="$PROJECT"
```
`cloudbuild.yaml` builds the image, pushes it, and deploys **staging only**.

### Promote to production (manual)
```bash
# Re-deploy the validated staging image to the prod service.
gcloud run deploy heartland-commons \
    --image="$REGION-docker.pkg.dev/$PROJECT/heartland/heartland-commons-staging:<SHA>" \
    --region="$REGION" --platform=managed --allow-unauthenticated
```

### Local Docker smoke test
```bash
docker build -t heartland-commons .
docker run -p 8080:8080 --env-file app/.env heartland-commons
```

---

## Layout
```
app/
  main.py                     FastAPI + WebSocket voice server (per-tenant)
  soar_orchestrator/          Copilot agent package (name kept for import path)
    agent.py                  build_agent(tenant_config) factory + render contract
    personas.py               ADR-7 stage-based personas
    tools.py                  merchant tools (Singlish docstrings, HITL pairs)
    subagents/
      session_owning.py       Onboarding / Training / Quote (stay active)
      ephemeral.py            HECS_Lookup / Supplier_Info (hand back)
  shared/
    firestore.py              cached Firestore client (asia-southeast1)
    firestore_session.py      FirestoreSessionService (ADR-3)
    tenant_config.py          progressive per-merchant config (ADR-7)
    localize.py               SEA-LION middleware (ADR-2)
    interaction_log.py        analytics + student knowledge-transfer layer
  static/                     console + landing (vanilla, warm/local)
tests/                        tenant_config, HITL, render contract
Dockerfile  cloudbuild.yaml   single shared image + staging gate (ADR-6)
CLAUDE.md                     ADR ledger + render-layer checklist
```

## Tests
```bash
pip install -e ".[dev]"
pytest
```
