
"""Client to fetch jira issues."""
import json
from typing import List, Dict

import requests


# pylint: disable=too-few-public-methods
class JiraClient:
    """Client for interacting with JIRA API."""

    def __init__(self, jira_url: str, jira_token: str):
        self.jira_url = jira_url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {jira_token}",
        }

    def get_issues(self, query: str,
                   max_results: int,
                   start_at: int = 0) -> List[Dict]:
        """Retrieve issues from JIRA with pagination."""
        full_url = (
            f"{self.jira_url}/rest/api/2/search?"
            f"jql={query}&maxResults={max_results}&"
            f"fields=*all&startAt={start_at}"
        )

        try:
            response = requests.get(
                full_url,
                headers=self.headers,
                timeout=(3.05, 180),
            )
            response.raise_for_status()
            return json.loads(response.text)["issues"]

        except requests.exceptions.Timeout:
            print(f"Request to {full_url} timed out.")
            return []
        except requests.exceptions.RequestException as e:
            print(f"Error fetching JIRA data: {e}")
            return []
