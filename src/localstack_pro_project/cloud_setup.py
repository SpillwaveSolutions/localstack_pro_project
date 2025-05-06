import os
import json
import logging
from pathlib import Path
import boto3
import botocore.exceptions
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

print(f"Using AWS credentials - Access Key ID: {os.environ.get('AWS_ACCESS_KEY_ID', 'None')[:4]}... Session token: {'Present' if os.environ.get('AWS_SESSION_TOKEN') else 'None'}")

def is_local_env():
    """Check if we're targeting LocalStack or AWS"""
    return os.getenv('DEPLOYMENT_ENV', 'LOCAL').upper() == 'LOCAL'


def get_endpoint_url():
    """Get the appropriate endpoint URL based on environment"""
    if is_local_env():
        return os.getenv('LOCALSTACK_ENDPOINT')
    return None  # AWS uses default endpoint


def get_client_kwargs():
    """Get common client keyword arguments based on environment"""
    # Check if in LocalStack mode
    if is_local_env():
        kwargs = {
            'region_name': os.getenv('AWS_REGION', 'us-east-1'),
            'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID', 'test'),
            'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
        }

        # Add endpoint URL for LocalStack
        endpoint_url = get_endpoint_url()
        if endpoint_url:
            kwargs['endpoint_url'] = endpoint_url
    else:
        # For AWS, use the environment variables directly
        # (which we know work from the debug script)
        kwargs = {
            'region_name': os.getenv('AWS_REGION', 'us-east-1')
        }

        # Only add credentials if they're all provided in the environment
        if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
            kwargs['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
            kwargs['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')

            # Add session token if available
            if os.getenv('AWS_SESSION_TOKEN'):
                kwargs['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')

    return kwargs


def get_lambda_client():
    """Create and return a Lambda client using environment variables"""
    return boto3.client('lambda', **get_client_kwargs())


def get_s3_client():
    """Create and return an S3 client using environment variables"""
    return boto3.client('s3', **get_client_kwargs())


def get_iam_client():
    """Create and return an IAM client using environment variables"""
    return boto3.client('iam', **get_client_kwargs())


def get_logs_client():
    """Create and return a CloudWatch Logs client using environment variables"""
    return boto3.client('logs', **get_client_kwargs())


def get_role_arn():
    """Get the appropriate IAM role ARN based on environment"""
    if is_local_env():
        # LocalStack accepts any role ARN
        return 'arn:aws:iam::000000000000:role/lambda-role'
    else:
        # Real AWS uses the configured role
        role_arn = os.getenv('AWS_ROLE_ARN')
        if not role_arn:
            account_id = os.getenv('AWS_ACCOUNT_ID')
            if not account_id:
                logger.warning("AWS_ACCOUNT_ID not set, using placeholder")
                account_id = '123456789012'
            role_name = "lambda-s3-processor-role"
            role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
            logger.warning(f"AWS_ROLE_ARN not set, using constructed ARN: {role_arn}")
        return role_arn


def ensure_role_exists():
    """Ensure the IAM role exists in AWS (no-op for LocalStack)"""
    if is_local_env():
        logger.info("Skipping IAM role creation in LocalStack")
        return get_role_arn()

    # For AWS, check if role exists and create if needed
    role_arn = os.getenv('AWS_ROLE_ARN')
    if not role_arn:
        # Handle missing role ARN
        account_id = os.getenv('AWS_ACCOUNT_ID')
        if not account_id:
            logger.error("AWS_ACCOUNT_ID environment variable is not set")
            logger.error("Please set AWS_ACCOUNT_ID in your .env file")
            return None

        # Create a default role name
        role_name = "lambda-s3-processor-role"
        logger.warning(f"AWS_ROLE_ARN not set. Will create role: {role_name}")
    else:
        # Extract role name from ARN
        role_name = role_arn.split('/')[-1]

    iam = get_iam_client()

    try:
        # Check if role exists
        response = iam.get_role(RoleName=role_name)
        logger.info(f"IAM role '{role_name}' already exists")
        role_arn = response['Role']['Arn']
        # Update environment variable
        os.environ['AWS_ROLE_ARN'] = role_arn
        return role_arn
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            logger.info(f"Creating IAM role '{role_name}'")

            # Trust policy for Lambda
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }

            # Create the role
            try:
                response = iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="Role for Lambda S3 processor function"
                )

                # Attach policies
                iam.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                )

                iam.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn="arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
                )

                logger.info(f"IAM role '{role_name}' created successfully")
                role_arn = response['Role']['Arn']
                # Update environment variable
                os.environ['AWS_ROLE_ARN'] = role_arn
                return role_arn
            except Exception as e:
                logger.error(f"Failed to create IAM role: {str(e)}")
                return None
        else:
            logger.error(f"Error checking IAM role: {str(e)}")
            return None


