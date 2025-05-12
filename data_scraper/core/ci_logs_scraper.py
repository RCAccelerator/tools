"""Code for scraping test operator logs data"""
import logging
from typing import TypedDict, List, Dict
import json

import pandas as pd

from data_scraper.core.scraper import Scraper

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class CILogsRecord(TypedDict):
    """CILogs data point."""
    url: str
    test_name: str
    text: str
    components: list[str]
    kind: str

class CILogsScraper(Scraper):
    """Main class for test operator logs scraping and processing."""

    def __init__(self, config: dict):
        super().__init__(config=config)
        self.config = config

    def get_documents(self) -> list[dict]:
        all_failures = self._load_test_operator_results()

        return all_failures

    def get_records(self, documents: list[dict]) -> list[CILogsRecord]:
        ci_logs_records: list[CILogsRecord] = []

        for document in documents:
            ci_logs_records.append({
                "url": document["url"],
                "test_name": document["test_name"],
                "text": document["traceback"],
                "components": [],
                "kind": "zuul_jobs",
            })

        return ci_logs_records

    def get_chunks(self, record: dict) -> list[str]:
        chunks = []

        for field in ["text"]:
            chunks += self.text_processor.split_text(record[field])

        return chunks

    def record_postprocessing(self, record):
        # Postprocessing is not required
        pass

    # pylint: disable=R0801
    def cleanup_records(
        self, records: list, backup_path: str = "ci_logs_all_data.pickle"
    ) -> list:
        df = pd.DataFrame(records)

        LOG.info("Records stats BEFORE cleanup:")
        LOG.info(df.info())

        df = df.dropna()
        df = df.drop_duplicates(subset=["text"])

        LOG.info("Records stats AFTER cleanup:")
        LOG.info(df.info())

        LOG.info("Saving backup to: %s", backup_path)
        df.to_pickle(backup_path)

        return [CILogsRecord(**row) for row in df.to_dict(orient="records")]

    def _get_job_url(self, url: str) -> str:
        """
        Extract the job URL from a test report URL by removing everything from 'logs/controller-0'.

        Args:
            url (str): The complete report URL

        Returns:
            str: The job URL
        """
        split_marker = "logs/controller-0"
        if split_marker in url:
            base_url = url.split(split_marker)[0]
            return base_url.rstrip('/')

        return url

    def _load_test_operator_results(self) -> List[Dict[str, str]]:
        """
        Loads test results from the tempest_tests_tracebacks.json

        Args:
            url: URL of the tempest report (used as a key to find matching results)

        Returns:
            List of dictionaries containing test names and tracebacks
        """
        try:
            file_name = self.config["tracebacks_json"]
            with open(file_name, "r", encoding="utf-8") as f:
                tracebacks = json.load(f)

            results = []
            for report in tracebacks:
                job_url = self._get_job_url(report.get("url", "Unknown url"))
                for test in report.get("failed_tests", []):
                    results.append({
                        "url": job_url,
                        "test_name": test.get("name", "Unknown test"),
                        "traceback": test.get("traceback", "No traceback available")
                    })
            return results

        except json.JSONDecodeError:
            LOG.error("%s", "Error parsing tempest_tests_tracebacks.json file")
            return []
