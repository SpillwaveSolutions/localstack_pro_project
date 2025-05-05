import os
import logging
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.setup_localstack import (
    get_s3_client,
    get_lambda_client
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
    """Deploy Lambda function to LocalStack"""
    import boto3

    # Create Lambda deployment package
    zip_path = create_lambda_package()
    if not zip_path:
        logger.error("Failed to create Lambda package")
        return False

    try:
        # Ensure S3 bucket exists
        from localstack_pro_project.setup_localstack import (
            setup_bucket
        )
        bucket_name = setup_bucket()
        logger.info(f"S3 bucket '{bucket_name}' exists")

        # Create Lambda client
        lambda_client = get_lambda_client()

        # Read deployment package
        with open(zip_path, 'rb') as f:
            zip_content = f.read()

        # Function name
        function_name = 'todo-processor'

        # Set environment variables
        environment_variables = {
            'IS_LOCAL': 'true',
            'AWS_ENDPOINT': os.getenv('LOCALSTACK_ENDPOINT'),
            'AWS_REGION': os.getenv('AWS_REGION'),
            'DEBUG_MODE': os.getenv('DEBUG_MODE', 'false'),
            'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO')
        }

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
                        import time
                        time.sleep(1.5)

                    lambda_client.update_function_configuration(
                        FunctionName=function_name,
                        Environment={
                            'Variables': environment_variables
                        }
                    )
                    update_config_success = True
                except (
                    lambda_client.exceptions
                    .ResourceConflictException
                ) as e:
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

        except (
            lambda_client.exceptions.ResourceNotFoundException
        ):
            logger.info(f"Creating new Lambda {function_name}")

            # Create function
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.9',
                Role='arn:aws:iam::000000000000:role/'
                'lambda-role',
                Handler='s3_event_processor.handler',
                Code={
                    'ZipFile': zip_content
                },
                Environment={
                    'Variables': environment_variables
                },
                Timeout=30
            )

        logger.info(
            f"Lambda deployed: {response['FunctionName']}"
        )

        # Wait for Lambda to be active
        logger.info(
            f"Waiting for Lambda {function_name} to activate"
        )
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

        # Configure S3 trigger
        configure_s3_trigger(function_name)

        return True
    except Exception as e:
        logger.error(f"Error deploying Lambda: {str(e)}")
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

        # Add S3 invoke permission
        try:
            lambda_client.add_permission(
                FunctionName=function_name,
                StatementId='s3-trigger',
                Action='lambda:InvokeFunction',
                Principal='s3.amazonaws.com',
                SourceArn=f'arn:aws:s3:::{bucket_name}'
            )
            logger.info("Added S3 invoke permission")
        except (
            lambda_client.exceptions.ResourceConflictException
        ):
            logger.info("S3 permission exists")

        # Configure bucket trigger
        function_arn = (
            f'arn:aws:lambda:{region}:000000000000:'
            f'function:{function_name}'
        )

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
        logger.info(
            f"Setting notification on {bucket_name}"
        )
        s3.put_bucket_notification_configuration(
            Bucket=bucket_name,
            NotificationConfiguration=notification_config
        )

        # Verify config
        try:
            config = s3.get_bucket_notification_configuration(
                Bucket=bucket_name
            )
            logger.info("S3 trigger configured successfully")
            logger.info(f"Config: {config}")
        except Exception as e:
            logger.warning(
                f"Config verify failed: {str(e)}"
            )

        return True
    except Exception as e:
        logger.error(f"Error configuring trigger: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

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