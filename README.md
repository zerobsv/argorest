# Document Server API

A FastAPI REST API backed by SQLite. Opening `/` redirects to the Swagger UI at `/docs`; the OpenAPI JSON is available at `/openapi.json`.

## Kubernetes deployment with Helm

The FastAPI module now lives in `app/main.py`; the image runs it as
`app.main:app`. Build the image from the repository root and make it available
to your cluster. For a local kind cluster:

```sh
docker build -t document-server:1.5.0 .
docker tag document-api:1.0.0 YOUR_REGISTRY/document-api:1.0.0
docker push YOUR_REGISTRY/document-api:1.0.0
docker run --rm -p 8000:8000 document-server:1.5.0
```

```sh
kind load docker-image document-server:1.5.0
helm lint ./helm/telemetry
helm lint ./helm/document-server
helm upgrade --install telemetry ./helm/telemetry --namespace observability --create-namespace
helm upgrade --install document-server ./helm/document-server --namespace observability
```

The charts and their manifests are under [helm](./helm/):

- `helm/telemetry` deploys Prometheus, OpenSearch, Jaeger, and the ConfigMaps for
  `prometheus.yml` and the OpenTelemetry Collector configuration.
- `helm/document-server` deploys the REST API from `app.main:app` and its
  OpenTelemetry Collector sidecar. Metrics are exposed through the
  `otel-collector` Service for Prometheus to scrape.

Telemetry routing sends metrics to Prometheus, traces to Jaeger and OpenSearch,
and logs to OpenSearch. OpenSearch is configured as a single-node development
instance with its security plugin disabled. Prometheus and API data use
persistent volume claims; Jaeger stores traces in memory. Configure security,
storage, resources, and image registries appropriately before production use.
OpenSearch nodes may require the host's `vm.max_map_count` to be at least
`262144`.

## Run on Minikube

```
minikube start -p devx --driver=docker --nodes=3 --memory=4096m

minikube image load -p devx document-server:1.5.0

Cleanup:

minikube delete -p devx
```


## Install and Run Argo CD

```
kubectl create ns argocd

kubectl apply -n argocd --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'

kubectl port-forward svc/argocd-server -n argocd 8080:443

Cleanup:

kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl delete ns argocd
```

## Install Argo CD CLI

```
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64
```

## Staged deployment with Argo CD

#### Get admin password
```
argocd admin initial-password -n argocd
```

[argocd/application-set.yaml](./argocd/application-set.yaml)
uses an ApplicationSet `RollingSync` strategy with two stages: telemetry
backends first, then the document-server release. The second stage proceeds
when the telemetry Application is Healthy. The API's collector is a sidecar,
so it is deployed together with the API after the standalone backends are
healthy. Deletion uses reverse order so the API is removed before telemetry.

Before applying the ApplicationSet:

1. Push this repository to Git and replace `REPLACE_ME` in `repoURL` with its
   owner/organization. Adjust `targetRevision` if needed.
2. Use Argo CD 3.3 or later and enable Progressive Syncs on the ApplicationSet
   controller. For example, set
   `ARGOCD_APPLICATIONSET_CONTROLLER_ENABLE_PROGRESSIVE_SYNCS=true` on that
   controller, then restart it. The controller also supports the
   `--enable-progressive-syncs` argument or the
   `applicationsetcontroller.enable.progressive.syncs: "true"` command
   parameter.
3. Ensure Argo CD can access the repository and create resources in the target
   cluster.

Apply the staged deployment:

```sh
kubectl apply -n argocd -f argocd/application-set.yaml
```

RollingSync deliberately disables automated sync on its generated Applications.
The ApplicationSet controller initiates each stage and waits for every
Application in that stage to become Healthy before proceeding.

Forward ports to access the API and UIs:

```sh
kubectl -n observability port-forward service/document-server 8000:8000
kubectl -n observability port-forward service/prometheus 9090:9090
kubectl -n observability port-forward service/jaeger 16686:16686
kubectl -n observability port-forward service/opensearch 9200:9200
```

Open the API at [http://localhost:8000/](http://localhost:8000/) (or
[http://localhost:8000/docs](http://localhost:8000/docs)),
Prometheus at [http://localhost:9090](http://localhost:9090), and Jaeger at
[http://localhost:16686](http://localhost:16686). OpenSearch is available
inside the cluster at
`http://opensearch.observability.svc.cluster.local:9200`.

## Run the API locally

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python3 app/main.py
```

## Endpoints

- `POST /documents` accepts `{ "name": "xyz", "phone_name": ["a", "b", "c"], "location": "abc" }`; the server assigns an integer `id` and returns the stored document.
- `GET /document/{id}` returns a document, or `404` if it does not exist.

Example response:

```json
{ "id": 1, "name": "xyz", "phone_name": ["a", "b", "c"], "location": "abc" }
```

The API exports FastAPI request traces, endpoint request counts and durations,
and endpoint log records over OTLP. Set `DATABASE_PATH` to change the SQLite
file, or `OTEL_EXPORTER_OTLP_ENDPOINT` to point to another collector. The
default database path is `documents.db` in the working directory.


## Curl Commands

#### POST Command:

```
curl -X POST http://localhost:8000/documents   -H 'Content-Type: application/json'   -d '{"id":1,"name":"xyz","phone_name":["apple"],"location":"string"}'
```

#### GET Command:

```
curl -k http://localhost:8000/document/1
```

#### Demo Curl Requests:

```
curl -X POST http://localhost:8000/documents   -H 'Content-Type: application/json'   -d '{"id":1,"name":"axyz","phone_name":["apple"],"location":"string"}'   
curl -X POST http://localhost:8000/documents   -H 'Content-Type: application/json'   -d '{"id":2,"name":"bxyz","phone_name":["apple"],"location":"string"}'   
curl -k http://localhost:8000/document/1
curl -k http://localhost:8000/document/2
```
