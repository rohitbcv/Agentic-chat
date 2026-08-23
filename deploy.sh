#!/bin/bash
# Deployment script for Agentic Chat
# Run on the server at: /root/AI_Automated_agent/Agentic-chat/deploy.sh
# Triggered by GitHub Actions on every push to main.
set -e

REPO_DIR="/root/AI_Automated_agent/Agentic-chat"
LOG_TAG="[agentic-deploy]"

echo "$LOG_TAG Starting deployment at $(date)"

cd "$REPO_DIR"

echo "$LOG_TAG Pulling latest code from origin main..."
git pull origin main

echo "$LOG_TAG Installing/updating Python dependencies..."
pip install -r requirements.txt --quiet

echo "$LOG_TAG Restarting backend service..."
systemctl restart agentic-backend

echo "$LOG_TAG Installing/updating frontend dependencies..."
cd frontend
npm install --silent
cd ..

echo "$LOG_TAG Restarting frontend service..."
systemctl restart agentic-frontend

echo "$LOG_TAG Deployment complete at $(date)"
