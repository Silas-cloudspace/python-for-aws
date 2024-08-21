import json
import boto3
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_latest_instance_with_volume(ec2, instance_tag_key, instance_tag_value, max_retries=3, delay=5):
    for attempt in range(max_retries):
        logger.info(f"Attempt {attempt + 1} to retrieve instances with tag {instance_tag_key}={instance_tag_value}")
        
        instances = ec2.describe_instances(
            Filters=[{'Name': f'tag:{instance_tag_key}', 'Values': [instance_tag_value]}]
        )
        
        logger.info(f"DescribeInstances Response: {json.dumps(instances, default=str)}")

        latest_instance = None
        latest_launch_time = datetime.min.replace(tzinfo=timezone.utc)  # Make datetime.min offset-aware
        
        for reservation in instances['Reservations']:
            for instance in reservation['Instances']:
                logger.info(f"Checking Instance ID: {instance['InstanceId']} with Launch Time: {instance['LaunchTime']}")
                
                launch_time = instance['LaunchTime']  # This is offset-aware
                if launch_time > latest_launch_time:
                    latest_launch_time = launch_time
                    latest_instance = instance
        
        if latest_instance and 'BlockDeviceMappings' in latest_instance:
            for block_device in latest_instance['BlockDeviceMappings']:
                if 'Ebs' in block_device:
                    logger.info(f"Found Volume ID: {block_device['Ebs']['VolumeId']} for Instance ID: {latest_instance['InstanceId']}")
                    return latest_instance, block_device['Ebs']['VolumeId']

        logger.warning(f"No volume ID found on attempt {attempt + 1}. Retrying after {delay} seconds...")
        time.sleep(delay)
    
    raise Exception("No volume ID found after multiple retries.")

def get_instance_if_stable(ec2, instance_id, max_retries=3, delay=5):
    for attempt in range(max_retries):
        instance = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
        if instance['State']['Name'] == 'running':
            logger.info(f"Instance {instance_id} is in 'running' state.")
            return instance
        logger.warning(f"Instance {instance_id} is in state '{instance['State']['Name']}'. Waiting for 'running' state.")
        time.sleep(delay)
    raise Exception(f"Instance {instance_id} did not reach a stable state.")

def lambda_handler(event, context):
    ec2 = boto3.client('ec2')
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        instance_tag_key = os.environ['INSTANCE_TAG_KEY']
        instance_tag_value = os.environ['INSTANCE_TAG_VALUE']
        
        latest_instance, volume_id = get_latest_instance_with_volume(ec2, instance_tag_key, instance_tag_value)
        
        # Optionally, check if the instance is in a stable (running) state before creating a snapshot
        stable_instance = get_instance_if_stable(ec2, latest_instance['InstanceId'])
        
        response = ec2.create_snapshot(
            VolumeId=volume_id,
            Description='My EC2 Snapshot',
            TagSpecifications=[
                {
                    'ResourceType': 'snapshot',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': f"My EC2 snapshot {current_date}"
                        }
                    ]
                }
            ]
        )
        
        logger.info(f"Successfully created snapshot: {json.dumps(response, default=str)}")
    
    except Exception as e:
        logger.error(f"Error creating snapshot: {str(e)}")
        raise
