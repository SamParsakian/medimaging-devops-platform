# MinIO

MinIO is the object storage service for this project.

- Console: http://localhost:9001
- API: http://localhost:9000

Login with the `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` values from `.env`.

One bucket is used for everything processed:

```text
medimaging
```

Objects inside it use a path prefix per category, for example:

```text
processed/anonymized/{study_uid}/{filename}
```

More prefixes (previews, AI outputs, backups) can be added the same way later.
