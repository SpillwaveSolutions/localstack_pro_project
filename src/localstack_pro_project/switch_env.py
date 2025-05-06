import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv, set_key

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def switch_environment(target_env=None):
    """Switch between LocalStack and AWS environments"""
    # Load current environment variables
    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)

    current_env = os.getenv('DEPLOYMENT_ENV', 'LOCAL').upper()

    # Determine target environment
    if target_env is None:
        # If no target specified, toggle to the other environment
        target_env = 'AWS' if current_env == 'LOCAL' else 'LOCAL'
    else:
        target_env = target_env.upper()

    if target_env not in ['LOCAL', 'AWS']:
        logger.error(f"Invalid environment: {target_env}. Must be 'LOCAL' or 'AWS'")
        return False

    # No change needed if already in target environment
    if current_env == target_env:
        logger.info(f"Already targeting {target_env} environment")
        return True

    # Update the .env file
    try:
        set_key(env_path, 'DEPLOYMENT_ENV', target_env)
        logger.info(f"Switched environment from {current_env} to {target_env}")

        # Provide helpful guidance
        if target_env == 'AWS':
            required_vars = ['AWS_ACCOUNT_ID', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_ROLE_ARN']
            missing = [var for var in required_vars if not os.getenv(var)]

            if missing:
                logger.warning(f"AWS environment activated, but missing required variables: {', '.join(missing)}")
                logger.info("Make sure to set these variables in your .env file")
        else:
            logger.info("LocalStack environment activated")
            if not os.getenv('LOCALSTACK_ENDPOINT'):
                logger.warning("LOCALSTACK_ENDPOINT not set, using default http://localhost:4566")

        return True
    except Exception as e:
        logger.error(f"Failed to switch environment: {str(e)}")
        return False


def main():
    """Main entry point for environment switching"""
    # Parse command line argument if provided
    target_env = None
    if len(sys.argv) > 1:
        target_env = sys.argv[1]

    switch_environment(target_env)


if __name__ == "__main__":
    main()