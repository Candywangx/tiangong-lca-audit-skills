# Environment Variables

No new mandatory environment variables are introduced. The client requires POSIX (`fcntl` for file locking). The standalone standard-library client reads the process environment; it does not require the audit runtime or a third-party HTTP package. Export variables explicitly when invoking it directly; copying a `.env` file does not itself export them.

| Variable | Use |
| --- | --- |
| `UNSTRUCTURED_API_BASE_URL` | Service root, including any reverse-proxy prefix, or a known full endpoint; a CLI endpoint override can replace it |
| `UNSTRUCTURED_AUTH_TOKEN` | Existing service Bearer credential, sent as an authorization header |
| `UNSTRUCTURED_PROVIDER` | Optional independent image-description provider override for image modes |
| `UNSTRUCTURED_MODEL` | Optional independent image-description model override for image modes |

```bash
export UNSTRUCTURED_API_BASE_URL="https://your-unstructured-host:7770"
export UNSTRUCTURED_AUTH_TOKEN="your-fastapi-bearer-token"
```

Leave provider/model unset to use deployment defaults. They do not choose parsing quality. Configure mode, quality, and waiting budgets with CLI options; see [request-response.md](request-response.md) for authoritative endpoint-resolution, parameter-precedence, and resumption rules. No separate prompt, mode, or tier environment variable is required.

Keep credentials out of request records, logs, case evidence, and Git. Credentials can be rotated while querying an existing task; the stored endpoint and parameters still identify the original request. The schema must be reachable for new submissions; a gateway may protect `/openapi.json` even when the service's automatic schema route is public.

See [config.example.env](../assets/config.example.env) for configuration names.
