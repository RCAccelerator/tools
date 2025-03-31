#!/usr/bin/env python
# coding: utf-8

from argparse import ArgumentParser
import json
import multiprocessing as mp

import requests
import pandas as pd
from tqdm import tqdm

from qdrant_client import QdrantClient

from llama_index.core import StorageContext, Document, VectorStoreIndex, Settings
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.node_parser import SentenceSplitter

COLLECTION_NAME = "all-jira-tickets"
TOKENIZER_MODEL = "BAAI/bge-large-en-v1.5"

DEFAULT_EMBEDDING_MODEL_ID = "BAAI/bge-large-en-v1.5"

DEFAULT_JIRA_PROJECTS = [
    "OSP",
    "RHOSINFRA",
    "OSPCIX",
    "RHOSBUGS",
    "OSPK8",
    "RHOSPRIO",
    "OSPRH",
]


def get_jira_data(
        jira_url: str, headers: dict, query: str, max_results: int, start_at: int):
    """Retrieve data from JIRA"""
    full_url = f"{jira_url}/rest/api/2/search?jql={query}&maxResults={max_results}&fields=*all&startAt={start_at}"
    print(f"Getting: {full_url}")
    try:
        response = requests.get(
            full_url,
            headers=headers,
            timeout=(3.05, 180),
        )

    except requests.exceptions.Timeout:
        print(f"Request to {jira_url} failed with time out.")
        return []

    if response.status_code == 200:
        data = json.loads(response.text)
    else:
        print(f"Couldn't retrieve data from JIRA {response.status_code} for {full_url}")
        return []

    return data["issues"]


def update_database(
    database_client_url: str,
    llm_server_url: str,
    llm_api_key: str,
    jira_token: str,
    embedding_model: str,
    database_api_key: str,
    max_results: int = 10000,
    jira_url: str = "https://issues.redhat.com",
    chunk_size: int = 1024,
    jira_database_bkp_path: str = "jira_all_bugs.pickle",
    jira_projects: list = DEFAULT_JIRA_PROJECTS,
):

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {jira_token}",
    }
    results = []

    projects = " OR ".join([f"project={e}" for e in jira_projects])
    query = f"{projects} AND type=bug AND status=Closed"
    query = requests.utils.quote(query)
    # Get initial batch of data
    try:
        response = requests.get(
            f"{jira_url}/rest/api/2/search?jql={query}&maxResults={max_results}&fields=*all",
            headers=headers,
            timeout=(3.05, 180),
            )
    except requests.exceptions.Timeout as e:
        print(f"Request to {jira_url} failed with time out.")
        raise e

    if response.status_code == 200:
        data = json.loads(response.text)
    else:
        print(f"Couldn't retrieve any data from JIRA {response.status_code}")
        raise ValueError

    total = data["total"]
    print(f"{total} items found for query {query}")

    # Retrieve results going further back
    with mp.Pool(10) as pool:
        results = pool.starmap(
            get_jira_data,
            [(jira_url, headers, query, max_results, page) for page in range(1000, total, 1000)])

    results.append(data["issues"])

    # Flatten the list of issues
    results = [issue for e in results for issue in e]

    dataset = []

    for raw_result in tqdm(results):
        row = {}
        row["id"] = raw_result["id"]
        row["url"] = f"{jira_url}/browse/{raw_result['key']}"
        row["summary"] = raw_result["fields"]["summary"]
        row["description"] = raw_result["fields"]["description"]
        row["comments"] = "\n".join(
            [comment["body"] for comment in raw_result["fields"]["comment"]["comments"]])
        dataset.append(row)

    df = pd.DataFrame(dataset)
    df["text"] = df.summary + "\n" + df.description.fillna(" ") + df.comments

    # Remove duplicates
    df = df.drop_duplicates(subset=["id"])

    print(df.info())

    # Back up data
    df.to_pickle(jira_database_bkp_path)

    # Set up client
    client = QdrantClient(database_client_url, api_key=database_api_key)

    # Settings for llama-index
    Settings.text_splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=20)

    Settings.embed_model = OpenAIEmbedding(
        model=embedding_model,
        api_key=llm_api_key,
        api_base=llm_server_url)

    # Create vector store tied to collection and storage context
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Create base documents with their metadata
    documents = [
        Document(text=row["text"], metadata={"url": row["url"]}) for _, row in df.iterrows()]

    # Build index
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
    )

    print(
        f"Number of records: {client.get_collection(collection_name=COLLECTION_NAME).points_count}"
    )


def main():
    parser = ArgumentParser("jira_scraper")
    parser.add_argument("--jira_url", type=str, default="https://issues.redhat.com")
    parser.add_argument("--jira_token", type=str)
    parser.add_argument("--max_results", type=int, default=10000)
    parser.add_argument("--chunk_size", type=int, default=1024)
    parser.add_argument("--database_client_url", type=str, default="")
    parser.add_argument("--database_api_key", type=str, default="")
    parser.add_argument("--llm_server_url", type=str, default="")
    parser.add_argument("--llm_api_key", type=str, default="")
    parser.add_argument("--embedding_model", type=str, default=DEFAULT_EMBEDDING_MODEL_ID)
    parser.add_argument("--jira_projects", nargs='+', type=str, default=DEFAULT_JIRA_PROJECTS)
    args = parser.parse_args()

    update_database(
        llm_server_url=args.llm_server_url,
        llm_api_key=args.llm_api_key,
        jira_token=args.jira_token,
        embedding_model=args.embedding_model,
        max_results=args.max_results,
        jira_url=args.jira_url,
        chunk_size=args.chunk_size,
        database_client_url=args.database_client_url,
        jira_projects=args.jira_projects,
        database_api_key=args.database_api_key,
    )


if __name__ == "__main__":
    main()
