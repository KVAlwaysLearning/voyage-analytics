// Voyage Analytics - CI/CD pipeline for the prediction API (api/ folder)
//
//   CI : Prepare -> Build image -> Unit tests (inside the image) -> Smoke test (running container)
//   CD : Push to Docker Hub -> Deploy to Render -> Verify live API serves this exact build
//
// Every build gets its own version (1.0.<build>-<commit>) that is baked into the image and
// reported by GET /health, so the last stage can prove the new build is live on Render.

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    triggers {
        pollSCM('H/5 * * * *')      // check GitHub every 5 minutes - a new commit starts a build
    }

    parameters {
        booleanParam(name: 'DEPLOY', defaultValue: true,
                     description: 'Push to Docker Hub and redeploy Render after the tests pass (untick for a CI-only run)')
    }

    stages {

        stage('Prepare') {
            steps {
                script {
                    if (!env.DOCKERHUB_USERNAME?.trim()) {
                        error('DOCKERHUB_USERNAME is not set - restart Jenkins with: bash jenkins/start_jenkins.sh')
                    }
                    env.GIT_SHORT   = sh(script: 'git rev-parse --short=7 HEAD', returnStdout: true).trim()
                    env.APP_VERSION = "1.0.${env.BUILD_NUMBER}-${env.GIT_SHORT}"
                    env.IMAGE       = "docker.io/${env.DOCKERHUB_USERNAME.toLowerCase()}/voyage-api"
                    env.TAG         = "${env.BUILD_NUMBER}-${env.GIT_SHORT}"
                    env.DO_DEPLOY   = (params.DEPLOY == false) ? 'false' : 'true'
                    currentBuild.displayName = "#${env.BUILD_NUMBER} - ${env.GIT_SHORT}"
                }
                sh '''
                    rm -rf reports && mkdir -p reports
                    echo "Commit : $(git log -1 --pretty='%h %s (%an)')"
                    echo "Version: $APP_VERSION"
                    echo "Image  : $IMAGE:$TAG"
                    docker version --format 'Docker client {{.Client.Version}} / server {{.Server.Version}}'
                    for f in api/Dockerfile api/requirements.txt api/app.py api/model_service.py; do
                        test -f "$f" || { echo "Missing $f"; exit 1; }
                    done
                    test -d api/models && test -d api/tests
                    ls -la api/models
                '''
            }
        }

        stage('Build image') {
            steps {
                sh '''
                    docker build --pull --progress=plain -t "voyage-api-ci:$BUILD_NUMBER" api
                    # stamp this build's version into the image so GET /health reports it
                    printf 'FROM voyage-api-ci:%s\\nENV APP_VERSION=%s\\nLABEL org.opencontainers.image.revision=%s\\n' "$BUILD_NUMBER" "$APP_VERSION" "$GIT_SHORT" > reports/Dockerfile.version
                    docker build --progress=plain -t "$IMAGE:$TAG" -t "$IMAGE:latest" - < reports/Dockerfile.version
                    docker image ls "$IMAGE"
                '''
            }
        }

        stage('Unit tests') {
            steps {
                // tests/ is kept out of the production image (.dockerignore), so copy it into a throw-away container
                sh '''
                    C="ut-$BUILD_NUMBER"
                    docker rm -f "$C" >/dev/null 2>&1 || true
                    docker create --name "$C" --entrypoint sh "$IMAGE:$TAG" -c "pip install --quiet --user pytest && python -m pytest -v --junitxml=/tmp/junit.xml tests"
                    docker cp api/tests "$C:/app/tests"
                    docker start -a "$C" || true
                    docker cp "$C:/tmp/junit.xml" reports/junit.xml || true
                    rc=$(docker inspect -f '{{.State.ExitCode}}' "$C")
                    docker rm -f "$C" >/dev/null
                    echo "pytest exit code: $rc"
                    [ "$rc" = "0" ]
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/junit.xml'
                }
            }
        }

        stage('Smoke test') {
            steps {
                // run the real image the way Render/Kubernetes would, and call it over HTTP
                sh '''
                    C="smoke-$BUILD_NUMBER"
                    docker rm -f "$C" >/dev/null 2>&1 || true
                    docker run -d --name "$C" "$IMAGE:$TAG"
                    IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$C")
                    URL="http://$IP:5000"

                    echo "Waiting for $URL/health ..."
                    for i in $(seq 1 40); do
                        if curl -fsS --max-time 5 "$URL/health" -o reports/smoke_health.json; then break; fi
                        sleep 3
                    done
                    cat reports/smoke_health.json; echo
                    grep -Eq '"status": ?"ok"' reports/smoke_health.json
                    grep -qF "$APP_VERSION" reports/smoke_health.json

                    curl -fsS --max-time 30 -X POST "$URL/predict/price" -H 'Content-Type: application/json' -d '{"from": "Recife (PE)", "to": "Florianopolis (SC)", "flightType": "firstClass", "agency": "FlyingDrops"}' -o reports/smoke_price.json
                    cat reports/smoke_price.json; echo
                    grep -q '"predicted_price"' reports/smoke_price.json

                    curl -fsS --max-time 30 -X POST "$URL/predict/gender" -H 'Content-Type: application/json' -d '{"name": "Maria Silva", "age": 34, "company": "4You"}' -o reports/smoke_gender.json
                    cat reports/smoke_gender.json; echo
                    grep -q '"predicted_gender"' reports/smoke_gender.json

                    curl -fsS --max-time 30 -X POST "$URL/recommend/hotels" -H 'Content-Type: application/json' -d '{"userCode": 0, "origin": "Recife (PE)", "max_price": 250, "k": 3}' -o reports/smoke_hotels.json
                    cat reports/smoke_hotels.json; echo
                    grep -q '"recommendations"' reports/smoke_hotels.json

                    code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/predict/price" -H 'Content-Type: application/json' -d '{"from": "Natal (RN)", "to": "Natal (RN)", "flightType": "economic", "agency": "Rainbow"}')
                    echo "Invalid request returned HTTP $code (expected 400)"
                    [ "$code" = "400" ]
                '''
            }
            post {
                always {
                    sh '''
                        docker logs "smoke-$BUILD_NUMBER" > reports/smoke_container.log 2>&1 || true
                        docker rm -f "smoke-$BUILD_NUMBER" >/dev/null 2>&1 || true
                    '''
                }
            }
        }

        stage('Push to Docker Hub') {
            when { expression { env.DO_DEPLOY == 'true' } }
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub', usernameVariable: 'DH_USER', passwordVariable: 'DH_TOKEN')]) {
                    sh '''
                        echo "$DH_TOKEN" | docker login docker.io -u "$DH_USER" --password-stdin
                        docker push "$IMAGE:$TAG"
                        docker push "$IMAGE:latest"
                    '''
                }
            }
            post {
                always {
                    sh 'docker logout docker.io >/dev/null 2>&1 || true'
                }
            }
        }

        stage('Deploy to Render') {
            when { expression { env.DO_DEPLOY == 'true' && env.RENDER_DEPLOY_ENABLED == 'true' } }
            steps {
                withCredentials([string(credentialsId: 'render-deploy-hook', variable: 'HOOK')]) {
                    sh '''
                        curl -fsS -X POST "$HOOK" -o reports/render_deploy.json
                        cat reports/render_deploy.json; echo
                    '''
                }
            }
        }

        stage('Verify live API') {
            when { expression { env.DO_DEPLOY == 'true' && env.RENDER_DEPLOY_ENABLED == 'true' } }
            steps {
                timeout(time: 15, unit: 'MINUTES') {
                    sh '''
                        echo "Waiting for $RENDER_API_URL to serve version $APP_VERSION (a free Render deploy takes a few minutes)"
                        until curl -fsS --max-time 90 "$RENDER_API_URL/health" -o reports/live_health.json && grep -qF "$APP_VERSION" reports/live_health.json; do
                            echo "  live API is on: $(grep -o '"version": *"[^"]*"' reports/live_health.json 2>/dev/null || echo 'starting up')"
                            sleep 20
                        done
                        echo "Live API is serving this build:"
                        cat reports/live_health.json; echo
                    '''
                }
            }
        }
    }

    post {
        success {
            script {
                currentBuild.description = (env.DO_DEPLOY == 'true') ? "shipped ${env.IMAGE}:${env.TAG}" : "tested ${env.TAG} (not deployed)"
            }
        }
        failure {
            echo 'Pipeline failed - nothing after the failed stage was run, so Docker Hub and Render still have the previous good build.'
        }
        always {
            archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
            sh '''
                docker rmi "voyage-api-ci:$BUILD_NUMBER" >/dev/null 2>&1 || true
            '''
        }
    }
}
