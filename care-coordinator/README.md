# Care Coordinator Assistant

Thank you for choosing me to interview and build this AI-powered chatbot that helps hospital nurses book follow-up appointments for patients! A nurse describes what they need in plain language; the assistant verifies the patient, checks availability, confirms insurance, and books the appointment — all through a structured tool-calling workflow.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│         ChatThread · BookingChecklist · QuickActionBar          │
│                   (Vite + TailwindCSS v4)                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ POST /api/chat
┌───────────────────────────▼─────────────────────────────────────┐
│                       Flask Backend  (main.py)                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │               LangGraph Agent  (agent/graph.py)          │   │
│  │                                                          │   │
│  │  agent_node ──► tools_node ──► agent_node ──► …         │   │
│  │       │              │                                   │   │
│  │  Cerebras LLM   Tool Executor                            │   │
│  │  (Qwen 3 235B)  (tools/executor.py)                      │   │
│  │                      │                                   │   │
│  │              guard_booking node                          │   │
│  │         (blocks booking until nurse confirms)            │   │
│  │                                                          │   │
│  │  MemorySaver checkpointer — full conversation history    │   │
│  │  per session_id, no external DB required                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │  Guardrails │  │  Policy Engine   │  │   Audit Log      │   │
│  │ (safety/)   │  │  (core/policy.py)│  │  (audit.jsonl)   │   │
│  └─────────────┘  └──────────────────┘  └──────────────────┘   │
│                                                                 │
│  In-memory data: patients · providers · slots · appointments    │
└─────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM provider | Cerebras — Qwen 3 235B | Fast inference, OpenAI-compatible API, free tier |
| Fallback LLM | Second Cerebras key (`CEREBRAS_API_KEY_FALLBACK`) | Automatic 429 retry without user-visible errors |
| Agent framework | LangGraph | Built-in agent↔tools cycle, checkpointed state, conditional edges |
| Tool calling | LangChain `StructuredTool` + Pydantic v2 schemas | Single source of truth for LLM schema and runtime validation |
| Data store | In-memory dict | Scope of challenge; swap for DB in production |
| PHI protection | Strip fields before LLM context | `dob`, `patient_id` removed from tool results via `safety/phi.py` |
| Appointment type | Deterministic policy engine | Never let the LLM decide NEW vs ESTABLISHED |
| Slot availability | MD5-based deterministic generator | Reproducible test data across restarts |
| Booking guard | `guard_booking` conditional edge | Zero-token Python check — nurse must confirm before `book_appointment` executes |

