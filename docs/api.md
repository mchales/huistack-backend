# Chinese Map API Reference (v1)

This document describes the available API endpoints, how to call them, and what they do. The API uses URL path versioning; all routes below are under the base path `/api/v1/` unless noted.

- Base URL: `/api/v1/`
- Versioning: URL path versioning (`v1` currently active; `v2` reserved)
- Format: JSON by default (multipart for file uploads)
- Authentication: JWT Bearer tokens for protected endpoints

## Authentication

Auth uses SimpleJWT with refresh tokens stored in a Secure, HttpOnly cookie. Most dictionary and lesson endpoints are public; progress endpoints require authentication.

- Header for protected endpoints: `Authorization: Bearer <access-token>`

Endpoints:

- POST `/auth/users/`

  - Description: Register a new user.
  - Body: `{ "username": string, "email": string, "first_name": string, "last_name": string, "password": string }`
  - Response: `201 Created` with user: `{ id, username, email, first_name, last_name }`
  - Example:
    - curl: `curl -X POST /api/v1/auth/users/ -H 'Content-Type: application/json' -d '{"username":"alice","email":"a@example.com","first_name":"Alice","last_name":"L","password":"secret123"}'`

- POST `/auth/jwt/create/`

  - Description: Login. Issues an access token in the response and sets the refresh token in a Secure, HttpOnly cookie.
  - Body: EITHER `{ "username": string, "password": string }` OR `{ "email": string, "password": string }`
  - Response JSON: `{ "access": string }` (no `refresh` field)
  - Response Headers: `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=None; Path=/` (flags depend on environment)
  - curl example (captures cookies for subsequent calls):
    ```sh
    curl -i -c cookies.txt -X POST /api/v1/auth/jwt/create/ \
      -H 'Content-Type: application/json' \
      -d '{"username":"alice","password":"secret123"}'
    ```

- POST `/auth/jwt/refresh/`

  - Description: Refreshes the access token using the refresh cookie. Also rotates the refresh cookie.
  - Body: `{}` (optional; if omitted, the server reads the refresh token from the cookie)
  - Response JSON: `{ "access": string }`
  - Response Headers: `Set-Cookie: refresh_token=...` (rotated)
  - curl example (sends stored cookies and updates them):
    ```sh
    curl -i -b cookies.txt -c cookies.txt -X POST /api/v1/auth/jwt/refresh/
    ```

- POST `/auth/token/blacklist/`

  - Description: Logout. Blacklists the refresh token and clears the cookie.
  - Body: `{}` (optional; taken from the cookie)
  - Response: `200 OK` or `205 Reset Content`
  - Response Headers: `Set-Cookie: refresh_token=; Max-Age=0; ...` (cleared)
  - curl example:
    ```sh
    curl -i -b cookies.txt -X POST /api/v1/auth/token/blacklist/
    ```

- GET `/auth/users/me/`
  - Description: Get the current user profile.
  - Auth: Required (`Authorization: Bearer <access>`)
  - Response: `{ id, username, email, first_name, last_name }`

Additional Djoser user routes are included (activation, password reset, etc.). JWT routes are provided by custom views to support cookie-based refresh. See `/api/v1/auth/routes/` for a quick list.

- GET `/auth/routes/`
  - Description: Convenience listing of major auth endpoints.

Notes on cookies and local development:

- Cookie name: `refresh_token` (configurable via settings).
- In production, the cookie is `Secure` and typically `SameSite=None`. For local HTTP testing, set `REFRESH_TOKEN_COOKIE_SECURE=false`.
- If you call endpoints without a trailing slash and `APPEND_SLASH=True`, Django redirects to the canonical slash URL; clients should follow redirects.
- For cross-site SPAs, send credentials on requests that need cookies (e.g., `fetch(..., { credentials: 'include' })`).

## Dictionary

Models: `Lemma` (headword) and `Sense` (definitions). These endpoints support DRF search and ordering filters.

Common query params:

- `search=` full-text across configured fields
- `ordering=` for sort fields (prefix with `-` for descending)

### Lemmas

- GET `/dictionary/lemmas/`

  - Description: List lemmas.
  - Filters:
    - `search`: matches `simplified`, `traditional`, `pinyin_numbers`, `senses__gloss`
    - `ordering`: one of `simplified`, `traditional` (default `simplified`)
  - Example: `GET /api/v1/dictionary/lemmas/?search=学习&ordering=traditional`
  - Response item fields:
    - `id`, `traditional`, `simplified`, `pinyin_numbers`, `meta`, `senses[]`

