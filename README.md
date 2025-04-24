# RCAccelerator Tools

This repository contains useful tools that can be useful when deploying the
[RCAccelerator/chatbot](https://github.com/RCAccelerator/chatbot). As of now,
this repository contains:

- `data_scraper`: a tool that scrapes jira issues and more to store the collected data
in a vector database.
- `feedback_exporter`: a tool to fetch user feedback from Chainlit DB and write it in to a Google Spreadsheet.


## Getting Started

1. Run a tool:
   ```bash
   pip install .
   data_scraper --help
   ```

## Feedback Exporter Tool

This tool fetches user feedback from the Chainlit PostgreSQL database and writes it into a Google Spreadsheet.

### Usage

1. Set the following environment variables:

```bash
export DATABASE_URL=postgresql://user:pass@host:port/dbname
export APP_BASE_URL=https://chainlit.example.com/thread/
export GOOGLE_SPREADSHEET_ID=your_google_sheet_id
export GOOGLE_CREDENTIALS_JSON='{"type": "service_account", ...}'  # raw JSON string
```

2. Run the tool:

```bash
python feedback_exporter/export_feedback.py
```

This will populate the Google Spreadsheet with columns: score, thread URL, input, output, comment, and user name.
