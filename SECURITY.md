# Security policy

EmotionVector is a research prototype, not a production safety or personality
control system. Do not deploy its steering or post-training paths as a security
boundary.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for security-sensitive findings.
Do not open a public issue containing credentials, private data, exploit
details, restricted condition keys, or unpublished review artifacts.

If private vulnerability reporting is unavailable, contact the repository
owner through the GitHub profile associated with this repository and disclose
only the minimum information required to establish a private channel.

## Secrets and local artifacts

Never commit `.env`, API keys, database dumps, model weights, Hugging Face
caches, raw downloaded datasets, adapters, activation arrays, or files under
`results/local_artifacts/`. Treat generated outputs as untrusted text when
rendering them in a UI or downstream tool.
