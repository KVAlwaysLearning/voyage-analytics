# Voyage Analytics on Kubernetes (kind)

| File | Purpose |
|---|---|
| kind-config.yaml | Local 1-node cluster; maps node port 30080 to localhost:8080 |
| namespace.yaml | `voyage` namespace |
| deployment.yaml | 2 replicas of the API image, rolling updates, startup/readiness/liveness probes on /health, CPU/memory requests and limits |
| service.yaml | NodePort service - one stable address that load-balances across pods |
| hpa.yaml | Horizontal Pod Autoscaler: 2-5 pods, target 50% average CPU |
| load-test.yaml | In-cluster Job: 20 workers call /predict/price for 4 minutes to trigger autoscaling |

Quick reference
```bash
kind create cluster --config k8s/kind-config.yaml
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/hpa.yaml
kubectl get pods,svc,hpa -n voyage
curl localhost:8080/health
kubectl apply -f k8s/load-test.yaml && kubectl get hpa -n voyage -w
kind delete cluster --name voyage
```
