#!/bin/bash
# Builds a sanitized release ZIP of Galactic AI.

VERSION_ARG=""
if [ -n "$1" ]; then
    VERSION_ARG="--set-version $1"
    echo -e "\033[33mSyncing versions to $1...\033[0m"
fi

echo -e "\033[36mStarting Galactic AI Release Builder...\033[0m"

# Ensure Python is available
if ! command -v python3 &> /dev/null
then
    if ! command -v python &> /dev/null
    then
        echo -e "\033[31mError: Python is not installed or not in PATH.\033[0m"
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# Run the release script
$PYTHON_CMD scripts/release.py $VERSION_ARG

if [ $? -eq 0 ]; then
    echo -e "\033[32mRelease build complete! Check the 'releases' directory.\033[0m"
else
    echo -e "\033[31mRelease build failed. Check output above for details.\033[0m"
fi