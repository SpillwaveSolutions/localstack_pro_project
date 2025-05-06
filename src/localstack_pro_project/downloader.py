
import os
import csv
import io
import logging
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.cloud_setup import get_s3_client, is_local_env

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

def download_and_display_csv(output_path=None):
    """Download a CSV file from LocalStack S3 bucket and display its contents"""
    s3 = get_s3_client()
    bucket = os.getenv('S3_BUCKET_NAME')
    key = os.getenv('S3_DEFAULT_KEY')

    try:
        # Download the object
        logger.info(f"Downloading s3://{bucket}/{key}")
        response = s3.get_object(Bucket=bucket, Key=key)

        # Read the content
        content = response['Body'].read().decode('utf-8')

        # Save to file if output path is provided
        if output_path:
            with open(output_path, 'w') as f:
                f.write(content)
            logger.info(f"Saved to {output_path}")

        # Display content as a table
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        # Print headers
        if rows:
            headers = rows[0].keys()
            header_row = ' | '.join(headers)
            separator = '-' * len(header_row)
            print(header_row)
            print(separator)

            # Print rows
            for row in rows:
                print(' | '.join(str(row[h]) for h in headers))

        logger.info(f"Total: {len(rows)} todo items")
        return rows

    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return None

def main():
    """Main function to run the downloader"""
    logger.info("Starting CSV download process...")
    rows = download_and_display_csv()
    if rows:
        logger.info("CSV file downloaded and displayed successfully.")
    else:
        logger.error("Failed to download and display CSV file.")

if __name__ == "__main__":
    main()

