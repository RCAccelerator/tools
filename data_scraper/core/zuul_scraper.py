"""Code for scraping Zuul data"""
import logging
import multiprocessing as mp
from datetime import datetime
from typing import TypedDict, List, Dict, Any
import uuid

import pandas as pd
from tqdm import tqdm

from data_scraper.core.scraper import Scraper
from data_scraper.processors.zuul_provider import ZuulProvider


LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class ZuulRecord(TypedDict):
    """Represents a record extracted from Zuul by logjuicer.
      e.g report #42

    """
    zuul_server_name: str
    zuul_job_name: str
    zuul_build_id: str
    zuul_build_start_time: str
    zuul_build_end_time: str
    zuul_logjuicer_record: List[str]



class ZuulScraper(Scraper):
    """Main class for Zuul scraping and processing."""

    def __init__(self, config: dict):
        super().__init__(config=config)
        self.zuul_provider = ZuulProvider(
            query_url=self.config["zuul_url"], 
            verify_ssl=self.config.get("verify_ssl", False)
        )

    def run(self) -> List[Dict[str, Any]]:
        """Retrieve Zuul reports.
        
        Returns:
            List of processed Zuul reports
        """
        reports = []
        
        report_ids = [42, 45, 47]  # use commons here
        total_reports = len(report_ids)
        
        LOG.info("Starting to retrieve %d Zuul reports", total_reports)
        
        for report_id in report_ids:
            LOG.info("Processing report ID: %d", report_id)
            report_data = self.zuul_provider.get_report(report_id)
            
            if report_data:
                LOG.info("Successfully retrieved report %d with %d lines of text", 
                        report_id, len(report_data))
                
                # Create a document structure with the report data
                document = {
                    "id": f"zuul_report_{report_id}",
                    "source": f"{self.config['zuul_url']}/api/report/{report_id}",
                    "content": "\n".join(report_data),  # Join all lines for storage
                    "metadata": {
                        "report_id": report_id,
                        "lines_count": len(report_data),
                        "source_url": f"{self.config['zuul_url']}/api/report/{report_id}",
                        "timestamp": datetime.now().isoformat()
                    }
                }
                
                reports.append(document)
            else:
                LOG.error("Failed to retrieve report %d", report_id)
        
        LOG.info("Retrieved %d of %d Zuul reports", len(reports), total_reports)
        
        # Process the reports if any were retrieved
        if reports:
            self.process_reports(reports)
        
        return reports

    def process_reports(self, reports: List[Dict[str, Any]]) -> None:
        """Process the retrieved reports and store them in the database.
        
        Args:
            reports: List of report documents to process
        """
        LOG.info("Processing %d Zuul reports for storage", len(reports))
        
        # 1. Create chunks for each report
        # 2. Generate embeddings
        # 3. Store in database
        
        try:
            # Example processing logic (implement according to your actual needs)
            for report in reports:
                # Example: Split content into chunks
                content = report["content"]
                chunks = self.create_chunks(content)
                
                # Process and store each chunk
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{report['id']}_chunk_{i}"
                    
                    # Store the chunk in your database
                    # This is a placeholder - implement your actual storage logic
                    LOG.info("Storing chunk %s with %d characters", 
                            chunk_id, len(chunk))
                    
                    # Your database storage code here
                    
        except Exception as e:
            LOG.error("Error processing reports: %s", e)
            import traceback
            LOG.error(traceback.format_exc())

    def create_chunks(self, content: str, max_chunk_size: int = None) -> List[str]:
        """Split content into chunks of appropriate size.
        
        Args:
            content: Text content to split
            max_chunk_size: Maximum size for each chunk (defaults to config value)
            
        Returns:
            List of text chunks
        """
        if max_chunk_size is None:
            max_chunk_size = self.config.get("chunk_size", 1000)
            
        # Simple line-based chunking - adjust according to your needs
        lines = content.split("\n")
        chunks = []
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line)
            
            if current_size + line_size > max_chunk_size and current_chunk:
                # Current chunk is full, store it
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                # Add to current chunk
                current_chunk.append(line)
                current_size += line_size
        
        # Add the last chunk if it's not empty
        if current_chunk:
            chunks.append("\n".join(current_chunk))
        
        return chunks