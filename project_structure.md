# localstack_pro_project

## ./

### pyproject.toml

```toml
[project]
name = "localstack-pro-project"
version = "0.1.0"
description = ""
authors = [
    {name = "Rick Hightower",email = "richardhightower@gmail.com"}
]
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "boto3 (>=1.34.0,<2.0.0)",
    "python-dotenv (>=1.0.0,<2.0.0)"
]


[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.0"
awscli-local = "^0.22.0"
moto = "^4.2.7"

[tool.poetry.scripts]
setup-localstack = "localstack_pro_project.setup_localstack:main"
upload-todo = "localstack_pro_project.uploader:main"
read-todo = "localstack_pro_project.downloader:main"

```

### localstack-data/

#### localstack-data/cache/

##### localstack-data/cache/certs/

###### localstack-data/cache/certs/ca/

#### localstack-data/logs/

#### localstack-data/lib/

#### localstack-data/tmp/

### data/

### src/

#### src/localstack_pro_project/

##### __init__.py

```python

```

##### downloader.py

```python

import os
import csv
import io
import logging
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.setup_localstack import get_s3_client

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


```

##### setup_localstack.py

```python
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

```

##### uploader.py

```python

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.setup_localstack import get_s3_client, setup_bucket

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


```

