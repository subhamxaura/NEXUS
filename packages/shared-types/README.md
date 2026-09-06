# shared-types (generated)

TypeScript types generated from the FastAPI OpenAPI schema. Generation lands in Phase 1:

```bash
# from repo root (planned)
curl http://localhost:8000/openapi.json -o /tmp/openapi.json
npx openapi-typescript /tmp/openapi.json -o packages/shared-types/index.d.ts
```
