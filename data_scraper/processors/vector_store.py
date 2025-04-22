
"""Vector DB Manager"""
import abc
from typing import List, Dict
from qdrant_client import QdrantClient, models


class VectorStoreManager(abc.ABC):
    """Abstract class defining `VectorStoreManager` interface."""

    @abc.abstractmethod
    def recreate_collection(self, collection_name: str, vector_size: int):
        """Recreate the collection with specified parameters."""

    @abc.abstractmethod
    def upsert_data(self, collection_name: str,
                    points: List[any]):
        """Upsert data into the collection."""

    @abc.abstractmethod
    def get_collection_stats(self, collection_name: str) -> Dict:
        """Get collection statistics."""

    @abc.abstractmethod
    def build_record(self, record_id: str,
                     payload: dict,
                     vector: any) -> any:
        """Build record with vector and payload."""


class QdrantVectorStoreManager(VectorStoreManager):
    """Manages interactions with Qdrant database."""

    def __init__(self, client_url: str, api_key: str, timeout=100):
        self.client = QdrantClient(client_url, api_key=api_key, timeout=timeout)

    def recreate_collection(self, collection_name: str, vector_size: int):
        """Recreate the collection with specified parameters."""
        if self.check_collection(collection_name):
            self.client.delete_collection(collection_name)

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM,
                )
            ),
        )

    def check_collection(self, collection_name) -> bool:
        """Test presence of collection."""
        return self.client.collection_exists(collection_name)

    def upsert_data(self, collection_name: str,
                    points: List[models.PointStruct]):
        """Upsert data into the collection."""
        self.client.upsert(
            collection_name=collection_name,
            points=points,
        )

    def get_collection_stats(self, collection_name: str) -> Dict:
        """Get collection statistics."""
        return self.client.get_collection(collection_name=collection_name)

    def build_record(self, record_id: str,
                     payload: dict,
                     vector: models.VectorStruct) -> models.PointStruct:
        """Build record with vector and payload."""
        return models.PointStruct(
                    id=record_id,
                    payload=payload,
                    vector=vector)
