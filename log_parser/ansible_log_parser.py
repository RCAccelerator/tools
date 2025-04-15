#!/usr/bin/env python3

import argparse
import os
import re

def extract_minimal_failures(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    failures = []
    block = []
    collecting = False

    for line in lines:
        if 'fatal:' in line and 'FAILED!' in line:
            if block:
                failures.append(''.join(block))
                block = []
            collecting = True
            block.append(line)
            continue

        if collecting:
            # End of the failure block
            if line.startswith("TASK [") or "PLAY RECAP" in line:
                failures.append(''.join(block))
                block = []
                collecting = False
                continue

            # Retain only relevant failure details
            if re.search(r'\b(msg|stderr|stdout|rc|status|url|changed|error|elapsed):', line):
                block.append(line)

    if collecting and block:
        failures.append(''.join(block))

    with open(output_file, 'w', encoding='utf-8') as out:
        for idx, failure in enumerate(failures, 1):
            out.write(f"\n--- Failure {idx} ---\n")
            out.write(failure)

    print(f"✅ Extracted {len(failures)} failure(s) to: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Extract minimal Ansible task failures from logs.")
    parser.add_argument("input", help="Path to Ansible log file")
    parser.add_argument("output", help="Path to output file with failures")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Input file '{args.input}' does not exist.")
        return

    extract_minimal_failures(args.input, args.output)

if __name__ == "__main__":
    main()
