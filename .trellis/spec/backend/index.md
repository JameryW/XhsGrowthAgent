# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Active |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | Active |
| [Error Handling](./error-handling.md) | Error types, retry, cancel/pause | Active |
| [Workflow State](./workflow-state.md) | Status derivation, interrupts, event emission | Active |
| [OMP Integration](./omp-integration.md) | Cross-layer API contracts for omp extension + Web TUI | Active |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |
| [Browser Auth Probes](./browser-auth-probes.md) | Read-only browser-backed login evidence | Active |
| [Browser Automation Safety](./browser-automation-safety.md) | Headed CDP browser and risk-stop conventions | Active |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