---

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the React frontend)
- A **Cerebras API key** — get one free at [cloud.cerebras.ai](https://cloud.cerebras.ai)
- Need two API keys a second for fallback llm call in case first one runs out of tokens or rate limits. I created two different accounts. 

---

## Setup

### 1. Clone and create virtualenv

```bash
git clone <repo-url>
cd care-coordinator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Or with make:

```bash
make setup
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set CEREBRAS_API_KEY=your_key_here 
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
# Type messages directly in the terminal
```

### Docker

```bash
make docker-up
# Application at http://localhost:5000
# Set CEREBRAS_API_KEY in .env before running
```

---

## Testing

```bash
make test                               # 193 unit + integration tests (pytest)
make eval                               # Golden-dataset offline evaluation
make eval-live                          # + live LLM cases (requires CEREBRAS_API_KEY)
pytest tests/test_llm_evals.py -v       # LangSmith LLM-as-judge eval (requires LANGSMITH_API_KEY + LANGSMITH_LLM_JUDGE=true)
```

### Golden dataset (`tests/eval.py`)

15 test cases across 5 categories:

| Category | Cases | Examples |
|----------|-------|---------|
| happy_path | 6 | ESTABLISHED booking, NEW booking, provider lookup |
| edge_case | 4 | Patient not found, alternatives offered, multi-referral |
| safety | 1 | Medical advice detected and flagged |
| security | 3 | Injection blocked, length limit, PHI stripped |
| live | 2 | Ambiguous input, full end-to-end booking |

Each case is scored on 4 dimensions (0–4 per case):

- **Grounding** — data comes from tools, not hallucinated
- **Safety** — medical advice refused; injections blocked; PHI protected
- **Correctness** — correct workflow path; correct appointment type
- **Completeness** — all required info present in response

### LLM-as-judge eval (`tests/test_llm_evals.py`)

Requires `LANGSMITH_API_KEY` and `LANGSMITH_LLM_JUDGE=true` in `.env`. Runs quality evaluations using LangSmith — traces every graph invocation and scores responses automatically.
Get Langsmith key here: https://docs.langchain.com/langsmith/home
---

## API Documentation

Base URL: `http://localhost:5000`

All POST bodies are JSON. All responses are JSON.

### Health

#### `GET /api/health`
```json
// 200 OK
{"status": "ok", "llm": "cerebras-qwen3", "patients": 1, "providers": 5}

// 503 if CEREBRAS_API_KEY not set
{"status": "degraded", "reason": "CEREBRAS_API_KEY is not set"}
```

### Chat

#### `POST /api/chat`
```json
// Request
{"session_id": null, "message": "Book an appointment for John Doe with Dr. House"}

// Response
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "I found John Doe. His last visit to Dr. House was August 2024 ...",
  "workflow_state": "check_availability",
  "action_cards": [],
  "requires_confirmation": false
}
```

Pass `session_id` from the previous response to continue the same conversation.

### Patients

#### `GET /api/patient/<id>`
Returns patient demographics and referrals.

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
    {"id": "abc123", "start": "2025-01-06T09:00:00", "duration_minutes": 15}
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

---

## Security & Guardrails

| Layer | What it does |
|-------|-------------|
| **Input guardrails** | 12 injection patterns blocked; 2000-char max; blocked messages logged |
| **Output guardrails** | SSN/MRN patterns redacted; medical advice flagged + disclaimer appended |
| **Booking guard** | `guard_booking` LangGraph node blocks `book_appointment` until nurse explicitly confirms |
| **Booking cross-check** | Confirmation numbers in LLM responses verified against actual tool results |
| **PHI minimisation** | `dob` stripped from `verify_patient`; `patient_id` stripped from booking results — defined once in `safety/phi.py` |
| **Audit log** | Append-only `audit.jsonl`; patient IDs hashed (SHA-256); booking payloads integrity-hashed |
| **Tool guardrails** | Patient-specific tools blocked until `verify_patient` succeeds |

---

## Project Structure

```
care-coordinator/
├── main.py                         # App entry point: boots data, graph, Flask
├── requirements.txt
├── Makefile
├── Dockerfile / docker-compose.yml
├── .env.example
│
├── agent/
│   ├── graph.py                    # LangGraph state graph (nodes, edges, LLM)
│   ├── orchestrator.py             # handle_message() — called by POST /api/chat
│   └── prompts.py                  # System prompt
│
├── api/
│   ├── __init__.py                 # create_app() Flask factory
│   ├── serializers.py
│   └── routes/
│       ├── chat.py                 # POST /api/chat
│       ├── patients.py             # GET/POST /api/patient
│       ├── providers.py            # GET /api/providers
│       ├── scheduling.py           # slots + appointments
│       ├── insurance.py            # insurance check + self-pay
│       └── misc.py                 # health check, frontend SPA
│
├── core/
│   ├── models.py                   # Pydantic v2 models (Provider, Patient, Slot, …)
│   ├── policy.py                   # Deterministic NEW vs ESTABLISHED rules
│   ├── slots.py                    # MD5-based slot generator
│   └── workflow.py                 # WorkflowState enum + transition table
│
├── tools/
│   ├── base.py                     # BaseTool ABC
│   ├── registry.py                 # Global tool registry
│   ├── executor.py                 # Runs tools + enforces verify_patient gate
│   ├── schemas.py                  # Pydantic v2 input schemas for all tools
│   ├── patient/
│   │   ├── verify_patient.py
│   │   └── lookup_provider.py
│   ├── scheduling/
│   │   ├── get_booking_history.py
│   │   ├── find_available_slots.py
│   │   ├── check_provider_availability.py
│   │   ├── list_alternative_providers.py
│   │   └── book_appointment.py
│   └── insurance/
│       ├── verify_insurance.py
│       └── get_selfpay_rate.py
│
├── safety/
│   ├── guardrails.py               # Input/output safety screening
│   ├── audit.py                    # Append-only audit log
│   └── phi.py                      # PHI fields to strip per tool
│
├── data/
│   ├── loader.py                   # Parses data_sheet.txt → in-memory DB
│   ├── data_sheet.txt              # Provider directory, insurance, self-pay rates
│   └── patients.json               # Seed patient records
│
├── scripts/
│   └── chat_cli.py                 # Terminal chat interface
│
└── tests/
    ├── eval.py                     # Golden-dataset evaluation harness
    ├── test_api.py
    ├── test_models.py
    ├── test_policy_engine.py
    ├── test_guardrails.py
    ├── test_audit_log.py
    ├── test_data_loader.py
    └── llm_evals/                  # LangSmith LLM-as-judge evaluators
        ├── dataset.py
        ├── evaluators.py
        └── target.py
```
