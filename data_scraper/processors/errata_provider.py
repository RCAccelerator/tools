"""Client to fetch Erratas."""
import logging
import requests

from requests_kerberos import HTTPKerberosAuth, OPTIONAL

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

class ErrataProvider:
    """Provider for JIRA."""

    def __init__(self, query_url: str):
        self.query_url = query_url

    def search_erratas(self, product_ids: list[int], page: int = 1) -> dict:
        """Search erratas related to given product IDs with pagination support.

        Args:
            product_ids: A list of product IDs for which erratas need to be searched.
            page: The page number to retrieve, by default 1.

        Returns:
            dict: Containing response from the /api/v1/erratum/search endpoint.
        """
        query = f"{self.query_url}/api/v1/erratum/search?"

        params = []
        for product_id in product_ids:
            params.append(f"product[]={product_id}")
        params.append(f"page={page}")

        query = f"{query}{"&".join(params)}"
        LOG.info("Sending the following request to errata -> %s", query)

        try:
            auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
            response = requests.get(query, auth=auth, verify=False, timeout=(3.05, 180))
        except requests.exceptions.Timeout:
            LOG.error("Request to errata %s timed out.", query)
            return {}
        except requests.exceptions.RequestException as e:
            LOG.error("Error fetching Errata data: %s", e)
            return {}

        return response.json()

    def get_errata(self, errata_id: int) -> dict:
        """Fetch the errata details based on the provided errata id.

        Args:
            errata_id: The identifier of the errata to be fetched.

        Returns:
            dict:
                A dictionary containing the details of the errata (response
                from /api/v1/erratum/<errata_id>.
        """
        query = f'{self.query_url}/api/v1/erratum/{errata_id}'
        LOG.info("Sending the following request to errata -> %s", query)

        try:
            auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
            response = requests.get(query, auth=auth, verify=False, timeout=(3.05, 180))
        except requests.exceptions.Timeout:
            LOG.error("Request to errata %s timed out.", query)
            return {}
        except requests.exceptions.RequestException as e:
            LOG.error("Error fetching Errata data: %s", e)
            return {}

        return response.json()
