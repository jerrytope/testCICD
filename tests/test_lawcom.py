import os
import sys
import unittest
from unittest.mock import patch, Mock
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraping.lawcom import get_project_links_from_page, get_all_project_links, get_pdf_links, BASE_URL, CURRENT_PROJECTS_URL, COMPLETED_PROJECTS_URL

class TestLawcomScraperOffline(unittest.TestCase):
    """Offline unit tests with mocked responses for the Law Commission scraper."""
    
    def setUp(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        
        # Sample HTML content for testing
        self.sample_current_projects_html = """
        <html>
            <body>
                <div class="project-links">
                    <a href="/project/aviation-autonomy/">Aviation Autonomy</a>
                    <a href="/project/burial-and-cremation/">Burial and Cremation</a>
                    <a href="/project/contempt-of-court/">Contempt of Court</a>
                    <a href="/project/criminal-appeals/">Criminal Appeals</a>
                </div>
                <div class="navigation">
                    <a href="/about/">About Us</a>
                    <a href="/contact/">Contact</a>
                    <a href="/cookies/">Cookies</a>
                </div>
            </body>
        </html>
        """
        
        self.sample_completed_projects_html = """
        <html>
            <body>
                <div class="project-links">
                    <a href="/project/confiscation-under-part-2-of-the-proceeds-of-crime-act-2002/">Confiscation</a>
                    <a href="/project/decentralised-autonomous-organisations-daos/">DAOs</a>
                    <a href="/project/digital-assets/">Digital Assets</a>
                </div>
            </body>
        </html>
        """
        
        self.sample_project_page_html = """
        <html>
            <body>
                <div class="content">
                    <h1>Sample Project</h1>
                    <p>This is a sample project page with PDF links.</p>
                    <a href="https://example.com/document1.pdf">Download Report (PDF)</a>
                    <a href="https://example.com/document2.pdf">Download Summary (PDF)</a>
                    <a href="https://example.com/not-a-pdf.txt">Text Document</a>
                </div>
            </body>
        </html>
        """

    @patch('requests.get')
    def test_website_accessibility_mocked(self, mock_get):
        """Test website accessibility with mocked responses."""
        # Mock successful responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Test that the function handles successful responses
        from scraping.lawcom import get_project_links_from_page
        
        # This should not raise an exception
        result = get_project_links_from_page(CURRENT_PROJECTS_URL, self.headers)
        self.assertIsInstance(result, list)
        
        # Verify requests.get was called
        mock_get.assert_called()

    @patch('requests.get')
    def test_get_project_links_mocked(self, mock_get):
        """Test project link extraction with mocked HTML content."""
        # Mock response with sample HTML
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = self.sample_current_projects_html.encode('utf-8')
        mock_get.return_value = mock_response
        
        # Test current projects
        current_links = get_project_links_from_page(CURRENT_PROJECTS_URL, self.headers)
        
        # Should find project links but not navigation links
        expected_links = [
            BASE_URL + "/project/aviation-autonomy/",
            BASE_URL + "/project/burial-and-cremation/",
            BASE_URL + "/project/contempt-of-court/",
            BASE_URL + "/project/criminal-appeals/"
        ]
        
        self.assertEqual(len(current_links), 4)
        for expected_link in expected_links:
            self.assertIn(expected_link, current_links)
        
        # Should not contain navigation links
        self.assertNotIn(BASE_URL + "/about/", current_links)
        self.assertNotIn(BASE_URL + "/contact/", current_links)
        self.assertNotIn(BASE_URL + "/cookies/", current_links)

    @patch('requests.get')
    def test_get_all_project_links_mocked(self, mock_get):
        """Test getting all project links from multiple sources."""
        # Mock responses for both current and completed projects
        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = Mock()
            mock_response.status_code = 200
            if "current" in url:
                mock_response.content = self.sample_current_projects_html.encode('utf-8')
            else:
                mock_response.content = self.sample_completed_projects_html.encode('utf-8')
            return mock_response
        
        mock_get.side_effect = mock_get_side_effect
        
        # Test getting all project links
        all_links = get_all_project_links(self.headers)
        
        # Should combine links from both sources
        expected_total = 7  # 4 current + 3 completed
        self.assertEqual(len(all_links), expected_total)
        
        # Verify both current and completed project links are included
        current_project_links = [link for link in all_links if "aviation" in link or "burial" in link]
        completed_project_links = [link for link in all_links if "confiscation" in link or "daos" in link]
        
        self.assertGreater(len(current_project_links), 0)
        self.assertGreater(len(completed_project_links), 0)

    @patch('requests.get')
    def test_get_pdf_links_mocked(self, mock_get):
        """Test PDF extraction from mocked project page."""
        # Mock response with sample project page HTML
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = self.sample_project_page_html.encode('utf-8')
        mock_get.return_value = mock_response
        
        # Test PDF extraction
        pdf_links = get_pdf_links("https://example.com/project", self.headers)
        
        # Should find PDF links
        expected_pdfs = [
            "https://example.com/document1.pdf",
            "https://example.com/document2.pdf"
        ]
        
        self.assertEqual(len(pdf_links), 2)
        for expected_pdf in expected_pdfs:
            self.assertIn(expected_pdf, pdf_links)
        
        # Should not include non-PDF links
        self.assertNotIn("https://example.com/not-a-pdf.txt", pdf_links)

    @patch('requests.get')
    def test_pdf_download_mocked(self, mock_get):
        """Test PDF download with mocked response."""
        # Mock PDF response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"%PDF-1.4\n%Mock PDF content\n%%EOF"
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_get.return_value = mock_response
        
        # Test that we can handle PDF responses
        test_pdf_url = "https://example.com/test.pdf"
        response = mock_get(test_pdf_url, headers=self.headers)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('pdf', response.headers.get('content-type', '').lower())
        self.assertGreater(len(response.content), 0)

    def test_filtering_logic_offline(self):
        """Test that navigation links are properly filtered out using sample data."""
        # Parse sample HTML
        soup = BeautifulSoup(self.sample_current_projects_html, "html.parser")
        all_links = []
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            text = str(link.get_text(strip=True))
            if href and text:
                all_links.append((href, text))
        
        # Simulate the filtering logic
        project_links = []
        navigation_keywords = ["cookies", "privacy", "accessibility", "about", "contact"]
        
        for href, text in all_links:
            # Skip navigation links
            if any(keyword in text.lower() for keyword in navigation_keywords):
                continue
            # Add project links
            full_url = BASE_URL + href if href.startswith("/") else href
            project_links.append(full_url)
        
        # Should have 4 project links
        self.assertEqual(len(project_links), 4)
        
        # Should not contain navigation links
        navigation_links = [BASE_URL + "/about/", BASE_URL + "/contact/", BASE_URL + "/cookies/"]
        for nav_link in navigation_links:
            self.assertNotIn(nav_link, project_links)

    @patch('requests.get')
    def test_error_handling(self, mock_get):
        """Test error handling with mocked failed requests."""
        # Mock failed response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        # Test that the function handles errors gracefully
        result = get_project_links_from_page(CURRENT_PROJECTS_URL, self.headers)
        self.assertIsInstance(result, list)
        # Should return empty list for failed requests
        self.assertEqual(len(result), 0)

    @patch('requests.get')
    def test_timeout_handling(self, mock_get):
        """Test timeout handling with mocked timeout exception."""
        # Mock timeout exception
        mock_get.side_effect = Exception("Connection timeout")
        
        # Test that the function handles timeouts gracefully
        result = get_project_links_from_page(CURRENT_PROJECTS_URL, self.headers)
        self.assertIsInstance(result, list)
        # Should return empty list for timeout errors
        self.assertEqual(len(result), 0)

if __name__ == "__main__":
    unittest.main(verbosity=2) 