def setup_bucket():
    """Create S3 bucket if it doesn't exist"""
    try:
        s3 = get_s3_client()
        bucket_name = os.getenv('S3_BUCKET_NAME')

        if not bucket_name:
            logger.error("S3_BUCKET_NAME environment variable is not set")
            logger.error("Please set S3_BUCKET_NAME in your .env file")
            return None

        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' already exists")
        except botocore.exceptions.ClientError as e:
            # If we're in AWS and the bucket is owned by someone else, we need to use a different name
            if not is_local_env() and e.response['Error']['Code'] == '403':
                logger.error(f"Bucket '{bucket_name}' exists but is owned by another account")
                account_id = os.getenv('AWS_ACCOUNT_ID')
                bucket_name = f"{bucket_name}-{account_id}"
                logger.info(f"Trying with account-specific bucket name: '{bucket_name}'")

                try:
                    s3.head_bucket(Bucket=bucket_name)
                    logger.info(f"Account-specific bucket '{bucket_name}' already exists")
                except botocore.exceptions.ClientError:
                    logger.info(f"Creating account-specific bucket '{bucket_name}'")
                    if os.getenv('AWS_REGION') == 'us-east-1':
                        s3.create_bucket(Bucket=bucket_name)
                    else:
                        s3.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={
                                'LocationConstraint': os.getenv('AWS_REGION')
                            }
                        )
            else:
                # Create the bucket
                logger.info(f"Creating bucket '{bucket_name}'")
                if not is_local_env() and os.getenv('AWS_REGION') != 'us-east-1':
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={
                            'LocationConstraint': os.getenv('AWS_REGION')
                        }
                    )
                else:
                    s3.create_bucket(Bucket=bucket_name)

        # Save the bucket name in case we had to modify it
        os.environ['S3_BUCKET_NAME'] = bucket_name
        return bucket_name
    except botocore.exceptions.ClientError as e:
        logger.error(f"S3 client error: {str(e)}")
        return None


def validate_aws_credentials():
    """Validate AWS credentials from environment variables"""
    if is_local_env():
        return True  # Skip validation for LocalStack

    # Check if environment variables are set
    access_key = os.getenv('AWS_ACCESS_KEY_ID')
    secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    if not access_key or not secret_key:
        logger.error("AWS credentials are missing from environment variables")
        logger.error("Please ensure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set in your .env file")
        return False

    # Check if using temporary credentials
    session_token = os.getenv('AWS_SESSION_TOKEN')
    using_temp_creds = session_token is not None

    try:
        # Try to get the AWS account ID as a simple test
        sts_client = boto3.client('sts', **get_client_kwargs())
        account_id = sts_client.get_caller_identity()['Account']
        logger.info(f"AWS credentials are valid for account: {account_id}")
        logger.info(f"Using {'temporary' if using_temp_creds else 'permanent'} credentials")

        # Update the environment variable if it wasn't set
        if not os.getenv('AWS_ACCOUNT_ID'):
            os.environ['AWS_ACCOUNT_ID'] = account_id
            logger.info(f"Set AWS_ACCOUNT_ID to {account_id}")

        return True
    except botocore.exceptions.ClientError as e:
        logger.error(f"AWS credential validation failed: {str(e)}")

        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'InvalidClientTokenId':
            logger.error("The AWS credentials provided in environment variables are invalid or expired.")
            if using_temp_creds:
                logger.error("You are using temporary credentials that may have expired.")
                logger.error("Please obtain fresh temporary credentials.")
            else:
                logger.error("Please verify your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY values")
        elif error_code == 'AccessDenied':
            logger.error("Your AWS credentials don't have sufficient permissions.")
            logger.error("Ensure your IAM user has permissions for IAM and S3 operations")

        logger.error("To run in LocalStack instead, use: poetry run switch-env LOCAL")
        return False


def debug_credentials():
    """Print credential information for debugging"""
    access_key = os.environ.get('AWS_ACCESS_KEY_ID', '')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    session_token = os.environ.get('AWS_SESSION_TOKEN', '')

    # Mask credentials for safety
    masked_access = access_key[:4] + '...' + access_key[-4:] if len(access_key) > 8 else '[NOT SET]'
    masked_secret = '[SET]' if secret_key else '[NOT SET]'
    masked_token = '[SET]' if session_token else '[NOT SET]'

    logger.info(
        f"AWS Credentials - Access Key: {masked_access}, Secret Key: {masked_secret}, Session Token: {masked_token}")
    logger.info(f"AWS Region: {os.environ.get('AWS_REGION', '[NOT SET]')}")

def main():
    """Run the setup process"""
    env_name = "LocalStack" if is_local_env() else "AWS"
    logger.info(f"Setting up {env_name} environment...")

    debug_credentials()

    if not is_local_env():
        # Validate AWS credentials before proceeding
        if not validate_aws_credentials():
            logger.error("AWS credential validation failed. Aborting setup.")
            return

        role_arn = ensure_role_exists()
        if not role_arn:
            logger.error("Failed to ensure IAM role exists. Aborting setup.")
            return

    bucket_name = setup_bucket()
    if bucket_name:
        logger.info(f"{env_name} setup complete. Bucket '{bucket_name}' is ready.")
    else:
        logger.error(f"{env_name} setup failed.")

if __name__ == "__main__":
    main()