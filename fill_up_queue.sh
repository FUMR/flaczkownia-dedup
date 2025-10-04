#!/bin/bash

DIR="$1"
URL="$2"

[[ -d "$DIR" ]] || { echo "Usage: $0 <directory_path> <url>"; exit 1; }

declare -A lookup

for f in *; do
    filename="$(basename "$f")"
    msg_id="${filename%% *}"
    [[ "$msg_id" =~ ^[0-9]+$ ]] || continue
    lookup[$msg_id]="$f"
done

for id in "${!lookup[@]}"; do
    echo "$id"
done | sort -nr | while read -r id; do
    curl -s -X POST -H "Content-Type: application/json" -d '{"fname": '"${lookup[$id]}"'}' "$URL"
done
