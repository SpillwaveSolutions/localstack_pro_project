
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.cloud_setup import get_s3_client, setup_bucket, is_local_env

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

def upload_csv_to_s3(file_path=None):
    """Upload a CSV file to LocalStack S3 bucket"""
    # Get the file path from .env if not provided
    if file_path is None:
        file_path = os.getenv('CSV_FILE_PATH')

    # Ensure the file exists
    if not os.path.exists(file_path):
        logger.error(f"Error: File {file_path} does not exist!")
        return False

    # Get S3 client and ensure bucket exists
    s3 = get_s3_client()
    bucket_name = setup_bucket()
    key = os.getenv('S3_DEFAULT_KEY')

    # Upload file
    try:
        logger.info(f"Uploading {file_path} to s3://{bucket_name}/{key}")
        with open(file_path, 'rb') as f:
            s3.upload_fileobj(f, bucket_name, key)
        logger.info("Upload successful!")
        return True
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return False

def main():
    """Main function to run the uploader"""
    logger.info("Starting CSV upload process...")
    success = upload_csv_to_s3()
    if success:
        logger.info("CSV file uploaded successfully.")
    else:
        logger.error("Failed to upload CSV file.")

if __name__ == "__main__":
    main()

