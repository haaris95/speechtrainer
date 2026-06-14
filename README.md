# Speech Trainer Python

This is a Python-backend version of Speech Trainer. It keeps the same browser UI
and replaces the Node backend with a small Python standard-library server.

## What It Does

- Serves the Speech Trainer web app at `http://localhost:8789`
- Uses a modern Typeform-style interview UI with one question at a time
- Records each IELTS answer as WAV audio in the browser
- Fetches one IELTS-style question at a time from Azure AI Foundry
- Processes each answer privately when the user clicks Next
- Stores per-answer scoring and feedback until the final report
- Sends audio to `/api/evaluate-answer`
- Uses Azure AI Speech - pronunciation assessment for pronunciation, fluency,
  prosody, and word-level metrics
- Sends speech metrics plus transcript to Azure AI Foundry for IELTS-style
  scoring and feedback
- Presents the final results as a professional business-style report after all answers are complete

## Install

```powershell
cd C:\Users\mailh\Documents\Codex\2026-06-08\i-m-planning-to-build-an\outputs\speechtrainerpy\server
python -m pip install -r requirements.txt
```

## Environment

Rotate any key that was pasted into chat, then set:

```powershell
$env:PORT="8789"
$env:AZURE_SPEECH_REGION="eastus"
$env:AZURE_SPEECH_KEY="YOUR_ROTATED_SPEECH_KEY"
$env:FOUNDRY_PROJECT_ENDPOINT="https://speechtrainer-resource.services.ai.azure.com/api/projects/speechtrainer"
$env:FOUNDRY_MODEL="gpt-4.1-mini"
$env:FOUNDRY_AGENT_NAME="speechtrainer"
$env:FOUNDRY_AGENT_VERSION="1"
$env:AZURE_AI_AUTH_TOKEN="YOUR_FOUNDRY_TOKEN"
```

Get the Foundry token with:

```powershell
az login
az account get-access-token --scope https://ai.azure.com/.default
```

## Run

```powershell
python app.py
```

Open:

```text
http://localhost:8789
```
