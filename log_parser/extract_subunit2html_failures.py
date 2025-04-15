#!/usr/bin/env python3

import argparse
import os
import re
from bs4 import BeautifulSoup
from pathlib import Path

# Match the end of traceback
EXCEPTION_LINE_RE = re.compile(r'^\s*(\w+Error|Exception|AssertionError|KeyboardInterrupt|SystemExit)\b.*:')

# Safe filename generation
def sanitize_filename(name):
    return re.sub(r'[^\w\-_.]+', '_', name)

def extract_all_complete_tracebacks(text):
    lines = text.strip().splitlines()
    tracebacks = []
    buffer = []
    in_traceback = False

    for line in lines:
        if "Traceback (most recent call last):" in line:
            if buffer:
                buffer = []
            buffer = [line]
            in_traceback = True
        elif in_traceback:
            buffer.append(line)
            if EXCEPTION_LINE_RE.match(line):
                tracebacks.append('\n'.join(buffer))
                buffer = []
                in_traceback = False

    return tracebacks

def extract_tracebacks_to_files(html_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    with open(html_file, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    failure_rows = soup.find_all('tr', id=lambda x: x and x.startswith('ft'))
    written = 0

    for row in failure_rows:
        testname_div = row.find('div', class_='testcase')
        testname = testname_div.get_text(strip=True) if testname_div else "Unnamed_Test"

        details_div_id = 'div_' + row['id']
        details_div = soup.find('div', id=details_div_id)
        traceback_pre = details_div.find('pre') if details_div else None
        full_text = traceback_pre.get_text(strip=False).strip() if traceback_pre else ""

        trace_blocks = extract_all_complete_tracebacks(full_text)
        if not trace_blocks:
            continue

        safe_filename = sanitize_filename(testname)[:200]  # trim overly long names
        filepath = os.path.join(output_dir, f"{safe_filename}.txt")

        with open(filepath, 'w', encoding='utf-8') as out:
            out.write(f"Test: {testname}\n\n")
            for i, block in enumerate(trace_blocks, 1):
                out.write(f"Traceback #{i}:\n")
                out.write(block + "\n")
                out.write("~" * 60 + "\n")
        written += 1

    print(f"✅ Created {written} test error file(s) to directory: {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Extract tracebacks into individual files per test case.")
    parser.add_argument("html_file", help="Path to subunit2html HTML report")
    parser.add_argument("output_dir", help="Directory to store one .txt file per test failure")
    args = parser.parse_args()

    extract_tracebacks_to_files(args.html_file, args.output_dir)

if __name__ == "__main__":
    main()
