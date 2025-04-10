
"""Client to fetch jira issues."""
import logging
import abc
import json
from typing import List, Dict

import requests


LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

# pylint: disable=too-few-public-methods
class IssueProvider(abc.ABC):
    """Abstract class defining `IssueProvider` interface."""

    @abc.abstractmethod
    def get_issues(self, query: str,
                   max_results: int,
                   start_at: int = 0) -> List[Dict]:
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

        response = requests.get(
            full_url,
            headers=self.headers,
            timeout=(3.05, 180),
        )
        response.raise_for_status()
        return json.loads(response.text)

    def get_initial_issues(self, query: str,
                           max_results: int) -> tuple[List[Dict], int]:
        """Retrieve intial issues and total count."""
        try:
            data = self._get_issues(query, max_results)
            return (data["issues"], data['total'])
        except requests.exceptions.Timeout:
            LOG.error("Request to jira query %s timed out.", query)
            return ([], 0)
        except requests.exceptions.RequestException as e:
            LOG.error("Error fetching JIRA data: %s", e)
            return ([], 0)

    def get_issues(self, query: str,
                   max_results: int,
                   start_at: int = 0) -> List[Dict]:
        """Retrieve issues from JIRA with pagination."""
        try:
            data = self._get_issues(query, max_results,
                                    start_at)
            return data["issues"]
        except requests.exceptions.Timeout:
            LOG.error("Request to jira query %s timed out.", query)
            return []
        except requests.exceptions.RequestException as e:
            LOG.error("Error fetching JIRA data: %s", e)
            return []
