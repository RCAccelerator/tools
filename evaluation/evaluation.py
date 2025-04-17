import asyncio
import argparse
import pandas as pd
import numpy as np
import httpx

from tqdm import tqdm
from openai import AsyncOpenAI


async def call_chatbot_api(client: httpx.AsyncClient,
                           url: str,
                           prompt: str,
                           similarity_threshold: float,
                           temperature: float,
                           timeout: int):
    payload = {
        "content": prompt,
        "similarity_threshold": similarity_threshold,
        "temperature": temperature,
    }

    try:
        response = await client.post(url,
                                     json=payload,
                                     timeout=timeout)
        return response.json()
    except httpx.HTTPError as e:
        print(f"Request failed: {e}")
        return None


def hit_at_k(pred_urls: list, true_url: str, k: int) -> int:
    """
    Returns 1 if the ground truth URL is in the top K predicted URLs, else 0.
    """
    top_k = pred_urls[:k]
    return int(true_url in top_k)


async def calculate_cosine_similarity(llm: AsyncOpenAI,
                                      model_name: str,
                                      text1: str,
                                      text2: str) -> float:

    emb1 = await llm.embeddings.create(
        model=model_name,
        input=text1)
    emb1 = emb1.data[0].embedding

    emb2 = await llm.embeddings.create(
        model=model_name,
        input=text2)
    emb2 = emb2.data[0].embedding

    vec1 = np.array(emb1)
    vec2 = np.array(emb2)

    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    else:
        score = np.dot(vec1, vec2) / (norm1 * norm2)
        return float(score)


async def process_row(client: httpx.AsyncClient,
                      llm: AsyncOpenAI,
                      idx: int,
                      row: pd.Series,
                      args: argparse.Namespace,
                      model_name: str) -> dict:
    # Call the API
    out = await call_chatbot_api(client,
                                 args.chatbot_api_url,
                                 row['user_prompt'],
                                 args.similarity_threshold,
                                 temperature=args.temperatur,
                                 timeout=args.chatbot_api_timeout)

    result = {
        "idx": idx,
        "response": None,
        "similarity_score": None,
        "hit_at_k": None
        }

    if out:
        result["response"] = out['response']

        if args.semantic_similarity and 'ground_truth' in row and row['ground_truth']:
            similarity = await calculate_cosine_similarity(
                llm,
                model_name,
                out['response'],
                row['ground_truth']
            )
            result["similarity_score"] = similarity

        if args.retrieval_metric and 'url' in row and row['url']:
            if 'urls' in out:
                accuracy = hit_at_k(out['urls'], row['url'], k=args.num_k)
                result["hit_at_k"] = accuracy

    return result


async def main_async():
    parser = argparse.ArgumentParser(
        description="Run the Chatbot evaluation")

    parser.add_argument(
        '-i', '--input',
        type=str,
        required=True,
        help="Path to the evaluation dataset"
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        required=True,
        help="Path to the output file"
    )

    parser.add_argument(
        "--similarity_threshold",
        type=float,
        required=True,
        help="Set the Chatbot search sensitivity"
    )

    parser.add_argument(
        "--chatbot_api_url",
        type=str,
        required=True,
        help="Chatbot API endpoint")

    parser.add_argument(
        "--llm_server_url",
        type=str,
        required=True,
        help="LLM API endpoint URL")

    parser.add_argument(
        "--llm_api_key",
        type=str,
        required=True,
        help="LLM API key")

    parser.add_argument(
        '-k', '--num_k',
        type=int,
        default=5,
        required=False,
        help="Sets the K for Hits@K metric"
    )

    parser.add_argument(
        '--semantic_similarity',
        action='store_true',
        required=False,
        default=False,
        help="Enable calculating the semantic similarity metric"
    )

    parser.add_argument(
        '--retrieval_metric',
        action='store_true',
        default=False,
        required=False,
        help="Enable calculating the retrieval Hit@K metric"
    )

    parser.add_argument(
        "--chatbot_api_timeout",
        type=int,
        default=30,
        required=False,
        help="Chatbot API timeout, sec")

    parser.add_argument(
        "--llm_model_name",
        type=str,
        required=False,
        help="Embeddings LLM model name")

    parser.add_argument(
        "--concurrency_limit",
        type=int,
        default=5,
        required=False,
        help="Maximum number of concurrent API calls"
    )

    parser.add_argument(
        "--temperatur" ,
        type=float,
        default=0,
        required=False,
        help="temperature value to be used by the model"
    )

    # Parse the arguments
    args = parser.parse_args()

    llm = AsyncOpenAI(
        base_url=args.llm_server_url,
        organization='',
        api_key=args.llm_api_key
    )

    avg_semantic_similarity = []
    avg_hit_at_k = []

    try:
        df = pd.read_csv(args.input)

        # Get model name
        models = await llm.models.list()
        if not args.llm_model_name:
            model_name = models.data[0].id
        else:
            model_name = args.llm_model_name

        num_test_records = df.shape[0]
        print(f"Number of records: {num_test_records}")
        print(f"Using concurrency limit: {args.concurrency_limit}")

        async with httpx.AsyncClient() as client:
            tasks = []
            for idx, row in df.iterrows():
                task = process_row(client, llm, idx, row, args, model_name)
                tasks.append(task)

            semaphore = asyncio.Semaphore(args.concurrency_limit)

            async def bounded_process_row(task):
                async with semaphore:
                    return await task

            bounded_tasks = [bounded_process_row(task) for task in tasks]

            results = []
            for f in tqdm(asyncio.as_completed(bounded_tasks),
                          total=len(bounded_tasks)):
                result = await f
                results.append(result)

        # Update dataframe with results
        for result in results:
            idx = result["idx"]
            if result["response"]:
                df.loc[idx, 'chatbot_response'] = result["response"]

            if result["similarity_score"]:
                df.loc[idx, 'similarity_score'] = result["similarity_score"]
                avg_semantic_similarity.append(result["similarity_score"])

            if result["hit_at_k"]:
                df.loc[idx, 'hit_at_k'] = result["hit_at_k"]
                avg_hit_at_k.append(result["hit_at_k"])

        if avg_semantic_similarity:
            avg_sim_score = sum(avg_semantic_similarity)/len(avg_semantic_similarity)
            print(f"Average semantic similarity score: {avg_sim_score}")

        if avg_hit_at_k:
            avg_hit_score = sum(avg_hit_at_k)/len(avg_hit_at_k)
            print(f"Average Hit @ {args.num_k} score: {avg_hit_score}")

    except Exception as e:
        # Catch any exception
        print(f"An unexpected error occurred: {e}")
    finally:
        # Save to output
        df.to_csv(args.output, index=False)
        print(f"The results have been saved to the file {args.output}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
