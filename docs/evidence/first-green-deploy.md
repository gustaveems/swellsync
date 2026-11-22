# First green deploy from main

The pipeline in `.github/workflows/cd.yml` deploys on every push to `main`. It calls
the CI and image workflows, then signs in to Azure with the managed identity (OIDC),
points both Container Apps at the commit's image, uploads the UI, and checks that
each `/health` reports the commit.

## The first run failed

| | |
|---|---|
| Run | `cd` 45051869246, commit `71d8092` (merge of PR 2) |
| CI and image jobs | all passed |
| Azure sign-in (OIDC) | passed |
| Apps updated to `71d8092` | passed, including migration 002 on the Azure database |
| UI upload | **failed**: `HttpMethodIsNotSupported` |
| Health check | skipped |

Cause: the deploy job read `$UI_STORAGE` but never defined it, so the storage account
name was empty. The step before it built `ALLOWED_ORIGIN` from the same empty name and
set it to an empty string on both services. I set the origin back by hand on the live
apps, and fixed the workflow in PR 3 (`UI_STORAGE` is defined, and the job stops if the
UI origin is not an `https://` address).

## The run after the fix passed

| | |
|---|---|
| Run | `cd` 45052424748, commit `bfa6f73` (merge of PR 3) |
| Result | success, every step |

| Step | Result |
|---|---|
| CI (lint, unit tests spots and sessions, cross-seam integration, contracts) | success |
| Image build, spots and sessions | success |
| Azure sign-in (OIDC) | success |
| Point both Container Apps at this commit's image | success |
| Write `ui/config.js` and upload the UI | success |
| Health check, both services | success |

## Checked on the live system afterwards

```text
spots     {"db":"ok","status":"ok","version":"bfa6f73a74792abbb397c4041e97128ac6ed3949"}
sessions  {"db":"ok","status":"ok","version":"bfa6f73a74792abbb397c4041e97128ac6ed3949"}
ALLOWED_ORIGIN on both: https://gamsoulasieu2024ui.z1.web.core.windows.net
```

The sessions page at https://gamsoulasieu2024ui.z1.web.core.windows.net/sessions.html
lists all six sessions with spot names, so the browser, the sessions service and the
spots lookup across the seam all work in the deployed system.

## A failed CI run and its fix, on a throwaway branch

To show the gate, a deliberately broken contract was pushed to `evidence/failed-then-fixed`
(never merged): `system.yaml` named the spot path `{id}`, the OpenAPI document says `{spot_id}`.

| Commit | Run | Result |
|---|---|---|
| `18e8335` broken | `ci` 45051801890 | `contracts` failed; lint, both unit-test jobs and integration passed |
| `5a05243` fixed | `ci` 45051902632 | all five checks passed |
