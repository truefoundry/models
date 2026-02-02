# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this repository, please report it responsibly.

Please [open a GitHub issue](https://github.com/truefoundry/models/issues/new) with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

We will review and respond as soon as possible.

## Scope

This repository contains static YAML configuration files for LLM model metadata (pricing, features, limits). It does not contain executable code or handle sensitive data.

Security concerns for this repo are primarily:

- Malicious content in YAML files
- Incorrect pricing data that could lead to financial impact
- Supply chain concerns if used as a dependency

## Supported Versions

We only support the latest version on the `main` branch.
