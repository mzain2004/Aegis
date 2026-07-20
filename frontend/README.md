# Veto Ops Control Room

Frontend for the approval workflow.

```bash
npm install
# Optional: point at Alibaba ECS (default) or local backend
# set VITE_API_TARGET=http://43.106.28.134:9000
# set VITE_API_KEY=admin-api-key-12345
npm run dev
```

Vite proxies `/api/*` to the FastAPI service. The UI falls back to demo queue data when the API is unavailable.
