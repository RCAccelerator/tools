"""fetch data from Zuul using Selenium."""
import logging
import json
import urllib3 as http
import requests
import browser_cookie3
import time
from typing import List, Dict, Any, Tuple, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

class ZuulProvider:
    """Provider for Zuul data using Selenium for better extraction."""

    def __init__(self, query_url: str, verify_ssl: bool = False):
        """Initialize the Zuul provider.
        
        Args:
            query_url: Base URL for Zuul API
            verify_ssl: Whether to verify SSL certificates
        """
        self.query_url = query_url
        self.verify_ssl = verify_ssl
        self.http = http.PoolManager(
            retries=http.Retry(
                total=5,
                connect=5,
                backoff_factor=0.1,
                status_forcelist=[429, 500, 502, 503, 504]
            ),
            timeout=http.Timeout(connect=5.0, read=180)
        )
        # Initialize Selenium WebDriver when needed
        self._driver = None
        
        
    def __del__(self):
        """Clean up resources when the object is destroyed."""
        if self._driver:
            try:
                self._driver.quit()
                LOG.info("Closed WebDriver")
            except Exception as e:
                LOG.error("Error closing WebDriver: %s", e)
                
    def get_browser_cookies(self, domain_name: str) -> Dict[str, str]:
        """Get cookies from the browser for the specified domain.
        
        Args:
            domain_name: Domain name to get cookies for
            
        Returns:
            Dictionary of cookies
        """
        try:
            # Try Chrome cookies first
            cookies = browser_cookie3.chrome(domain_name=domain_name)
            LOG.info("Successfully extracted Chrome cookies for %s", domain_name)
            return {c.name: c.value for c in cookies}
        except Exception as e:
            LOG.warning("Failed to get Chrome cookies: %s", e)
            try:
                # Try Firefox cookies as fallback
                cookies = browser_cookie3.firefox(domain_name=domain_name)
                LOG.info("Successfully extracted Firefox cookies for %s", domain_name)
                return {c.name: c.value for c in cookies}
            except Exception as e:
                LOG.error("Failed to get Firefox cookies: %s", e)
                return {}

    def get_report(self, report_id: int) -> Optional[List[str]]:
        """Get a Zuul report by ID and extract content with colored text.
        
        Args:
            report_id: ID of the report
            
        Returns:
            List of text strings from the report with color information, or None if the request failed
        """
        url = self._construct_report_url(report_id)
        
        try:
            # Use the web interface URL instead of API for Selenium
            web_url = url.replace('/api/report/', '/report/')
            LOG.info("Using web URL for Selenium: %s", web_url)
            
            # Extract colored elements using Selenium
            colored_elements = self._extract_colored_elements_selenium(web_url)
            if not colored_elements:
                LOG.warning("No colored elements found via Selenium or authentication failed, falling back to API")
                return self._fallback_to_api(url, report_id)
                
            # Format the final output
            data = self._format_colored_text(colored_elements)
                
            # Save formatted output for debugging
            self._save_formatted_output(report_id, data)
                
            LOG.info("Extracted %d lines of text from colored elements via Selenium", len(data))
            return data
                
        except Exception as e:
            LOG.error("Error processing Zuul report %d with Selenium: %s", report_id, str(e))
            import traceback
            LOG.error(traceback.format_exc())
            LOG.info("Falling back to API method")
            return self._fallback_to_api(url, report_id)

            
    def _process_api_response(self, response: requests.Response, report_id: int) -> List[str]:
        """Process the API response and extract key information.
        
        Args:
            response: API response object
            report_id: ID of the report
            
        Returns:
            Processed text lines with color information
        """
        # Save the raw response for debugging
        with open(f"api_response_{report_id}.txt", "w", encoding="utf-8", errors="replace") as f:
            f.write(response.text)
            
        # Try to parse as JSON
        try:
            data = response.json()
            # Save JSON structure for analysis
            with open(f"api_json_{report_id}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                
            # Process the JSON data
            return self._process_json_data(data)
            
        except json.JSONDecodeError:
            # Not JSON, try to process as plain text
            LOG.info("Response is not JSON, processing as text")
            return self._process_text_data(response.text)
            
    def _process_json_data(self, data: Dict[str, Any]) -> List[str]:
        """Process JSON data from API response.
        
        Args:
            data: JSON data
            
        Returns:
            Processed text lines with color information
        """
        lines = []
        
        # Look for common fields in the JSON that might contain log data
        if isinstance(data, dict):
            # Check for logs field
            if 'logs' in data and isinstance(data['logs'], list):
                lines.append("Color: blue")
                lines.append("LOGS FROM JSON:")
                
                for log in data['logs']:
                    if isinstance(log, dict):
                        if 'name' in log:
                            lines.append("------------------------------------- separator line")
                            lines.append(f"Color: green")
                            lines.append(f"LOG: {log['name']}")
                        
                        if 'content' in log and log['content']:
                            log_lines = log['content'].split('\n')
                            
                            # Apply color based on content
                            for line in log_lines:
                                if 'error' in line.lower() or 'fail' in line.lower():
                                    if lines[-1] != "Color: red":
                                        lines.append("Color: red")
                                    lines.append(line)
                                elif 'warn' in line.lower():
                                    if lines[-1] != "Color: yellow":
                                        lines.append("Color: yellow")
                                    lines.append(line)
                                else:
                                    if not lines or lines[-1].startswith("Color:"):
                                        lines.append("Color: default")
                                    lines.append(line)
            
            # Check for test results
            if 'results' in data and isinstance(data['results'], list):
                lines.append("------------------------------------- separator line")
                lines.append("Color: blue")
                lines.append("TEST RESULTS:")
                
                for result in data['results']:
                    if isinstance(result, dict):
                        status = result.get('status', '').lower()
                        if status in ('failed', 'failure'):
                            lines.append("Color: red")
                        elif status == 'success':
                            lines.append("Color: green")
                        else:
                            lines.append("Color: default")
                            
                        lines.append(f"Test: {result.get('name', 'Unknown')} - Status: {status}")
                        
                        if 'message' in result:
                            lines.append(result['message'])
        
        # If we couldn't extract any meaningful data, just return the JSON as text
        if not lines:
            lines.append("Color: default")
            lines.append(json.dumps(data, indent=2))
            
        return lines
            
    def _process_text_data(self, text: str) -> List[str]:
        """Process plain text data from API response.
        
        Args:
            text: Plain text data
            
        Returns:
            Processed text lines with color information
        """
        lines = []
        current_color = None
        
        # Split into lines and process
        for line in text.split('\n'):
            # Apply color based on content
            if 'fatal:' in line or 'error:' in line or 'fail' in line.lower():
                if current_color != "red":
                    current_color = "red"
                    lines.append("Color: red")
            elif 'warn' in line.lower():
                if current_color != "yellow":
                    current_color = "yellow"
                    lines.append("Color: yellow")
            elif 'success' in line.lower() or 'ok:' in line:
                if current_color != "green":
                    current_color = "green"
                    lines.append("Color: green")
            elif not lines or lines[-1].startswith("Color:"):
                # Only add default color if we don't have a color or the last line was a color
                current_color = "default"
                lines.append("Color: default")
                
            # Add the line
            lines.append(line)
                
        return lines

    def _construct_report_url(self, report_id: int) -> str:
        """Construct the report URL with proper formatting.
        
        Args:
            report_id: ID of the report
            
        Returns:
            Properly formatted URL for the report
        """
        # Ensure the base URL has a scheme
        if not self.query_url.startswith(('http://', 'https://')):
            base_url = f"https://{self.query_url}"
        else:
            base_url = self.query_url
        
        # Fix double slashes and remove trailing slashes
        base_url = base_url.rstrip('/')
        
        # Use the API endpoint
        url = f"{base_url}/api/report/{report_id}"
        
        LOG.info("Constructed API URL: %s", url)
        return url

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for cookie retrieval.
        
        Args:
            url: The URL to extract domain from
            
        Returns:
            Domain name
        """
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        LOG.info("Extracted domain: %s from URL: %s", domain, url)
        return domain

    def _fetch_url(self, url: str, cookies: Dict[str, str]) -> Optional[requests.Response]:
        """Fetch URL with provided cookies.
        
        Args:
            url: URL to fetch
            cookies: Cookies to use for request
            
        Returns:
            Response object or None if request failed
        """
        try:
            response = requests.get(
                url,
                cookies=cookies if cookies else None,
                verify=self.verify_ssl,
                timeout=(5.0, 180)
            )
            
            if response.status_code != 200:
                LOG.error("Failed to get URL %s: HTTP %d", url, response.status_code)
                return None
                
            return response
            
        except requests.RequestException as e:
            LOG.error("Request error for %s: %s", url, e)
            return None
 

    def _format_colored_text(self, colored_elements: List[Dict[str, str]]) -> List[str]:
        """Format colored elements into text output with separators.
        
        Args:
            colored_elements: List of dictionaries with text and color information
            
        Returns:
            Formatted list of strings
        """
        data = []
        current_color = None
        
        for item in colored_elements:
            if item['color'] != current_color:
                # New color encountered
                if current_color is not None:  # Not the first color
                    data.append("------------------------------------- separator line")
                current_color = item['color']
                data.append(f"Color: {current_color}")
            
            # Add the text with this color
            data.append(item['text'])
                
        return data

    def _save_formatted_output(self, report_id: int, data: List[str]) -> None:
        """Save formatted output for debugging.
        
        Args:
            report_id: ID of the report
            data: Formatted output data
        """
        with open(f"report_{report_id}_colored.txt", "w", encoding="utf-8") as f:
            for line in data:
                f.write(f"{line}\n")


    def _get_driver(self):
        """Get or create a headless browser instance without trying to set cookies.
        
        Returns:
            WebDriver instance
        """
        if self._driver is None:
            LOG.info("Initializing headless Chrome browser")
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            
            # Create browser without setting cookies
            try:
                self._driver = webdriver.Chrome(options=chrome_options)
                LOG.info("Chrome WebDriver initialized successfully")
            except Exception as e:
                LOG.error("Error creating WebDriver: %s", e)
                self._driver = None
                
        return self._driver
            
    def _extract_colored_elements_selenium(self, url: str) -> List[Dict[str, str]]:
        """Extract colored elements using Selenium with improved cookie handling.
        
        Args:
            url: URL to scrape
            
        Returns:
            List of dictionaries with text and color information
        """
        driver = self._get_driver()
        if not driver:
            LOG.error("WebDriver not available")
            return []
            
        try:
            # Extract domain properly
            from urllib.parse import urlparse
            parsed_url = urlparse(url if url.startswith(('http://', 'https://')) else f"https://{url}")
            domain = parsed_url.netloc
            
            # Get browser cookies
            cookies = self.get_browser_cookies(domain)
            
            # First load a simple page from the domain
            base_url = f"https://{domain}"
            LOG.info(f"Loading base URL {base_url}")
            driver.get(base_url)
            
            # Wait for base page to load
            time.sleep(2)
            
            # Add cookies with more complete information
            if cookies:
                LOG.info(f"Setting {len(cookies)} cookies from browser")
                for name, value in cookies.items():
                    try:
                        # More complete cookie dictionary
                        cookie_dict = {
                            'name': name,
                            'value': value,
                            'domain': domain,
                            'path': '/'
                        }
                        driver.add_cookie(cookie_dict)
                        LOG.info(f"Added cookie: {name}")
                    except Exception as e:
                        LOG.warning(f"Failed to add cookie {name}: {e}")
            
            # Take screenshot before navigating to report URL
            driver.save_screenshot(f"before_navigation_{domain}.png")
            
            # Now navigate to the actual URL
            LOG.info(f"Navigating to {url}")
            driver.get(url)
            
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            LOG.info("Basic page loaded")
            
            # Take screenshot to see what loaded
            driver.save_screenshot(f"after_navigation_{url.split('/')[-1]}.png")
            
            # Check if login page is shown
            page_source = driver.page_source.lower()
            if "sign in" in page_source or "login" in page_source:
                LOG.warning("Login page detected, authentication failed")
                
                # Try using direct requests instead
                LOG.info("Falling back to API access")
                return []
            
            # Wait for content to load
            time.sleep(10)
            
            # Take another screenshot after waiting
            driver.save_screenshot(f"after_wait_{url.split('/')[-1]}.png")
            
            # Extract elements with their styling
            colored_elements = driver.execute_script("""
                function getElementsWithColor() {
                    const result = [];
                    const allElements = document.querySelectorAll('*');
                    
                    for (let elem of allElements) {
                        if (elem.textContent && elem.textContent.trim()) {
                            const style = window.getComputedStyle(elem);
                            const color = style.color;
                            
                            // Skip black text and gray text
                            if (color && 
                                !color.match(/rgba?\\(0,\\s*0,\\s*0/) && 
                                !color.match(/rgba?\\(107,\\s*114,\\s*128/)) { 
                                result.push({
                                    text: elem.textContent.trim(),
                                    color: color
                                });
                            }
                        }
                    }
                    return result;
                }
                return getElementsWithColor();
            """)
            
            LOG.info(f"Found {len(colored_elements)} colored text elements with Selenium")
            
            # Save full page source for debugging
            with open(f"page_source_{url.split('/')[-1]}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            
            # Save debug info
            with open(f"selenium_elements_{url.split('/')[-1]}.txt", "w", encoding="utf-8") as f:
                for item in colored_elements:
                    f.write(f"Color: {item['color']} - Text: {item['text']}\n")
            
            # If we're still seeing the login page, return empty list to trigger fallback
            for item in colored_elements:
                if "sign in" in item['text'].lower() or "need help signing in" in item['text'].lower():
                    LOG.warning("Login text detected in colored elements, authentication likely failed")
                    return []
                    
            return colored_elements
            
        except Exception as e:
            LOG.error(f"Error extracting colored elements with Selenium: {e}")
            import traceback
            LOG.error(traceback.format_exc())
            return []
        

    def _fallback_to_api(self, url: str, report_id: int) -> Optional[List[str]]:
        """Fallback to the API method if Selenium fails.
        
        Args:
            url: API URL to fetch
            report_id: ID of the report
            
        Returns:
            Processed text data or None if failed
        """
        try:
            domain = self._extract_domain(url)
            cookies = self.get_browser_cookies(domain)
            
            LOG.info(f"Falling back to API request for {url}")
            # Fetch the report without processing the response yet
            response = requests.get(
                url,
                cookies=cookies if cookies else None,
                verify=self.verify_ssl,
                timeout=(5.0, 180),
                stream=True  # Stream the response to handle binary data better
            )
            
            if response.status_code != 200:
                LOG.error(f"API request failed with status code {response.status_code}")
                return None
                
            # Save raw response content for debugging
            with open(f"raw_response_{report_id}.bin", "wb") as f:
                f.write(response.content)
                
            # Try to process as text first with error handling
            try:
                text_content = response.content.decode('utf-8', errors='replace')
                with open(f"text_response_{report_id}.txt", "w", encoding="utf-8") as f:
                    f.write(text_content)
                    
                # Extract meaningful information from the text
                return self._extract_log_patterns_from_text(text_content)
                
            except Exception as e:
                LOG.warning(f"Error processing response as text: {e}")

                
        except Exception as e:
            LOG.error(f"API fallback failed: {e}")
            return None
            
    def _extract_log_patterns_from_text(self, text: str) -> List[str]:
        """Extract log patterns and add color coding to text.
        
        Args:
            text: Raw text content
            
        Returns:
            List of strings with color coding
        """
        lines = []
        current_color = None
        
        # Process line by line
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            lines.append(line)
            
        return lines
        