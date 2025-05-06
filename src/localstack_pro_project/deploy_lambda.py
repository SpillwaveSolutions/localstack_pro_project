import os
import logging
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path
import boto3
from dotenv import load_dotenv
import json


from localstack_pro_project.cloud_setup import (
    get_s3_client,
    get_lambda_client,
    is_local_env,
    get_client_kwargs
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - '
    '%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

def create_lambda_package():
    """Create deployment package for Lambda function"""
    temp_dir = tempfile.mkdtemp()
    try:
        # Path to Lambda function file
        lambda_file = (
            Path(__file__).parent /
            'lambda_functions' /
            's3_event_processor.py'
        )

        # Copy Lambda function to temp directory
        shutil.copy(
            lambda_file,
            os.path.join(temp_dir, 's3_event_processor.py')
        )

        # Create zip with Lambda function
        zip_path = os.path.join(temp_dir, 'lambda_function.zip')
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(
                os.path.join(
                    temp_dir,
                    's3_event_processor.py'
                ),
                's3_event_processor.py'
            )

        logger.info(
            f"Created Lambda package at {zip_path}"
        )
        return zip_path
    except Exception as e:
        logger.error(f"Error creating package: {str(e)}")
        shutil.rmtree(temp_dir)
        return None


def deploy_lambda():
    """Deploy Lambda function to the target environment"""
    # Create Lambda deployment package
    zip_path = create_lambda_package()
    if not zip_path:
        logger.error("Failed to create Lambda package")
        return False

    try:
        # Environment name for logging
        env_name = "LocalStack" if is_local_env() else "AWS"
        logger.info(f"Deploying Lambda to {env_name}...")

        # Ensure S3 bucket exists
        from localstack_pro_project.cloud_setup import setup_bucket
        bucket_name = setup_bucket()
        logger.info(f"S3 bucket '{bucket_name}' exists")

        # Create Lambda client
        lambda_client = get_lambda_client()

        # For AWS deployment, use a different approach for the role
        if not is_local_env():
            # Get AWS account ID
            sts_client = boto3.client('sts', **get_client_kwargs())
            account_id = sts_client.get_caller_identity()['Account']

            # Create IAM client
            iam_client = boto3.client('iam', **get_client_kwargs())

            # Create a role name with a unique suffix
            import uuid
            role_name = f"lambda-s3-processor-{uuid.uuid4().hex[:8]}"

            logger.info(f"Creating new IAM role: {role_name}")

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
            response = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Role for Lambda S3 processor function"
            )

            role_arn = response['Role']['Arn']
            logger.info(f"Created role with ARN: {role_arn}")

            # Attach policies
            logger.info("Attaching policies to the role...")
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
            )

            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
            )

            # Wait for role propagation
            logger.info("Waiting for IAM role to propagate...")
            import time
            time.sleep(10)  # IAM changes can take time to propagate
        else:
            # For LocalStack, use the standard role
            role_arn = 'arn:aws:iam::000000000000:role/lambda-role'

        # Read deployment package
        with open(zip_path, 'rb') as f:
            zip_content = f.read()

        # Function name
        function_name = 'todo-processor'

        # Set environment variables
        environment_variables = {
            'IS_LOCAL': 'true' if is_local_env() else 'false',
            'DEBUG_MODE': os.getenv('DEBUG_MODE', 'false'),
            'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO')
        }

        # Only add AWS_ENDPOINT for LocalStack
        if is_local_env() and os.getenv('LOCALSTACK_ENDPOINT'):
            environment_variables['AWS_ENDPOINT'] = os.getenv('LOCALSTACK_ENDPOINT')

        # Remove None values
        environment_variables = {k: v for k, v in environment_variables.items() if v is not None}

        # Check if function exists
        try:
            lambda_client.get_function(
                FunctionName=function_name
            )
            logger.info(
                f"Lambda {function_name} exists. Updating..."
            )

            # Update function code
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_content
            )

            # Update environment variables with retry
            max_retries = 3
            retry_count = 0
            update_config_success = False

            while (
                    retry_count < max_retries and
                    not update_config_success
            ):
                try:
                    if retry_count > 0:
                        logger.info(
                            "Retry config update "
                            f"(attempt {retry_count + 1})"
                        )
                        time.sleep(1.5)

                    lambda_client.update_function_configuration(
                        FunctionName=function_name,
                        Environment={
                            'Variables': environment_variables
                        }
                    )
                    update_config_success = True
                except Exception as e:
                    if retry_count >= max_retries - 1:
                        logger.warning(
                            "Config update failed after "
                            f"{max_retries} tries: {str(e)}"
                        )
                        logger.info(
                            "Continuing - code was updated"
                        )
                        break
                    retry_count += 1
        except Exception:
            logger.info(f"Creating new Lambda {function_name}")

            # Create function
            create_params = {
                'FunctionName': function_name,
                'Runtime': 'python3.9',
                'Role': role_arn,
                'Handler': 's3_event_processor.handler',
                'Code': {
                    'ZipFile': zip_content
                },
                'Environment': {
                    'Variables': environment_variables
                },
                'Timeout': 30
            }

            response = lambda_client.create_function(**create_params)

        logger.info(
            f"Lambda deployed: {response['FunctionName']}"
        )

        # Wait for Lambda to be active
        logger.info(
            f"Waiting for Lambda {function_name} to activate"
        )

        if is_local_env():
            try:
                subprocess.run([
                    "awslocal",
                    "lambda",
                    "wait",
                    "function-active-v2",
                    "--function-name",
                    function_name
                ], check=True)
                logger.info(
                    f"Lambda {function_name} is now active"
                )
            except Exception as e:
                logger.warning(
                    f"Failed waiting for active: {str(e)}"
                )
                logger.info(
                    "Continuing - function may be pending"
                )
        else:
            # For AWS, wait using the AWS CLI
            logger.info("Waiting for Lambda function to become active...")
            try:
                subprocess.run([
                    "aws",
                    "lambda",
                    "wait",
                    "function-active-v2",
                    "--function-name",
                    function_name
                ], check=True)
                logger.info(f"Lambda function {function_name} is now active")
            except Exception as e:
                logger.warning(f"Failed waiting for function to become active: {str(e)}")
                logger.info("Continuing - function may still be updating")

        # Configure S3 trigger
        configure_s3_trigger(function_name)

        return True
    except Exception as e:
        logger.error(f"Error deploying Lambda: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        # Clean up temp directory
        if zip_path:
            shutil.rmtree(os.path.dirname(zip_path))


def configure_s3_trigger(function_name):
    """Configure S3 bucket trigger for Lambda"""
    try:
        # Get bucket name
        bucket_name = os.getenv('S3_BUCKET_NAME')

        # Create clients
        s3 = get_s3_client()
        lambda_client = get_lambda_client()

        # Get region
        region = os.getenv('AWS_REGION', 'us-east-1')

        # Get account ID for function ARN
        if is_local_env():
            account_id = '000000000000'
        else:
            # Get account ID from STS
            sts_client = boto3.client('sts', **get_client_kwargs())
            account_id = sts_client.get_caller_identity()['Account']

        # Function ARN
        function_arn = (
            f'arn:aws:lambda:{region}:{account_id}:'
            f'function:{function_name}'
        )

        # First give S3 permission to invoke the Lambda function
        logger.info(f"Adding permission for S3 to invoke Lambda function {function_name}")
        try:
            statement_id = f's3-trigger-{bucket_name}'

            # Add permission for S3 to invoke Lambda
            lambda_client.add_permission(
                FunctionName=function_name,
                StatementId=statement_id,
                Action='lambda:InvokeFunction',
                Principal='s3.amazonaws.com',
                SourceArn=f'arn:aws:s3:::{bucket_name}'
            )
            logger.info("Added S3 invoke permission successfully")
        except Exception as e:
            # Check if it's a ResourceConflictException (permission already exists)
            if "ResourceConflictException" in str(e) or "already exists" in str(e):
                logger.info("S3 invoke permission already exists")
            else:
                # Re-raise if it's a different error
                raise

        # Wait a moment to ensure permissions have propagated
        logger.info("Waiting for permissions to propagate...")
        import time
        time.sleep(5)

        # Configure bucket notification
        notification_config = {
            'LambdaFunctionConfigurations': [
                {
                    'Id': 'ObjectCreatedEvent',
                    'LambdaFunctionArn': function_arn,
                    'Events': ['s3:ObjectCreated:*']
                }
            ]
        }

        # Apply notification config
        logger.info(f"Setting notification on {bucket_name}")
        s3.put_bucket_notification_configuration(
            Bucket=bucket_name,
            NotificationConfiguration=notification_config
        )

        logger.info("S3 trigger configured successfully")
        return True
    except Exception as e:
        logger.error(f"Error configuring trigger: {str(e)}")
        # Still return True to indicate Lambda deployment was successful
        # even if trigger configuration failed
        logger.info("Lambda was deployed successfully despite trigger configuration issues")
        return True

def main():
    """Deploy Lambda function"""
    logger.info("Starting Lambda deployment...")
    success = deploy_lambda()
    if success:
        logger.info("Lambda deployed successfully")
    else:
        logger.error("Lambda deployment failed")

if __name__ == "__main__":
    main()