- GET `/dictionary/lemmas/{id}/`

  - Description: Retrieve a lemma by id.

- POST `/dictionary/lemmas/`

  - Description: Create a lemma. Note: No explicit write permissions are set in code; ensure production permissions restrict writes if needed.
  - Body: `{ traditional, simplified, pinyin_numbers, meta? }`

- PUT/PATCH `/dictionary/lemmas/{id}/`

  - Description: Update a lemma.

- DELETE `/dictionary/lemmas/{id}/`
  - Description: Delete a lemma.

Example response (truncated):

```json
{
  "id": 123,
  "traditional": "學習",
  "simplified": "学习",
  "pinyin_numbers": "xue2 xi2",
  "meta": {},
  "senses": [
    { "id": 456, "lemma": 123, "sense_index": 1, "gloss": "to study; to learn" }
  ]
}
```

### Senses

- GET `/dictionary/senses/`

  - Description: List senses.
  - Filters:
    - `search`: matches `gloss`, `lemma__simplified`, `lemma__traditional`, `lemma__pinyin_numbers`
    - `ordering`: `sense_index`, `lemma__simplified` (default `lemma__simplified`, `sense_index`)

- GET `/dictionary/senses/{id}/`

  - Description: Retrieve a sense.

- POST `/dictionary/senses/`

  - Body: `{ lemma: <lemma_id>, sense_index, gloss }`

- PUT/PATCH `/dictionary/senses/{id}/`, DELETE `/dictionary/senses/{id}/`

### Misc

- GET `/dictionary/routes/`
  - Description: Convenience listing of dictionary endpoints.

## Lessons

Lessons represent a set of sentences derived from text or SRT. Listing and retrieving lessons are public; ingest endpoints create lessons and their sentences/tokens.

### Browse Lessons

- GET `/lessons/`

  - Description: List lessons (sorted by `created_at` desc)
  - Response fields: `id (UUID)`, `title`, `source_language`, `target_language`, `meta`, `created_at`, `sentences[]`, `sources[]`

- GET `/lessons/{id}/`
  - Description: Retrieve a lesson with nested sentences, tokens, and translations.

Example lesson (truncated):

```json
{
  "id": "3f9e7b0c-...",
  "title": "My Lesson",
  "source_language": "zh",
  "target_language": "en",
  "meta": {"ingest": "jieba"},
  "created_at": "2024-05-24T10:23:12Z",
  "sources": [
    { "id": 1, "name": "", "text": "你好世界", "order": 1 }
  ],
  "sentences": [
    {
      "id": 10,
      "index": 1,
      "text": "你好世界",
      "start_char": 0,
      "end_char": 4,
      "start_ms": null,
      "end_ms": null,
      "tokens": [ {"id": 100, "index": 1, "text": "你", "kind": "word", "lemma": 200}, ... ],
      "translations": [ {"id": 300, "language": "en", "text": "Hello world", "source": "machine"} ]
    }
  ]
}
```

### My Lessons

- GET `/lessons/mine/`

  - Description: List lessons created by the authenticated user (sorted by `created_at` desc).
  - Auth: Required (`Authorization: Bearer <access>`)
  - Response item fields: `title`, `created_at`
  - Example response:

    ```json
    [
      { "title": "Episode 1", "created_at": "2024-05-24T10:23:12Z" },
      { "title": "Greeting", "created_at": "2024-05-20T09:01:45Z" }
    ]
    ```

### Ingest Text

- POST `/lessons/ingest/`
  - Description: Create a lesson by ingesting raw text. Automatically splits into sentences, tokenizes, links tokens to lemmas where possible, and adds best-effort machine translations per sentence. Returns any missing characters not found in the dictionary.
  - Body (JSON):
    - `title` (required): string
    - `text` (required): string
    - `name` (optional): string, source label
    - `source_language` (optional, default `zh`)
    - `target_language` (optional, default `en`)
  - Response: `{ lesson: <Lesson>, created: true, sentence_count: number, missing_characters: [string] }`
  - Example curl:
    ```sh
    curl -X POST /api/v1/lessons/ingest/ \
      -H 'Content-Type: application/json' \
      -d '{
            "title": "Greeting",
            "text": "你好！今天怎么样？",
            "source_language": "zh",
            "target_language": "en"
          }'
    ```

