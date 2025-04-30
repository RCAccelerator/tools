import requests
from bs4 import BeautifulSoup
import re
import sys
import os
import unittest
from io import StringIO
from unittest.mock import patch, mock_open
import urllib.parse
import warnings
import browser_cookie3


class TempestResultsParser:
    def __init__(self, source=None):
        self.source = source
        self.html_content = None
        self.soup = None
        self.failed_tests = []

        if source:
            self.load_content(source)

    def load_content(self, source):
        self.source = source
        self.html_content = self._get_content(source)
        self.soup = BeautifulSoup(self.html_content, 'html.parser')
        return self

    def _get_content(self, source):
        if source.startswith('http://') or source.startswith('https://'):
            print(f"Downloading from URL: {source}")

            parsed_url = urllib.parse.urlparse(source)
            domain = parsed_url.netloc
            cookies = None
            verify = False
            warnings.filterwarnings('ignore', 'Unverified HTTPS request')

            if 'redhat.com' in domain:
                try:
                    cookies = browser_cookie3.chrome(domain_name=domain)
                    print(f"Using Chrome cookies for domain: {domain}")
                except Exception as e:
                    print(f"Warning: Could not get browser cookies: {e}")

            response = requests.get(
                source,
                cookies=cookies,
                verify=verify
            )
            response.raise_for_status()

            filename = os.path.basename(source) or "testr_results.html"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(response.text)

            print(f"Downloaded content to: {filename}")
            return response.text
        else:
            print(f"Reading local file: {source}")
            with open(source, 'r', encoding='utf-8') as f:
                content = f.read()
            return content

    def parse(self):
        if not self.soup:
            raise ValueError("No content loaded. Call load_content() first.")

        self.failed_tests = []
        self._parse_html_format()
        return self.failed_tests

    def _parse_html_format(self):
        self._find_table_failures()

    def _find_table_failures(self):
        fail_links = self.soup.find_all('a', class_='popup_link')

        for link in fail_links:
            if link.text.strip().lower() != "fail":
                continue

            row = link.find_parent('tr')
            if not row:
                continue

            test_name = self._extract_full_test_name(row)

            traceback = None
            popup_id = link.get('href', '').split("'")[1] if "'" in link.get('href', '') else None

            if popup_id:
                popup_div = self.soup.find('div', id=popup_id)
                if popup_div:
                    pre_elem = popup_div.find('pre')
                    if pre_elem:
                        traceback = self._extract_traceback_from_text(pre_elem.text.strip())

            self.failed_tests.append((test_name, traceback or "No traceback found"))

    def _extract_full_test_name(self, row):
        test_case = ""

        test_case_div = row.find('div', class_='testcase')
        if test_case_div:
            test_case = test_case_div.text.strip()

        if not test_case:
            return "Unknown test"

        current = row
        while current:
            if current.get('class') and 'failClass' in current.get('class'):
                testname_cell = current.find('td', class_='testname')
                if testname_cell:
                    suite_name = testname_cell.text.strip()
                    return f"{suite_name}.{test_case}"

            current = current.find_previous_sibling('tr')

        popup_id = None
        popup_link = row.find('a', class_='popup_link')
        if popup_link:
            href = popup_link.get('href', '')
            if 'showTestDetail' in href:
                popup_id = href.split("'")[1] if "'" in href else None

        if popup_id:
            popup_div = self.soup.find('div', id=popup_id)
            if popup_div:
                pre_elem = popup_div.find('pre')
                if pre_elem:
                    content = pre_elem.text.strip()
                    parts = content.split(':', 1)
                    if len(parts) > 1 and '.' in parts[1]:
                        full_name = parts[1].strip()
                        if full_name.endswith(test_case):
                            return full_name
                        else:
                            return full_name + '.' + test_case

        return test_case

    def _extract_traceback_from_text(self, text):
        if not text:
            return None

        traceback_pattern = re.compile(r'Traceback \(most recent call last\):[\r\n]+\s+File "', re.MULTILINE)
        match = traceback_pattern.search(text)

        if match:
            start_pos = match.start()
            return text[start_pos:].strip()

        traceback_start = text.find("Traceback")
        if traceback_start != -1:
            lines = text[traceback_start:].split('\n')
            if len(lines) > 1 and "File " in lines[1]:
                return text[traceback_start:].strip()

        return text.strip()

    def print_results(self):
        if not self.failed_tests:
            print("No failed tests found.")
            return

        print(f"Found {len(self.failed_tests)} failed tests:")

        for test_name, traceback_text in self.failed_tests:
            print("===========================================================================================================")
            print(f"TEST: {test_name}")

            if traceback_text and traceback_text != "No traceback found":
                print(traceback_text)
            else:
                print("No traceback found")

