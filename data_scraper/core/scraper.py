"""Jira Scraper"""

import uuid
import logging
import multiprocessing as mp
from typing import List, Dict, TypedDict, Any
from datetime import datetime
import os

import pandas as pd
from tqdm import tqdm
from openai import OpenAI

from data_scraper.processors.jira_provider import JiraProvider
from data_scraper.processors.vector_store import QdrantVectorStoreManager
from data_scraper.processors.text_processor import TextProcessor


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


class Scraper:
    """Base Scraper class."""

    def __init__(self, config: Dict):
        self.config = config
        self.db_manager = QdrantVectorStoreManager(
            config["database_client_url"], config["database_api_key"]
        )
        self.text_processor = TextProcessor(
            config["embedding_model"], config["chunk_size"]
        )
        self.llm_client = OpenAI(
            base_url=config["llm_server_url"],
            organization="",
            api_key=config["llm_api_key"],
        )

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for the model."""
        response = self.llm_client.embeddings.create(
            model=self.config["embedding_model"], input="test"
        )
        return len(response.data[0].embedding)

    def get_chunks(self, record: Any) -> List[str]:
        """Create chunks of text to be passed to embedding model.
        Length must respect model context constraint."""
        raise NotImplementedError

    def record_postprocessing(self, record: dict) -> None:
        """Perform anything that needs to be done to record dictionary
        after it has been created but before storing in vectorDB."""
        raise NotImplementedError

    def store_records(self,
                      records: list,
                      record_fields_for_key: tuple[str, ...],
                      recreate: bool = True) -> None:
        """Process text and store embeddings in database."""
        vector_size = self.get_embedding_dimension()

        if recreate:
            self.db_manager.recreate_collection(
                self.config["db_collection_name"], vector_size
            )
        elif not self.db_manager.check_collection(self.config["db_collection_name"]):
            LOG.error(
                "Requested database collection %s does not exist.",
                self.config["db_collection_name"])
            raise IOError

        for record in tqdm(records, desc="Processing embeddings"):
            combined_key = "_".join([record[field] for field in record_fields_for_key])
            record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, combined_key))
            if not record['url']:
                # Check if all required fields for the key are present
                missing_fields = [
                    field for field in record_fields_for_key
                    if field not in record or not record[field]
                ]
                if missing_fields:
                    LOG.error("Missing required fields for key generation: %s", missing_fields)
                    continue

                combined_key = "_".join([record[field] for field in record_fields_for_key])
                record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, combined_key))
                LOG.error("Missing required URL field")
                continue

            chunks: list[str] = self.get_chunks(record)

            embeddings: list[list[float]] = []
            for chunk in chunks:
                embeddings.append(
                    self.llm_client.embeddings.create(
                        model=self.config["embedding_model"], input=chunk
                    )
                    .data[0]
                    .embedding
                )

            self.record_postprocessing(record)
            point = self.db_manager.build_record(
                record_id=record_id,
                payload=dict(record),
                vector=embeddings,
            )
            self.db_manager.upsert_data(self.config["db_collection_name"], [point])

    def cleanup_records(
        self, records: list, backup_path: str = "all_data.pickle"
    ) -> list:
        """Cleanup Records"""

        raise NotImplementedError

    def get_documents(self) -> List[dict]:
        """Retrieve original documents as a list of dictionaries."""
        raise NotImplementedError

    def get_records(self, documents: List[Dict]) -> list[dict]:
        """Convert raw data into list of dictionaries."""
        raise NotImplementedError

    def run(self, record_fields_for_key: tuple[str,...] = ("url",)):
        """Main execution method."""
        documents = self.get_documents()
        if not documents:
            LOG.error("No issues found to process.")
            return

        records = self.get_records(documents)
        records = self.cleanup_records(records)

        # Process and store embeddings
        self.store_records(records, record_fields_for_key, self.config["recreate_collection"])

        # Print final stats
        stats = self.db_manager.get_collection_stats(self.config["db_collection_name"])
        LOG.info("Number of records: %s", stats.points_count)


class JiraScraper(Scraper):
    """Main class for JIRA scraping and processing."""

    def __init__(self, config: Dict):
        super().__init__(config=config)

        self.jira_client = JiraProvider(config["jira_url"], config["jira_token"])

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
        initial_issues, total = self.jira_client.get_issues(query, max_results)

        if not initial_issues:
            LOG.error("No jira tickets found!")
            return []

        # Fetch remaining issues in parallel using a process pool executor
        with mp.Pool(self.config["scraper_processes"]) as pool:
            args = [(query, max_results, page) for page in range(1000, total, 1000)]

            results = pool.starmap(self.jira_client.get_issues, args)

        # Combine all issues
        all_issues = initial_issues + [issue for batch in results for issue in batch[0]]
        return all_issues

    def get_records(self, documents: List[Dict]) -> list[JiraRecord]:
        """Convert Jira API responses to JiraRecords"""
        jira_records: list[JiraRecord] = []

        for issue in tqdm(documents, desc="Processing issues"):
            jira_url = f"{self.config['jira_url']}/browse/{issue['key']}"

            components = [
                component["name"] for component in issue["fields"]["components"]
            ]

            fix_versions = [
                fixVersion["name"] for fixVersion in issue["fields"]["fixVersions"]
            ]

            versions = [version["name"] for version in issue["fields"]["versions"]]

            comment_text = ""
            for idx, comment in enumerate(issue["fields"]["comment"]["comments"]):
                comment_text += f"### Comment no.{idx}\n" f"{comment['body']}\n\n"

            # Concatenate all comments for a jira
            jira_text_format = """
            Summary: {summary}
            Description: {description}
            Comments: {comments}
            """

            jira_records.append(
                {
                    "kind": "full-ticket",
                    "jira_id": issue["id"],
                    "affects_versions": versions,
                    "components": components,
                    "fix_versions": fix_versions,
                    "url": jira_url,
                    "text": jira_text_format.format(
                        summary=issue["fields"]["summary"],
                        description=issue["fields"]["description"],
                        comments=comment_text,
                    ),
                    # TODO(lpiwowar): Experimental fields that are not stored in the database
                    # Remove once we decide what values we are going to use to calculate the
                    # embeddings.
                    "summary": issue["fields"]["summary"],
                    "description": issue["fields"]["description"],
                    "comments": comment_text,
                }
            )

        return jira_records

    def record_postprocessing(self, record):
        # TODO(lpiwowar): Experimental fields that are not stored in the database
        # Remove once we decide what values we are going to use to calculate the
        # embeddings.
        del record["description"]
        del record["comments"]
        del record["summary"]

    def get_documents(self) -> List[dict]:
        query = self.build_query(
            self.config["jira_projects"], self.config["date_cutoff"]
        )
        documents = self.fetch_all_issues(query, self.config["max_results"])

        return documents

    def get_chunks(self, record: dict) -> list[str]:
        chunks = []
        for jira_field in ["summary", "description", "comments"]:
            chunks += self.text_processor.split_text(record[jira_field])
        return chunks

    def cleanup_records(
        self, records: list[JiraRecord], backup_path: str = "jira_all_bugs.pickle"
    ) -> list[JiraRecord]:
        """Cleanup Jira Records"""
        df = pd.DataFrame(records)

        LOG.info("Jira records stats BEFORE cleanup:")
        LOG.info(df.info())

        df = df.dropna()
        df = df.drop_duplicates(subset=["text"])

        LOG.info("Jira records stats AFTER cleanup:")
        LOG.info(df.info())

        LOG.info("Saving backup to: %s", backup_path)
        df.to_pickle(backup_path)

        return [JiraRecord(**row) for row in df.to_dict(orient="records")]


class OSPDocScraper(Scraper):
    """Main class for JIRA scraping and processing."""

    def __init__(self, config: Dict):
        super().__init__(config=config)
        self.base_url = "https://docs.openstack.org"
        self.base_rhoso_url = (
            "https://docs.redhat.com/en/documentation/"
            "red_hat_openstack_services_on_openshift/{version}/html-single")
        self.osp_version = config["osp_version"]
        self.docs_path = os.path.abspath(config['docs_location'])
        if self.docs_path.endswith("/"):
            self.docs_path = self.docs_path[:-1]
        self.rhoso_docs_path = config["rhoso_docs_path"]
        if self.rhoso_docs_path:
            self.rhoso_docs_path = os.path.abspath(self.rhoso_docs_path)
            if self.rhoso_docs_path.endswith("/"):
                self.rhoso_docs_path = self.rhoso_docs_path[:-1]


    def get_url(self, file_path: str, rhoso_docs: bool = False):
        """Derive URL from file path."""
        if rhoso_docs:
            return (
                self.base_rhoso_url.format(
                    version=self.osp_version) + "/" + file_path.split('/')[-2]
            )
        return (
            self.base_url
            + file_path.removeprefix(self.docs_path).removesuffix("txt")
            + "html"
        )


    def get_records(self, documents: List[Dict]) -> list[Dict]:
        """Convert Jira API responses to JiraRecords"""
        document_records: list[dict] = []

        for document in tqdm(documents, desc="Processing documents"):

            document_records.append(
                {
                    "kind": "osp-documentation-chunk",
                    "components": [document["project"]],
                    "url": document["url"],
                    "text": document["text"],
                    "osp_version": document["osp_version"],
                }
            )

        return document_records

    def record_postprocessing(self, record):
        pass

    def get_documents(self) -> List[dict]:

        documents = []
        LOG.info("Reading documents from %s", self.docs_path)
        for root, _, files in os.walk(self.docs_path):
            for file in files:
                if file.endswith(".txt"):
                    doc_path = os.path.join(root, file)
                    with open(doc_path, mode='r', encoding='utf-8') as document:
                        documents.append({
                            "text": document.read(),
                            "project" : doc_path.removeprefix(self.docs_path).split("/")[1],
                            "path": doc_path,
                            "osp_version": self.config["osp_version"],
                            "url": self.get_url(doc_path),
                        }
                    )
        if self.rhoso_docs_path:
            LOG.info("Reading documents from %s", self.rhoso_docs_path)
            for root, _, files in os.walk(self.rhoso_docs_path):
                for file in files:
                    if file.endswith(".txt"):
                        doc_path = os.path.join(root, file)
                        with open(doc_path, mode='r', encoding='utf-8') as document:
                            documents.append({
                                "text": document.read(),
                                "project" : doc_path.removeprefix(
                                    self.rhoso_docs_path).split("/")[1],
                                "path": doc_path,
                                "osp_version": self.config["osp_version"],
                                "url": self.get_url(doc_path, rhoso_docs=True),
                            }
                        )
        return documents

    def get_chunks(self, record: dict) -> list[str]:

        return self.text_processor.split_text(record["text"])

    def cleanup_records(
        self, records: list[dict], backup_path: str = "osp_all_docs.pickle"
    ) -> list[dict]:
        """Cleanup document records"""
        df = pd.DataFrame(records)

        LOG.info("Document records stats BEFORE cleanup:")
        LOG.info(df.info())

        df = df.dropna()
        df = df.drop_duplicates(subset=["text"])

        LOG.info("Document records stats AFTER cleanup:")
        LOG.info(df.info())

        LOG.info("Saving backup to: %s", backup_path)
        df.to_pickle(backup_path)

        return [JiraRecord(**row) for row in df.to_dict(orient="records")]
