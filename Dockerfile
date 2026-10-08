# syntax=docker/dockerfile:1
# =============================================================================
#  SDD Individual Assignment 1: container template
# =============================================================================
#
#  WHAT THIS FILE IS
#    A skeleton, provided to everyone. Copy it to the root of your repository
#    and fill in ONLY the four lines marked `TODO`. Do not restructure it, do
#    not add stages, do not add services. Writing real Docker is Assignment 2.
#
#  THE OUTPUT CONTRACT
#    Whatever you put in the TODOs, the image this file produces MUST behave
#    exactly like this. This is what we run, and what we grade against (§7).
#
#      Build     docker build -t myapp .
#                ...from a clean clone of your repo, with no extra flags, no
#                build args, and no files that are gitignored.
#
#      Run       docker run -p 8000:8000 -v myapp-data:/data myapp
#                ...and the app is serving within a few seconds, with no
#                interactive prompt, no manual migration, and no .env file.
#
#      Reach     curl http://localhost:8000/  answers from the host.
#                So your app binds 0.0.0.0, never 127.0.0.1 (§7.2).
#
#      Port      docker run -e PORT=9000 -p 9000:9000 myapp  also works.
#                So your app reads the PORT variable (§7.3). Hardcoding 8000
#                in your source breaks this even though the default matches.
#
#      Persist   Your SQLite file is written under $DATA_DIR, nowhere else, and
#                your app creates its own schema on first boot (§7.4, §7.5).
#                `docker rm` the container, run it again on the same volume,
#                and the data is still there.
#
#      Config    Every other setting is read from an environment variable with
#                a sane default (§7.9). No editing source to reconfigure.
#
#    Check all of this with the provided run.sh before you submit. If it fails,
#    the fix belongs in your application code, not in this file.
#
# =============================================================================


# -----------------------------------------------------------------------------
#  TODO 1  Pick your base image. Use the `-slim` variant of your language.
# -----------------------------------------------------------------------------
FROM python:3.12-slim
# Node:  FROM node:22-slim


# -----------------------------------------------------------------------------
#  Contract environment. Do not change these two. They are the defaults the
#  grading script relies on; override them at `docker run` time if you need to.
# -----------------------------------------------------------------------------
ENV PORT=8000 \
    DATA_DIR=/data

WORKDIR /app

# Unprivileged user, and the directory your SQLite file lives in. /data is
# deliberately outside /app so a volume can be mounted there and your database
# survives the container being rebuilt.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data /app


# -----------------------------------------------------------------------------
#  TODO 2  Copy your dependency manifest and install from it.
#
#  Keep this ABOVE the source copy in TODO 3. Docker caches layers: if your
#  dependencies are installed before your source is copied, editing one source
#  file does not reinstall every package. Swapping the two blocks costs you that
#  cache on every build, and is a question we may ask at the comprehension check.
#
#  Pin your versions (`flask==3.0.3`, not `flask`). An unpinned manifest means
#  the image you build in December is not the image you built in October.
# -----------------------------------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Node:  COPY package.json package-lock.json ./
#        RUN npm ci
#
# uv, if that is already how you work locally. Use whichever matches your own
# setup: the point is that the container installs the way you do, not that you
# adopt a new tool for this assignment. pip above is the safe default.
#
#   same requirements.txt, uv just resolves it faster:
#       COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /bin/uv
#       COPY requirements.txt ./
#       RUN uv pip install --system --no-cache -r requirements.txt
#
#   pyproject.toml + uv.lock as your manifest (that lockfile is then the one
#   file §1a asks you to commit, and --frozen makes the build fail rather than
#   silently re-resolve if it is out of date):
#       COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /bin/uv
#       COPY pyproject.toml uv.lock ./
#       RUN uv sync --frozen --no-dev
#       ENV PATH="/app/.venv/bin:$PATH"


# -----------------------------------------------------------------------------
#  TODO 3  Copy your application source. List only what the app needs to RUN.
#
#  Replace the line below with your own files and folders. Examples:
#      COPY app.py ./
#      COPY src/ ./src/
#      COPY templates/ ./templates/ static/ ./static/
#
#  Do NOT write `COPY . .`. Your build context is your working directory, not a
#  clean clone, and .gitignore does not apply to it: `COPY . .` copies your .git
#  history, your .venv or node_modules, your local *.db, and your .env straight
#  into the image. A leaked .env in a built image is the classic way secrets get
#  published. Listing what you copy is also faster, because editing a file you
#  did not copy cannot invalidate the layer cache.
#
#  Leave your tests out too: the image runs the app, it does not run pytest.
#
#  SEED DATA: if your app needs reference data to be useful, copy the seed FILE
#  here (`COPY seed.sql ./`) and have your app load it on first boot when the
#  table is empty. Do not copy a prebuilt .db into /data: that directory is a
#  mounted volume at runtime, so anything you bake in there is shadowed or
#  ignored, and the app you tested is not the app that runs (§7.11).
# -----------------------------------------------------------------------------
COPY app.py domain_logic.py seed.json ./
COPY templates/ ./templates/
COPY static/ ./static/

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Proves the app is reachable on PORT from outside the process, without
# assuming any particular route exists. A real /health endpoint is Assignment 2.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/${PORT}' || exit 1


# -----------------------------------------------------------------------------
#  TODO 4  The single command that starts your app (§7.1).
#
#  This is the same command you document in your README. It must start the app
#  and nothing else: no migrations to run first, no prompts, no setup wizard.
# -----------------------------------------------------------------------------
CMD ["python", "app.py"]
# Node:  CMD ["npm", "start"]
