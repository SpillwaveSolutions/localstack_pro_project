import os
import logging
import shutil
import zipfile
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from localstack_pro_project.setup_localstack import get_s3_client, get_lambda_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


def create_lambda_package():
    """Create a deployment package for the Lambda function"""
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    try:
        # Path to the Lambda function file
        lambda_file = Path(__file__).parent / 'lambda_functions' / 's3_event_processor.py'

        # Copy the Lambda function to the temp directory
        shutil.copy(lambda_file, os.path.join(temp_dir, 's3_event_processor.py'))

        # Create a zip file containing the Lambda function
        zip_path = os.path.join(temp_dir, 'lambda_function.zip')
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(os.path.join(temp_dir, 's3_event_processor.py'), 's3_event_processor.py')

        logger.info(f"Created Lambda deployment package at {zip_path}")
        return zip_path
    except Exception as e:
        logger.error(f"Error creating Lambda package: {str(e)}")
        shutil.rmtree(temp_dir)
        return None


def deploy_lambda():
    """Deploy the Lambda function to LocalStack"""
    import boto3

    # Create the Lambda deployment package
    zip_path = create_lambda_package()
    if not zip_path:
        logger.error("Failed to create Lambda deployment package")
        return False

    try:
        # First, ensure that the S3 bucket exists
        from localstack_pro_project.setup_localstack import setup_bucket
        bucket_name = setup_bucket()
        logger.info(f"Ensured S3 bucket '{bucket_name}' exists")

        # Create Lambda client using our get_lambda_client function
        lambda_client = get_lambda_client()

        # Read the deployment package
        with open(zip_path, 'rb') as f:
            zip_content = f.read()

        # Function name
        function_name = 'todo-processor'

        # Set environment variables for the Lambda function
        environment_variables = {
            'IS_LOCAL': 'true',
            'AWS_ENDPOINT': os.getenv('LOCALSTACK_ENDPOINT'),
            'AWS_REGION': os.getenv('AWS_REGION'),
            'DEBUG_MODE': os.getenv('DEBUG_MODE', 'false'),
            'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO')
        }

        # Check if the function already exists
        try:
            lambda_client.get_function(FunctionName=function_name)
            logger.info(f"Lambda function {function_name} already exists. Updating...")

            # Update the function code
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_content
            )

            # Update environment variables
            # Add retry mechanism for ResourceConflictException
            max_retries = 3
            retry_count = 0
            update_config_success = False

            while retry_count < max_retries and not update_config_success:
                try:
                    if retry_count > 0:
                        logger.info(f"Retrying function configuration update (attempt {retry_count + 1})")
                        # Add a small delay before retrying
                        import time
                        time.sleep(1.5)

                    lambda_client.update_function_configuration(
                        FunctionName=function_name,
                        Environment={'Variables': environment_variables}
                    )
                    update_config_success = True
                except lambda_client.exceptions.ResourceConflictException as e:
                    if retry_count >= max_retries - 1:
                        logger.warning(
                            f"Could not update function configuration after {max_retries} attempts: {str(e)}")
                        logger.info("Continuing with deployment anyway - the function code has been updated")
                        break
                    retry_count += 1
        except lambda_client.exceptions.ResourceNotFoundException:
            logger.info(f"Creating new Lambda function {function_name}...")

            # Create the function
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.9',  # Using Python 3.9 for Lambda
                Role='arn:aws:iam::000000000000:role/lambda-role',  # Dummy role for LocalStack
                Handler='s3_event_processor.handler',
                Code={
                    'ZipFile': zip_content
                },
                Environment={
                    'Variables': environment_variables
                }
            )

        logger.info(f"Lambda function deployed: {response['FunctionName']}")

        # Configure S3 to trigger the Lambda function
        configure_s3_trigger(function_name)

        return True
    except Exception as e:
        logger.error(f"Error deploying Lambda function: {str(e)}")
        return False
    finally:
        # Clean up the temporary directory
        if zip_path:
            shutil.rmtree(os.path.dirname(zip_path))


def configure_s3_trigger(function_name):
    """Configure S3 bucket to trigger the Lambda function"""
    try:
        # Get the bucket name from environment variables
        bucket_name = os.getenv('S3_BUCKET_NAME')

        # Create S3 client
        s3 = get_s3_client()

        # Create Lambda client using our get_lambda_client function
        lambda_client = get_lambda_client()

        # Get the region from environment variables or default to us-east-1
        region = os.getenv('AWS_REGION', 'us-east-1')

        # Add permission for S3 to invoke the Lambda function
        try:
            lambda_client.add_permission(
                FunctionName=function_name,
                StatementId='s3-trigger',
                Action='lambda:InvokeFunction',
                Principal='s3.amazonaws.com',
                SourceArn=f'arn:aws:s3:::{bucket_name}'
            )
            logger.info(f"Added permission for S3 to invoke Lambda function {function_name}")
        except lambda_client.exceptions.ResourceConflictException:
            logger.info(f"Permission for S3 to invoke Lambda already exists - continuing with deployment")

        # Configure the S3 bucket to trigger the Lambda function
        # Use the proper format with Id field to avoid InvalidArgument errors
        function_arn = f'arn:aws:lambda:{region}:000000000000:function:{function_name}'

        notification_config = {
            'LambdaFunctionConfigurations': [
                {
                    'Id': 'ObjectCreatedEvent',  # Add an Id field to avoid InvalidArgument errors
                    'LambdaFunctionArn': function_arn,
                    'Events': ['s3:ObjectCreated:*']
                }
            ]
        }

        # Apply the notification configuration
        logger.info(f"Setting notification configuration on bucket {bucket_name} to trigger Lambda {function_name}")
        s3.put_bucket_notification_configuration(
            Bucket=bucket_name,
            NotificationConfiguration=notification_config
        )

        # Verify the configuration
        try:
            config = s3.get_bucket_notification_configuration(Bucket=bucket_name)
            logger.info(f"Successfully configured S3 bucket {bucket_name} to trigger Lambda function {function_name}")
            logger.info(f"Current notification configuration: {config}")
        except Exception as e:
            logger.warning(f"Could not verify notification configuration: {str(e)}")

        return True
    except Exception as e:
        logger.error(f"Error configuring S3 trigger: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Main function to deploy the Lambda function"""
    logger.info("Starting Lambda deployment process...")
    success = deploy_lambda()
    if success:
        logger.info("Lambda function deployed and configured successfully.")
    else:
        logger.error("Failed to deploy Lambda function.")


if __name__ == "__main__":
    main()