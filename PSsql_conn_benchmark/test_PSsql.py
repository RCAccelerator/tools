import asyncpg
import asyncio
import time
from tqdm import tqdm
import sys

NUM_REQUESTS = 1000


DB_URI = "postgresql://uname:password@IP:5432/name"


async def test_connection():
    print("🔄 Testing database connection...")
    try:
        conn = await asyncpg.connect(DB_URI, timeout=10)
        print("✅ Connection to PostgreSQL successful")
        
        # Get version to verify connection works
        version = await conn.fetchval("SELECT version();")
        print(f"PostgreSQL Version: {version}")
        
        await conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")

async def benchmark_pgsql():
    try:
        conn = await asyncpg.connect(DB_URI)
        await conn.execute("DROP TABLE IF EXISTS perf_test;")
        await conn.execute("CREATE TABLE perf_test (id SERIAL PRIMARY KEY, data TEXT);")
        print("🔄 Inserting data...")
        
        # Calculate metrics for data writes
        total_bytes_written = 0
        total_operations_write = 0
        insert_times = []
        
        for i in tqdm(range(NUM_REQUESTS), desc="Inserting records"):
            data_value = f"test_data_{i}"
            data_size = sys.getsizeof(data_value)
            total_bytes_written += data_size
            
            start = time.perf_counter()
            await conn.execute("INSERT INTO perf_test (data) VALUES ($1);", data_value)
            insert_times.append(time.perf_counter() - start)
            total_operations_write += 1
        
        print("🔄 Fetching data...")
        # Calculate metrics for data reads
        total_bytes_read = 0
        total_operations_read = 0
        fetch_times = []
        
        for i in tqdm(range(NUM_REQUESTS), desc="Fetching records"):
            start = time.perf_counter()
            result = await conn.fetch("SELECT * FROM perf_test WHERE id = $1;", i + 1)
            fetch_times.append(time.perf_counter() - start)
            
            # Calculate size of fetched data
            for row in result:
                data_size = sys.getsizeof(row['data'])
                total_bytes_read += data_size
            
            total_operations_read += 1
        
        # Get table size from PostgreSQL
        table_size = await conn.fetchval("""
            SELECT pg_total_relation_size('perf_test') AS total_bytes;
        """)
        
        await conn.close()
        
        # Format byte measurements for better readability
        def format_bytes(size):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0 or unit == 'GB':
                    return f"{size:.2f} {unit}"
                size /= 1024.0
        
        print("\n📊 Performance Metrics:")
        print(f"Avg Insert Time: {sum(insert_times) / NUM_REQUESTS:.6f} sec")
        print(f"Avg Fetch Time: {sum(fetch_times) / NUM_REQUESTS:.6f} sec")
        print(f"Total Execution Time: {sum(insert_times) + sum(fetch_times):.6f} sec")
        
        print("\n📝 Write Operations:")
        print(f"Total Write Operations: {total_operations_write}")
        print(f"Total Bytes Written: {format_bytes(total_bytes_written)} (Python object size)")
        print(f"Bytes Written Per Operation: {format_bytes(total_bytes_written/total_operations_write)}")
        
        print("\n📝 Read Operations:")
        print(f"Total Read Operations: {total_operations_read}")
        print(f"Total Bytes Read: {format_bytes(total_bytes_read)} (Python object size)")
        print(f"Bytes Read Per Operation: {format_bytes(total_bytes_read/total_operations_read)}")
        
        print("\n📝 Database Storage:")
        print(f"Total Table Size in Database: {format_bytes(table_size)}")
        
    except Exception as e:
        print(f"❌ Benchmark failed: {e}")

async def main():
    await test_connection()
    
    await benchmark_pgsql()

if __name__ == "__main__":
    asyncio.run(main())