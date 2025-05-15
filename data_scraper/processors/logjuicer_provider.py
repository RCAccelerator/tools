"""Code for logjuicer based diffs provisioning"""
# Standard library imports

import json
import logging
import os
import urllib.parse
import warnings
import subprocess
from datetime import datetime, timedelta

import browser_cookie3
import requests

from data_scraper.common import constants


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
FILTER_RESULT_SUCCESS = "SUCCESS"
FILTER_LIMIT = 20000

# Time filter constant - builds older than this will be excluded
CUTOFF_TIME = datetime.now() - timedelta(days=14)  # 2 weeks ago

# Define output directory for files (using /tmp for OpenShift compatibility)
OUTPUT_DIR = "/tmp"


def make_authenticated_request(url, params=None, timeout=30.0):
    """
    Make an authenticated request to a URL using Chrome or Firefox cookies.
    This method is the only one supported by logjuicer ATM. 
    We need to address the issue of running this code in openshift containers:
    see https://github.com/RCAccelerator/tools/pull/59

    Args:
        url: URL to fetch
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        Response content as text, or None if an error occurs
        For JSON responses, the caller will need to parse the text
    """
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc

    verify = False
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


class ZuulClient:
    """Client for fetching Zuul build data and analyzing test reports."""

    def __init__(self, base_url):
        """
        Initialize the client with the base URL.

        Args:
            base_url: Base URL for the Zuul server
        """
        self.base_url = base_url.rstrip('/')

    def retrieve_failed_builds(self, tenant, pipeline, limit=FILTER_LIMIT):
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
    
    def retrieve_successful_builds(self, tenant, job_name, limit=FILTER_LIMIT):
        """
        Get successful builds for a specific job as JSON.

        Args:
            tenant: Tenant name
            job_name: Job name
            limit: Maximum number of builds to return

        Returns:
            JSON response as dictionary with successful builds
        """
        endpoint = API_BUILDS.format(tenant=tenant)
        url = f"{self.base_url}/{endpoint}"

        params = {
            "limit": limit,
            "result": FILTER_RESULT_SUCCESS,
            "job_name": job_name
        }

        LOG.info("Fetching successful builds for job %s from: %s", job_name, url)

        try:
            content_text = make_authenticated_request(url, params=params, timeout=60.0)
            if not content_text:
                return []

            result = json.loads(content_text)
            LOG.info("Successfully fetched %d successful builds for job %s", len(result), job_name)
            return result

        except (requests.RequestException, requests.HTTPError, requests.ConnectionError,
                requests.Timeout, requests.TooManyRedirects) as e:
            LOG.error("Error fetching successful builds: %s", e)
            return []
    
    def retrieve_all_builds_for_job(self, tenant, job_name, limit=FILTER_LIMIT):
        """
        Get all builds for a specific job as JSON, regardless of status.

        Args:
            tenant: Tenant name
            job_name: Job name
            limit: Maximum number of builds to return

        Returns:
            JSON response as dictionary with all builds for the job
        """
        endpoint = API_BUILDS.format(tenant=tenant)
        url = f"{self.base_url}/{endpoint}"

        params = {
            "limit": limit,
            "job_name": job_name
        }

        LOG.info("Fetching all builds for job %s from: %s", job_name, url)

        try:
            content_text = make_authenticated_request(url, params=params, timeout=60.0)
            if not content_text:
                return []

            result = json.loads(content_text)
            LOG.info("Successfully fetched %d builds for job %s", len(result), job_name)
            return result

        except (requests.RequestException, requests.HTTPError, requests.ConnectionError,
                requests.Timeout, requests.TooManyRedirects) as e:
            LOG.error("Error fetching all builds: %s", e)
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

    def parse_build_time(self, build):
        """
        Parse the timestamp from a build.

        Args:
            build: Build dictionary

        Returns:
            Datetime object or None if parsing fails
        """
        end_time = build.get("end_time")
        if not end_time:
            end_time = build.get("start_time")

        # Skip if no timestamp available
        if not end_time:
            return None

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
            
            return build_time
        except ValueError:
            LOG.warning("Could not parse timestamp for build: %s", build.get("uuid", "unknown"))
            return None

    def calculate_build_duration(self, build):
        """
        Calculate the duration of a build in seconds.

        Args:
            build: Build dictionary

        Returns:
            Duration in seconds or 0 if calculation fails
        """
        end_time = build.get("end_time")
        start_time = build.get("start_time")

        if not end_time or not start_time:
            return 0

        try:
            # Parse timestamps
            if 'Z' in end_time:
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            elif 'T' in end_time and '+' in end_time:
                end = datetime.fromisoformat(end_time)
            else:
                end = datetime.fromisoformat(end_time)

            if 'Z' in start_time:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            elif 'T' in start_time and '+' in start_time:
                start = datetime.fromisoformat(start_time)
            else:
                start = datetime.fromisoformat(start_time)

            # Calculate duration
            duration = (end - start).total_seconds()
            return duration
        except ValueError:
            LOG.warning("Could not calculate duration for build: %s", build.get("uuid", "unknown"))
            return 0

    def find_reference_build(self, tenant, job_name, failed_build):
        """
        Find a reference build for a failed job.
        
        Strategy:
        1. Try to find a successful build before the cutoff time
        2. If no successful build is found, find the build that took the longest time to complete
        
        Args:
            tenant: Tenant name
            job_name: Job name
            failed_build: The failed build dictionary
        
        Returns:
            Reference build dictionary or None if not found
        """
        LOG.info("Finding reference build for job: %s", job_name)
        
        # First, try to find a successful build
        successful_builds = self.retrieve_successful_builds(tenant, job_name)
        
        if successful_builds:
            # Sort by end_time to get the most recent successful build
            successful_builds.sort(
                key=lambda b: self.parse_build_time(b) or datetime.min, 
                reverse=True
            )
            reference_build = successful_builds[0]
            LOG.info("Found successful reference build: %s", reference_build.get("uuid", "unknown"))
            return reference_build
        
        # If no successful builds, get all builds for the job
        LOG.info("No successful builds found, looking for longest running build")
        all_builds = self.retrieve_all_builds_for_job(tenant, job_name)
        
        if not all_builds:
            LOG.warning("No reference builds found for job: %s", job_name)
            return None
        
        # Filter out the current failed build
        all_builds = [b for b in all_builds if b.get("uuid") != failed_build.get("uuid")]
        
        if not all_builds:
            LOG.warning("No other builds found for job: %s", job_name)
            return None
        
        # Sort by duration to find the longest running build
        all_builds.sort(
            key=lambda b: self.calculate_build_duration(b),
            reverse=True
        )
        
        reference_build = all_builds[0]
        LOG.info("Found longest running reference build: %s, duration: %s seconds", 
                reference_build.get("uuid", "unknown"),
                self.calculate_build_duration(reference_build))
        
        return reference_build


