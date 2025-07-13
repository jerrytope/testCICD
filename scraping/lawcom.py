import os
import sys
from os import path
import requests
from bs4 import BeautifulSoup
import re

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
from utils import trim_filename, setup_container, upload_file_to_storage
from custom_logger import setup_logger

logger = setup_logger(__name__)

BASE_URL = "https://www.lawcom.gov.uk"
CURRENT_PROJECTS_URL = f"{BASE_URL}/current-projects/"
COMPLETED_PROJECTS_URL = f"{BASE_URL}/completed-projects/"

# Utility: filter out navigation and utility links
SKIP_URL_KEYWORDS = [
    "/cookies", "/privacy", "/accessibility", "/about-us", "/contact", "/freedom-of-information", "/corporate-documents", "/vacancies", "/news", "/events", "/media-centre", "/publications", "/terms", "/sitemap"
]
SKIP_TEXT_KEYWORDS = [
    "cookie", "privacy", "accessibility", "contact", "skip", "about", "freedom", "corporate", "vacanc", "news", "event", "media", "publication", "terms", "sitemap"
]

PROJECT_URL_PATTERN = re.compile(r"^/project/[^/]+/?$")
PROJECT_URL_PATTERN_FULL = re.compile(r"^https?://[^/]+/project/[^/]+/?$")


def get_project_links_from_page(page_url, headers):
    """Extract /project/slug/ links from a given page."""
    try:
        response = requests.get(page_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        links = set()
        
        # Look for project links in specific div elements
        project_divs = soup.find_all("div", class_=re.compile(r"list-item|mojblocks-featured-item"))
        
        for div in project_divs:
            for link in div.find_all("a", href=True):
                href = str(link.get("href", ""))
                text = str(link.get_text(strip=True))
                if not href or not text or len(text) < 4:
                    continue
                # Only include /project/slug/ links (relative or absolute)
                if PROJECT_URL_PATTERN.match(href) or PROJECT_URL_PATTERN_FULL.match(href):
                    # Filter out navigation/utility links
                    if (any(skip in href for skip in SKIP_URL_KEYWORDS) or
                        any(skip in text.lower() for skip in SKIP_TEXT_KEYWORDS)):
                        continue
                    full_url = BASE_URL + href if href.startswith("/") else href
                    links.add(full_url)
        
        # Also check all links as fallback
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            text = str(link.get_text(strip=True))
            if not href or not text or len(text) < 4:
                continue
            # Only include /project/slug/ links (relative or absolute)
            if PROJECT_URL_PATTERN.match(href) or PROJECT_URL_PATTERN_FULL.match(href):
                # Filter out navigation/utility links
                if (any(skip in href for skip in SKIP_URL_KEYWORDS) or
                    any(skip in text.lower() for skip in SKIP_TEXT_KEYWORDS)):
                    continue
                full_url = BASE_URL + href if href.startswith("/") else href
                links.add(full_url)
        
        return sorted(links)
    except Exception as e:
        logger.error(f"Error getting project links from {page_url}: {e}")
        return []

def get_all_project_links(headers):
    """Extract all /project/ links from homepage, current, and completed projects pages."""
    all_links = set()
    # From homepage
    all_links.update(get_project_links_from_page(BASE_URL, headers))
    # From current projects
    all_links.update(get_project_links_from_page(CURRENT_PROJECTS_URL, headers))
    # From completed projects
    all_links.update(get_project_links_from_page(COMPLETED_PROJECTS_URL, headers))
    return sorted(all_links)

def get_pdf_links(project_url, headers):
    """Extract PDF links from a project page."""
    try:
        response = requests.get(project_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        pdf_links = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            if href.lower().endswith(".pdf") or ".pdf" in href.lower():
                full_pdf_url = BASE_URL + href if href.startswith("/") else href
                pdf_links.add(full_pdf_url)
        return sorted(pdf_links)
    except Exception as e:
        logger.error(f"Error extracting PDFs from {project_url}: {e}")
        return []

def scrape_lawcom_publications():
    """Production-grade Law Commission scraper: extracts all project PDFs from the site."""
    try:
        container_client = setup_container("lawcom-scraped-text")
        container_client_links = setup_container("lawcom-translated-text-links")
        blobs_list = list(container_client.list_blobs())
        files = set(blob.name for blob in blobs_list)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        all_pdf_links = set()
        # Extract all project links from homepage, current, and completed projects
        logger.info("Extracting all project links from Law Commission site...")
        project_links = get_all_project_links(headers)
        logger.info(f"Found {len(project_links)} project links")
        for project_url in project_links:
            logger.debug(f"Processing project: {project_url}")
            pdfs = get_pdf_links(project_url, headers)
            all_pdf_links.update(pdfs)
            logger.debug(f"Found {len(pdfs)} PDFs in project")
        logger.info(f"Total unique PDF links found: {len(all_pdf_links)}")
        # Download and upload PDFs
        for file_url in all_pdf_links:
            filename = trim_filename(file_url.split("/")[-1])
            file_path = filename
            if filename in files:
                logger.debug(f"File already exists: {filename}")
                continue
            logger.info(f"Downloading: {filename} from {file_url}")
            try:
                file_response = requests.get(file_url, stream=True, headers=headers, timeout=60)
                file_response.raise_for_status()
                with open(file_path, "wb") as file:
                    for chunk in file_response.iter_content(chunk_size=8192):
                        file.write(chunk)
                logger.info(f"Successfully downloaded: {filename}")
                # Upload to Azure storage with better error handling
                blob_client_links = container_client_links.get_blob_client(trim_filename(file_url.split("/")[-1] + ".txt"))
                links_upload_success = upload_file_to_storage(blob_client_links, None, file_url)
                
                blob_client = container_client.get_blob_client(file_path)
                file_upload_success = upload_file_to_storage(blob_client, file_path)
                
                if links_upload_success and file_upload_success:
                    logger.info(f"Successfully uploaded: {filename}")
                else:
                    logger.error(f"Failed to upload one or more components for: {filename}")
            except Exception as e:
                logger.error(f"Download/upload failed for {filename}: {e}")
            finally:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except OSError:
                    pass
        logger.info("Law Commission scraping completed successfully")
    except Exception as e:
        logger.error(f"Error in scrape_lawcom_publications: {e}")
        raise

if __name__ == "__main__":
    scrape_lawcom_publications()
