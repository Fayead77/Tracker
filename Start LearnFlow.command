#!/bin/bash
# Double-click this file to start LearnFlow.
cd "$(dirname "$0")"

# First-time setup: create the virtual environment if it doesn't exist yet.
if [ ! -d "venv" ]; then
  echo "First time setup — installing dependencies..."
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt
fi

# Open the browser shortly after the server starts.
( sleep 2 && open http://127.0.0.1:5001 ) &

echo "Starting LearnFlow — leave this window open while you use the app."
echo "Close this window (or press Ctrl+C) to stop the server."
./venv/bin/python app.py
