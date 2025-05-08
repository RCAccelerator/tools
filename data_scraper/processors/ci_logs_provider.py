"""Code for test operator logs data provisioning"""
# Standard library imports
import asyncio
import json
import logging
import os
import re
import urllib.parse
import warnings
from datetime import datetime, timedelta

import browser_cookie3
import httpx
import requests
from bs4 import BeautifulSoup
from httpx_gssapi import HTTPSPNEGOAuth
from httpx_gssapi.gssapi_ import OPTIONAL

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
LOG = logging.getLogger(__name__)

# API endpoint constants
API_BASE = "zuul/api"
API_TENANT = API_BASE + "/tenant/{tenant}"
API_BUILDS = API_TENANT + "/builds"

# Filter constants
FILTER_RESULT_FAILURE = "FAILURE"
FILTER_LIMIT = 20000

# Time filter constant - builds older than this will be excluded
CUTOFF_TIME = datetime.now() - timedelta(days=14)  # 2 weeks ago

# Test path constants
TEST_OPERATOR_PATH = "logs/controller-0/ci-framework-data/tests/test_operator"
TEMPEST_TEST_PATTERN = "tempest-"
TOBIKO_TEST_PATTERN = "tobiko-"

async def fetch_with_gssapi(url, params=None, timeout=30.0):
    """
    Fetch content using Kerberos authentication.

    Args:
        url: URL to fetch
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        Response text content
    """
    async with httpx.AsyncClient(
        verify=False,
        follow_redirects=True,
        timeout=timeout
    ) as session:
        response = await session.get(
            url,
            params=params,
            auth=HTTPSPNEGOAuth(mutual_authentication=OPTIONAL)
        )
        response.raise_for_status()
        return response.text

def make_authenticated_request(url, params=None, timeout=30.0):
    """
    Make an authenticated request to a URL using multiple authentication methods.

    Args:
        url: URL to fetch
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        Response content as text, or None if an error occurs
        For JSON responses, the caller will need to parse the text
    """
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc

    verify = False
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')

    # First try with Kerberos
    try:
        LOG.info("Attempting to authenticate using Kerberos...")
        content = asyncio.run(fetch_with_gssapi(url, params, timeout))
        LOG.info("Kerberos authentication successful")
        return content

    except (httpx.HTTPError, httpx.RequestError, httpx.TimeoutException) as e:
        LOG.warning("Kerberos authentication failed due to HTTP error: %s", e)
        LOG.info("Falling back to browser cookies authentication...")

        # Second try with cookies from browsers
        cookies = None
        if 'redhat.com' in domain:
            try:
                cookies = browser_cookie3.chrome(domain_name=domain)
                LOG.info("Using Chrome cookies for domain: %s", domain)
            except (ImportError, RuntimeError, FileNotFoundError) as chrome_error:
                LOG.warning("Could not get Chrome cookies: %s", chrome_error)

                try:
                    cookies = browser_cookie3.firefox(domain_name=domain)
                    LOG.info("Using Firefox cookies for domain: %s", domain)
                except (ImportError, RuntimeError, FileNotFoundError) as firefox_error:
                    LOG.warning("Could not get Firefox cookies: %s", firefox_error)

        try:
            response = requests.get(
                url,
                params=params,
                cookies=cookies,
                verify=verify,
                timeout=timeout
            )
            response.raise_for_status()
            return response.text

        except (requests.RequestException, requests.HTTPError, requests.ConnectionError,
                requests.Timeout, requests.TooManyRedirects) as request_error:
            LOG.error("Error fetching from %s: %s", url, request_error)
            return None

