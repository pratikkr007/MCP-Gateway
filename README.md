MCP Gateway
A centralized gateway for exposing tools from multiple MCP upstreams to authenticated clients. The repository contains the gateway/backend, dashboard, MCP upstream services, chat agent, and Helm deployment assets.
> **Configuration note:** Paths, service names, environment variable names, ports, and chart values can differ between branches. Before running a command, compare it with the checked-in `.env.example`, Docker Compose file (if present), and `deploy/helm/charts/team-mcp/values*.yaml`. Never commit real API keys, WordPress credentials, or Kubernetes Secret values.
Architecture at a glance
Clients: the built-in chat agent and external MCP clients such as MCP Inspector.
Gateway/backend: authenticates clients, enforces configured authorization, aggregates/routes tool calls to upstream MCP servers, and records audit events.
Upstreams: inventory/notes and WooCommerce-related MCP services (confirm the deployed names in the Helm values).
Dashboard: administration and visibility into configured gateway resources and audit events.
Deployment: Helm/Kubernetes resources for local development and production-like deployment.
Requirements
Git
Docker Desktop (with Kubernetes/Kind if using the local Kubernetes workflow)
Python version required by the backend's dependency files
Node.js/npm version required by the frontend/chat-agent package files
`kubectl`, `kind`, and Helm for the Kubernetes workflow
A configured LLM provider API key for chat-agent functionality
WooCommerce/WordPress configuration for store operations
Check the versions and scripts declared in the project files before installing dependencies.
Local setup
1. Clone and inspect the repository
```bash
git clone https://github.com/pratikkr007/MCP-Gateway.git
cd MCP-Gateway
```
Inspect the repository's actual setup files before proceeding:
```bash
git status
git ls-files
```
Look for `.env.example`, `docker-compose.yml` / `compose.yaml`, backend dependency files, frontend `package.json` files, and Helm values files.
2. Configure environment
If an example environment file exists, copy it to the local ignored environment file and fill in values locally. For example, on PowerShell:
```powershell
Copy-Item .env.example .env
```
Only use this command if `.env.example` exists. Configure the variables documented by the project, including the LLM provider/model/base URL, gateway secrets, and WooCommerce credentials. Do not commit `.env`.
3. Install dependencies and start services
Use the repository's declared commands rather than guessing package managers or entry points:
Python backend: follow the backend dependency file and startup instructions.
Frontend/dashboard/chat agent: follow the relevant `package.json` scripts.
Upstream MCP servers and WordPress/WooCommerce: use the checked-in Compose file or documented service-specific instructions if provided.
If the repository includes Docker Compose, inspect the service names and start the intended stack using the Compose file's documented profile/configuration.
4. Verify
For a local Kubernetes deployment, see the next section. For non-Kubernetes development, use the health endpoint and ports documented in the backend and frontend configuration.
Local Kubernetes / Kind setup
The project's known chart location is:
```text
deploy/helm/charts/team-mcp
```
Create or select a Kind cluster if your local setup does not already have one. If the cluster is named `team-mcp`, check it with:
```powershell
kind get clusters
kubectl cluster-info
kubectl get nodes
```
Install/upgrade using the chart and the local values file that actually exists in the repository. Example shape (replace the values filename with the real one):
```powershell
helm upgrade --install team-mcp .\deploy\helm\charts\team-mcp `
  --namespace team-mcp --create-namespace `
  -f .\deploy\helm\charts\team-mcp\values-local.yaml
```
If there is no `values-local.yaml`, use the checked-in local values filename instead; do not create a guessed filename. If using prebuilt local images, build and load them into Kind according to the image names and tags in the chart:
```powershell
docker build -t team-mcp-gateway:local -f backend/Dockerfile .
kind load docker-image team-mcp-gateway:local --name team-mcp
```
These two commands apply only if the chart expects `team-mcp-gateway:local` and the cluster is named `team-mcp`.
Verify resources:
```powershell
kubectl get pods -n team-mcp
kubectl get deployments -n team-mcp
kubectl get svc -n team-mcp
kubectl get ingress -n team-mcp
kubectl rollout status deployment/gateway -n team-mcp --timeout=120s
```
If a deployment is not named `gateway`, use the name returned by `kubectl get deployments -n team-mcp`.
Production-like setup (k3s)
Provision a Linux VPS with a supported container runtime and install k3s following the official k3s documentation.
Install Helm and configure `kubectl` for the cluster.
Configure a real DNS name and point its A/AAAA record to the VPS.
Configure an Ingress controller and TLS certificates. Ensure the chart's Ingress host and TLS settings match your DNS and certificate issuer.
Select a production StorageClass and configure persistent volumes for WordPress/database data. Confirm backup and restore procedures.
Create Kubernetes Secrets from an external secret manager or secure deployment process. Do not commit Secret values in Helm values or source control.
Configure image registry references and pull credentials if images are private. Use pinned image tags/digests instead of mutable tags.
Set resource requests/limits, readiness/liveness probes, replica counts, and disruption/backup policies appropriate to the VPS capacity.
Restrict internal services to cluster-internal access where possible. Expose only intended entry points through Ingress/firewall rules.
Deploy the chart using the production values file actually present in the repository:
```bash
helm upgrade --install team-mcp ./deploy/helm/charts/team-mcp \
  --namespace team-mcp --create-namespace \
  -f ./deploy/helm/charts/team-mcp/values-production.yaml
```
Replace `values-production.yaml` if the repository uses a different production values filename. Review the rendered manifests before applying:
```bash
helm template team-mcp ./deploy/helm/charts/team-mcp \
  --namespace team-mcp -f ./deploy/helm/charts/team-mcp/values-production.yaml
```
Do not expose database, WordPress administration, or upstream MCP services publicly unless explicitly required and protected.
Place an order
Open the storefront URL configured by your local Ingress or port-forward.
Find a published product, add it to the cart, and proceed to checkout.
Enter test customer details and use a configured test payment method (for example, Cash on Delivery if enabled).
Place the order and note the order number.
In WordPress Admin, open WooCommerce → Orders and verify the order status and total.
If an order-query tool is exposed through the gateway, ask the chat agent to retrieve that order and compare the response with WooCommerce Admin.
For local port-forwarding, first inspect the actual service names and ports:
```powershell
kubectl get svc -n team-mcp
```
Example only, if the service is named `wordpress` and its service port is `80`:
```powershell
kubectl port-forward svc/wordpress 8080:80 -n team-mcp
```
Then open `http://localhost:8080`. Do not assume the port-forward works until the command reports that forwarding is active.
Connect an external MCP client (MCP Inspector)
Start Inspector:
```bash
npx @modelcontextprotocol/inspector
```
Open the URL printed by the command (often `http://localhost:6274`).
Forward the gateway service port locally if needed. Find the service and port first:
```powershell
kubectl get svc -n team-mcp
```
Inspect the gateway source/configuration to identify the exact MCP endpoint path, supported transport, and required authentication header. Do not assume `/mcp`, `Authorization`, or `x-api-key` without verifying the implementation.
In Inspector, choose the transport supported by the gateway, enter the full endpoint URL, configure User B's own API key/header, and connect.
Open the tools list, invoke a harmless read-only tool, and inspect the result.
If connection fails, check the gateway logs and status:
```powershell
kubectl logs deployment/gateway -n team-mcp --tail=100
kubectl get pods -n team-mcp
```
Use a separate test key for external clients. Never paste API keys into screenshots or commit them.
Use the chat agent
Open the chat-agent URL configured by the project.
Configure the LLM provider/model and API key using the environment variables documented by the code. Keep secrets in `.env`/Kubernetes Secrets and out of source control.
Authenticate using a gateway user/key if required by the implementation.
Ask the agent to list available tools or perform a supported operation.
For a product demo, request a product creation only if the agent is exposed to a product-creation tool. Verify the returned product ID in WooCommerce Admin.
For an order demo, use a real test order ID and query it only if an order-retrieval tool is exposed. Compare the result with WooCommerce Admin.
The chat agent's configured model/provider should be verified from the active environment/configuration rather than inferred from the UI.
Troubleshooting
```powershell
kubectl get pods -n team-mcp
kubectl get deployments -n team-mcp
kubectl get svc -n team-mcp
kubectl describe deployment gateway -n team-mcp
kubectl logs deployment/gateway -n team-mcp --tail=100
```
404 in Inspector: verify the exact MCP path.
401/403: verify key validity, header format, and permissions.
Connection refused: verify the port-forward and Service target port.
No tools: verify that the MCP session connected and upstreams are healthy.
Order missing: verify that checkout completed and the product/order exists in WooCommerce Admin.
Additional notes
System design and tradeoffs
Threat model
