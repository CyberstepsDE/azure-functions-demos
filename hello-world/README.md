# Hello World — Azure Function

A minimal Azure Function: one HTTP-triggered endpoint that reads a `name`
parameter and returns a greeting. Uses the Python v2 programming model and
deploys with a single `az functionapp deployment source config-zip` call —
no Functions Core Tools needed.

## Deploy

Clone the repo and enter the demo directory first — the zip step below packs the
current directory, so running it from anywhere else uploads the wrong files.

```bash
git clone https://github.com/CyberstepsDE/azure-functions-demos.git
cd azure-functions-demos/hello-world
```

```bash
RG=rg-func-helloworld-demo
LOC=westeurope
STORAGE=sthellofuncdemo$RANDOM
FUNCAPP=func-helloworld-demo-$RANDOM

az group create -n $RG -l $LOC
az storage account create -n $STORAGE -g $RG -l $LOC --sku Standard_LRS
az functionapp create -g $RG --consumption-plan-location $LOC \
  --runtime python --runtime-version 3.11 --functions-version 4 \
  --name $FUNCAPP --storage-account $STORAGE --os-type Linux

az functionapp config appsettings set -g $RG -n $FUNCAPP \
  --settings AzureWebJobsFeatureFlags=EnableWorkerIndexing SCM_DO_BUILD_DURING_DEPLOYMENT=true

zip -r /tmp/hello-world.zip . -x "*.git*"
az functionapp deployment source config-zip -g $RG -n $FUNCAPP --src /tmp/hello-world.zip
```

## Test

```bash
curl "https://$FUNCAPP.azurewebsites.net/api/hello?name=Cybersteps"
```

```
Hello, Cybersteps!
```

## Cleanup

```bash
az group delete -n $RG --yes --no-wait
```