# pylint: disable=too-few-public-methods
class LogjuicerDiffsProvider:
    """Class responsible for retrieving and processing logjuicer diffs."""

    def __init__(self, server_url, tenant, pipelines, logjuicer_diffs_json, auth_openidc=None):
        """Initialize the LogjuicerDiffsProvider with a server URL.

        Args:
            server_url (str): The URL of the Zuul server.
            tenant (str): The tenant name.
            pipelines (list): A list of pipeline names.
            logjuicer_diffs_json (str): Path to the logjuicer diffs JSON file.
            auth_openidc (str, optional): The auth_openidc cookie for authentication.
        """
        self.server_url = server_url
        self.tenant = tenant
        self.pipelines = pipelines
        self.auth_openidc = auth_openidc

        if not logjuicer_diffs_json.startswith('/'):
            self.tracebacks_json = os.path.join(OUTPUT_DIR, logjuicer_diffs_json)
        else:
            self.tracebacks_json = logjuicer_diffs_json

        self.failed_builds_file = os.path.join(OUTPUT_DIR, "failed_builds.txt")
        self.reference_builds_json = os.path.join(OUTPUT_DIR, "reference_builds.json")
        self.logjuicer_reports_dir = os.path.join(OUTPUT_DIR, "logjuicer_reports")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(self.logjuicer_reports_dir, exist_ok=True)

    def _load_failed_builds_from_file(self):
        """
        Load failed builds from the existing file.
        
        Returns:
            List of failed build dictionaries
        """
        LOG.info("Loading failed builds from %s", self.failed_builds_file)
        builds = []
        
        try:
            with open(self.failed_builds_file, "r", encoding='utf-8') as f:
                for line in f:
                    try:
                        build = eval(line.strip())  # Using eval since the file contains Python dict literals
                        builds.append(build)
                    except (SyntaxError, ValueError) as e:
                        LOG.error("Error parsing build from file: %s", e)
        except FileNotFoundError:
            LOG.error("Failed builds file not found: %s", self.failed_builds_file)
            
        LOG.info("Loaded %d failed builds from file", len(builds))
        return builds
    
    def _load_reference_builds_from_file(self):
        """
        Load reference builds data from the existing JSON file.
        
        Returns:
            List of reference build records
        """
        LOG.info("Loading reference builds from %s", self.reference_builds_json)
        reference_data = []
        
        try:
            with open(self.reference_builds_json, "r", encoding='utf-8') as f:
                reference_data = json.load(f)
                
            LOG.info("Loaded %d reference build records from file", len(reference_data))
        except FileNotFoundError:
            LOG.error("Reference builds file not found: %s", self.reference_builds_json)
        except json.JSONDecodeError as e:
            LOG.error("Error parsing reference builds JSON: %s", e)
            
        return reference_data
    
    def _create_zuul_url(self, tenant, uuid):
        """
        Create a Zuul URL for a build.
        
        Args:
            tenant: Tenant name
            uuid: Build UUID
            
        Returns:
            Zuul URL string
        """
        return f"{self.server_url}/zuul/t/{tenant}/build/{uuid}/"

    def run(self):
        """Entry point of LogjuicerDiffsProvider.
        """
        server_url = self.server_url
        tenant = self.tenant

        client = ZuulClient(server_url)

        all_builds = []
        reference_data = []

        # Check if reference_builds_json exists and load from it if it does
        if os.path.exists(self.reference_builds_json):
            LOG.info("Reference builds file exists, skipping reference build processing")
            reference_data = self._load_reference_builds_from_file()
        else:
            # Check if failed_builds_file exists and load from it if it does
            if os.path.exists(self.failed_builds_file):
                LOG.info("Failed builds file exists, skipping pipeline processing")
                all_builds = self._load_failed_builds_from_file()
            else:
                # Process all pipelines to get failed builds
                for pipeline in self.pipelines:
                    LOG.info("Processing pipeline: %s", pipeline)
                    builds = client.retrieve_failed_builds(tenant, pipeline)

                    if not builds:
                        LOG.warning("No builds found for pipeline %s", pipeline)
                        continue

                    LOG.info("Found %d failed builds in pipeline %s within the last 2 weeks (after %s)",
                            len(builds), pipeline, CUTOFF_TIME.isoformat())

                    all_builds.extend(builds)

                # Save all_builds to the failed_builds_file
                with open(self.failed_builds_file, "w", encoding='utf-8') as f:
                    for build in all_builds:
                        f.write(f"{build}\n")

                LOG.info("Saved %d failed builds to %s", len(all_builds), self.failed_builds_file)

            # Find reference builds for each failed job
            for failed_build in all_builds:
                job_name = failed_build.get("job_name")
                if not job_name:
                    LOG.warning("Build missing job_name, skipping: %s", failed_build.get("uuid", "unknown"))
                    continue
                    
                reference_build = client.find_reference_build(tenant, job_name, failed_build)
                
                if not reference_build:
                    LOG.warning("No reference build found for job: %s", job_name)
                    continue
                    
                # Create a record with the specified information and Zuul URLs
                record = {
                    "failed_build": {
                        "uuid": failed_build.get("uuid"),
                        "job_name": job_name,
                        "url": self._create_zuul_url(tenant, failed_build.get("uuid")),
                        "date": failed_build.get("start_time"),
                    },
                    "reference_build": {
                        "uuid": reference_build.get("uuid"),
                        "job_name": reference_build.get("job_name"),
                        "url": self._create_zuul_url(tenant, reference_build.get("uuid")),
                        "status": reference_build.get("result"),
                        "date": reference_build.get("start_time"),
                    }
                }
                
                reference_data.append(record)
                
            # Save reference data to JSON file
            with open(self.reference_builds_json, "w", encoding='utf-8') as f:
                json.dump(reference_data, f, indent=2)
                
            LOG.info("Saved reference builds data for %d failed builds to %s", 
                    len(reference_data), self.reference_builds_json)

        # Run logjuicer on each build pair

        for i, build_pair in enumerate(reference_data):
            failed_build = build_pair["failed_build"]
            reference_build = build_pair["reference_build"]
            
            LOG.info("[%d/%d] Running logjuicer diff on %s vs %s", 
                    i+1, len(reference_data), 
                    reference_build.get("uuid"), 
                    failed_build.get("uuid"))
            
            report_file = os.path.join(
                self.logjuicer_reports_dir, 
                f"{failed_build.get('uuid')}_{reference_build.get('uuid')}.json"
            )
            
            # Skip if report already exists
            if os.path.exists(report_file):
                LOG.info("Report file already exists, skipping: %s", report_file)
                continue
            
            # Run logjuicer command
            cmd = [
                "env", 
                f"LOGJUICER_HTTP_AUTH=\"Cookie: mod_auth_openidc_session={self.auth_openidc}\"",
                "~/Downloads/bin/logjuicer",
                "--report",
                report_file,
                "diff",
                reference_build.get("url"),
                failed_build.get("url")
            ]
            
            LOG.info("Running command: %s", " ".join(cmd))
            
            try:
                result = subprocess.run(
                    " ".join(cmd), 
                    shell=True, 
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                LOG.info("Logjuicer command completed successfully")
                LOG.debug("Command output: %s", result.stdout)
            except subprocess.CalledProcessError as e:
                LOG.error("Logjuicer command failed: %s", e)
                LOG.error("Command stderr: %s", e.stderr)
            except Exception as e:
                LOG.error("Error running logjuicer command: %s", e)

