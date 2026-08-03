from config.minio_config import minio_config
print("endpoint:", minio_config.endpoint)
print("access_key:", minio_config.access_key)
print("bucket:", minio_config.bucket_name)

from utils.minio_utils import get_minio_client
client = get_minio_client()
print("client:", client)