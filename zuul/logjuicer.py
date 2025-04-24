import requests
from bs4 import BeautifulSoup
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams
import json

import requests
import random

from bs4 import BeautifulSoup

import browser_cookie3 
import os



from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException



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


def scrape_logjuicer(url):
    driver.get(url)
       
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print("Basic page loaded")
        
        driver.save_screenshot("page_loaded.png")
        
        time.sleep(60)  # for colored content to load
        
        driver.save_screenshot("after_wait.png")
        
        # extract elements with their styling
        colored_elements = driver.execute_script("""
            function getElementsWithColor() {
                const result = [];
                const allElements = document.querySelectorAll('*');
                
                for (let elem of allElements) {
                    if (elem.textContent && elem.textContent.trim()) {
                        const style = window.getComputedStyle(elem);
                        const color = style.color;
                        
                        // Skip black text and gray text
                        if (color && 
                            !color.match(/rgba?\(0,\s*0,\s*0/) && 
                            !color.match(/rgba?\(107,\s*114,\s*128/)) { 
                            result.push({
                                text: elem.textContent.trim(),
                                color: color
                            });
                        }
                    }
                }
                return result;
            }
            return getElementsWithColor();
        """)
        
        print(f"Found {len(colored_elements)} colored text elements")
        
        # debugging
        with open("colored_elements.txt", "w", encoding="utf-8") as f:
            for item in colored_elements:
                f.write(f"Color: {item['color']} - Text: {item['text']}\n")
        
        data = []
        current_color = None
        
        for item in colored_elements:
            if item['color'] != current_color:
                # New color encountered
                if current_color is not None:  # Not the first color
                    data.append("------------------------------------- separator line")
                current_color = item['color']
                data.append(f"Color: {current_color}")
            
            # Add the text with this color
            data.append(item['text'])

        # another dbg
        with open('your_file.txt', 'w') as f:  
            for line in data:
                f.write(f"{line}\n")
        
        print(f"Processed into {len(data)} lines with color separation")

        return data
    except Exception:
        print (Exception)
   

def insert_data_to_qdrant(collection_name, data):
    """Insert data into Qdrant vector database using the VectorStoreManager."""
    # Get API key from environment variable
    api_key = os.environ.get("QDRANT__SERVICE__API_KEY")
    if not api_key:
        print("Warning: QDRANT__SERVICE__API_KEY not set. Connection may fail.")
    
    # Create vector store manager instance
    vector_store = QdrantVectorStoreManager(
        client_url="http://127.0.0.1:6333",  # Use HTTP protocol for local connection
        api_key=api_key
    )
    
    # Check if collection exists, if not create it
    vector_size = 768  # Size of your embedding vectors
    if not vector_store.check_collection(collection_name):
        print(f"Collection not found, creating collection: {collection_name}")
        vector_store.recreate_collection(collection_name, vector_size)
    
    # Prepare points
    points = []
    for i, item in enumerate(data):
        # Create a random vector (in real scenario, this would be your embedding)
        vector = [random.uniform(-1.0, 1.0) for _ in range(vector_size)]
        
        # Build the record using the manager's method
        # Use integer i directly instead of converting to string
        point = vector_store.build_record(
            record_id=i,  # Use integer directly
            payload={"text": item},
            vector=vector
        )
        points.append(point)
    
    # Insert data in batches to avoid timeouts
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        vector_store.upsert_data(collection_name, batch)
    
    print(f"Successfully inserted {len(points)} records into {collection_name}")

def main():
    #url = 'https://sf.apps.int.gpc.ocp-hub.prod.psi.redhat.com/logjuicer/report/33'
    url = 'https://sf.apps.int.gpc.ocp-hub.prod.psi.redhat.com/logjuicer/report/42'
    collection_name = 'logs_collection'

    data = scrape_logjuicer(url) # this part is just for debugging

    insert_data_to_qdrant(collection_name, data)
    print(f"Data from {url} has been inserted into Qdrant collection '{collection_name}'.")

# Setup Chrome options
chrome_options = Options()
chrome_options.add_argument("user-data-dir=~/.config/google-chrome/")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(options=chrome_options)

if __name__ == "__main__":
    main()

print("Closing browser")
driver.quit()