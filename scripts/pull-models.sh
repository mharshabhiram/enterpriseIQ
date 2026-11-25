#!/bin/sh
# Idempotent model download for Ollama. Model names come from the environment.
set -e
LLM="${OLLAMA_LLM_MODEL:-mistral}"
EMBED="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"

echo "Waiting for Ollama at ${OLLAMA_HOST:-http://localhost:11434} ..."
i=0
until ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -gt 60 ] && { echo "Ollama did not become reachable"; exit 1; }
  sleep 2
done

for model in "$LLM" "$EMBED"; do
  if ollama list | awk 'NR>1 {print $1}' | grep -Eq "^${model}(:latest)?$"; then
    echo "✓ ${model} already installed"
  else
    echo "↓ pulling ${model} (first time only — this can take a while)"
    ollama pull "$model"
  fi
done
echo "Models ready: ${LLM}, ${EMBED}"
