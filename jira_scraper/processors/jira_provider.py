
"""Client to fetch jira issues."""
import logging
import abc
import json

import urllib3 as http


LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

# pylint: disable=too-few-public-methods
class IssueProvider(abc.ABC):
    """Abstract class defining `IssueProvider` interface."""

    @abc.abstractmethod
    def get_issues(self, query: str,
                   max_results: int,
                   start_at: int = 0) -> tuple[list[dict], int]:
        """Retrieve issues from the provider."""


class JiraProvider(IssueProvider):
    """Provider for JIRA."""

    def __init__(self, query_url: str, query_token: str):
        self.query_url = query_url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {query_token}",
        }

    def get_issues(self, query: str,
                   max_results: int,
                   start_at: int = 0) -> tuple[list[dict], int]:
        """Get issues from Jira.

        Gets issues from Jira and returns list of all the issues and number
        of retrieved issues.

        Args:
            query: Query for Jira (e.g., project="ABC")
            max_results: Maximum number of tickets that should be retrieved
            start_at: Specififes which chunk of tickets you want to download.
        """
        full_url = (
            f"{self.query_url}/rest/api/2/search?"
            f"jql={query}&maxResults={max_results}&"
            f"fields=*all&startAt={start_at}"
        )

        LOG.info("Processing Jira request [query: %s, max_results: %d, "
                 "start_at: %d]", query, max_results, start_at)

        try:
            response = http.request(
                method="GET",
                url=full_url,
                headers=self.headers,
                timeout=http.Timeout(connect=3.05, read=180),
                retries=http.Retry(
                    total=10,
                    connect=10,
                    backoff_factor=0.1,
                    status_forcelist=[429,443]
                ),
            )
        except http.exceptions.TimeoutError:
            LOG.error("Request to jira query %s timed out.", query)
            return ([], 0)
        except http.exceptions.RequestError as e:
            LOG.error("Error fetching JIRA data: %s", e)
            return ([], 0)

        parsed_response = json.loads(response.data.decode("utf-8"))

        LOG.info("Found %d Jira tickets matching the query and retrieved %d " \
                 "of them. [query: %s, max_results: %d, start_at: %d]",
                 parsed_response["total"],
                 len(parsed_response["issues"]),
                 query, max_results, start_at)

        return parsed_response["issues"], parsed_response["total"]
