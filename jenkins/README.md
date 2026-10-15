# Voyage Analytics - Jenkins CI/CD

Jenkins runs in a Docker container inside the GitHub Codespace and uses the Codespace's Docker engine
(through `/var/run/docker.sock`) to build and run the API image.

## Pipeline (`Jenkinsfile` in the repo root)

| # | Stage | What it does | Fails when |
|---|---|---|---|
| 1 | Prepare | Reads the commit, sets the build version `1.0.<build>-<commit>` and image tag | required files missing |
| 2 | Build image | `docker build` of `api/`, then stamps `APP_VERSION` into the image | Dockerfile / dependency error |
| 3 | Unit tests | Runs the 13 pytest tests inside the built image, publishes JUnit results | any test fails |
| 4 | Smoke test | Starts the container, calls `/health`, price, gender, hotels and an invalid request (expects 400) | API does not start or answers wrongly |
| 5 | Push to Docker Hub | Pushes `<user>/voyage-api:<build>-<commit>` and `:latest` | login / push error |
| 6 | Deploy to Render | Calls the Render deploy hook so Render pulls the new `:latest` image | hook rejected |
| 7 | Verify live API | Polls the Render URL until `/health` reports this build's version (max 15 min) | new build never goes live |

A failure stops the pipeline, so Docker Hub and Render keep the last good build.
Triggers: GitHub is polled every 5 minutes (new commit on `main` -> build), or click **Build Now**.
**Build with Parameters -> untick DEPLOY** runs CI only (stages 1-4).

## Files

| File | Purpose |
|---|---|
| `Jenkinsfile` (repo root) | The pipeline |
| `jenkins/Dockerfile` | Jenkins LTS + Docker CLI + plugins + configuration |
| `jenkins/plugins.txt` | Plugins (Pipeline, Git, JCasC, Job DSL, JUnit, Stage View ...) |
| `jenkins/casc.yaml` | Configuration as Code: admin user, credentials, the `voyage-api-ci` job |
| `jenkins/start_jenkins.sh` | Builds and starts Jenkins with the right settings |

## Start

```bash
export DOCKERHUB_USERNAME=<docker hub username>
export DOCKERHUB_TOKEN=<docker hub access token>
export RENDER_DEPLOY_HOOK='<render deploy hook url>'      # optional
export RENDER_API_URL=https://<your-api>.onrender.com     # optional
bash jenkins/start_jenkins.sh
```

Open port 8090 from the Ports tab and log in as `admin` with the printed password.
Stop with `docker rm -f jenkins` (build history is kept in the `jenkins_home` Docker volume).
