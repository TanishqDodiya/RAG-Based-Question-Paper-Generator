# RAG-Based Question Paper Generator

An offline, retrieval-augmented question paper generator for teachers. Upload your own study material, define an exam blueprint, and generate a validated question paper grounded strictly in your notes. The application ships with a FastAPI backend, a React frontend, and runs entirely on your own machine using local Ollama models and ChromaDB.

---

## Overview

Preparing a balanced question paper usually means manually checking coverage, marks distribution, difficulty, and cognitive levels. This project automates that process with a local RAG pipeline:

1. Study notes are uploaded and split into page-aware chunks with unit metadata.
2. The chunks are embedded and stored in a local ChromaDB collection.
3. A blueprint is expanded into per-question slots (type, marks, difficulty, Bloom level, unit).
4. Relevant context is retrieved for each unit and supplied to a local Ollama model.
5. The generated paper is validated deterministically against the blueprint and rejected/retried if it does not match.
6. The paper can be reviewed, edited, analyzed, checked for duplicates, exported to PDF, and saved to local history.

All inference and storage stay on the local machine. No cloud AI service is used.

---

## Key Features

- **Notes upload and indexing** — PDF, PPTX, DOCX, TXT, and Markdown files, with per-file size and count limits.
- **Page-aware chunking** — text is split into bounded chunks that retain source file, page, and unit metadata.
- **Unit metadata enrichment** — chunks are associated with units so retrieval can target the blueprint's topic coverage.
- **RAG retrieval preview** — inspect which source chunks would be retrieved for a unit before generating.
- **Blueprint validation and expansion** — checks marks, difficulty split, Bloom split, and question types, then expands them into concrete per-question slots.
- **Two generation modes**
  - **Structured generation** — one question per blueprint slot, with strict per-question metadata.
  - **Legacy generation** — section-and-count based paper generation (kept for compatibility).
- **Deterministic validation** — verifies question count, total marks, per-question marks, type, difficulty, Bloom level, and unit after generation.
- **Retry with corrective feedback** — invalid output is retried once with the exact validation errors while preserving the original blueprint.
- **Duplicate detection** — identifies similar or repeated questions across a paper.
- **Single-question regeneration** — regenerate one question while keeping its original slot metadata and id.
- **Paper analytics** — marks distribution, difficulty and Bloom coverage, and unit coverage.
- **PDF export** — export the paper with an optional answer key.
- **Saved paper history** — store, reopen, and delete generated papers and their blueprints locally.
- **Session isolation** — notes and history are scoped by session id.
- **Optional shared-token auth** — enable `APP_AUTH_TOKEN` to require a token; localhost-only by default.
- **Review and edit workflow** — edit question text, options, and marks, and reject individual questions in the UI.

---

## Technology Stack

### Backend
- **Python**
- **FastAPI** + **Uvicorn**
- **Pydantic v2**
- **ChromaDB** (persistent local vector store)
- **Ollama** with:
  - `llama3.2` for generation (configurable)
  - `nomic-embed-text` for embeddings (configurable)
- **pypdf** and **pdfplumber** for PDF extraction
- **python-pptx** and **python-docx** for PowerPoint and Word extraction
- **langchain-text-splitters** for chunking
- **reportlab** for PDF export
- **SQLite** for saved paper history

### Frontend
- **React 18**
- **Vite 5**
- **Tailwind CSS 3**
- **lucide-react** icons

---

## Project Architecture

```text
RAG-Based Question Paper Generator
|
+-- backend/
|   +-- main.py              FastAPI app, routes, session handling, RAG pipeline
|   +-- generate.py          Structured slot expansion, prompting, parsing, validation
|   +-- blueprint.py         Blueprint validation and expansion helpers
|   +-- validator.py         Deterministic paper/question validation
|   +-- duplicates.py        Duplicate question detection
|   +-- analytics.py         Paper statistics and coverage analysis
|   +-- export_pdf.py        PDF export with optional answer key
|   +-- history.py           SQLite-backed saved paper history
|   +-- metadata_enrich.py   Unit metadata enrichment for chunks
|   +-- requirements.txt     Python dependencies
|   +-- test_*.py            Regression and integration test suites
|
+-- frontend/
    +-- src/
    |   +-- App.jsx          Main application shell and workflow state
    |   +-- components/      Upload, blueprint, generator, preview, review, history,
    |   |                    analytics, duplicate panel, and error boundary
    |   +-- services/api.js  Backend API client
    |   +-- utils/           Paper state, validation, and formatting helpers
    +-- tests/               Frontend regression tests
    +-- vite.config.js       Dev server (port 3000) and backend proxy
    +-- package.json         Frontend dependencies and scripts
```

