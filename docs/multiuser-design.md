# Multi-user design

This document captures the design decisions for VaultKeeper's multi-user support:
separate admin and end-user dashboards, invitation-based enrollment, user self-service
vault management, and the associated privacy model.

---

## Goals

VaultKeeper is intended as a public-facing tool that server operators can run for
friends, family, or small communities. The operator (admin) sets up VaultKeeper once
and then users can independently manage their own LiveSync vaults without admin
intervention for day-to-day operations.

---

## Roles

### Admin

- Full visibility: all users, all vaults, server status
- Can delete any vault or user
- Creates invitation links to onboard new users
- Sets per-user limits (vault count, size cap)
- _Cannot_ see vault document contents (see Privacy model below)

### End user

- Sees only their own vaults (`vault_<username>_*`)
- Can create, compact, delete, and generate Setup URIs for their own vaults
- Cannot see or manage other users' vaults
- Cannot create or delete other users

---

## Invitation enrollment flow

The admin never sets a user's password. Instead:

1. Admin creates an invitation link in the dashboard (a one-time token with an expiry)
2. Admin shares the link with the intended user out of band
3. User opens the link and is shown an enrollment page where they choose their own
   username and password
4. VaultKeeper creates a CouchDB user with the supplied credentials
5. The invitation token is consumed and cannot be reused

Invitation tokens are stored in the `vaultkeeper_config` CouchDB database with an
expiry timestamp. Expired or already-used tokens are rejected.

---

## Authentication

### VaultKeeper session

End users log into VaultKeeper with the username and password they chose at enrollment.
VaultKeeper maintains a server-side session after successful login.

### CouchDB operations

VaultKeeper authenticates to CouchDB using the server admin credentials
(`COUCHDB_USER` / `COUCHDB_PASSWORD`) for all management operations (creating
databases, setting `_security` documents, triggering compaction, etc.).

End users never interact with CouchDB directly through VaultKeeper. The Obsidian
LiveSync plugin connects to CouchDB directly using the user's own CouchDB credentials -
that connection is outside VaultKeeper's data path entirely.

Authorization in VaultKeeper is enforced at the application layer: authenticated users
can only manage resources in their own namespace (`vault_<username>_*`).

---

## User self-service vault management

After enrollment, users can freely create and delete vaults within their namespace up
to their per-user limits. No admin action is required.

### Per-user limits

Stored in `vaultkeeper_config` alongside the user's metadata:

| Limit | Enforcement |
|---|---|
| Max vault count | Hard - VaultKeeper refuses creation when limit is reached |
| Max vault size | Soft - checked at creation time and surfaced in the UI; cannot be enforced during an active sync |

Size limits are advisory at the CouchDB level: VaultKeeper can read reported database
sizes and warn or block vault creation, but it cannot interrupt a sync mid-flight once
a vault is in use.

---

## Metadata storage

VaultKeeper uses a dedicated CouchDB database (`vaultkeeper_config`) to store
application-level metadata that CouchDB does not natively track:

- Invitation tokens (with expiry)
- Per-user limits (vault count cap, size cap)

No external database is required. `vaultkeeper_config` is created automatically on
first run alongside the other server init steps.

---

## Privacy model

### What VaultKeeper never does

VaultKeeper is an infrastructure management tool. It creates and deletes databases,
sets security documents, and generates setup URIs. It never fetches, reads, or
displays the contents of vault documents. This is a hard scope boundary, not a
permission check.

### Admin visibility

The admin can see that a vault exists, its name, its document count, and its disk
size. They cannot see vault contents through VaultKeeper.

### Infrastructure-level access

A CouchDB server admin bypasses `_security` documents by design. An operator with
direct CouchDB access (Fauxton, curl) can read any database regardless of VaultKeeper.
This is a CouchDB architectural fact, not a VaultKeeper limitation.

### E2E encryption

LiveSync's end-to-end encryption encrypts vault content client-side in Obsidian before
it reaches CouchDB. With E2E enabled, CouchDB stores only ciphertext - the operator
cannot read vault contents even with direct CouchDB access.

VaultKeeper should default E2E encryption to enabled during setup URI generation and
make the passphrase clearly visible with a prompt to store it in a password manager.
Users choosing to host sensitive notes on a shared server should be informed that E2E
encryption is the privacy boundary, not the application layer.
