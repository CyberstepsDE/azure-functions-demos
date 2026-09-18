# Azure Functions Demos

Small, self-contained Azure Function demos. Each folder deploys
independently with a few `az` CLI commands — no Functions Core Tools
required.

- [`hello-world/`](hello-world/) — a minimal Azure Function with a single
  HTTP endpoint.
- [`keyvault-secret-leak-demo/`](keyvault-secret-leak-demo/) — a Function
  reads a Key Vault secret via its managed identity and never returns it,
  but a command-injection bug elsewhere in the same Function lets an
  attacker steal the identity's token and read the secret directly from
  Key Vault instead.
