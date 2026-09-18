# Azure Functions Demos

Small, self-contained Azure Function demos for class. Each folder deploys
independently with a few `az` CLI commands — no Functions Core Tools
required.

- [`hello-world/`](hello-world/) — simplest possible Azure Function, sanity
  check that deploy tooling works.
- [`keyvault-secret-leak-demo/`](keyvault-secret-leak-demo/) — a Function
  legitimately reads a Key Vault secret via its managed identity and never
  returns it, but an unrelated command-injection bug in the same process
  lets an attacker steal the identity's token and read the secret directly
  from Key Vault, bypassing the app's own logic entirely. Tested end to end
  with a real (fake-value) secret.
