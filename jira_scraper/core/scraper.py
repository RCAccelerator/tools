
"""Jira Scraper"""
import uuid
import logging
import multiprocessing as mp
from typing import List, Dict, TypedDict
from datetime import datetime

import pandas as pd
from tqdm import tqdm
from openai import OpenAI

from jira_scraper.processors.jira_provider import JiraProvider
from jira_scraper.processors.vector_store import QdrantVectorStoreManager
from jira_scraper.processors.text_processor import TextProcessor


LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

class JiraRecord(TypedDict, total=False):
    """Represents a record extracted from a Jira ticket.

    This dictionary contains information from a single Jira ticket. The
    dictionary stores information from summary, description, comments,
    fix_versions, affects_versions and components field.

    Attributes:
        text: The content extracted from a specific field (e.g., summary,
            description, comment). Or entire ticket if kind contains
            "full-ticket" value.
        kind: Specifies the type of field the data originates from (e.g.,
            summary, description, comment). Or "full-ticket" value if text field
            contains the entire ticket.
        jira_id: A unique identifier assigned to the ticket (e.g., 16238715).
        url: The URL pointing directly to the Jira ticket
            (e.g., http://issues.redhat.com/OSPRH-1234).
        components: A list of components impacted by the ticket.
        fix_versions: A value from Fix Versions
        affects_versions: A value from Affects Versions
    """
    kind: str
    text: str
    jira_id: str
    url: str
    fix_versions: list[str]
    affects_versions: list[str]
    components: list[str]

    # TODO(lpiwowar): Experimental fields that are not stored in the database
    # Remove once we decide what values we are going to use to calculate the
    # embeddings.
    summary: str
    description: str
    comments: str


