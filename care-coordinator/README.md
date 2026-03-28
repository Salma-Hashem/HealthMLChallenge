# Care Coordinator Assistant

An AI-powered chatbot that helps hospital nurses book follow-up appointments after patient discharge. Built with a Google Gemini LLM backend, a deterministic policy engine, and a React + TailwindCSS frontend.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│   ChatThread · BookingChecklist · QuickActionBar · SlotPicker   │
│                   (Vite + TailwindCSS v4)                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ POST /api/chat
┌───────────────────────────▼─────────────────────────────────────┐
│                       Flask Backend                             │
│  app.py — 20+ REST endpoints + SPA static file serving          │
│                                                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ Orchestrator│──▶│  Gemini LLM  │   │   Guardrails         │ │
│  │ (tool loop) │   │ (gemini-2.5- │   │  · Input screening   │ │
│  │            │◀──│  flash)       │   │  · Output PHI scan   │ │
│  └──────┬──────┘   └──────────────┘   │  · Injection block   │ │
│         │                             └──────────────────────┘ │
│  ┌──────▼──────────────────────────────────────────────────┐   │
│  │               Tool Dispatcher (tools.py)                │   │
│  │  verify_patient · lookup_provider · get_booking_history │   │
│  │  find_slots · book_appointment · verify_insurance · …   │   │
│  └──────┬──────────────────────────────────────────────────┘   │
│         │                                                       │
│  ┌──────▼───────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Policy Engine   │  │   Workflow   │  │   Audit Log      │  │
│  │ (appt type, dur) │  │ State Machine│  │  (audit.jsonl)   │  │
│  └──────────────────┘  └──────────────┘  └──────────────────┘  │
│                                                                 │
│  In-memory data: patients · providers · slots · appointments    │
└─────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM provider | Google Gemini 2.5 Flash | Free tier, function-calling support, low latency |
| Tool calling | Gemini FunctionDeclaration | Structured tool dispatch prevents hallucination |
| Data store | In-memory (dict) | Scope of challenge; swap for DB in production |
| PHI protection | Strip fields from LLM context | `dob`, `patient_id` stripped before LLM sees results |
| Appointment type | Deterministic policy engine | Never let the LLM decide NEW vs ESTABLISHED |
| Slot availability | MD5-based deterministic generator | Reproducible test data across restarts |

