#!/usr/bin/env python3

import argparse
import requests
import sys
import os

def main():
    parser = argparse.ArgumentParser(description="Send file content to the RCAccelerator API endpoint.")
    parser.add_argument("input_file", help="Path to the file containing content to send.")
    parser.add_argument("url", help="RCAccelerator API endpoint URL (e.g., http://<host>/prompt).")
    args = parser.parse_args()

    # Validate input file
    if not os.path.isfile(args.input_file):
        print(f"Error: File '{args.input_file}' not found.", file=sys.stderr)
        sys.exit(1)

    # Read the input file content
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except Exception as e:
        print(f"Error reading '{args.input_file}': {e}", file=sys.stderr)
        sys.exit(1)

    # Prepare the POST request
    headers = {"Content-Type": "application/json"}
    payload = {"content": file_content, "similarity_threshold": 0.6}

    try:
        response = requests.post(args.url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error making POST request to {args.url}: {e}", file=sys.stderr)
        sys.exit(1)

    # Print the response body
    print(response.text)

if __name__ == "__main__":
    main()