class JiraScraper:
    """Main class for JIRA scraping and processing."""

    def __init__(self, config: Dict):
        self.config = config
        self.jira_client = JiraProvider(
            config["jira_url"], config["jira_token"])
        self.db_manager = QdrantVectorStoreManager(
            config["database_client_url"],
            config["database_api_key"]
        )
        self.text_processor = TextProcessor(
            config["embedding_model"],
            config["chunk_size"]
        )
        self.llm_client = OpenAI(
            base_url=config["llm_server_url"],
            organization="",
            api_key=config["llm_api_key"],
        )

    def build_query(self, projects: List[str], date_cutoff: datetime) -> str:
        """Build JQL query from project dictionary.

        Args:
            projects: List of project names.
            date_cutoff: Only issues created after this date (inclusive) will be used.

        Returns:
            JQL query string with appropriate filters
        """
        projects_str = " OR ".join([f"project={e}" for e in projects])
        query = f"({projects_str})"

        # Apply date cutoff
        date_filter = f'created >= "{date_cutoff.strftime("%Y-%m-%d")}"'
        query = f"{query} AND {date_filter}"

        return query

    def fetch_all_issues(self, query: str, max_results: int) -> List[Dict]:
        """Fetch all issues matching the query."""
        # Get initial batch to determine total count
        initial_issues, total = self.jira_client.get_issues(
            query, max_results
        )

        if not initial_issues:
            LOG.error("No jira tickets found!")
            return []

        # Fetch remaining issues in parallel using a process pool executor
        with mp.Pool(self.config["scraper_processes"]) as pool:
            args = [(query, max_results, page)
                    for page in range(1000, total, 1000)]

            results = pool.starmap(self.jira_client.get_issues, args)

        # Combine all issues
        all_issues = initial_issues + [
            issue for batch in results for issue in batch[0]]
        return all_issues

    def get_jira_records(self, issues: List[Dict]) -> list[JiraRecord]:
        """Convert Jira API responses to JiraRecords"""
        jira_records: list[JiraRecord] = []

        for issue in tqdm(issues, desc="Processing issues"):
            jira_url = f"{self.config['jira_url']}/browse/{issue['key']}"

            components = [
                component["name"]
                for component in issue["fields"]["components"]
            ]

            fix_versions = [
                fixVersion["name"]
                for fixVersion in issue["fields"]["fixVersions"]
            ]

            versions = [
                version["name"]
                for version in issue["fields"]["versions"]
            ]

            comment_text = ""
            for idx, comment in enumerate(issue["fields"]["comment"]["comments"]):
                comment_text += (f"### Comment no.{idx}\n"
                                 f"{comment['body']}\n\n")

            # Concatenate all comments for a jira
            jira_text_format = """
            Summary: {summary}
            Description: {description}
            Comments: {comments}
            """

            jira_records.append({
                "kind": "full-ticket",
                "jira_id": issue["id"],
                "affects_versions": versions,
                "components": components,
                "fix_versions": fix_versions,
                "url": jira_url,
                "text": jira_text_format.format(
                    summary=issue["fields"]["summary"],
                    description=issue["fields"]["description"],
                    comments=comment_text
                ),

                # TODO(lpiwowar): Experimental fields that are not stored in the database
                # Remove once we decide what values we are going to use to calculate the
                # embeddings.
                "summary": issue["fields"]["summary"],
                "description": issue["fields"]["description"],
                "comments": comment_text,
            })


        return jira_records

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for the model."""
        response = self.llm_client.embeddings.create(
            model=self.config["embedding_model"],
            input="test"
        )
        return len(response.data[0].embedding)

    def store_jira_records(self, jira_records: list[JiraRecord]) -> None:
        """Process text and store embeddings in database."""
        vector_size = self.get_embedding_dimension()

        self.db_manager.recreate_collection(
            self.config["db_collection_name"],
            vector_size
        )

        for jira_record in tqdm(jira_records, desc="Processing embeddings"):

            chunks: list[str] = []
            for jira_field in ["summary", "description", "comments"]:
                chunks += self.text_processor.split_text(jira_record[jira_field])

            embeddings: list[list[float]] = []
            for chunk in chunks:
                embeddings.append(self.llm_client.embeddings.create(
                    model=self.config["embedding_model"],
                    input=chunk
                ).data[0].embedding)

            # TODO(lpiwowar): Experimental fields that are not stored in the database
            # Remove once we decide what values we are going to use to calculate the
            # embeddings.
            del jira_record["description"]
            del jira_record["comments"]
            del jira_record["summary"]

            point = self.db_manager.build_record(
                record_id=str(uuid.uuid4()),
                payload=dict(jira_record),
                vector=embeddings,
            )

            self.db_manager.upsert_data(
                self.config["db_collection_name"],
                [point]
            )

    def cleanup_jira_records(
            self, jira_records: list[JiraRecord],
            backup_path: str = "jira_all_bugs.pickle") -> list[JiraRecord]:
        """Cleanup Jira Records"""
        df = pd.DataFrame(jira_records)

        LOG.info("Jira records stats BEFORE cleanup:")
        LOG.info(df.info())

        df = df.dropna()
        df = df.drop_duplicates(subset=["text"])

        LOG.info("Jira records stats AFTER cleanup:")
        LOG.info(df.info())

        LOG.info("Saving backup to: %s", backup_path)
        df.to_pickle(backup_path)

        return [JiraRecord(**row) for row in df.to_dict(orient='records')]

    def run(self):
        """Main execution method."""
        query = self.build_query(self.config["jira_projects"], self.config["date_cutoff"])
        issues = self.fetch_all_issues(query, self.config["max_results"])
        if not issues:
            LOG.error("No issues found to process.")
            return

        jira_records = self.get_jira_records(issues)
        jira_records = self.cleanup_jira_records(jira_records)

        # Process and store embeddings
        self.store_jira_records(jira_records)

        # Print final stats
        stats = self.db_manager.get_collection_stats(
            self.config["db_collection_name"])
        LOG.info("Number of records: %s", stats.points_count)
