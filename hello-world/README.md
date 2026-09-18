# Hello World — Azure Function

Simplest possible Azure Function demo: one HTTP-triggered endpoint, Python v2
programming model, deployed with a single `az functionapp deployment source
config-zip` call — no Functions Core Tools needed.

## Deploy

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
