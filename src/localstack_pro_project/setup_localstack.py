import os
import logging
from pathlib import Path
import boto3
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

def get_s3_client():
    """Create and return a LocalStack S3 client using environment variables"""
    return boto3.client(
        's3',
        endpoint_url=os.getenv('LOCALSTACK_ENDPOINT'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION')
    )

def setup_bucket():
    """Create S3 bucket if it doesn't exist"""
    s3 = get_s3_client()
    bucket_name = os.getenv('S3_BUCKET_NAME')

    try:
        # Check if bucket exists
        s3.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' already exists")
    except Exception as e:
        logger.info(f"Creating bucket '{bucket_name}'")
        s3.create_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' created successfully")

    return bucket_name

def main():
    """Run the LocalStack setup process"""
    logger.info("Setting up LocalStack environment...")
    bucket_name = setup_bucket()
    logger.info(f"LocalStack setup complete. Bucket '{bucket_name}' is ready.")

if __name__ == "__main__":
    main()
