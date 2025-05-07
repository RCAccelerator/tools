"""Module for config constants."""

JIRA_COLLECTION_NAME = "rca-knowledge-base"
OSP_DOCS_COLLECTION_NAME = "rca-osp-docs-knowledge-base"
ERRATA_COLLECTION_NAME = "rca-errata"
ZULL_COLLECTION_NAME = "rca-ci"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_JIRA_URL = "https://issues.redhat.com"
DEFAULT_JIRA_PROJECTS = {
    "OSP",
    "OSPCIX",
    "OSPRH",
}
DEFAULT_CHUNK_SIZE = 1024
DEFAULT_MAX_RESULTS = 10000
DEFAULT_DATE_CUTOFF = "2000-01-01T00:00:00Z"
DEFAULT_NUM_SCRAPER_PROCESSES=10
DEFAULT_ERRATA_PUBLIC_URL="https://access.redhat.com/errata"
DEFAULT_ZULL_URL="sf.apps.int.gpc.ocp-hub.prod.psi.redhat.com/logjuicer"
DEFAULT_ZUUL_REPORTS = {
    42,
    45,
    47
}