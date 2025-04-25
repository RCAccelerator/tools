"""Main module for jira scraper."""
import logging
from datetime import datetime

from argparse import ArgumentParser
from jira_scraper.common import constants
from jira_scraper.core.scraper import JiraScraper

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def command():
    """Entry point for command line execution."""
    parser = ArgumentParser("jira_scraper")

    # Required arguments
    parser.add_argument("--jira_token", type=str, required=True)
    parser.add_argument("--database_client_url", type=str, required=True)
    parser.add_argument("--llm_server_url", type=str, required=True)
    parser.add_argument("--llm_api_key", type=str, required=True)
    parser.add_argument("--database_api_key", type=str, required=True)

    # Optional arguments
    parser.add_argument("--jira_url", type=str,
                        default=constants.DEFAULT_JIRA_URL)
    parser.add_argument("--max_results", type=int,
                        default=constants.DEFAULT_MAX_RESULTS)
    parser.add_argument("--chunk_size", type=int,
                        default=constants.DEFAULT_CHUNK_SIZE)
    parser.add_argument("--embedding_model", type=str,
                        default=constants.DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--jira_projects", nargs='+', type=str,
                        default=constants.DEFAULT_JIRA_PROJECTS)
    parser.add_argument("--db_collection_name", type=str,
                        default=constants.COLLECTION_NAME)
    parser.add_argument("--scraper-processes", type=int,
                        default=constants.DEFAULT_NUM_SCRAPER_PROCESSES)
    parser.add_argument("--date_cutoff", type=datetime.fromisoformat,
                        default=datetime.fromisoformat(constants.DEFAULT_DATE_CUTOFF),
                        help=(
                            "No issues from before this date will be used. "
                            "Date must follow ISO format 'YYYY-MM-DD'"
                        )
    )
    parser.add_argument("--recreate_collection", type=bool, default=False,
                        help="Recreate database collection from scratch.")
    args = parser.parse_args()

    config_args = {
        "jira_token": args.jira_token,
        "database_client_url": args.database_client_url,
        "llm_server_url": args.llm_server_url,
        "llm_api_key": args.llm_api_key,
        "database_api_key": args.database_api_key,
        "jira_url": args.jira_url,
        "max_results": args.max_results,
        "chunk_size": args.chunk_size,
        "embedding_model": args.embedding_model,
        "jira_projects": args.jira_projects,
        "db_collection_name": args.db_collection_name,
        "date_cutoff": args.date_cutoff,
        "scraper_processes": args.scraper_processes,
        "recreate_collection": args.recreate_collection,
    }

    scraper = JiraScraper(config_args)
    scraper.run()


if __name__ == "__main__":
    command()
