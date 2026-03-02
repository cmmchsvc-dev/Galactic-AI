#!/bin/bash

# Check if .env file exists
if [ -f .env ]; then
    # Extract GEMINI_API_KEY and export it as an environment variable
    # Assumes the format GEMINI_API_KEY=value in .env
    export GEMINI_API_KEY=$(grep "^GEMINI_API_KEY" .env | cut -d '=' -f2-)
    echo "GEMINI_API_KEY has been set in this shell context."
else
    echo ".env file not found."
fi
