# Deployment controls

## Before deployment

The service owner must document the model version, data version, intended users, known limitations, rollback procedure, and monitoring signals. Security review must confirm secret management, input validation, least-privilege access, and dependency scanning. The evaluation release gate must pass before deployment approval.

## Safe rollout

High-impact changes use a staged rollout. Start with an internal test group, inspect errors and latency, then increase traffic gradually. Keep the previous stable version available so the team can roll back without retraining.

## Operational monitoring

Monitor request failures, latency, cost, input drift, output quality samples, and user-reported incidents. Alerts must identify an on-call owner and link to the relevant response playbook.