class TempestResultsParser:
    """Parser for tempest test HTML reports."""

    def __init__(self, source=None):
        self.source = source
        self.html_content = None
        self.soup = None
        self.failed_tests = []

        if source:
            self.load_content(source)

    def load_content(self, source):
        """Load content from a URL or file."""
        self.source = source
        self.html_content = self._get_content(source)
        if self.html_content:
            self.soup = BeautifulSoup(self.html_content, 'html.parser')
        return self

    def _get_content(self, source):
        """Retrieve content from a URL or file."""
        if source.startswith('http://') or source.startswith('https://'):
            LOG.info("Downloading from URL: %s", source)
            return make_authenticated_request(source, timeout=30.0)

        LOG.info("Reading local file: %s", source)
        try:
            with open(source, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except IOError as e:
            LOG.error("IO error reading file %s: %s", source, e)
            return None

    def parse(self):
        """Parse the HTML content and extract failed tests."""
        if not self.soup:
            LOG.warning("No content loaded or parsing failed. Nothing to parse.")
            return self.failed_tests

        self.failed_tests = []
        self._parse_html_format()
        return self.failed_tests


    def _extract_test_name(self, test_name_part: str) -> str:
        """Extract the test name from the text before the traceback."""
        # Extract the test name using a regex pattern
        test_name_match = re.search(r'ft\d+\.\d+:\s*(.*?)\)?testtools', test_name_part)
        if test_name_match:
            test_name = test_name_match.group(1).strip()
            if test_name.endswith('('):
                test_name = test_name[:-1].strip()
        else:
            # Try alternative pattern for different formats
            test_name_match = re.search(r'ft\d+\.\d+:\s*(.*?)$', test_name_part)
            if test_name_match:
                test_name = test_name_match.group(1).strip()
            else:
                test_name = "Unknown Test Name"

        # Remove any content within square brackets
        # e.g. test_tagged_boot_devices[id-a2e65a6c,image,network,slow,volume]
        # becomes test_tagged_boot_devices
        test_name = re.sub(r'\[.*?\]', '', test_name).strip()

        # Remove any content within parentheses
        test_name = re.sub(r'\(.*?\)', '', test_name).strip()

        return test_name

    def _parse_html_format(self):
        """Parse HTML formatted tempest test results."""

        soup = self.soup

        # The code is copy/past-ed from src/api.py#L101-L141
        # https://github.com/RCAccelerator/chatbot/. Get rid
        # of duplication at some stage. ATM it's a QnD solution to have exaclty the same
        # parsing of tempest test reports both at the endpoint and in scraper.
        failed_test_rows = soup.find_all('tr', id=re.compile(r'^ft\d+\.\d+'))

        for row in failed_test_rows:
            row_text = row.get_text().strip()

            traceback_start_marker = "Traceback (most recent call last):"
            traceback_start_index = row_text.find(traceback_start_marker)

            if traceback_start_index != -1:
                test_name_part = row_text[:traceback_start_index].strip()
                test_name = self._extract_test_name(test_name_part)

                traceback_text = row_text[traceback_start_index:]
                end_marker_index = traceback_text.find("}}}")
                if end_marker_index != -1:
                    traceback_text = traceback_text[:end_marker_index].strip()
                else:
                    traceback_text = traceback_text.strip()

                self.failed_tests.append((test_name, traceback_text or "No traceback found"))


    def has_failures(self):
        """Check if any failed tests were found."""
        return len(self.failed_tests) > 0

    def get_failure_summary(self):
        """Get a summary of the failed tests."""
        if not self.failed_tests:
            return "No failed tests found."

        summary = f"Found {len(self.failed_tests)} failed tests:\n"
        for test_name, _ in self.failed_tests:
            summary += f"- {test_name}\n"

        return summary


class ZuulClient:
    """Client for fetching Zuul build data and analyzing test reports."""

    def __init__(self, base_url):
        """
        Initialize the client with the base URL.

        Args:
            base_url: Base URL for the Zuul server
        """
        self.base_url = base_url.rstrip('/')

    def retrive_failed_builds(self, tenant, pipeline, limit=FILTER_LIMIT):
        """
        Get failed builds for a specific pipeline as JSON.

        Args:
            tenant: Tenant name
            pipeline: Pipeline name
            limit: Maximum number of builds to return

        Returns:
            JSON response as dictionary with builds filtered by cutoff time
        """
        endpoint = API_BUILDS.format(tenant=tenant)
        url = f"{self.base_url}/{endpoint}"

        params = {
            "limit": limit,
            "result": FILTER_RESULT_FAILURE,
            "pipeline": pipeline
        }

        LOG.info("Fetching data from: %s with params: %s", url, params)

        try:
            content_text = make_authenticated_request(url, params=params, timeout=60.0)
            if not content_text:
                return []

            result = json.loads(content_text)
            LOG.info("Successfully fetched %d builds", len(result))

            filtered_builds = self._filter_builds_by_date(result)
            return filtered_builds

        except (requests.RequestException, requests.HTTPError, requests.ConnectionError,
                requests.Timeout, requests.TooManyRedirects) as e:
            LOG.error("Error fetching data: %s", e)
            return []

    def _filter_builds_by_date(self, builds):
        """
        Filter builds based on the cutoff time.

        Args:
            builds: List of build dictionaries

        Returns:
            Filtered list of build dictionaries
        """
        filtered_builds = []

        for build in builds:
            end_time = build.get("end_time")
            if not end_time:
                end_time = build.get("start_time")

            # Skip if no timestamp available
            if not end_time:
                continue

            # Parse the timestamp
            try:
                # Handle different timestamp formats
                if 'Z' in end_time:
                    # ISO format with Z for UTC
                    build_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                elif 'T' in end_time and '+' in end_time:
                    # ISO format with timezone offset
                    build_time = datetime.fromisoformat(end_time)
                else:
                    # Assume simple format
                    build_time = datetime.fromisoformat(end_time)

                # Include only builds newer than the cutoff time
                if build_time >= CUTOFF_TIME:
                    filtered_builds.append(build)
            except ValueError:
                LOG.warning("%s", "Could not parse timestamp")
                # Include builds with unparseable timestamps by default
                filtered_builds.append(build)

        LOG.info("Filtered to %d builds after cutoff time", len(filtered_builds))
        return filtered_builds

    def fetch_html_content(self, url):
        """
        Fetch HTML content from a URL.

        Args:
            url: URL to fetch

        Returns:
            HTML content as string, or None if an error occurs
        """
        LOG.info("Fetching HTML from: %s", url)
        return make_authenticated_request(url)

    def find_test_reports(self, builds_json):
        """
        Find test reports in the build logs.

        Args:
            builds_json: JSON dictionary of builds

        Returns:
            Dictionary mapping build UUIDs to test report information
        """
        results = {}

        for build in builds_json:
            build_uuid = build.get("uuid", "unknown")
            log_url = build.get("log_url")

            if not log_url:
                LOG.info("Build %s has no log_url", build_uuid)
                continue

            LOG.info("Processing build %s with log URL %s", build_uuid, log_url)

            results[build_uuid] = self._process_build_reports(log_url)

        return results

    def _process_build_reports(self, log_url):
        """
        Process test reports for a single build.

        Args:
            log_url: URL to the build logs

        Returns:
            Dictionary with test report information
        """
        test_operator_path = f"{log_url.rstrip('/')}/{TEST_OPERATOR_PATH}"
        operator_html = self.fetch_html_content(test_operator_path)

        if not operator_html:
            LOG.info("Log URL %s contains no test_operator directory", log_url)
            return {
                "log_url": log_url,
                "status": "no_test_operator_dir",
                "tempest_reports": [],
                "tobiko_reports": []
            }

        test_dirs = self._find_test_directories(operator_html)

        if not test_dirs:
            LOG.info("No test directories found in %s", test_operator_path)
            return {
                "log_url": log_url,
                "status": "no_test_directories",
                "tempest_reports": [],
                "tobiko_reports": []
            }

        tempest_reports = []
        tobiko_reports = []

        for test_dir in test_dirs:
            test_dir_url = f"{test_operator_path}/{test_dir}"

            if TEMPEST_TEST_PATTERN in test_dir:
                tempest_reports.extend(self._process_tempest_directory(test_dir_url, test_dir))
            elif TOBIKO_TEST_PATTERN in test_dir:
                tobiko_reports.extend(self._process_tobiko_directory(test_dir_url, test_dir))

        status = "test_reports_found" if (tempest_reports or tobiko_reports) else "no_test_reports"

        return {
            "log_url": log_url,
            "status": status,
            "tempest_reports": tempest_reports,
            "tobiko_reports": tobiko_reports
        }

    def _find_test_directories(self, html_content):
        """Find test directories in HTML content."""
        soup = BeautifulSoup(html_content, "html.parser")
        test_dirs = []

        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Look for directories (ends with /)
            if href.endswith("/") and not href.startswith("/") and href != "../":
                test_dirs.append(href)

        return test_dirs

    def _process_tempest_directory(self, dir_url, dir_name):
        """Process a tempest test directory."""
        LOG.info("Checking tempest test directory: %s", dir_url)
        reports = []
        html_files = self._find_html_files(dir_url)

        for html_file in html_files:
            parser = TempestResultsParser(html_file)
            parser.parse()
            has_failures = parser.has_failures()

            report = {
                "url": html_file,
                "directory": dir_name,
                "has_failures": has_failures,
                "failed_tests": []
            }

            if has_failures:
                for test_name, traceback in parser.failed_tests:
                    report["failed_tests"].append({
                        "name": test_name,
                        "traceback": traceback
                    })

            reports.append(report)

        return reports

    def _process_tobiko_directory(self, dir_url, dir_name):
        """Process a tobiko test directory."""
        LOG.info("Checking tobiko test directory: %s", dir_url)
        reports = []
        html_files = self._find_html_files(dir_url)

        for html_file in html_files:
            # For now, we're not checking tobiko reports for failures
            reports.append({
                "url": html_file,
                "directory": dir_name,
                "has_failures": False,  # Placeholder
                "failed_tests": []      # Placeholder
            })

        return reports

    def _find_html_files(self, directory_url):
        """
        Find HTML files in a directory.

        Args:
            directory_url: URL of the directory to search

        Returns:
            List of HTML file URLs
        """
        html_files = []

        dir_html = self.fetch_html_content(directory_url)

        if not dir_html:
            LOG.info("Could not access directory: %s", directory_url)
            return html_files

        dir_soup = BeautifulSoup(dir_html, "html.parser")

        for link in dir_soup.find_all("a", href=True):
            href = link["href"]
            if href.endswith(".html") and not href.startswith("/"):
                html_url = f"{directory_url}/{href}"
                html_files.append(html_url)
                LOG.info("Found HTML file: %s", html_url)

        return html_files


def save_failed_tempest_paths(report_results):
    """
    Save only the failed tempest report paths to a file.

    Args:
        report_results: Dictionary mapping build UUIDs to test report information
    """
    failed_paths = []

    for _, result in report_results.items():
        if result["status"] == "test_reports_found":
            tempest_reports = result["tempest_reports"]
            for report in tempest_reports:
                if report["has_failures"]:
                    failed_paths.append(report["url"])

    with open("failed_tempest_paths.txt", "w", encoding='utf-8') as f:
        for path in failed_paths:
            f.write(f"{path}\n")

    return failed_paths


def create_tempest_failures_json(report_results, tracebacks_json):
    """
    Create a JSON file containing tempest report URLs and their failed tests.

    Args:
        report_results: Dictionary mapping build UUIDs to test report information
    """
    tempest_failures = []

    for _, result in report_results.items():
        if result["status"] == "test_reports_found":
            tempest_reports = result["tempest_reports"]
            for report in tempest_reports:
                if report["has_failures"]:
                    tempest_failures.append({
                        "url": report["url"],
                        "failed_tests": report["failed_tests"]
                    })

    with open(tracebacks_json, "w", encoding='utf-8') as f:
        json.dump(tempest_failures, f, indent=2)

    return tempest_failures


# # pylint: disable=too-few-public-methods

# class TestOperatorReportsProvider:
#     """Class responsible for retrieving and processing test operator reports."""

#     def __init__(self, server_url, tenant, pipeline, tracebacks_json):
#         """Initialize the TestOperatorReportsProvider with a server URL.

#         Args:
#             server_url (str): The URL of the Zuul server.
#         """
#         self.server_url = server_url
#         self.tenant = tenant
#         self.pipeline = pipeline
#         self.tracebacks_json = tracebacks_json

#     def run(self):
#         """Entry point of TestOperatorReportsProvider.
#         """
#         server_url = self.server_url
#         tenant = self.tenant
#         pipeline = self.pipeline

#         client = ZuulClient(server_url)


#         builds = client.get_failed_builds_json(tenant, pipeline)

#         if not builds:
#             LOG.error("%s", "No builds found or authentication failed")
#             return

#         LOG.info("Found %d failed builds within the last 2 weeks (after %s)",
#                     len(builds), CUTOFF_TIME.isoformat())

#         with open("failed_builds.json", "w", encoding='utf-8') as f:
#             json.dump(builds, f, indent=2)

#         report_results = client.find_test_reports(builds)

#         failed_paths = save_failed_tempest_paths(report_results)

#         for path in failed_paths:
#             print(path)

#         create_tempest_failures_json(report_results,self.tracebacks_json )


class TestOperatorReportsProvider:
    """Class responsible for retrieving and processing test operator reports."""

    def __init__(self, server_url, tenant, pipelines, tracebacks_json):
        """Initialize the TestOperatorReportsProvider with a server URL.

        Args:
            server_url (str): The URL of the Zuul server.
            tenant (str): The tenant name.
            pipelines (list): A list of pipeline names.
            tracebacks_json (str): Path to the tracebacks JSON file.
        """
        self.server_url = server_url
        self.tenant = tenant
        self.pipelines = pipelines
        self.tracebacks_json = tracebacks_json

        if os.path.exists("failed_builds.txt"):
            os.remove("failed_builds.txt")
            LOG.info("Deleted existing failed_builds.txt file")

        if os.path.exists(self.tracebacks_json):
            os.remove(self.tracebacks_json)
            LOG.info("Deleted existing %s file", self.tracebacks_json)

    def run(self):
        """Entry point of TestOperatorReportsProvider.
        """
        server_url = self.server_url
        tenant = self.tenant

        client = ZuulClient(server_url)

        all_builds = []

        for pipeline in self.pipelines:
            LOG.info("Processing pipeline: %s", pipeline)
            builds = client.retrive_failed_builds(tenant, pipeline)

            if not builds:
                LOG.warning("No builds found for pipeline %s", pipeline)
                continue

            LOG.info("Found %d failed builds in pipeline %s within the last 2 weeks (after %s)",
                    len(builds), pipeline, CUTOFF_TIME.isoformat())

            all_builds.extend(builds)

            with open("failed_builds.txt", "a", encoding='utf-8') as f:
                for build in builds:
                    f.write(f"{build}\n")

        report_results = client.find_test_reports(all_builds)

        failed_paths = save_failed_tempest_paths(report_results)

        for path in failed_paths:
            print(path)

        create_tempest_failures_json(report_results,self.tracebacks_json)
