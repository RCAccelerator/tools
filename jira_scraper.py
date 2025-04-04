#!/usr/bin/env python
# coding: utf-8

import uuid
from argparse import ArgumentParser
import json
import multiprocessing as mp

import requests
import pandas as pd
from tqdm import tqdm

from langchain.text_splitter import (
    RecursiveCharacterTextSplitter,
)
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings

from transformers import AutoTokenizer
from openai import APIConnectionError
from qdrant_client import QdrantClient, models


COLLECTION_NAME = "all-jira-tickets"
TOKENIZER_MODEL = "BAAI/bge-large-en-v1.5"

DEFAULT_EMBEDDING_MODEL_ID = "BAAI/bge-large-en-v1.5"

DEFAULT_JIRA_PROJECTS = [
    "OSPCIX",
    "OSPRH",
    "OSASINFRA",
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

def assemble_jira_query(jira_projects: list = DEFAULT_JIRA_PROJECTS) -> str:
    projects = " OR ".join([f"project={e}" for e in jira_projects])

    # Define the terms to search for in descriptions and comments
    search_terms = [
        "root cause",
        "RCA",
        "failure description",
        "impacted component",
        "resolved"
    ]

    # Create the description and comment search part
    desc_comment_search = " OR ".join([
        f'description ~ "{term}"' for term in search_terms
    ] + [
        f'comment ~ "{term}"' for term in search_terms
    ])

    pr_search = " OR ".join([
        'description ~ "github.com"',
        'description ~ "review.opendev.org"',
        'description ~ "gitlab.*com"', # for GitLab domains
        'comment ~ "github.com"',
        'comment ~ "review.opendev.org"',
        'comment ~ "gitlab.*com"',
        'description ~ "pull request"',
        'comment ~ "pull request"',
        'comment ~ "merged"'
    ])

    # Assemble the full query
    query = f"{projects} AND ({desc_comment_search})"
    query += f" AND ({pr_search})"

    # URL encode the query for API use
    query = requests.utils.quote(query)

    return query

def dbg_print(df: pd.DataFrame) -> None:
    if __debug__:
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', None)
        for index, row in df.iterrows():
            print(f"Row {index}:")
            for column, value in row.items():
                print(f"  {column}: {value}")
            print("-" * 50)


def insert_row(data: str, record_id: str, record_key: str, jira_url: str, field: str, dataset: pd.DataFrame):
    """Insert row into dataset, keep information about source field and URL."""
    row = {}
    row["id"] = record_id
    row["url"] = f"{jira_url}/browse/{record_key}"
    row["text"] = data
    row["kind"] = field
    dataset.append(row)


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
    if llm_server_url:
        model = OpenAIEmbeddings(
            model=embedding_model,
            base_url=llm_server_url,
            api_key=llm_api_key)
        try:
            model.embed_query("Hello world")
        except APIConnectionError as e:
            print(f"Connection error: {e} occured when calling model {embedding_model} at {llm_server_url}")
            exit(1)
    else:
        model = HuggingFaceEmbeddings(model_name=embedding_model)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {jira_token}",
    }
    results = []

    query = assemble_jira_query(jira_projects)

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

        # Summaries and descriptions
        for text_field in ["summary", "description"]:
            insert_row(
                raw_result["fields"][text_field],
                raw_result["id"],
                raw_result["key"],
                jira_url,
                text_field,
                dataset)
        # Inserting comments
        for comment in raw_result["fields"]["comment"]["comments"]:
            insert_row(
                comment["body"],
                raw_result["id"],
                raw_result["key"],
                jira_url,
                "comment",
                dataset)

    df = pd.DataFrame(dataset)

    # Remove duplicates
    df = df.drop_duplicates(subset=["id", "kind"])

    # Remove rows with missing values
    df = df.dropna()

    print(df.info())
    dbg_print(df)

    llm = OpenAI(
        base_url=llm_server_url,
        organization="",
        api_key=llm_api_key,
    )

    # Back up data
    df.to_pickle(jira_database_bkp_path)

    ## Upload data
    client = QdrantClient(database_client_url, api_key=database_api_key)

    tokenizer = AutoTokenizer.from_pretrained(embedding_model)

    splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
        tokenizer, chunk_size=chunk_size, chunk_overlap=20
    )

    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE),
        timeout=200
    )

    for _, row in tqdm(df.iterrows()):
        chunks = splitter.split_text(row["text"])
        for _, chunk in enumerate(chunks):
            embedding = model.embed_query(chunk)
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        payload={
                            "url": row["url"],
                            "text": row["text"],
                            "kind": row["kind"],
                            },
                        vector=embedding,
                    ),
                ],
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
