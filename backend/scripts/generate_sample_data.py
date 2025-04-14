import pandas as pd
import random
from faker import Faker
from pathlib import Path
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
NUM_CUSTOMERS = random.randint(50, 150)
NUM_PRODUCTS = random.randint(50, 100)
NUM_SALES = random.randint(100, 250) # Allow more sales than customers/products

OUTPUT_DIR = Path(__file__).parent.parent / "data"
SALES_CSV = OUTPUT_DIR / "sales.csv"
PRODUCTS_CSV = OUTPUT_DIR / "products.csv"
CUSTOMERS_CSV = OUTPUT_DIR / "customers.csv"

fake = Faker()
Faker.seed(0) # for reproducibility

def generate_customers(n):
    logger.info(f"Generating {n} customers...")
    data = []
    for i in range(1, n + 1):
        data.append({
            "customer_id": i,
            "name": fake.name(),
            "email": fake.unique.email(),
            "city": fake.city(),
            "created_at": fake.date_time_between(start_date="-2y", end_date="now", tzinfo=None) # Prisma likes datetime
        })
    return pd.DataFrame(data)

def generate_products(n):
    logger.info(f"Generating {n} products...")
    data = []
    categories = ["Electronics", "Clothing", "Home Goods", "Books", "Groceries", "Toys", "Sports"]
    for i in range(1, n + 1):
        data.append({
            "product_id": 100 + i, # Start product IDs from 101
            "name": fake.unique.catch_phrase().replace("'", ""), # Simple product names
            "category": random.choice(categories) if random.random() > 0.05 else None, # Add some null categories
            "unit_price": round(random.uniform(5.0, 500.0), 2),
            "added_date": fake.date_time_between(start_date="-1y", end_date="now", tzinfo=None)
        })
    # Ensure unique names might fail with high N, handle if necessary
    return pd.DataFrame(data)

def generate_sales(n, customer_ids, product_ids):
    logger.info(f"Generating {n} sales...")
    data = []
    for i in range(1, n + 1):
        sale_date = fake.date_time_between(start_date="-6m", end_date="now", tzinfo=None)
        data.append({
            "sale_id": 1000 + i, # Start sale IDs from 1001
            "customer_id": random.choice(customer_ids),
            "product_id": random.choice(product_ids),
            "amount": round(random.uniform(5.0, 1000.0), 2), # Sale amount different from unit price
            "sale_date": sale_date.isoformat(sep=' ', timespec='seconds') # Make date a string format LLM might see
        })
    return pd.DataFrame(data)

if __name__ == "__main__":
    logger.info("Starting sample data generation...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    customers_df = generate_customers(NUM_CUSTOMERS)
    products_df = generate_products(NUM_PRODUCTS)

    # Ensure IDs exist for referential integrity in sales
    valid_customer_ids = customers_df['customer_id'].tolist()
    valid_product_ids = products_df['product_id'].tolist()

    sales_df = generate_sales(NUM_SALES, valid_customer_ids, valid_product_ids)

    # Save to CSV
    try:
        customers_df.to_csv(CUSTOMERS_CSV, index=False)
        logger.info(f"Saved {len(customers_df)} customers to {CUSTOMERS_CSV}")

        products_df.to_csv(PRODUCTS_CSV, index=False)
        logger.info(f"Saved {len(products_df)} products to {PRODUCTS_CSV}")

        sales_df.to_csv(SALES_CSV, index=False)
        logger.info(f"Saved {len(sales_df)} sales to {SALES_CSV}")

        logger.info("Sample data generation complete.")
    except Exception as e:
        logger.error(f"Failed to save CSV files: {e}")
