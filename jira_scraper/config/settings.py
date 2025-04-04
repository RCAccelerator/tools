"""Module for config settings."""


# pylint: disable=too-few-public-methods
class JiraScraperConfig:
    """Configuration class for JIRA scraper."""
    COLLECTION_NAME = "all-jira-tickets"
    DEFAULT_EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
    DEFAULT_JIRA_URL = "https://issues.redhat.com"
    DEFAULT_JIRA_PROJECTS = [
        "OSP", "RHOSINFRA", "OSPCIX", "RHOSBUGS",
        "OSPK8", "RHOSPRIO", "OSPRH"
    ]
    DEFAULT_CHUNK_SIZE = 1024
    DEFAULT_MAX_RESULTS = 10000
