# Threat model

## Assets and trust boundaries

Assets include client API keys, shared upstream credentials, store/customer/order data, administrative controls, and audit records.

Trust boundaries exist between external clients and the gateway, between the gateway and each upstream MCP server, between dashboard users and administrative APIs, and between Kubernetes workloads and their Secrets/storage.

## Shared upstream credentials: what can a member do with a credential they never see?

A gateway may hold a shared upstream credential (for example, a WooCommerce API credential) and use it when executing tools. A member does not need to see the credential to exercise its authority: they may be able to invoke every upstream operation that the gateway exposes and permits to them.

The effective risk is determined by the exposed tool set, per-user/role authorization, argument validation, and the privileges granted to the shared credential. If the credential has broad write access and the gateway exposes those writes to members, a member could create, modify, or delete data even without ever learning the credential string.

Mitigations:
- Give upstream credentials the least privileges possible.
- Enforce authorization at the gateway for every tool call, not only in the UI.
- Restrict destructive operations and validate arguments.
- Audit actor, tool, upstream, outcome, and timestamp without logging credential values.
- Rotate credentials and revoke client keys promptly when needed.

## Why client tokens are not passed through to upstream servers

Client tokens represent the client's identity and authorization at the gateway. They are not automatically valid credentials for upstream systems and should not be forwarded as upstream authentication.

Forwarding them could leak tokens to services that do not need them, confuse trust boundaries, and grant upstreams unintended authority. Instead, the gateway authenticates the client, applies its own authorization policy, and uses a separately configured upstream credential to call the upstream. The upstream credential must remain server-side.

## Untrusted upstreams: tool descriptions that manipulate the model

An upstream can return misleading tool names/descriptions or content designed to manipulate the LLM (prompt injection), for example instructions telling the model to reveal secrets, ignore policy, or call unrelated tools.

Treat tool descriptions and tool results as untrusted data, not as system instructions. Mitigations include:
- Do not place upstream-provided descriptions into privileged system instructions.
- Keep the model's tool permissions narrow and require confirmation for consequential actions where appropriate.
- Validate tool arguments and enforce authorization in backend code independently of the model.
- Avoid returning secrets or unnecessary sensitive data to the model.
- Log tool selection and outcomes safely, and test with malicious tool descriptions/results.

## What one team member can do to another

Potential abuse depends on the implementation's roles and isolation. If a member can manage another user's keys, permissions, upstreams, or data, they may be able to lock that user out, impersonate their access, or alter shared resources. If permissions are correctly scoped, a member should not be able to issue/revoke another user's keys or change their permissions unless explicitly authorized.

Review and test:
- Whether member users can issue/revoke keys for other users.
- Whether user-specific resources and audit records are scoped by identity.
- Whether members can alter upstream definitions or shared tool permissions.
- Whether an administrator can revoke a member's key and whether revocation takes effect immediately.
- Whether users can read another user's key material (they should not be able to retrieve plaintext secrets after creation).

Mitigations:
- Separate administrator and member permissions server-side.
- Scope key management to the current user unless an admin action is explicitly authorized.
- Store only hashed client API keys where supported and show plaintext only once at creation.
- Audit all key/permission/upstream changes.
- Add tests for cross-user access and IDOR-style resource access.

## Residual risks and verification

This note describes risks and controls to verify; it does not assert that every mitigation is implemented. Confirm actual enforcement in backend code and tests. Do not rely on hiding UI controls as an authorization mechanism.
