import json
import logging
import boto3
import csv
import io
import os
import sys
import traceback
import time
from urllib.parse import unquote_plus

# Configure more detailed logging
logger = logging.getLogger()

# Set log level based on environment variable
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
if log_level == 'DEBUG':
    logger.setLevel(logging.DEBUG)
elif log_level == 'INFO':
    logger.setLevel(logging.INFO)
elif log_level == 'WARNING':
    logger.setLevel(logging.WARNING)
elif log_level == 'ERROR':
    logger.setLevel(logging.ERROR)
else:
    logger.setLevel(logging.INFO)

# Add a custom formatter with more details
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s | %(funcName)s:%(lineno)d')
handler.setFormatter(formatter)
logger.handlers = [handler]  # Replace default handlers

# Check if debug mode is enabled
DEBUG_MODE = os.environ.get('DEBUG_MODE', 'false').lower() == 'true'
if DEBUG_MODE:
    logger.info("DEBUG MODE ENABLED - Detailed diagnostic information will be logged")


def is_csv_file(filename):
    """
    Check if the given filename has a .csv extension

    Args:
        filename: The name of the file to check

    Returns:
        bool: True if the file has a .csv extension, False otherwise
    """
    return filename.lower().endswith('.csv')


def process_csv(content, filename):
    """
    Process CSV content and return the parsed data

    Args:
        content: The CSV content as a string
        filename: The original filename (for logging)

    Returns:
        list: The parsed CSV rows as dictionaries
    """
    # Try to handle various CSV formats (different delimiters, etc.)
    csv_dialects = [',', ';', '\t']  # Common delimiters to try
    rows = []

    # First try with csv.Sniffer to auto-detect the CSV format
    try:
        dialect = csv.Sniffer().sniff(content[:1024])  # Sample first 1KB to detect format
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        rows = list(reader)
        if rows:
            logger.info(f"Successfully detected CSV format for {filename} using sniffer")
            return rows
    except Exception as e:
        logger.warning(f"Could not auto-detect CSV format: {str(e)}. Trying standard dialects.")

    # If sniffer failed, try common delimiters
    for delimiter in csv_dialects:
        try:
            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            test_rows = list(reader)

            # If we got valid rows with column names, use this delimiter
            if test_rows and all(len(row) > 1 for row in test_rows[:5]):
                logger.info(f"Successfully parsed CSV with delimiter '{delimiter}'")
                return test_rows
        except Exception as e:
            logger.debug(f"Failed parsing with delimiter '{delimiter}': {str(e)}")

    # If all else fails, try the default CSV parser
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        logger.warning(f"CSV parsing produced no data rows for {filename}")

    return rows


def validate_event(event):
    """
    Validate that the event contains the necessary S3 information

    Args:
        event: The Lambda event object

    Returns:
        tuple: (is_valid, bucket_name, object_key)
    """
    # Check basic event structure
    if not event or 'Records' not in event or not event['Records']:
        logger.error("Event does not contain Records array")
        return False, None, None

    # Get the first record (we only process one file at a time)
    record = event['Records'][0]

    # Check if this is an S3 event
    if 's3' not in record or 'bucket' not in record['s3'] or 'object' not in record['s3']:
        logger.error("Event is not an S3 event or has incorrect structure")
        return False, None, None

    # Extract bucket and key
    try:
        bucket = record['s3']['bucket']['name']
        # URL decode the key (S3 keys may be URL encoded in events)
        key = unquote_plus(record['s3']['object']['key'])

        if not bucket or not key:
            logger.error("Bucket name or object key is empty")
            return False, None, None

        return True, bucket, key
    except Exception as e:
        logger.error(f"Error extracting bucket and key: {str(e)}")
        return False, None, None