class TestTempestResultsParser(unittest.TestCase):
    def test_no_failures(self):
        with patch('builtins.open', mock_open(read_data='<html><body>No failures here</body></html>')):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                parser = TempestResultsParser("tests/tempest.html")
                parser.parse()
                parser.print_results()
                output = fake_out.getvalue().strip()
                self.assertEqual("Reading local file: tests/tempest.html\nNo failed tests found.", output)

    def test_with_failures(self):
        # Create a mock HTML content for the failure case
        test_html = """
        <html>
        <body>
        <tr class="failClass">
            <td class="testname">whitebox_neutron_tempest_plugin.tests.scenario.test_api_server.NeutronAPIServerTest</td>
        </tr>
        <tr id="ft1.1" class="none">
            <td class="failCase"><div class="testcase">test_neutron_api_restart</div></td>
            <td colspan="7" align="left">
            <a class="popup_link" onfocus="this.blur();" href="javascript:showTestDetail('div_ft1.1')">fail</a>
            <div id="div_ft1.1" class="popup_window">
                <pre>
                ft1.1: whitebox_neutron_tempest_plugin.tests.scenario.test_api_server.NeutronAPIServerTest.test_neutron_api_restart
                Traceback (most recent call last):
                  File "/usr/lib/python3.9/site-packages/neutron_tempest_plugin/common/utils.py", line 85, in wait_until_true
                    eventlet.sleep(sleep)
                </pre>
            </div>
            </td>
        </tr>
        <tr class="failClass">
            <td class="testname">whitebox_neutron_tempest_plugin.tests.scenario.test_mtu</td>
        </tr>
        <tr id="ft2.1" class="none">
            <td class="failCase"><div class="testcase">GatewayMtuTestUdp.test_south_to_north_pmtud_udp_basic[id-7f7470ff-31b4-4ad8-bfa7-82dcca174744]</div></td>
            <td colspan="7" align="left">
            <a class="popup_link" onfocus="this.blur();" href="javascript:showTestDetail('div_ft2.1')">fail</a>
            <div id="div_ft2.1" class="popup_window">
                <pre>
                ft2.1: whitebox_neutron_tempest_plugin.tests.scenario.test_mtu.GatewayMtuTestUdp.test_south_to_north_pmtud_udp_basic[id-7f7470ff-31b4-4ad8-bfa7-82dcca174744]
                Traceback (most recent call last):
                  File "/usr/lib/python3.9/site-packages/whitebox_neutron_tempest_plugin/tests/scenario/test_mtu.py", line 247, in test_south_to_north_pmtud_udp_basic
                    self.check_pmtud_basic()
                </pre>
            </div>
            </td>
        </tr>
        </body>
        </html>
        """

        with patch('builtins.open', mock_open(read_data=test_html)):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                parser = TempestResultsParser("tests/tempest_err.html")
                parser.parse()
                parser.print_results()
                output = fake_out.getvalue().strip()

                # Check if output contains expected parts
                self.assertIn("Reading local file: tests/tempest_err.html", output)
                self.assertIn("Found 2 failed tests:", output)
                self.assertIn("TEST: whitebox_neutron_tempest_plugin.tests.scenario.test_api_server.NeutronAPIServerTest.test_neutron_api_restart", output)
                self.assertIn("Traceback (most recent call last):", output)
                self.assertIn("TEST: whitebox_neutron_tempest_plugin.tests.scenario.test_mtu.GatewayMtuTestUdp.test_south_to_north_pmtud_udp_basic[id-7f7470ff-31b4-4ad8-bfa7-82dcca174744]", output)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=['first-arg-is-ignored'])
        return

    if len(sys.argv) < 2:
        print("Usage: python test_parser.py <url_or_file>")
        print("       python test_parser.py --test (to run tests)")
        sys.exit(1)

    source = sys.argv[1]

    try:
        parser = TempestResultsParser(source)
        parser.parse()
        parser.print_results()

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
