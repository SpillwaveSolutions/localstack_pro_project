import json
import logging
import boto3
import csv
import io
import os
from urllib.parse import unquote_plus

logger = logging.getLogger()

log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
if log_level == 'DEBUG':
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


def is_csv_file(filename):
    """Check if file has .csv extension"""
    return filename.lower().endswith('.csv')


def process_csv(content):
    """Process CSV content and return parsed data"""
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


def handler(event, context):
    """Process CSV files from S3 events"""
    logger.info(f"Event: {json.dumps(event)}")

    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = unquote_plus(record['s3']['object']['key'])

        logger.info(f"Reading s3://{bucket}/{key}")

        if not is_csv_file(key):
            msg = f"Skipped non-CSV: {key}"
            return {
                'statusCode': 200,
                'body': json.dumps({'message': msg})
            }

        s3_args = {}
        if os.environ.get('IS_LOCAL', '').lower() == 'true':
            endpoint = os.environ.get('AWS_ENDPOINT')
            s3_args['endpoint_url'] = endpoint
            logger.debug(f"Local endpoint: {endpoint}")

        s3 = boto3.client('s3', **s3_args)
        response = s3.get_object(
            Bucket=bucket,
            Key=key
        )
        content = response['Body'].read().decode('utf-8')
        logger.debug(f"Content length: {len(content)}")

        rows = process_csv(content)

        stats = {
            'total_rows': len(rows),
            'columns': list(rows[0].keys()) if rows else []
        }

        logger.info(
            f"Processed {stats['total_rows']} rows with "
            f"columns: {stats['columns']}"
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': (
                    f"Processed {stats['total_rows']} "
                    f"rows from {key}"
                ),
                'stats': stats
            })
        }

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': f'Error: {str(e)}'
            })
        }