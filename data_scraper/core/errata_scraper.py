"""Code for scraping Errata data"""
import logging
import multiprocessing as mp
import subprocess
import sys
from datetime import datetime
from typing import TypedDict
import regex as re

import pandas as pd

from data_scraper.core.scraper import Scraper
from data_scraper.processors.errata_provider import ErrataProvider


LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class ErrataRecord(TypedDict):
    """Represents a record extracted from Errata.

    Attributes:
         errata_id: Unique identifier assigned to the errata (e.g., 12345678)
         errata_full_id: Full errata identifier (e.g., ABCD-2025:1234)
         kind: Specifies the type of data stored in the dictionary (errata)
         topic: Topic field from errata
         description: Description field from errata
         jira_issues: Linked jira issues to the errata
         url: URL of the errata
         components: List of components impacted by the errata.
         text:
            Text representation of the Errata. This will be passed to the
            generative model.
    """
    errata_id: str
    errata_full_id: str
    kind: str
    topic: str
    description: str
    jira_issues: list[str]
    url: str
    text: str
    components: list[str]


class ErrataScraper(Scraper):
    """Main class for Errata scraping and processing."""

    def __init__(self, config: dict):
        super().__init__(config=config)
        self.config = config
        self.errata_provider = ErrataProvider(self.config["errata_url"])
        self._kerberos_authenticate()

    def _kerberos_authenticate(self):
        try:
            cmd = ["kinit", f"{self.config["kerberos_username"]}"]
            subprocess.run(
                cmd,
                input=f"{self.config["kerberos_password"]}\n".encode(),
                check=True
            )
        except subprocess.CalledProcessError as e:
            LOG.error("Failed to authenticate with kerberos: %s", e)
            sys.exit(1)

    @staticmethod
    def _get_fulladvisory(response: dict) -> str:
        """Get full fulladvisory field from response."""
        key = next(iter(response["errata"]))
        return re.sub(r"-\d{2}$", "", response["errata"][key]["fulladvisory"])

    def get_documents(self) -> list[dict]:
        results = self.errata_provider.search_erratas(self.config["errata_product_ids"])
        if not results:
            LOG.error("No erratas found to process.")
            return []

        results = [results]
        current_page = results[0]["page"]["current_page"]
        total_pages = results[0]["page"]["total_pages"]

        # Get all erratas assigned to specific projects
        with mp.Pool(self.config["scraper_processes"]) as pool:
            args = [(self.config["errata_product_ids"],page)
                    for page in range(current_page + 1, total_pages + 1)]

            results += pool.starmap(self.errata_provider.search_erratas, args)\

        # Filter erratas based on created_at date
        project_erratas: list[dict] = []
        for result in results:
            for data in result["data"]:
                errata_created_at = datetime.fromisoformat(data["timestamps"]["created_at"])
                if self.config["date_cutoff"] < errata_created_at:
                    project_erratas.append(data)

        LOG.info("Number of erratas to process: %s", len(project_erratas))
        # Get additional info for obtained erratas
        with mp.Pool(self.config["scraper_processes"]) as pool:
            args = [errata["id"] for errata in project_erratas]
            results = pool.map(self.errata_provider.get_errata, args)

        return results

    def get_records(self, documents: list[dict]) -> list[ErrataRecord]:
        errata_records: list[ErrataRecord] = []

        for result in documents:
            errata_id = result["content"]["content"]["errata_id"]
            errata_full_id = ErrataScraper._get_fulladvisory(result)
            errata_url = f"{self.config['errata_public_url']}/{errata_full_id}"
            errata_jira_issues_ids = [
                f"{self.config["jira_url"]}/browse/{issue["jira_issue"]["key"]}"
                for issue in result["jira_issues"]["jira_issues"]
            ]
            errata_topic = result['content']['content']['topic']
            errata_description = result['content']['content']['description']

            text = (f"Topic: {errata_topic}\n"
                    f"Description: {errata_description}\n"
                    f"URL: {errata_url}\n")

            errata_records.append({
                "errata_id": errata_id,
                "errata_full_id": errata_full_id,
                "kind": "errata",
                "components": [],
                "topic": errata_topic,
                "description": errata_description,
                "jira_issues": errata_jira_issues_ids,
                "url": errata_url,
                "text": text,
            })

        return errata_records

    def get_chunks(self, record: dict) -> list[str]:
        chunks = []

        for errata_field in ["topic", "description"]:
            chunks += self.text_processor.split_text(record[errata_field])

        return chunks

    def record_postprocessing(self, record):
        # Postprocessing is not required for Errata records
        pass

    def cleanup_records(
        self, records: list, backup_path: str = "errata_all_data.pickle"
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

        return [ErrataRecord(**row) for row in df.to_dict(orient="records")]