### Request flow

```text
Browser (React + Vite)
        |
        |  /api/*, /upload-notes, /generate-paper
        v
FastAPI backend
        |
        +-- ChromaDB (local vector store)
        +-- SQLite (paper history)
        +-- Ollama (local LLM + embeddings)
```

In development, Vite proxies API traffic from `http://localhost:3000` to the backend at `http://localhost:8000`.

---

## Installation

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm
- **Ollama** installed and running locally
- The required Ollama models pulled locally:

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

> The model names can be changed with the `LLM_MODEL` and `EMBEDDING_MODEL` environment variables.

### 1. Clone the repository

```bash
git clone https://github.com/TanishqDodiya/RAG-Based-Question-Paper-Generator.git
cd RAG-Based-Question-Paper-Generator
```

### 2. Backend setup

```bash
python -m venv .venv
```

Activate the virtual environment:

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r backend/requirements.txt
```

### 3. Frontend setup

```bash
cd frontend
npm install
cd ..
```

---

## Environment Setup

The backend reads configuration from environment variables. All variables are optional; the defaults are suitable for local use.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL` | `llama3.2` | Generation model |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `APP_AUTH_TOKEN` | *(empty)* | Shared token required on API requests when set |
| `MAX_FILE_SIZE_BYTES` | `26214400` (25 MB) | Maximum size per uploaded file |
| `MAX_FILES_PER_REQUEST` | `10` | Maximum files per upload request |
| `RAG_RELEVANCE_THRESHOLD` | `0.60` | Cosine-distance threshold for relevant chunks |
| `APP_HOST` | `127.0.0.1` | Backend bind address |
| `APP_PORT` | `8000` | Backend port |
| `APP_RELOAD` | `0` | Enable Uvicorn auto-reload (`1`/`true`) |

If `APP_AUTH_TOKEN` is set, clients must send it. The frontend reads an optional `VITE_API_TOKEN` build-time variable and sends it as the API token.

> Keep the backend bound to localhost. The shared token is not a replacement for full authentication when exposing the service to a network.

---

## Running the Application

### Start the backend

Run from the **`backend`** directory. This is required because the backend modules use sibling imports:

```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Alternatively:

```bash
cd backend
python main.py
```

Backend URLs:

- Health: `http://localhost:8000/health`
- Status: `http://localhost:8000/api/status`
- OpenAPI docs: `http://localhost:8000/docs`

### Start the frontend

In a second terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

### Production build

```bash
cd frontend
npm run build
```

The output is written to `frontend/dist/`.

---

## Usage

1. **Start Ollama** and make sure both models are available.
2. Open the frontend at `http://localhost:3000` and confirm the backend/Ollama status indicator is healthy.
3. **Upload study material** (PDF, PPTX, DOCX, TXT, or Markdown). Files are indexed into the local vector store for the current session.
4. **Optionally preview retrieval** for a unit to confirm the correct source material is found.
5. **Define a blueprint** with subject, exam name, total marks, duration, topics, difficulty split, question types, and Bloom levels. The blueprint is validated before use.
6. **Generate the paper** using structured generation. Each question is generated against a specific blueprint slot.
7. **Review the paper** in the preview/review mode. Edit question text, options, or marks, or reject individual questions.
8. **Run analytics and duplicate checks** to inspect coverage and repeated content.
9. **Regenerate individual questions** if needed.
10. **Export to PDF** with or without the answer key.
11. **Save the paper** to local history and reopen it later.

---

## Testing

Backend regression suites are deterministic and stub the Ollama/vector boundary where needed. Run them from the `backend` directory:

```bash
cd backend
python test_phase1_fixes.py
python test_phase2_fixes.py
python test_phase3_fixes.py
python test_milestones.py
python test_generation_fixes.py
```

`test_suite.py` is an integration suite that expects a running backend at `http://localhost:8000`:

```bash
cd backend
python test_suite.py
```

Frontend tests and production build:

```bash
cd frontend
node --test tests/phase3.test.mjs
npm run build
```

---

## Notes and Limitations

- The application is designed for **local, single-machine use**.
- Generation quality depends on the local model and the uploaded material.
- If the model repeatedly violates the slot contract, generation returns a controlled error instead of looping indefinitely.
- Generated questions are grounded in the uploaded notes; if the notes lack information for a slot, the model is instructed to report insufficient context rather than invent content.
- Local data directories (`backend/chroma_db/`, `backend/uploads/`, `papers.db`) are created at runtime and are excluded from version control.
