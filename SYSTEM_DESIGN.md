# System design and tradeoffs

## Architecture choices

The gateway centralizes client authentication, authorization, tool discovery/routing, and auditability. Clients such as the built-in chat agent and external MCP clients connect to the gateway rather than configuring every upstream independently.

The backend/gateway is implemented with FastAPI. The dashboard provides an administrative interface. Upstream MCP servers encapsulate separate tool domains (for example, inventory, notes, and WooCommerce). Kubernetes and Helm provide repeatable deployment and configuration.

### Tradeoffs

- **Centralized gateway:** consistent policy enforcement and audit visibility; the gateway becomes a critical dependency and must be monitored and scaled.
- **Separate upstream servers:** isolate domains and permit independent deployment; add network hops and introduce upstream availability/latency concerns.
- **Shared upstream service credentials:** users need not receive raw upstream credentials, but the gateway must tightly constrain which operations each user can invoke.
- **Kubernetes/Helm:** repeatable deployments and service discovery; more operational complexity than a single-process local setup.
- **Audit logging:** helps investigate actions; logs must avoid secrets and sensitive payloads and should have retention/access controls.

## Tool aggregation and routing

At a high level:

1. A client connects to the gateway using the configured MCP transport and credentials.
2. The gateway authenticates the client and evaluates configured permissions.
3. The gateway exposes/aggregates the tools that are available to that client under the implemented policy.
4. For a tool call, the gateway resolves the requested tool name to its upstream and forwards the arguments.
5. The upstream executes the operation and returns a result/error.
6. The gateway returns the result to the client and records an audit event where configured.

Tool-name collisions need a deterministic policy (for example, namespacing by upstream or rejecting ambiguous names). Document the exact policy from the implementation; do not assume a specific prefixing rule unless verified.

## Failure handling

Upstreams can fail, time out, or become unreachable. The gateway should surface a bounded, useful error for the failed call and avoid taking unrelated upstreams down. Timeouts should prevent indefinitely hanging requests. Whether retries, circuit breakers, per-upstream health tracking, and tool-list refresh are implemented must be verified from the source before claiming them.

A failure test can scale one non-critical upstream deployment to zero, invoke one of its tools, then invoke a tool from a different upstream. Restore the deployment immediately after the test and verify readiness.

## Production changes

- **DNS:** replace local hostnames/localhost URLs with a stable DNS name; configure DNS records to point to the VPS/Ingress endpoint.
- **Ingress and TLS:** configure the actual Ingress controller, host rules, TLS certificate and renewal; expose only intended endpoints.
- **Storage class:** choose a production StorageClass for persistent WordPress/database data; plan backups, restore tests, and disk capacity.
- **Secrets:** supply API keys, database credentials, and upstream credentials through Kubernetes Secrets or a secret manager; keep plaintext secrets out of Git and Helm values.
- **Images:** use a registry, immutable tags/digests, and image pull secrets if needed.
- **Resources and health:** set requests/limits and probes appropriate to each service; verify these are present in the rendered manifests.
- **Network/security:** keep internal upstreams and databases internal, restrict ingress/egress where feasible, and use least-privilege service accounts.
- **Operations:** add monitoring, centralized logs, backups, and a documented recovery procedure.

## Evidence to capture in a demo

- `kubectl get pods,deployments,svc -n team-mcp`
- One successful tool call through the gateway
- A failed or denied call, with the corresponding audit record if supported
- An upstream outage test showing its error and the result of a call to a different healthy upstream
- Rendered production Helm values/manifests showing DNS/Ingress, storage, and Secret references
