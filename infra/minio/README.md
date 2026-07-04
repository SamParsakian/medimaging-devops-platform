# MinIO

MinIO is the object storage service for this project. At this stage it's just running alongside Orthanc and PostgreSQL - no buckets are created automatically yet.

Later steps will start writing to it: processed image previews, AI inference outputs, and periodic backups of the Orthanc and PostgreSQL data.

- Console: http://localhost:9001
- API: http://localhost:9000

Login with the `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` values from `.env`.
