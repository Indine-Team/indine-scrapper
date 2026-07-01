import os
import glob
import boto3

def upload_results():
    endpoint = os.environ.get("SPACES_ENDPOINT")
    key = os.environ.get("SPACES_KEY")
    secret = os.environ.get("SPACES_SECRET")
    bucket = os.environ.get("SPACES_BUCKET")

    if not all([endpoint, key, secret, bucket]):
        print("SPACES env vars not set, skipping upload")
        return

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    for folder in ["restaurants", "menus"]:
        for filepath in glob.glob(f"{folder}/**", recursive=True):
            if os.path.isfile(filepath):
                remote_key = filepath.replace("\\", "/")
                client.upload_file(filepath, bucket, remote_key)
                print(f"Uploaded: {remote_key}")

    print("All results uploaded to Spaces")

if __name__ == "__main__":
    upload_results()