---

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the React frontend)
- A **Cerebras API key** — get one free at [cloud.cerebras.ai](https://cloud.cerebras.ai)

---

## Setup

### 1. Clone and create virtualenv

```bash
git clone <repo-url>
cd care-coordinator
make setup          # creates venv + installs dependencies
# OR manually:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY=your_key_here
```

### 3. Build the frontend (optional — Flask serves the built files)

```bash
make frontend
# OR manually:
cd frontend && npm install && npm run build
```

---

## Running

### Flask backend only

```bash
make run
# Server starts at http://localhost:5000
# React SPA served from http://localhost:5000/ (requires make frontend first)
```

### Full stack dev (backend + Vite HMR)

```bash
make dev
# Flask:  http://localhost:5000  (API)
# Vite:   http://localhost:3000  (UI, proxies /api → :5000)
```

### Production (gunicorn)

```bash
make run-prod
```

### CLI chat interface

```bash
make chat
# Type messages; enter 'state' to see workflow, 'reset' to start over
```

### Docker

```bash
make docker-up
# Application at http://localhost:5000
# Pass GOOGLE_API_KEY in .env (never bake into image)
```

---

## Testing

```bash
make test           # 176 unit + integration tests (pytest)
make eval           # 13 golden-dataset offline cases (100% pass)
make eval-live      # + 2 live LLM cases (requires GOOGLE_API_KEY)
```

### Golden dataset (`tests/golden_dataset.json`)

15 test cases across 5 categories:

| Category | Cases | Examples |
|----------|-------|---------|
| happy_path | 6 | ESTABLISHED booking, NEW booking, provider lookup |
| edge_case | 4 | Patient not found, alternatives offered, multi-referral |
| safety | 1 | Medical advice detected and flagged |
| security | 3 | Injection blocked, length limit, PHI stripped |
| live | 2 | Ambiguous input, full end-to-end booking |

### Evaluation dimensions (`tests/eval.py`)

Each case is scored on 4 dimensions (0–4 per case):

- **Grounding** — data comes from tools, not hallucinated
- **Safety** — medical advice refused; injections blocked; PHI protected
- **Correctness** — correct workflow path; correct appointment type
- **Completeness** — all required info present in response

---

## API Documentation

Base URL: `http://localhost:5000`

All POST bodies are JSON. All responses are JSON.

### Health

#### `GET /api/health`
```json
// 200 OK
{"status": "ok", "llm": "google-gemini", "patients": 1, "providers": 5}

// 503 if GOOGLE_API_KEY not set
{"status": "degraded", "reason": "GOOGLE_API_KEY is not set — ..."}
```

### Chat (LLM)

#### `POST /api/chat`
```json
// Request
{"session_id": null, "message": "Book an appointment for John Doe with Dr. House"}

// Response
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "I found John Doe. His last visit to Dr. House was August 2024 ...",
  "workflow_state": "CHECK_AVAILABILITY",
  "action_cards": [],
  "requires_confirmation": false
}
```

Pass `session_id` from the previous response to continue the same conversation.

### Patients

#### `GET /api/patient/<id>`
Returns patient demographics, referrals, and insurance.

#### `POST /api/patient/search`
```json
// Request
{"first_name": "John", "last_name": "Doe", "dob": "1975-01-01"}

// Response
{"patients": [{"id": 1, "first_name": "John", "last_name": "Doe", ...}]}
```

### Providers

#### `GET /api/providers`
Query params: `specialty`, `location`, `department`

#### `GET /api/providers/<id>`
Full provider profile with departments, hours, and contact info.

### Booking History & Appointment Type

#### `GET /api/history/<patient_id>/<provider_id>`
```json
{
  "last_seen_date": "2024-08-12",
  "appointment_type": "ESTABLISHED",
  "required_duration_minutes": 15,
  "arrival_instructions": "Please arrive 10 minutes before your appointment."
}
```

### Slots

#### `POST /api/slots/search`
```json
// Request
{
  "provider_id": 2,
  "location_id": 3,
  "duration": 15,
  "date_from": "2025-01-01",
  "date_to": "2025-01-14"
}

// Response
{
  "total_available": 42,
  "slots": [
    {"id": "abc123", "start": "2025-01-06T09:00:00", "duration_minutes": 15, ...}
  ]
}
```

### Appointments

#### `POST /api/appointments/book`
```json
// Request
{
  "patient_id": 1,
  "slot_id": "abc123",
  "appointment_type": "ESTABLISHED",
  "reason": "Orthopedics follow-up post-discharge"
}

// Response
{
  "success": true,
  "confirmation_number": "CCA-AB12CD34",
  "provider": "Gregory House MD",
  "date": "Monday, January 06, 2025",
  "time": "09:00 AM",
  "arrival_instructions": "Please arrive 10 minutes before your appointment."
}
```

### Insurance

#### `GET /api/insurance/check/<plan_name>`
```json
{"plan": "Aetna", "accepted": true}
{"plan": "Kaiser Permanente", "accepted": false, "self_pay_rates": {...}}
```

#### `GET /api/insurance/selfpay/<specialty>`
```json
{"specialty": "Orthopedics", "rate": 300.0, "currency": "USD"}
```

### Workflow Sessions

#### `POST /api/session` — Create session
#### `GET /api/session/<id>` — Get session state
#### `POST /api/session/<id>/advance` — Advance workflow state

Workflow states (in order):
`GREET → VERIFY_PATIENT → COLLECT_REFERRAL → DETERMINE_APPT_TYPE → CHECK_AVAILABILITY → VERIFY_INSURANCE → CONFIRM_BOOKING → BOOKING_CONFIRMED → FINAL_SUMMARY`

---

## Security & Guardrails

| Layer | What it does |
|-------|-------------|
| **Input guardrails** | 12 injection patterns blocked; 2000-char max; blocked messages logged |
| **Output guardrails** | SSN/MRN patterns redacted; medical advice flagged + disclaimer appended |
| **Booking cross-check** | Confirmation numbers in responses verified against actual tool results |
| **PHI minimisation** | `dob` stripped from `verify_patient`; `patient_id` stripped from booking results before LLM sees them |
| **Audit log** | Append-only `audit.jsonl`; patient IDs hashed (SHA-256); booking payloads integrity-hashed |
| **Tool guardrails** | Patient-specific tools blocked until `verify_patient` succeeds |

---

## Project Structure

```
care-coordinator/
├── app.py              # Flask app — 20+ REST endpoints + SPA serving
├── orchestrator.py     # LLM tool-calling loop (Google Gemini)
├── tools.py            # Tool schemas + executors
├── guardrails.py       # Input/output safety screening
├── audit_log.py        # Append-only JSONL audit trail
├── memory.py           # Rolling conversation window (40 msgs, 8 hr TTL)
├── prompts.py          # System prompt
├── policy_engine.py    # Deterministic appointment-type rules
├── workflow.py         # 9-state workflow state machine
├── models.py           # Dataclasses with to_dict()
├── data_loader.py      # data_sheet.txt → in-memory DB
├── slot_generator.py   # Deterministic slot availability generator
├── chat_cli.py         # Terminal chat interface
├── data_sheet.txt      # Provider directory & hospital policies
├── requirements.txt    # Pinned Python dependencies
├── Makefile            # Dev / test / build commands
├── Dockerfile          # Backend container
├── docker-compose.yml  # Full stack orchestration
├── .env.example        # Environment variable template
├── frontend/           # React + Vite + TailwindCSS
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── ChatThread.jsx
│   │   │   ├── MessageBubble.jsx
│   │   │   ├── BookingChecklist.jsx
│   │   │   ├── BookingCard.jsx
│   │   │   ├── SlotPicker.jsx
│   │   │   ├── SessionSummary.jsx
│   │   │   └── QuickActionBar.jsx
│   │   ├── hooks/useChat.js
│   │   └── services/api.js
│   └── vite.config.js
└── tests/
    ├── test_api.py
    ├── test_models.py
    ├── test_policy_engine.py
    ├── test_workflow.py
    ├── test_guardrails.py
    ├── test_audit_log.py
    ├── golden_dataset.json
    └── eval.py
```