def handler(event, context):
    """
    Lambda function that gets triggered by S3 events.
    Reads CSV files uploaded to the bucket and logs their contents.

    Args:
        event: The event dict containing info about the S3 event
        context: Lambda context object

    Returns:
        dict: Response with processing status
    """
    # Start execution timer for performance tracking
    start_time = time.time()

    # Generate a unique execution ID to correlate logs
    import uuid
    execution_id = str(uuid.uuid4())[:8]

    logger.info(f"[{execution_id}] LAMBDA INVOCATION STARTED")
    logger.info(f"[{execution_id}] Received S3 event: {json.dumps(event)}")

    # Log Lambda context information if available
    if context:
        logger.info(
            f"[{execution_id}] Lambda context: function_name={context.function_name}, aws_request_id={context.aws_request_id}, remaining_time_ms={context.get_remaining_time_in_millis()}")

    # Log environment variables (filtering out sensitive info)
    env_vars = {k: v for k, v in os.environ.items() if
                not any(sensitive in k.lower() for sensitive in ['key', 'secret', 'password', 'token'])}
    logger.info(f"[{execution_id}] Environment variables: {json.dumps(env_vars)}")

    # Log available memory
    mem_info = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if 'MemTotal' in line or 'MemAvailable' in line:
                    key, value = line.split(':')
                    mem_info[key.strip()] = value.strip()
        logger.info(f"[{execution_id}] Memory info: {json.dumps(mem_info)}")
    except:
        logger.info(f"[{execution_id}] Memory info not available")

    try:
        logger.info(f"[{execution_id}] STEP 1: Validating event structure")
        # Validate the event and extract bucket/key
        is_valid, bucket, key = validate_event(event)

        if not is_valid:
            logger.error(f"[{execution_id}] Event validation failed - invalid S3 event structure")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'message': 'Invalid S3 event structure',
                    'processingStatus': 'error',
                    'executionId': execution_id
                })
            }

        logger.info(f"[{execution_id}] Event validation successful - bucket={bucket}, key={key}")

        # Skip non-CSV files
        if not is_csv_file(key):
            logger.info(f"[{execution_id}] Skipping non-CSV file: {key}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Skipped non-CSV file: {key}',
                    'processingStatus': 'skipped',
                    'executionId': execution_id
                })
            }

        logger.info(f"[{execution_id}] STEP 2: Setting up S3 client")
        # Initialize S3 client
        # Check if running locally
        s3_client_args = {}

        # Only set endpoint_url if running locally
        if os.environ.get('IS_LOCAL', '').lower() == 'true':
            aws_endpoint = os.environ.get('AWS_ENDPOINT')
            if aws_endpoint:
                logger.info(f"[{execution_id}] Running in local mode with endpoint: {aws_endpoint}")
                s3_client_args['endpoint_url'] = aws_endpoint

        # Set region name if provided
        aws_region = os.environ.get('AWS_REGION')
        if aws_region:
            s3_client_args['region_name'] = aws_region
            logger.info(f"[{execution_id}] Using AWS region: {aws_region}")

        # Log S3 client configuration
        logger.info(f"[{execution_id}] S3 client configuration: {json.dumps(s3_client_args)}")

        # Create S3 client - boto3 will use the Lambda execution role credentials in AWS
        # or environment variables when running locally
        try:
            s3 = boto3.client('s3', **s3_client_args)
            logger.info(f"[{execution_id}] S3 client created successfully")
        except Exception as e:
            logger.error(f"[{execution_id}] Error creating S3 client: {str(e)}")
            raise

        logger.info(f"[{execution_id}] STEP 3: Retrieving object from S3 bucket={bucket}, key={key}")
        # Add retry logic for S3 get_object
        max_retries = 3
        retry_count = 0
        last_exception = None
        content = None

        while retry_count < max_retries:
            try:
                # Get the object from S3
                logger.info(f"[{execution_id}] Attempt {retry_count + 1}/{max_retries} to get object from S3")
                get_object_start = time.time()
                response = s3.get_object(Bucket=bucket, Key=key)
                get_object_duration = time.time() - get_object_start

                # Log response metadata
                metadata = {k: str(v) for k, v in response['ResponseMetadata'].items()}
                logger.info(f"[{execution_id}] S3 get_object response metadata: {json.dumps(metadata)}")
                logger.info(f"[{execution_id}] S3 get_object duration: {get_object_duration:.2f}s")

                # Read and decode content
                read_start = time.time()
                raw_content = response['Body'].read()
                content = raw_content.decode('utf-8')
                read_duration = time.time() - read_start

                logger.info(
                    f"[{execution_id}] Content read and decoded: {len(raw_content)} bytes, decode duration: {read_duration:.2f}s")
                # Log small sample of the content for debugging
                content_preview = content[:200] + ('...' if len(content) > 200 else '')
                logger.info(f"[{execution_id}] Content preview: {content_preview}")
                break
            except Exception as e:
                last_exception = e
                retry_count += 1
                logger.warning(f"[{execution_id}] Retry {retry_count}/{max_retries} getting object from S3: {str(e)}")
                if retry_count >= max_retries:
                    logger.error(f"[{execution_id}] All retries failed to get object from S3")
                    raise Exception(f"Failed to get object after {max_retries} retries: {str(e)}")
                # Add exponential backoff
                backoff_time = 2 ** retry_count * 0.1  # 0.2s, 0.4s, 0.8s
                logger.info(f"[{execution_id}] Backing off for {backoff_time:.2f}s before retry")
                time.sleep(backoff_time)

        if not content:
            logger.error(f"[{execution_id}] Failed to retrieve content from S3 (content is None or empty)")
            raise Exception("Failed to retrieve content from S3")

        logger.info(f"[{execution_id}] STEP 4: Processing CSV data")
        # Process the CSV file
        process_start = time.time()
        rows = process_csv(content, key)
        process_duration = time.time() - process_start
        logger.info(f"[{execution_id}] CSV processing duration: {process_duration:.2f}s")

        # Calculate basic statistics
        stats = {
            'total_rows': len(rows),
            'columns': list(rows[0].keys()) if rows else [],
            'column_count': len(rows[0].keys()) if rows else 0,
        }

        # Log the parsed data (limit to first 10 rows to avoid log flooding)
        logger.info(f"[{execution_id}] Successfully processed {stats['total_rows']} rows from {key}")
        logger.info(f"[{execution_id}] CSV columns: {stats['columns']}")

        display_limit = min(10, stats['total_rows'])
        logger.info(f"[{execution_id}] Showing first {display_limit} rows:")

        for i, row in enumerate(rows[:display_limit]):
            logger.info(f"[{execution_id}] Row {i + 1}: {json.dumps(row)}")

        if stats['total_rows'] > display_limit:
            logger.info(f"[{execution_id}] ... and {stats['total_rows'] - display_limit} more rows")

        # Calculate total execution time
        total_duration = time.time() - start_time
        logger.info(f"[{execution_id}] LAMBDA EXECUTION COMPLETED SUCCESSFULLY - Total duration: {total_duration:.2f}s")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Successfully processed {stats["total_rows"]} rows from {key}',
                'stats': stats,
                'processingStatus': 'success',
                'executionId': execution_id,
                'executionTimeSeconds': round(total_duration, 2)
            })
        }

    except Exception as e:
        # Calculate execution time for failed execution
        error_duration = time.time() - start_time

        # Log the full stack trace for better debugging
        logger.error(f"[{execution_id}] ERROR PROCESSING S3 EVENT: {str(e)}")
        logger.error(f"[{execution_id}] Stack trace: {traceback.format_exc()}")
        logger.error(f"[{execution_id}] LAMBDA EXECUTION FAILED - Total duration: {error_duration:.2f}s")

        # Get Python version and library versions for troubleshooting
        try:
            import platform
            import pip

            python_info = {
                "python_version": platform.python_version(),
                "system": platform.system(),
                "boto3_version": boto3.__version__
            }
            logger.error(f"[{execution_id}] System info: {json.dumps(python_info)}")
        except:
            pass

        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': f'Error processing file: {str(e)}',
                'processingStatus': 'error',
                'executionId': execution_id,
                'executionTimeSeconds': round(error_duration, 2)
            })
        }