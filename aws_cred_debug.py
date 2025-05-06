import os
import sys
import boto3
import botocore
import json
import subprocess

def print_hr():
    print("-" * 60)

# Print Python and boto3 versions
print_hr()
print(f"Python version: {sys.version}")
print(f"Boto3 version: {boto3.__version__}")
print(f"Botocore version: {botocore.__version__}")
print_hr()

# Check environment variables (safely print partial values)
print("Environment variables:")
for var in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_REGION']:
    value = os.environ.get(var, '')
    if var != 'AWS_REGION' and value:
        masked = value[:4] + '...' + value[-4:] if len(value) > 10 else '[SET]'
        print(f"  {var}: {masked}")
    else:
        print(f"  {var}: {value or '[NOT SET]'}")
print_hr()

# Try to get caller identity with boto3
print("Testing boto3 credentials:")
try:
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    print(f"  SUCCESS! Account: {identity['Account']}")
    print(f"  ARN: {identity['Arn']}")
except Exception as e:
    print(f"  ERROR: {str(e)}")
print_hr()

# Compare with AWS CLI
print("Testing AWS CLI credentials:")
try:
    result = subprocess.run(['aws', 'sts', 'get-caller-identity'],
                           capture_output=True, text=True, check=True)
    print(f"  SUCCESS! Output:")
    print("  " + result.stdout.replace('\n', '\n  '))
except subprocess.CalledProcessError as e:
    print(f"  ERROR: {e.stderr}")
print_hr()

# Check if AWS_SDK_LOAD_CONFIG is set
print("Additional configuration:")
print(f"  AWS_SDK_LOAD_CONFIG: {os.environ.get('AWS_SDK_LOAD_CONFIG', '[NOT SET]')}")

# Check default profile
try:
    cmd = ['aws', 'configure', 'list']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    print("  AWS CLI config:")
    print("  " + result.stdout.replace('\n', '\n  '))
except subprocess.CalledProcessError as e:
    print(f"  Error getting AWS CLI config: {e.stderr}")