### Ingest SRT (SubRip)

- POST `/lessons/ingest-srt/`
  - Description: Create a lesson by uploading an `.srt` subtitle file. Preserves cue timings on sentences and otherwise performs the same tokenization/translation as text ingest.
  - Body (multipart/form-data):
    - `title` (required): string
    - `file` (required): SRT file
    - `name` (optional): string, source label (defaults to uploaded filename)
    - `source_language` (optional, default `zh`)
    - `target_language` (optional, default `en`)
  - Example curl:
    ```sh
    curl -X POST /api/v1/lessons/ingest-srt/ \
      -H 'Authorization: Bearer <token>' \
      -F 'title=Episode 1' \
      -F 'file=@/path/to/subs.srt' \
      -F 'source_language=zh' \
      -F 'target_language=en'
    ```

## Progress

Tracks a user’s familiarity with specific lemmas (1–5 scale). All endpoints require authentication.

- Model fields: `id`, `lemma` (expanded in responses), `familiarity` (1..5), `created_at`, `updated_at`

Routes:

- GET `/progress/`

  - Description: List the current user’s lemma progress, ordered by `updated_at` desc.
  - Auth: Required

- PUT/PATCH `/progress/{id}/`

  - Description: Update familiarity for a specific progress record.
  - Body: `{ "familiarity": 1..5 }`
  - Auth: Required

- DELETE `/progress/{id}/`

  - Description: Delete a progress record.
  - Auth: Required

- POST `/progress/rank/`
  - Description: Upsert familiarity for a lemma for the current user.
  - Body: `{ "lemma": <lemma_id>, "familiarity": 1..5 }`
  - Response: The resulting progress record with expanded lemma.
  - Example curl:
    ```sh
    curl -X POST /api/v1/progress/rank/ \
      -H 'Authorization: Bearer <token>' \
      -H 'Content-Type: application/json' \
      -d '{"lemma": 123, "familiarity": 4}'
    ```

Example response:

```json
{
  "id": 42,
  "lemma": {
    "id": 123,
    "traditional": "學習",
    "simplified": "学习",
    "pinyin_numbers": "xue2 xi2",
    "meta": {},
    "senses": [
      {
        "id": 456,
        "lemma": 123,
        "sense_index": 1,
        "gloss": "to study; to learn"
      }
    ]
  },
  "familiarity": 4,
  "created_at": "2024-05-24T10:30:00Z",
  "updated_at": "2024-05-24T10:35:12Z"
}
```

## Search and Ordering

- Lemmas: `GET /dictionary/lemmas/?search=<q>&ordering=<field>`
- Senses: `GET /dictionary/senses/?search=<q>&ordering=<field>`

Notes:

- `search` uses DRF’s SearchFilter across configured fields.
- `ordering` uses DRF’s OrderingFilter; prefix with `-` for descending.

## Errors

Standard DRF error responses:

- Validation error: `400 Bad Request` with `{ "field": ["error message"] }`
- Authentication error: `401 Unauthorized`
- Permission error: `403 Forbidden`
- Not found: `404 Not Found`

## Quick Route Index

- Auth: `/auth/...` (Djoser + SimpleJWT)
- Dictionary: `/dictionary/lemmas/`, `/dictionary/senses/`, `/dictionary/routes/`
- Lessons: `/lessons/`, `/lessons/{id}/`, `/lessons/ingest/`, `/lessons/ingest-srt/`
- Progress: `/progress/`, `/progress/{id}/`, `/progress/rank/`

---

Implementation sources for reference:

- config routing: `config/urls.py`
- auth: `apps/accounts/api/v1/urls.py`, `apps/accounts/api/v1/views.py`, `apps/accounts/api/v1/serializers.py`
- dictionary: `apps/dictionary/api/v1/urls.py`, `apps/dictionary/api/v1/views.py`, `apps/dictionary/api/v1/serializers.py`
- lessons: `apps/lessons/api/v1/urls.py`, `apps/lessons/api/v1/views.py`, `apps/lessons/api/v1/serializers.py`
- progress: `apps/progress/api/v1/urls.py`, `apps/progress/api/v1/views.py`, `apps/progress/api/v1/serializers.py`
