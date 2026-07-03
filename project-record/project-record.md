# Project Record

This record documents the build of a medical imaging DevOps platform, step by step. The project is planned to grow from a basic imaging stack into a more complete platform, including DICOM handling, storage, security, monitoring, backup, and later deployment-related work.

## Step 0 — Verifying the Development Environment

Before the platform was built, the local environment was checked to confirm that the basic tools needed for the project were installed.

Required tools for the first steps:

- Git
- Docker
- Docker Compose
- VS Code

Commands used:

```bash
git --version
docker --version
docker compose version
```

Screenshot:

![Tool versions confirmed](images/step-0-tool-versions.png)

All three tools were found installed and working, so nothing was blocking the start of the actual build.
