# Run TDM Platform locally (Windows / PowerShell)

## 1. Requirements

- Python 3.10 or newer
- Node.js 18 or newer and npm
- Run commands from the extracted `TDM Platform` directory (the directory containing `api`, `alembic`, and `frontend-react`).

## 2. Install backend dependencies (once)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Start the backend

```powershell
.\start-backend.ps1
```

The script applies Alembic migrations, creates either missing demo source database (`hospital.db` and `banking.db`), and starts FastAPI. Local development authentication is enabled by default because the React API client sends development identity headers. **Do not use development authentication in production.**

- API: http://127.0.0.1:8000
- Swagger docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

If PowerShell blocks local scripts, run `Set-ExecutionPolicy -Scope Process Bypass` in that terminal, then retry.

## 4. Start the frontend in a second PowerShell terminal

```powershell
.\start-frontend.ps1
```

The script installs frontend dependencies with `npm ci` if needed and starts Vite.

- Frontend: http://127.0.0.1:5173
- The frontend uses `http://localhost:8000` as its default API URL. Override it by setting `VITE_API_BASE` before starting Vite if the backend is elsewhere.

## 5. Verify both domains

Open http://127.0.0.1:8000/docs and try `GET /domains` with development headers, or use the frontend's Data Relationship Validation page. The built-in domains should list Healthcare and Banking & Financial Services. The healthcare source contains `patients`, `doctors`, `appointments`, and `insurance_claims`; the banking source contains 11 tables.

## 6. Regenerate demo source databases manually

From the project root:

```powershell
python -m sample_domains.healthcare hospital.db 2026
python -m sample_domains.banking banking.db 2026
```

Both builders use deterministic fictional data for a fixed seed. Running either command explicitly replaces that database. Normal startup only rebuilds a database when it is missing.

## Production note

Configure `TDM_AUTH_MODE=production`, a strong `TDM_JWT_SECRET`, issuer/audience as appropriate, and `TDM_ALLOWED_ORIGINS` for the deployed frontend. The Render startup command runs `python -m alembic upgrade head` before starting the API. Never deploy with development authentication enabled.

## Registered sources (Source Registry)

See `docs/SOURCE_REGISTRY_INTEGRATION.md` for registering a source, selecting it on the Profiling tab and generating synthetic data from it. Run `python -m alembic upgrade head` once after upgrading (adds `source_id` columns).
