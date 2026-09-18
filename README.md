# Azure Functions Demos

Small, self-contained Azure Function demos for class. Each folder deploys
independently with a few `az` CLI commands — no Functions Core Tools
required.

- [`hello-world/`](hello-world/) — simplest possible Azure Function, sanity
  check that deploy tooling works.
- [`identity-abuse-demo/`](identity-abuse-demo/) — command injection in a
  Function's HTTP endpoint leads to abuse of an over-privileged
  (Contributor-scoped) system-assigned managed identity. Pairs with the
  Kubernetes over-privileged ServiceAccount demo — same lesson, different
  compute.
